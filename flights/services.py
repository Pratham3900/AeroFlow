"""
Flight-side business logic:
  - dynamic seat-map generation from an Aircraft's SeatCategory configuration
  - the per-flight seat map (available / occupied / blocked), driven entirely
    by the database - nothing about categories, counts, or layout is hard-coded
  - cumulative/incremental delay handling (every update ADDS to the running
    total, never overwrites it) with a full DelayRecord history
  - ONE centralized function for delay-facility eligibility, used everywhere
    (passenger dashboard, booking receipt, delay page, admin panel, emails)
"""
import string
from django.db import transaction
from django.utils import timezone

from .models import Aircraft, SeatCategory, Seat, Flight, DelayRecord

SEAT_LETTERS = string.ascii_uppercase  # "ABCDEFGHIJ..."


# ---------------------------------------------------------------
# Dynamic aircraft / seat-map configuration
# ---------------------------------------------------------------

@transaction.atomic
def generate_seats_for_aircraft(aircraft: Aircraft, category_rows: list):
    """
    Build the physical Seat rows for an Aircraft from an admin-supplied
    configuration, WITHOUT hard-coding categories, counts, or seats/row
    anywhere in code.

    `category_rows` is a list of dicts, one per SeatCategory already
    created for this aircraft, each shaped like:
        {"category": <SeatCategory instance>, "rows": 10, "seats_per_row": 6}
    Rows are numbered sequentially across categories in the order given
    (e.g. Business rows 1-3, Economy rows 4-33), matching how a real
    aircraft is laid out nose-to-tail.

    Existing (non-blocked) seats for this aircraft are replaced.
    """
    aircraft.seats.all().delete()
    row_number = 1
    created = []
    for entry in category_rows:
        category = entry["category"]
        rows = int(entry["rows"])
        seats_per_row = int(entry.get("seats_per_row", 6))
        letters = SEAT_LETTERS[:seats_per_row]
        for _ in range(rows):
            for letter in letters:
                created.append(Seat(
                    aircraft=aircraft, category=category,
                    seat_number=f"{row_number}{letter}", row_number=row_number, column_letter=letter,
                ))
            row_number += 1
    Seat.objects.bulk_create(created)
    return created


def get_seat_map(flight: Flight):
    """
    Build the seat map for one specific flight instance: every seat on the
    flight's aircraft, tagged with its category and current status
    (available / occupied / blocked). Occupied seats are derived from
    active BookingPassenger rows on THIS flight, not from the aircraft
    globally, so the same aircraft type flying two different routes has
    two independent seat maps.
    """
    from bookings.models import BookingPassenger, Booking

    if not flight.aircraft_id:
        return []

    taken_seats = set(
        BookingPassenger.objects.filter(
            booking__flight=flight,
            booking__status__in=[Booking.STATUS_CONFIRMED, Booking.STATUS_REBOOKED, Booking.STATUS_RESCHEDULED],
        ).exclude(seat_number="").values_list("seat_number", flat=True)
    )

    seats = Seat.objects.filter(aircraft_id=flight.aircraft_id).select_related("category").order_by("row_number", "column_letter")
    seat_map = []
    for seat in seats:
        if seat.is_blocked:
            status = "unavailable"
        elif seat.seat_number in taken_seats:
            status = "occupied"
        else:
            status = "available"
        seat_map.append({
            "seat_number": seat.seat_number,
            "row": seat.row_number,
            "column": seat.column_letter,
            "category": seat.category.name,
            "category_code": seat.category.code,
            "color": seat.category.color,
            "status": status,
        })
    return seat_map


def available_categories_for_flight(flight: Flight):
    """Only the seat categories actually configured on THIS flight's aircraft - never a hard-coded list."""
    if not flight.aircraft_id:
        return []
    return list(flight.aircraft.seat_categories.all())


# ---------------------------------------------------------------
# Centralized delay-facility eligibility rule (section 18 requirement:
# one function, used everywhere - passenger dashboard, booking receipt,
# delay page, admin panel, email notifications, facility records).
# ---------------------------------------------------------------

MEAL_THRESHOLD_MINUTES = 120   # > 120 (strictly greater) unlocks the meal voucher
FULL_THRESHOLD_MINUTES = 240   # >= 240 unlocks meal + hotel + transport


def calculate_facility_eligibility(total_delay_minutes: int) -> str:
    """
    Returns one of DelayRecord.FACILITY_NONE / FACILITY_MEAL /
    FACILITY_MEAL_HOTEL_TRANSPORT for a given cumulative delay.

    Exact boundary rule: exactly 120 minutes is still NONE; only once the
    cumulative delay goes strictly above 120 does the meal voucher unlock;
    240 minutes or more unlocks meal + hotel + transport.
    """
    if total_delay_minutes >= FULL_THRESHOLD_MINUTES:
        return DelayRecord.FACILITY_MEAL_HOTEL_TRANSPORT
    if total_delay_minutes > MEAL_THRESHOLD_MINUTES:
        return DelayRecord.FACILITY_MEAL
    return DelayRecord.FACILITY_NONE


def facility_levels_included(facility_level: str) -> set:
    """Expand a facility level into the individual facility types it includes."""
    if facility_level == DelayRecord.FACILITY_MEAL_HOTEL_TRANSPORT:
        return {"MEAL", "HOTEL", "TRANSPORT"}
    if facility_level == DelayRecord.FACILITY_MEAL:
        return {"MEAL"}
    return set()


# ---------------------------------------------------------------
# Cumulative delay update
# ---------------------------------------------------------------

@transaction.atomic
def add_flight_delay(flight: Flight, additional_minutes: int, reason: str, actor=None) -> DelayRecord:
    """
    Record an ADDITIONAL delay on top of whatever delay the flight already
    has. The previous cumulative total is NEVER overwritten - it is read,
    added to, and a new DelayRecord is appended to the flight's history.
    Returns the created DelayRecord; the caller (recovery.services) is
    responsible for the notification/email/facility side-effects so this
    function stays a single-purpose, reusable building block.
    """
    locked_flight = Flight.objects.select_for_update().get(pk=flight.pk)
    previous_total = locked_flight.delay_minutes
    new_total = previous_total + additional_minutes
    facility_level = calculate_facility_eligibility(new_total)

    locked_flight.delay_minutes = new_total
    locked_flight.delay_reason = reason
    if not locked_flight.original_departure_datetime:
        dt = timezone.datetime.combine(locked_flight.departure_date, locked_flight.departure_time)
        locked_flight.original_departure_datetime = timezone.make_aware(dt) if timezone.is_naive(dt) else dt
    base_dt = timezone.datetime.combine(locked_flight.departure_date, locked_flight.departure_time)
    base_dt = timezone.make_aware(base_dt) if timezone.is_naive(base_dt) else base_dt
    locked_flight.updated_departure_datetime = base_dt + timezone.timedelta(minutes=new_total)
    locked_flight.status = Flight.STATUS_DELAYED
    locked_flight.save()

    record = DelayRecord.objects.create(
        flight=locked_flight,
        previous_delay_minutes=previous_total,
        additional_delay_minutes=additional_minutes,
        total_delay_minutes=new_total,
        facility_level=facility_level,
        reason=reason,
        updated_by=actor if getattr(actor, "is_authenticated", False) else None,
    )
    return record
