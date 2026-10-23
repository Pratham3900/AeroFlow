"""
Management command to populate AeroFlow with realistic demo data:
airports (with full terminal/contact info), aircraft with dynamic seat
categories, flights (including one delayed twice - cumulative - and one
cancelled), demo passengers/staff/admin, single- and multi-passenger
bookings with real seat selections, a refund request, a rebooking
request, and vouchers.

Usage:
    python manage.py seed_demo_data
"""
from datetime import timedelta, time, date

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction

from accounts.models import User, PassengerProfile, StaffProfile
from flights.models import Airport, Terminal, Gate, Aircraft, SeatCategory, Flight
from flights.services import generate_seats_for_aircraft
from bookings.models import Booking, BookingPassenger
from bookings.services import create_booking
from recovery.services import process_flight_delay, process_flight_cancellation
from recovery.models import RefundRequest, RebookingRequest
from vouchers.services import issue_voucher
from vouchers.models import Voucher


class Command(BaseCommand):
    help = "Seed AeroFlow with demo airports, aircraft, flights, users, bookings, and disruption data."

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write("Seeding AeroFlow demo data...")

        airports = self._create_airports()
        aircraft = self._create_aircraft()
        flights = self._create_flights(airports, aircraft)
        users = self._create_users()
        bookings = self._create_bookings(users, flights)
        self._create_disruptions_and_requests(users, bookings, flights)

        self.stdout.write(self.style.SUCCESS("Demo data seeded successfully."))
        self.stdout.write("")
        self.stdout.write("Demo login credentials:")
        self.stdout.write("  Admin:     username=admin1      password=AeroFlow@123")
        self.stdout.write("  Staff:     username=staff1      password=AeroFlow@123")
        self.stdout.write("  Passenger: username=passenger1  password=AeroFlow@123")
        self.stdout.write("  Passenger: username=passenger2  password=AeroFlow@123")

    def _create_airports(self):
        data = [
            ("BOM", "Chhatrapati Shivaji Maharaj Intl", "Mumbai", "Maharashtra"),
            ("DEL", "Indira Gandhi Intl", "Delhi", "Delhi"),
            ("BLR", "Kempegowda Intl", "Bengaluru", "Karnataka"),
            ("MAA", "Chennai Intl", "Chennai", "Tamil Nadu"),
            ("HYD", "Rajiv Gandhi Intl", "Hyderabad", "Telangana"),
            ("GOI", "Goa Intl", "Goa", "Goa"),
            ("AMD", "Sardar Vallabhbhai Patel Intl", "Ahmedabad", "Gujarat"),
        ]
        airports = {}
        self.terminals = {}
        self.gates = {}
        for code, name, city, state in data:
            airport, _ = Airport.objects.get_or_create(code=code, defaults={
                "name": name, "city": city, "state": state,
                "contact_phone": "+91-22-6685-0000", "contact_email": f"info@{code.lower()}airport.example.com",
                "checkin_info": "Check-in counters open 3 hours before departure and close 45 minutes prior.",
                "boarding_info": "Boarding gates close 20 minutes before scheduled departure.",
            })
            airports[code] = airport

            # Give each demo airport two terminals with a couple of gates
            # each, so the Airport -> Terminal -> Gate dropdown cascade has
            # real, distinct data to show on every route.
            terminal1, _ = Terminal.objects.get_or_create(airport=airport, name="Terminal 1")
            terminal2, _ = Terminal.objects.get_or_create(airport=airport, name="Terminal 2")
            for gate_name in ("Gate 1", "Gate 2", "Gate 3"):
                Gate.objects.get_or_create(terminal=terminal1, name=gate_name)
            for gate_name in ("Gate 4", "Gate 5"):
                Gate.objects.get_or_create(terminal=terminal2, name=gate_name)

            self.terminals[code] = terminal1
            self.gates[code] = terminal1.gates.order_by("name").first()

        return airports

    def _create_aircraft(self):
        aircraft = {}

        # Aircraft 1: Airbus A320 - Economy + Premium (60 seats)
        a320, created = Aircraft.objects.get_or_create(name="Airbus A320 - VT-AF101", defaults={"model": "Airbus A320"})
        if created:
            economy = SeatCategory.objects.create(aircraft=a320, name="Economy", code="economy", display_order=1, price_multiplier="1.0", color="#1e88e5")
            premium = SeatCategory.objects.create(aircraft=a320, name="Premium", code="premium", display_order=0, price_multiplier="1.4", color="#7c4dff")
            generate_seats_for_aircraft(a320, [
                {"category": premium, "rows": 2, "seats_per_row": 4},
                {"category": economy, "rows": 8, "seats_per_row": 6},
            ])
        aircraft["A320"] = a320

        # Aircraft 2: Boeing 737 - Economy + Business (85 seats)
        b737, created = Aircraft.objects.get_or_create(name="Boeing 737 - VT-AF205", defaults={"model": "Boeing 737"})
        if created:
            economy = SeatCategory.objects.create(aircraft=b737, name="Economy", code="economy", display_order=1, price_multiplier="1.0", color="#1e88e5")
            business = SeatCategory.objects.create(aircraft=b737, name="Business", code="business", display_order=0, price_multiplier="2.2", color="#0b3d91")
            generate_seats_for_aircraft(b737, [
                {"category": business, "rows": 3, "seats_per_row": 4},
                {"category": economy, "rows": 12, "seats_per_row": 6},
            ])
        aircraft["B737"] = b737

        # Aircraft 3: ATR 72 - Economy only (100 seats)
        atr, created = Aircraft.objects.get_or_create(name="ATR 72 - VT-AF302", defaults={"model": "ATR 72"})
        if created:
            economy = SeatCategory.objects.create(aircraft=atr, name="Economy", code="economy", display_order=0, price_multiplier="1.0", color="#1e88e5")
            generate_seats_for_aircraft(atr, [{"category": economy, "rows": 20, "seats_per_row": 5}])
        aircraft["ATR72"] = atr

        return aircraft

    def _create_flights(self, airports, aircraft):
        today = timezone.now().date()
        flights = {}

        def make(number, origin, dest, day_offset, dep_time, ac, status=Flight.STATUS_SCHEDULED):
            flight, _ = Flight.objects.get_or_create(
                flight_number=number,
                defaults=dict(
                    origin=airports[origin], destination=airports[dest],
                    departure_date=today + timedelta(days=day_offset), departure_time=dep_time,
                    arrival_date=today + timedelta(days=day_offset), arrival_time=time((dep_time.hour + 2) % 24, dep_time.minute),
                    origin_terminal=self.terminals[origin], origin_gate=self.gates[origin],
                    destination_terminal=self.terminals[dest], destination_gate=self.gates[dest],
                    aircraft=ac, status=status,
                ),
            )
            flights[number] = flight
            return flight

        make("AF101", "BOM", "DEL", 1, time(6, 30), aircraft["A320"])
        make("AF102", "BOM", "DEL", 0, time(10, 0), aircraft["A320"])          # will be delayed twice (cumulative)
        make("AF103", "BOM", "DEL", 1, time(14, 0), aircraft["A320"])           # alt flight for AF102
        make("AF104", "BOM", "DEL", 2, time(18, 0), aircraft["A320"])           # alt flight for AF102
        make("AF205", "DEL", "BOM", 0, time(9, 0), aircraft["B737"])            # will be cancelled
        make("AF206", "DEL", "BOM", 1, time(11, 0), aircraft["B737"])           # alt flight for AF205
        make("AF301", "BLR", "MAA", 3, time(7, 0), aircraft["B737"])
        make("AF302", "HYD", "GOI", 4, time(16, 0), aircraft["ATR72"])
        make("AF303", "MAA", "BLR", -2, time(8, 0), aircraft["B737"], status=Flight.STATUS_COMPLETED)
        make("AF401", "AMD", "BOM", 0, time(9, 45), aircraft["ATR72"], status=Flight.STATUS_ON_TIME)  # for boarding-pass demo

        return flights

    def _create_users(self):
        users = {}

        admin, created = User.objects.get_or_create(
            username="admin1", defaults=dict(email="admin1@aeroflow.example.com", first_name="Ananya", last_name="Rao", role=User.ROLE_ADMIN, is_staff=True, is_superuser=True),
        )
        if created:
            admin.set_password("AeroFlow@123")
            admin.save()
        users["admin"] = admin

        staff, created = User.objects.get_or_create(
            username="staff1", defaults=dict(email="staff1@aeroflow.example.com", first_name="Rahul", last_name="Mehta", role=User.ROLE_STAFF),
        )
        if created:
            staff.set_password("AeroFlow@123")
            staff.save()
            StaffProfile.objects.get_or_create(user=staff, defaults=dict(employee_id="EMP1001", department="operations", designation="Duty Manager"))
        users["staff"] = staff

        for uname, first, last in [("passenger1", "Priya", "Sharma"), ("passenger2", "Arjun", "Iyer")]:
            passenger, created = User.objects.get_or_create(
                username=uname, defaults=dict(email=f"{uname}@example.com", first_name=first, last_name=last, role=User.ROLE_PASSENGER, phone_number="9800000000"),
            )
            if created:
                passenger.set_password("AeroFlow@123")
                passenger.save()
                PassengerProfile.objects.get_or_create(user=passenger, defaults=dict(nationality="Indian"))
            users[uname] = passenger

        return users

    def _next_free_seat(self, flight, exclude=None):
        from flights.services import get_seat_map
        exclude = exclude or set()
        for seat in get_seat_map(flight):
            if seat["status"] == "available" and seat["seat_number"] not in exclude:
                return seat["seat_number"]
        raise RuntimeError(f"No free seats left on {flight.flight_number} for demo data.")

    def _create_bookings(self, users, flights):
        bookings = {}

        def solo_passenger(flight, first, last, ptype=BookingPassenger.TYPE_ADULT, dob=None):
            return {
                "first_name": first, "middle_name": "", "last_name": last,
                "date_of_birth": dob, "gender": "", "nationality": "Indian",
                "email": "", "phone_number": "", "passenger_type": ptype, "is_primary": True,
                "seat_number": self._next_free_seat(flight),
            }

        b1 = create_booking(
            user=users["passenger1"], flight=flights["AF102"],
            passengers_data=[solo_passenger(flights["AF102"], "Priya", "Sharma")],
        )
        bookings["passenger1_AF102"] = b1

        b2 = create_booking(
            user=users["passenger2"], flight=flights["AF301"],
            passengers_data=[solo_passenger(flights["AF301"], "Arjun", "Iyer")],
        )
        bookings["passenger2_AF301"] = b2

        b3 = create_booking(
            user=users["passenger1"], flight=flights["AF303"],
            passengers_data=[solo_passenger(flights["AF303"], "Priya", "Sharma")],
        )
        bookings["passenger1_AF303"] = b3

        # --- Multi-passenger group booking: passenger1 books for herself,
        #     her spouse, and her child on the flight that will be cancelled.
        #     Seats are reserved within this in-memory batch (not just the
        #     DB) so all three passengers get distinct seat numbers even
        #     though none of them is saved yet when the dicts are built. ---
        flight_205 = flights["AF205"]
        reserved_205 = set()

        def next_seat_205():
            seat = self._next_free_seat(flight_205, exclude=reserved_205)
            reserved_205.add(seat)
            return seat

        group_passengers = [
            {
                "first_name": "Priya", "middle_name": "", "last_name": "Sharma",
                "date_of_birth": None, "gender": "", "nationality": "Indian",
                "email": "", "phone_number": "", "passenger_type": BookingPassenger.TYPE_ADULT, "is_primary": True,
                "seat_number": next_seat_205(),
            },
            {
                "first_name": "Rahul", "middle_name": "", "last_name": "Sharma",
                "date_of_birth": date(1988, 4, 12), "gender": "M", "nationality": "Indian",
                "email": "", "phone_number": "", "passenger_type": BookingPassenger.TYPE_ADULT, "is_primary": False,
                "seat_number": next_seat_205(),
            },
            {
                "first_name": "Riya", "middle_name": "", "last_name": "Sharma",
                "date_of_birth": date(2018, 9, 3), "gender": "F", "nationality": "Indian",
                "email": "", "phone_number": "", "passenger_type": BookingPassenger.TYPE_CHILD, "is_primary": False,
                "seat_number": next_seat_205(),
            },
        ]
        b4 = create_booking(user=users["passenger1"], flight=flight_205, passengers_data=group_passengers)
        bookings["passenger1_AF205_group"] = b4

        b5 = create_booking(
            user=users["passenger2"], flight=flights["AF102"],
            passengers_data=[solo_passenger(flights["AF102"], "Arjun", "Iyer")],
        )
        bookings["passenger2_AF102"] = b5

        # --- passenger2 on AF401, which stays ON_TIME and gets moved to
        #     BOARDING in this seed so the automatic-boarding-pass flow can
        #     be seen immediately without any staff action needed. ---
        b6 = create_booking(
            user=users["passenger2"], flight=flights["AF401"],
            passengers_data=[solo_passenger(flights["AF401"], "Arjun", "Iyer")],
        )
        bookings["passenger2_AF401"] = b6

        return bookings

    def _create_disruptions_and_requests(self, users, bookings, flights):
        # Two delay updates on the SAME flight to demonstrate the cumulative
        # rule: 120 + 120 = 240 minutes -> crosses into Meal+Hotel+Transport.
        process_flight_delay(flights["AF102"], additional_minutes=120, reason="Operational Issue", actor=users["staff"])
        process_flight_delay(flights["AF102"], additional_minutes=120, reason="Continued ATC congestion", actor=users["staff"])

        # Trigger the automatic cancellation workflow (affects the 3-passenger group booking)
        process_flight_cancellation(flights["AF205"], reason="Air Traffic Control restriction", actor=users["staff"])

        # Move AF401 straight to BOARDING so its automatic boarding passes exist in the demo.
        from bookings.services import generate_boarding_passes_for_flight
        flight_401 = flights["AF401"]
        flight_401.status = Flight.STATUS_BOARDING
        flight_401.save(update_fields=["status"])
        generate_boarding_passes_for_flight(flight_401, actor=users["staff"])

        # Demo refund request (staff-workflow) on the delayed booking
        delayed_booking = bookings["passenger1_AF102"]
        RefundRequest.objects.get_or_create(
            booking=delayed_booking, passenger=users["passenger1"],
            defaults=dict(reason="Flight delay exceeded acceptable wait time.", requested_amount=delayed_booking.payment_amount),
        )

        # Demo rebooking request on the cancelled GROUP booking (all 3 passengers move together)
        cancelled_booking = bookings["passenger1_AF205_group"]
        RebookingRequest.objects.get_or_create(
            original_booking=cancelled_booking, requested_flight=flights["AF206"], passenger=users["passenger1"],
        )

        # Demo voucher on the delayed booking (now eligible for all three facilities)
        if not Voucher.objects.filter(booking=delayed_booking, voucher_type=Voucher.TYPE_MEAL).exists():
            issue_voucher(delayed_booking, Voucher.TYPE_MEAL, actor=users["staff"])