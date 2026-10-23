"""
Booking-related business logic:
  - fare calculation (base fare x seat-category multiplier x passenger-type factor)
  - creating a multi-passenger booking with REAL seat selection (transactional,
    race-safe double-booking prevention against the flight's actual seat map)
  - Booking Receipt generation (sent immediately - see bookings/receipt.py)
  - Boarding pass generation (per passenger, with embedded QR code) - ONLY ever
    triggered externally once a flight reaches BOARDING status, never at
    booking time - see flights.views.staff_flight_mark_boarding
  - voluntary cancellation with the >=24h-before-departure refund rule
  - voluntary reschedule (passenger-initiated, distinct from disruption rebooking)
  - disruption rebooking for an entire group of passengers at once

All seat-count / seat-occupancy mutations run inside DB transactions with
`select_for_update()` to avoid race conditions when multiple passengers are
booking concurrently.
"""
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.core.files.base import ContentFile
from django.utils import timezone

from core.email_utils import send_templated_email
from core.utils import log_action
from notifications.models import Notification
from .models import Booking, BookingPassenger, BoardingPass, Cancellation, Refund
from .pdf import build_boarding_pass_pdf
from .receipt import build_booking_receipt_pdf

BASE_ECONOMY_FARE = Decimal("4500.00")

# Infants typically don't occupy a full seat and travel at a fraction of the
# adult fare; children pay the full class fare in this simplified model.
PASSENGER_TYPE_FARE_FACTOR = {
    BookingPassenger.TYPE_ADULT: Decimal("1.0"),
    BookingPassenger.TYPE_CHILD: Decimal("1.0"),
    BookingPassenger.TYPE_INFANT: Decimal("0.1"),
}

# Cancellation policy: refund is only offered if cancelled this far (or more)
# ahead of the scheduled departure. Centralized here - see cancel_booking().
CANCELLATION_REFUND_WINDOW_HOURS = 24


def calculate_fare_for_seat_category(seat_category, passenger_type: str = BookingPassenger.TYPE_ADULT) -> Decimal:
    """
    Per-passenger fare, driven by the seat category's admin-configured
    price_multiplier (flights.models.SeatCategory) rather than any
    hard-coded class list. `seat_category` may be None (legacy flights with
    no aircraft assigned), in which case a 1.0x multiplier is used.
    """
    multiplier = Decimal(str(seat_category.price_multiplier)) if seat_category else Decimal("1.0")
    factor = PASSENGER_TYPE_FARE_FACTOR.get(passenger_type, Decimal("1.0"))
    fare = BASE_ECONOMY_FARE * multiplier * factor
    return fare.quantize(Decimal("1.00"), rounding=ROUND_HALF_UP)


def _resolve_seats(flight, seat_numbers):
    """
    Look up flights.models.Seat rows for the given seat numbers on this
    flight's aircraft. Returns {seat_number: Seat}. Seats that don't exist
    on this aircraft are simply absent from the result (caller decides how
    to handle that as a validation error).
    """
    if not flight.aircraft_id or not seat_numbers:
        return {}
    from flights.models import Seat
    seats = Seat.objects.filter(aircraft_id=flight.aircraft_id, seat_number__in=seat_numbers).select_related("category")
    return {s.seat_number: s for s in seats}


def _taken_seat_numbers(flight):
    return set(
        BookingPassenger.objects.filter(
            booking__flight=flight,
            booking__status__in=[Booking.STATUS_CONFIRMED, Booking.STATUS_REBOOKED, Booking.STATUS_RESCHEDULED],
        ).exclude(seat_number="").values_list("seat_number", flat=True)
    )


def _legacy_auto_seats(flight, count):
    """Fallback seat auto-assignment for flights with no Aircraft configured
    (kept only for backward compatibility with data created before dynamic
    seat maps existed)."""
    import random
    taken = _taken_seat_numbers(flight)
    seats = []
    letters = "ABCDEF"
    row = 1
    while len(seats) < count and row < 999:
        for letter in letters:
            seat = f"{row}{letter}"
            if seat not in taken:
                seats.append(seat)
                taken.add(seat)
                if len(seats) == count:
                    break
        row += 1
    while len(seats) < count:
        candidate = f"{random.randint(1, 99)}{random.choice(letters)}"
        if candidate not in taken:
            seats.append(candidate)
            taken.add(candidate)
    return seats


