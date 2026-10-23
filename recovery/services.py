"""
Automation engine for flight disruptions.

This module is the heart of the "not just CRUD" requirement: whenever a
staff member updates a flight's delay, cancels it, or changes its gate/
terminal, these functions are called (see flights/views.py) and
automatically:

  1. Record/update the disruption on every affected booking.
  2. Calculate each passenger's facility eligibility using ONE centralized
     rule (flights.services.calculate_facility_eligibility) driven by the
     flight's cumulative delay - never a duplicated/local copy of the rule.
  3. Create/update PassengerFacility rows (never duplicated as delay grows).
  4. Create in-app notifications.
  5. Send the correct email for the event (delay/cancellation/gate change).
  6. Log the action to the audit trail.
"""
from django.utils import timezone
from django.db import transaction

from core.utils import log_action
from core.email_utils import send_templated_email
from bookings.models import Booking
from notifications.models import Notification
from flights.models import DelayRecord
from flights.services import add_flight_delay, calculate_facility_eligibility, facility_levels_included
from .models import DisruptionRecord, PassengerFacility


def _notify(passenger, notification_type, title, message, booking=None):
    Notification.objects.create(
        recipient=passenger,
        notification_type=notification_type,
        title=title,
        message=message,
        related_booking=booking,
    )


def _active_bookings_for_flight(flight):
    return Booking.objects.filter(
        flight=flight
    ).exclude(status__in=[Booking.STATUS_CANCELLED, Booking.STATUS_REFUNDED]).select_related(
        "passenger"
    ).prefetch_related("booking_passengers")


def _sync_facilities_for_booking(booking, facility_level):
    """
    Upsert (never duplicate) PassengerFacility rows for a booking based on
    the current facility_level. A facility already ISSUED is left alone
    (issuing is a one-way action, handled by vouchers.services.issue_voucher);
    a facility that's merely ELIGIBLE is created if missing.
    """
    included = facility_levels_included(facility_level)
    type_map = {"MEAL": PassengerFacility.TYPE_MEAL, "HOTEL": PassengerFacility.TYPE_HOTEL, "TRANSPORT": PassengerFacility.TYPE_TRANSPORT}
    for key in included:
        PassengerFacility.objects.get_or_create(
            booking=booking, facility_type=type_map[key],
            defaults={"status": PassengerFacility.STATUS_ELIGIBLE},
        )


@transaction.atomic
def process_flight_delay(flight, additional_minutes: int, reason: str, actor=None, request=None):
    """
    Automatic workflow triggered when staff add an ADDITIONAL delay to a
    flight. The cumulative total is computed by flights.services.add_flight_delay
    (which NEVER overwrites the previous total - see that function's
    docstring), and facility eligibility is derived from that one
    centralized rule and applied identically to every affected booking.
    Returns the list of DisruptionRecord objects touched (created or updated).
    """
    delay_record = add_flight_delay(flight, additional_minutes, reason, actor=actor)
    flight.refresh_from_db()
    total_delay = flight.delay_minutes
    facility_level = delay_record.facility_level

    records = []
    for booking in _active_bookings_for_flight(flight):
        # One DisruptionRecord per (booking, DELAY) - updated in place on
        # every subsequent delay update rather than creating a new row
        # each time, matching the "do not duplicate" requirement.
        record, _ = DisruptionRecord.objects.update_or_create(
            booking=booking, flight=flight, disruption_type=DisruptionRecord.TYPE_DELAY,
            defaults=dict(
                delay_minutes=total_delay,
                reason=reason,
                eligible_for_recovery=facility_level != DelayRecord.FACILITY_NONE,
                eligible_for_rebooking=facility_level != DelayRecord.FACILITY_NONE,
                eligible_for_refund=facility_level != DelayRecord.FACILITY_NONE,
                eligible_for_meal_voucher="MEAL" in facility_levels_included(facility_level),
                eligible_for_hotel_voucher="HOTEL" in facility_levels_included(facility_level),
                eligible_for_transport_voucher="TRANSPORT" in facility_levels_included(facility_level),
            ),
        )
        records.append(record)
        _sync_facilities_for_booking(booking, facility_level)

        message = _delay_notification_message(flight, total_delay, facility_level)
        _notify(booking.passenger, Notification.TYPE_DELAY, f"Flight {flight.flight_number} Delayed", message, booking)

        send_templated_email(
            subject=f"Flight {flight.flight_number} Delay Notification",
            template_name="flight_delay",
            context={
                "booking": booking, "flight": flight, "delay_minutes": total_delay,
                "additional_delay_minutes": additional_minutes, "reason": reason,
                "facility_level": facility_level,
                "facility_meal": "MEAL" in facility_levels_included(facility_level),
                "facility_hotel": "HOTEL" in facility_levels_included(facility_level),
                "facility_transport": "TRANSPORT" in facility_levels_included(facility_level),
                "passengers": booking.booking_passengers.all(),
            },
            to_email=booking.contact_email or booking.passenger.email,
        )

    log_action(
        actor, "recovery", f"Flight {flight.flight_number} delay updated",
        f"+{additional_minutes}min -> {total_delay}min total. Facility: {facility_level}. {len(records)} booking(s) affected.",
        request,
    )
    return records


def _delay_notification_message(flight, total_delay_minutes, facility_level):
    """Exact wording rules per the project's delay-facility policy (section 20)."""
    base = f"Your flight {flight.flight_number} ({flight.route_label}) is delayed by {total_delay_minutes} minutes."
    if facility_level == DelayRecord.FACILITY_NONE:
        return base + " Currently, no passenger facility/voucher is applicable."
    if facility_level == DelayRecord.FACILITY_MEAL:
        return base + " You are eligible for: Meal Voucher."
    return base + " You are eligible for: Meal, Hotel Accommodation, and Transportation."


@transaction.atomic
def process_flight_cancellation(flight, reason: str, actor=None, request=None):
    """
    Automatic workflow triggered when a flight's status becomes CANCELLED.
    All active bookings on the flight become eligible for full recovery
    (rebooking, refund, and vouchers).
    """
    flight.status = flight.STATUS_CANCELLED
    flight.cancellation_reason = reason
    flight.save()

    records = []
    for booking in _active_bookings_for_flight(flight):
        record, _ = DisruptionRecord.objects.update_or_create(
            booking=booking, flight=flight, disruption_type=DisruptionRecord.TYPE_CANCELLATION,
            defaults=dict(
                reason=reason,
                eligible_for_recovery=True,
                eligible_for_rebooking=True,
                eligible_for_refund=True,
                eligible_for_meal_voucher=True,
                eligible_for_hotel_voucher=True,
                eligible_for_transport_voucher=True,
            ),
        )
        records.append(record)
        for facility_type in (PassengerFacility.TYPE_MEAL, PassengerFacility.TYPE_HOTEL, PassengerFacility.TYPE_TRANSPORT):
            PassengerFacility.objects.get_or_create(booking=booking, facility_type=facility_type, defaults={"status": PassengerFacility.STATUS_ELIGIBLE})

        message = (
            f"Your flight {flight.flight_number} ({flight.route_label}) has been cancelled. "
            f"Reason: {reason or 'Operational issue'}. Please choose a recovery option."
        )
        _notify(booking.passenger, Notification.TYPE_CANCELLATION, f"Flight {flight.flight_number} Cancelled", message, booking)

        send_templated_email(
            subject=f"Flight {flight.flight_number} Cancellation Notice",
            template_name="flight_cancellation",
            context={"booking": booking, "flight": flight, "reason": reason, "passengers": booking.booking_passengers.all()},
            to_email=booking.contact_email or booking.passenger.email,
        )

    log_action(
        actor, "recovery", f"Flight {flight.flight_number} marked CANCELLED",
        f"Reason: {reason}. {len(records)} bookings affected.",
        request,
    )
    return records