@transaction.atomic
def create_booking(user, flight, passengers_data, contact=None, actor=None, request=None) -> Booking:
    """
    Core booking-creation transaction.

    `passengers_data` is a list of dicts, one per passenger, each with keys:
    first_name, middle_name, last_name, date_of_birth, gender, nationality,
    email, phone_number, passenger_type, is_primary, seat_number.

    Seat availability is checked and locked with select_for_update() on the
    flight row before any rows are written, and every requested seat number
    is re-validated against currently-occupied seats INSIDE the same
    transaction, so two passengers can never be sold the same seat - if a
    seat was taken between page load and submit, the whole booking fails
    with a clear "no longer available" error rather than silently
    double-booking it.

    Only a Booking Receipt is generated/emailed here. The boarding pass is
    never touched at booking time - see generate_boarding_passes_for_flight().
    """
    from flights.models import Flight

    locked_flight = Flight.objects.select_for_update().get(pk=flight.pk)
    passenger_count = len(passengers_data)

    if passenger_count < 1:
        raise ValueError("At least one passenger is required.")
    if passenger_count > 9:
        raise ValueError("A single booking supports a maximum of 9 passengers.")
    if locked_flight.available_seats < passenger_count:
        raise ValueError(f"Only {locked_flight.available_seats} seat(s) left on this flight.")
    if locked_flight.status == Flight.STATUS_CANCELLED:
        raise ValueError("This flight has been cancelled and cannot accept new bookings.")

    requested_seat_numbers = [p["seat_number"] for p in passengers_data]

    if locked_flight.aircraft_id:
        seat_lookup = _resolve_seats(locked_flight, requested_seat_numbers)
        taken = _taken_seat_numbers(locked_flight)
        for seat_no in requested_seat_numbers:
            seat = seat_lookup.get(seat_no)
            if seat is None:
                raise ValueError(f"Seat {seat_no} does not exist on this aircraft.")
            if seat.is_blocked:
                raise ValueError(f"Seat {seat_no} is not available for booking.")
            if seat_no in taken:
                raise ValueError(f"This seat ({seat_no}) is no longer available. Please select another seat.")
    else:
        # Legacy flight with no aircraft configured: fall back to auto-assignment.
        seat_lookup = {}

    booking = Booking.objects.create(
        passenger=user,
        flight=locked_flight,
        payment_amount=Decimal("0.00"),
        payment_status=Booking.PAYMENT_PAID,
        contact_name=(contact or {}).get("name", ""),
        contact_email=(contact or {}).get("email", ""),
        contact_phone=(contact or {}).get("phone", ""),
    )

    total_fare = Decimal("0.00")
    category_names = set()
    booking_passengers = []
    for data in passengers_data:
        seat = seat_lookup.get(data["seat_number"])
        category = seat.category if seat else None
        fare = calculate_fare_for_seat_category(category, data.get("passenger_type", BookingPassenger.TYPE_ADULT))
        total_fare += fare
        if category:
            category_names.add(category.name)

        bp = BookingPassenger.objects.create(
            booking=booking,
            first_name=data["first_name"],
            middle_name=data.get("middle_name", ""),
            last_name=data["last_name"],
            date_of_birth=data.get("date_of_birth") or None,
            gender=data.get("gender", ""),
            nationality=data.get("nationality", ""),
            email=data.get("email", ""),
            phone_number=data.get("phone_number", ""),
            passenger_type=data.get("passenger_type", BookingPassenger.TYPE_ADULT),
            is_primary=data.get("is_primary", False),
            seat_number=data["seat_number"],
            seat_category=category,
            fare=fare,
        )
        booking_passengers.append(bp)

    booking.payment_amount = total_fare
    booking.travel_class = ", ".join(sorted(category_names)) if category_names else "Economy"
    booking.save(update_fields=["payment_amount", "travel_class"])

    locked_flight.available_seats -= passenger_count
    locked_flight.save(update_fields=["available_seats"])

    generate_booking_receipt(booking, send_email=True)

    Notification.objects.create(
        recipient=user, notification_type=Notification.TYPE_BOOKING,
        title="Booking Confirmed", message=f"Your booking {booking.pnr} on flight {locked_flight.flight_number} is confirmed. Your boarding pass will be available once boarding opens.",
        related_booking=booking,
    )

    log_action(actor or user, "bookings", "Booking created", f"{booking.pnr} - {passenger_count} passenger(s)", request)
    return booking


# ---------------------------------------------------------------
# Booking Receipt (generated immediately; NOT the boarding pass)
# ---------------------------------------------------------------

def generate_booking_receipt(booking: Booking, send_email=True):
    """
    Returns the Booking object (as before, for backward compatibility with
    existing callers) but also stashes the freshly-generated PDF bytes on
    it as `_receipt_pdf_bytes`, so callers that need to attach the same
    receipt to a further email (e.g. a rebooking/reschedule confirmation)
    can reuse those bytes directly instead of re-reading the file back
    from storage via `booking.receipt_pdf.read()`, which is unnecessary
    I/O and, depending on the storage backend, not guaranteed to return
    the full content immediately after `.save()`.
    """
    pdf_bytes = build_booking_receipt_pdf(booking)
    filename = f"receipt_{booking.pnr}.pdf"
    booking.receipt_pdf.save(filename, ContentFile(pdf_bytes), save=False)
    booking.receipt_generated_at = timezone.now()
    booking.save(update_fields=["receipt_pdf", "receipt_generated_at"])
    booking._receipt_pdf_bytes = pdf_bytes

    if send_email:
        send_templated_email(
            subject=f"Booking Confirmed - PNR {booking.pnr}",
            template_name="booking_confirmation",
            context={"booking": booking, "flight": booking.flight, "passengers": booking.booking_passengers.all()},
            to_email=booking.contact_email or booking.passenger.email,
            attachments=[(filename, pdf_bytes, "application/pdf")],
        )
    return booking


# ---------------------------------------------------------------
# Boarding passes - ONLY called from the flight-status-change trigger
# (flights.views.staff_flight_mark_boarding), never from create_booking().
# ---------------------------------------------------------------

def generate_boarding_pass(booking_passenger, send_email=False):
    """Create the boarding pass PDF (with QR code) for one passenger.
    Idempotent: calling this again for the same passenger just refreshes
    the existing PDF rather than creating a duplicate row."""
    boarding_pass, created = BoardingPass.objects.get_or_create(booking_passenger=booking_passenger)
    if not created:
        boarding_pass.regenerated_count += 1

    flight = booking_passenger.booking.flight
    if flight.boarding_time:
        boarding_pass.boarding_time = flight.boarding_time
    elif not boarding_pass.boarding_time:
        boarding_dt = timezone.datetime.combine(timezone.now().date(), flight.departure_time) - timezone.timedelta(minutes=45)
        boarding_pass.boarding_time = boarding_dt.time()

    pdf_bytes = build_boarding_pass_pdf(booking_passenger, boarding_pass)
    filename = f"boarding_pass_{booking_passenger.booking.pnr}_{booking_passenger.id}.pdf"
    boarding_pass.pdf_file.save(filename, ContentFile(pdf_bytes), save=False)
    boarding_pass.qr_code_data = f"PNR:{booking_passenger.booking.pnr}|NAME:{booking_passenger.full_name()}"
    boarding_pass.save()

    if send_email and not boarding_pass.email_sent:
        send_templated_email(
            subject=f"Your Boarding Pass - {flight.flight_number}",
            template_name="boarding_pass_ready",
            context={"booking": booking_passenger.booking, "flight": flight, "passenger": booking_passenger},
            to_email=booking_passenger.email or booking_passenger.booking.contact_email,
            attachments=[(filename, pdf_bytes, "application/pdf")],
        )
        boarding_pass.email_sent = True
        boarding_pass.save(update_fields=["email_sent"])
    return boarding_pass