@transaction.atomic
def process_gate_terminal_change(flight, updates: dict, actor=None, request=None):
    """
    Dynamic gate/terminal/boarding-time update. Every affected passenger is
    notified in-app and by email with a clear "old -> new" summary for
    whichever fields actually changed.
    """
    changes = []
    field_labels = {
        "origin_terminal": "Origin Terminal", "origin_gate": "Origin Gate",
        "destination_terminal": "Destination Terminal", "destination_gate": "Destination Gate",
        "boarding_time": "Boarding Time",
    }
    for field, label in field_labels.items():
        new_value = updates.get(field)
        old_value = getattr(flight, field)
        if new_value != old_value and new_value not in (None, ""):
            changes.append((label, old_value, new_value))
            setattr(flight, field, new_value)

    if not changes:
        return []

    flight.save()

    bookings = list(_active_bookings_for_flight(flight))
    for booking in bookings:
        change_lines = [f"{label}: {old or '-'} -> {new}" for label, old, new in changes]
        message = f"Flight {flight.flight_number} information updated - " + "; ".join(change_lines)
        _notify(booking.passenger, Notification.TYPE_GENERAL, f"Flight {flight.flight_number} Updated", message, booking)

        send_templated_email(
            subject=f"Flight {flight.flight_number} - Gate/Terminal Update",
            template_name="gate_change",
            context={"booking": booking, "flight": flight, "changes": changes},
            to_email=booking.contact_email or booking.passenger.email,
        )

    log_action(actor, "flights", f"Flight {flight.flight_number} gate/terminal updated", "; ".join(f"{l}: {o}->{n}" for l, o, n in changes), request)
    return changes


def update_refund_status(refund_request, new_status, staff_user=None, remarks="", request=None):
    """
    Staff action: approve / reject / mark-processing / complete a refund
    request. Automatically updates the booking's payment status on
    completion and emails the passenger on every status change.
    """
    from .models import RefundRequest

    refund_request.status = new_status
    refund_request.staff_remarks = remarks or refund_request.staff_remarks
    refund_request.processed_by = staff_user
    refund_request.processed_date = timezone.now()
    refund_request.save()

    booking = refund_request.booking
    if new_status == RefundRequest.STATUS_COMPLETED:
        booking.payment_status = Booking.PAYMENT_REFUNDED
        booking.status = Booking.STATUS_REFUNDED
        booking.save(update_fields=["payment_status", "status"])

    status_messages = {
        RefundRequest.STATUS_APPROVED: "Your refund request has been approved and is being processed.",
        RefundRequest.STATUS_PROCESSING: "Your refund is now being processed by our finance team.",
        RefundRequest.STATUS_COMPLETED: "Your refund has been completed and credited to your original payment method.",
        RefundRequest.STATUS_REJECTED: "Your refund request has been reviewed and could not be approved.",
    }
    message = status_messages.get(new_status, f"Your refund request status changed to {new_status}.")

    _notify(refund_request.passenger, Notification.TYPE_REFUND, f"Refund {refund_request.refund_id} - {new_status.title()}", message, booking)

    send_templated_email(
        subject=f"Refund {refund_request.refund_id} - {new_status.title()}",
        template_name="refund_status",
        context={"refund": refund_request, "booking": booking, "message": message},
        to_email=refund_request.passenger.email,
    )

    log_action(
        staff_user, "recovery", f"Refund {refund_request.refund_id} {new_status}",
        remarks, request,
    )
    return refund_request


def get_alternative_flights(flight, limit=10, min_seats=1):
    """
    Alternative-flight search used by the rebooking UI: same origin/destination,
    a future departure, enough seats for the whole booking party, and an
    active (non-cancelled) status.
    """
    from flights.models import Flight
    return Flight.objects.filter(
        origin=flight.origin,
        destination=flight.destination,
        available_seats__gte=min_seats,
    ).exclude(
        id=flight.id
    ).exclude(
        status=Flight.STATUS_CANCELLED
    ).filter(
        departure_date__gte=timezone.now().date()
    ).order_by("departure_date", "departure_time")[:limit]