@transaction.atomic
def generate_boarding_passes_for_flight(flight, actor=None, request=None):
    """
    The automatic boarding-pass workflow triggered when a flight's status
    changes to BOARDING (see flights.views.staff_flight_mark_boarding):
      1. Find every confirmed booking on this flight.
      2. Generate a boarding pass (unique ID + QR code) for every passenger.
      3. Email each boarding pass to its passenger.
      4. Make them visible on the passenger dashboard (they already are,
         simply by existing - the dashboard checks for their presence).
      5. Stamp the flight so this never runs twice, even if staff later
         edit the flight again (e.g. a late gate change).

    Returns the list of BoardingPass objects created/refreshed. Safe to
    call more than once - idempotent both at the flight level (guarded by
    `boarding_passes_generated_at`) and the passenger level (get_or_create).
    """
    if flight.boarding_passes_generated_at is not None:
        return []  # already generated for this flight - do nothing

    bookings = Booking.objects.filter(
        flight=flight, status__in=[Booking.STATUS_CONFIRMED, Booking.STATUS_REBOOKED, Booking.STATUS_RESCHEDULED],
    ).prefetch_related("booking_passengers")

    boarding_passes = []
    for booking in bookings:
        for passenger in booking.booking_passengers.all():
            boarding_passes.append(generate_boarding_pass(passenger, send_email=True))

    flight.boarding_passes_generated_at = timezone.now()
    flight.save(update_fields=["boarding_passes_generated_at"])

    log_action(actor, "flights", "Boarding passes generated", f"{flight.flight_number}: {len(boarding_passes)} boarding pass(es)", request)
    return boarding_passes


# ---------------------------------------------------------------
# Voluntary cancellation (>=24h-before-departure refund rule)
# ---------------------------------------------------------------

@transaction.atomic
def cancel_booking(booking: Booking, actor=None, reason: str = "", request=None) -> Cancellation:
    """
    Voluntary passenger-initiated cancellation. Seats are released back to
    the flight, the booking (and its full history) is kept - never deleted.
    A Cancellation snapshot + Refund record are created: refund eligibility
    is decided once, right here, by the single project rule - cancelling
    24 hours or more before scheduled departure is refund-eligible;
    anything closer than that is not.
    """
    if not booking.is_active:
        raise ValueError("This booking is already cancelled or refunded.")

    from flights.models import Flight
    flight = Flight.objects.select_for_update().get(pk=booking.flight_id)
    flight.available_seats += booking.passenger_count
    flight.save(update_fields=["available_seats"])

    now = timezone.now()
    minutes_before_departure = int((flight.departure_datetime - now).total_seconds() // 60)
    refund_eligible = minutes_before_departure >= CANCELLATION_REFUND_WINDOW_HOURS * 60

    booking.status = Booking.STATUS_CANCELLED
    booking.save(update_fields=["status"])

    cancellation = Cancellation.objects.create(
        booking=booking,
        reason=reason,
        time_before_departure_minutes=minutes_before_departure,
        original_fare=booking.payment_amount,
        refund_eligible=refund_eligible,
    )
    refund = Refund.objects.create(
        cancellation=cancellation,
        amount=booking.payment_amount if refund_eligible else Decimal("0.00"),
        status=Refund.STATUS_PROCESSING if refund_eligible else Refund.STATUS_NOT_ELIGIBLE,
    )

    from .receipt_cancellation import build_cancellation_receipt_pdf
    pdf_bytes = build_cancellation_receipt_pdf(cancellation, refund)
    cancellation.pdf_file.save(f"cancellation_{booking.pnr}.pdf", ContentFile(pdf_bytes), save=True)

    Notification.objects.create(
        recipient=booking.passenger, notification_type=Notification.TYPE_BOOKING,
        title="Booking Cancelled",
        message=(
            f"Your booking {booking.pnr} has been cancelled. "
            + ("You are eligible for a refund." if refund_eligible else "This cancellation is not eligible for a refund (less than 24 hours before departure).")
        ),
        related_booking=booking,
    )
    send_templated_email(
        subject=f"Booking Cancelled - PNR {booking.pnr}",
        template_name="booking_cancelled",
        context={"booking": booking, "cancellation": cancellation, "refund": refund, "reason": reason},
        to_email=booking.contact_email or booking.passenger.email,
        attachments=[(f"cancellation_{booking.pnr}.pdf", pdf_bytes, "application/pdf")],
    )
    log_action(actor or booking.passenger, "bookings", "Booking cancelled (voluntary)", f"{booking.pnr}: refund_eligible={refund_eligible}", request)
    return cancellation


# ---------------------------------------------------------------
# Voluntary reschedule
# ---------------------------------------------------------------

@transaction.atomic
def reschedule_booking(booking: Booking, new_flight, actor=None, request=None) -> Booking:
    """
    Voluntary passenger-initiated reschedule onto a different flight. All
    passengers move together, each auto-assigned a seat on the new flight's
    aircraft (or the legacy grid if that flight has no aircraft configured).
    Distinct from `rebook_booking_group`, which is only used for airline-
    disruption recovery. The old booking is preserved for history
    (status RESCHEDULED). The new booking gets its own Booking Receipt;
    its boarding pass follows the same BOARDING-triggered rule as any
    other booking.
    """
    from flights.models import Flight

    flight = Flight.objects.select_for_update().get(pk=new_flight.pk)
    passenger_count = booking.passenger_count

    if flight.available_seats < passenger_count:
        raise ValueError(f"Only {flight.available_seats} seat(s) left on the selected flight.")
    if flight.status == Flight.STATUS_CANCELLED:
        raise ValueError("Cannot reschedule onto a cancelled flight.")

    old_flight = Flight.objects.select_for_update().get(pk=booking.flight_id)
    old_flight.available_seats += passenger_count
    old_flight.save(update_fields=["available_seats"])

    flight.available_seats -= passenger_count
    flight.save(update_fields=["available_seats"])

    original_passengers = list(booking.booking_passengers.all())
    seats = seats_for_group_move(flight, passenger_count)

    new_booking = Booking.objects.create(
        passenger=booking.passenger,
        flight=flight,
        rebooked_from=booking,
        rebook_reason=Booking.REBOOK_REASON_VOLUNTARY,
        payment_amount=Decimal("0.00"),
        payment_status=Booking.PAYMENT_PAID,
        contact_name=booking.contact_name, contact_email=booking.contact_email, contact_phone=booking.contact_phone,
    )

    total_fare = Decimal("0.00")
    category_names = set()
    for original_bp, seat_info in zip(original_passengers, seats):
        seat_number, category = seat_info
        fare = calculate_fare_for_seat_category(category, original_bp.passenger_type)
        total_fare += fare
        if category:
            category_names.add(category.name)
        BookingPassenger.objects.create(
            booking=new_booking,
            first_name=original_bp.first_name, middle_name=original_bp.middle_name, last_name=original_bp.last_name,
            date_of_birth=original_bp.date_of_birth, gender=original_bp.gender, nationality=original_bp.nationality,
            email=original_bp.email, phone_number=original_bp.phone_number,
            passenger_type=original_bp.passenger_type, is_primary=original_bp.is_primary,
            seat_number=seat_number, seat_category=category, fare=fare,
        )

    fare_difference = total_fare - booking.payment_amount
    new_booking.payment_amount = booking.payment_amount + max(fare_difference, Decimal("0.00"))
    new_booking.travel_class = ", ".join(sorted(category_names)) if category_names else "Economy"
    new_booking.save(update_fields=["payment_amount", "travel_class"])

    booking.status = Booking.STATUS_RESCHEDULED
    booking.save(update_fields=["status"])

    generate_booking_receipt(new_booking, send_email=False)

    Notification.objects.create(
        recipient=new_booking.passenger, notification_type=Notification.TYPE_REBOOKING,
        title="Flight Rescheduled",
        message=f"Your booking has been rescheduled to flight {flight.flight_number} ({flight.route_label}), new PNR {new_booking.pnr}.",
        related_booking=new_booking,
    )
    send_templated_email(
        subject="Flight Rescheduled",
        template_name="booking_rescheduled",
        context={"old_booking": booking, "new_booking": new_booking, "flight": flight, "fare_difference": fare_difference},
        to_email=new_booking.contact_email or new_booking.passenger.email,
        attachments=[(f"receipt_{new_booking.pnr}.pdf", getattr(new_booking, "_receipt_pdf_bytes", None) or new_booking.receipt_pdf.read(), "application/pdf")],
    )

    log_action(actor or booking.passenger, "bookings", "Booking rescheduled (voluntary)", f"{booking.pnr} -> {new_booking.pnr}", request)
    return new_booking


def seats_for_group_move(flight, count):
    """
    Auto-assign `count` seats for a group move (reschedule or disruption
    rebooking) on `flight`, preferring the same category mix where
    possible. Returns a list of (seat_number, SeatCategory-or-None) tuples.
    """
    if not flight.aircraft_id:
        return [(s, None) for s in _legacy_auto_seats(flight, count)]

    from flights.models import Seat
    taken = _taken_seat_numbers(flight)
    available = Seat.objects.filter(aircraft_id=flight.aircraft_id, is_blocked=False).exclude(
        seat_number__in=taken
    ).select_related("category").order_by("row_number", "column_letter")[:count]
    return [(s.seat_number, s.category) for s in available]


# ---------------------------------------------------------------
# Disruption-triggered rebooking (whole group moves together)
# ---------------------------------------------------------------

@transaction.atomic
def rebook_booking_group(original_booking: Booking, new_flight, actor=None, request=None) -> Booking:
    """
    Disruption-triggered rebooking: moves every passenger on the original
    booking onto `new_flight` together, in one transaction, with seat
    locking to avoid race conditions. Used by recovery.views after a staff
    member approves a passenger's rebooking request following a delay or
    cancellation (as opposed to `reschedule_booking`, which is voluntary).
    """
    from flights.models import Flight

    flight = Flight.objects.select_for_update().get(pk=new_flight.pk)
    passenger_count = original_booking.passenger_count

    if flight.available_seats < passenger_count:
        raise ValueError(f"Only {flight.available_seats} seat(s) available - this booking needs {passenger_count}.")
    if flight.status == Flight.STATUS_CANCELLED:
        raise ValueError("Cannot rebook onto a cancelled flight.")

    old_flight = Flight.objects.select_for_update().get(pk=original_booking.flight_id)
    old_flight.available_seats += passenger_count
    old_flight.save(update_fields=["available_seats"])

    flight.available_seats -= passenger_count
    flight.save(update_fields=["available_seats"])

    original_passengers = list(original_booking.booking_passengers.all())
    seats = seats_for_group_move(flight, passenger_count)

    new_booking = Booking.objects.create(
        passenger=original_booking.passenger,
        flight=flight,
        rebooked_from=original_booking,
        rebook_reason=Booking.REBOOK_REASON_DISRUPTION,
        payment_amount=original_booking.payment_amount,
        payment_status=Booking.PAYMENT_PAID,
        contact_name=original_booking.contact_name, contact_email=original_booking.contact_email,
        contact_phone=original_booking.contact_phone,
    )

    category_names = set()
    for original_bp, seat_info in zip(original_passengers, seats):
        seat_number, category = seat_info
        if category:
            category_names.add(category.name)
        BookingPassenger.objects.create(
            booking=new_booking,
            first_name=original_bp.first_name, middle_name=original_bp.middle_name, last_name=original_bp.last_name,
            date_of_birth=original_bp.date_of_birth, gender=original_bp.gender, nationality=original_bp.nationality,
            email=original_bp.email, phone_number=original_bp.phone_number,
            passenger_type=original_bp.passenger_type, is_primary=original_bp.is_primary,
            seat_number=seat_number, seat_category=category, fare=original_bp.fare,
        )
    new_booking.travel_class = ", ".join(sorted(category_names)) if category_names else original_booking.travel_class
    new_booking.save(update_fields=["travel_class"])

    original_booking.status = Booking.STATUS_REBOOKED
    original_booking.save(update_fields=["status"])

    generate_booking_receipt(new_booking, send_email=False)

    Notification.objects.create(
        recipient=new_booking.passenger, notification_type=Notification.TYPE_REBOOKING,
        title="Rebooking Confirmed",
        message=f"You have been rebooked onto flight {flight.flight_number} ({flight.route_label}), new PNR {new_booking.pnr}.",
        related_booking=new_booking,
    )
    send_templated_email(
        subject="Rebooking Confirmed",
        template_name="rebooking_confirmed",
        context={"old_booking": original_booking, "new_booking": new_booking, "flight": flight},
        to_email=new_booking.contact_email or new_booking.passenger.email,
        attachments=[(f"receipt_{new_booking.pnr}.pdf", getattr(new_booking, "_receipt_pdf_bytes", None) or new_booking.receipt_pdf.read(), "application/pdf")],
    )

    log_action(actor, "bookings", "Passenger group rebooked (disruption)", f"{original_booking.pnr} -> {new_booking.pnr}", request)
    return new_booking
