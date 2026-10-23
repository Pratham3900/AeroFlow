from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.http import Http404, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST, require_GET

from core.utils import staff_required, log_action
from core.email_utils import send_templated_email
from bookings.models import Booking
from bookings.services import rebook_booking_group
from vouchers.services import issue_voucher
from vouchers.models import Voucher
from notifications.models import Notification
from .models import DisruptionRecord, RebookingRequest, RefundRequest
from .forms import RefundRequestForm, RefundDecisionForm
from .services import get_alternative_flights, update_refund_status


# ---------------------------------------------------------------
# Passenger-facing recovery
# ---------------------------------------------------------------

@login_required
def recovery_page(request, booking_id):
    booking = get_object_or_404(Booking.objects.select_related("flight"), pk=booking_id)
    if booking.passenger_id != request.user.id:
        raise Http404

    disruption = booking.disruptions.order_by("-created_at").first()
    alternatives = []
    if disruption and disruption.eligible_for_rebooking:
        alternatives = get_alternative_flights(booking.flight, min_seats=booking.passenger_count)

    existing_vouchers = booking.vouchers.all()
    pending_rebooking = booking.rebooking_requests.filter(status=RebookingRequest.STATUS_PENDING).first()
    refund_requests = booking.refund_requests.all()

    return render(request, "recovery/recovery_page.html", {
        "booking": booking,
        "disruption": disruption,
        "alternatives": alternatives,
        "existing_vouchers": existing_vouchers,
        "pending_rebooking": pending_rebooking,
        "refund_requests": refund_requests,
        "voucher_types": Voucher.TYPE_CHOICES,
    })


@login_required
@require_POST
def request_rebooking(request, booking_id):
    booking = get_object_or_404(Booking, pk=booking_id)
    if booking.passenger_id != request.user.id:
        raise Http404

    disruption = booking.disruptions.order_by("-created_at").first()
    if not disruption or not disruption.eligible_for_rebooking:
        messages.error(request, "This booking is not currently eligible for rebooking.")
        return redirect("recovery:recovery_page", booking_id=booking.id)

    flight_id = request.POST.get("flight_id")
    from flights.models import Flight
    new_flight = get_object_or_404(Flight, pk=flight_id)

    if new_flight.available_seats < booking.passenger_count:
        messages.error(request, f"Sorry, only {new_flight.available_seats} seat(s) left - this booking needs {booking.passenger_count}.")
        return redirect("recovery:recovery_page", booking_id=booking.id)

    rebooking_request = RebookingRequest.objects.create(
        original_booking=booking, requested_flight=new_flight, passenger=request.user,
    )
    log_action(request.user, "recovery", "Rebooking requested", f"{booking.pnr} -> {new_flight.flight_number}", request)
    messages.success(request, "Your rebooking request has been submitted and is awaiting staff approval.")
    return redirect("recovery:recovery_page", booking_id=booking.id)


@login_required
def submit_refund_request(request, booking_id):
    booking = get_object_or_404(Booking, pk=booking_id)
    if booking.passenger_id != request.user.id:
        raise Http404

    disruption = booking.disruptions.order_by("-created_at").first()
    if not disruption or not disruption.eligible_for_refund:
        messages.error(request, "This booking is not currently eligible for a refund.")
        return redirect("recovery:recovery_page", booking_id=booking.id)

    if request.method == "POST":
        form = RefundRequestForm(request.POST)
        if form.is_valid():
            refund = form.save(commit=False)
            refund.booking = booking
            refund.passenger = request.user
            refund.save()

            Notification.objects.create(
                recipient=request.user, notification_type=Notification.TYPE_REFUND,
                title="Refund Request Received", message=f"Your refund request {refund.refund_id} has been received.",
                related_booking=booking,
            )
            send_templated_email(
                subject="Refund Request Received", template_name="refund_status",
                context={"refund": refund, "booking": booking, "message": "We have received your refund request and will review it shortly."},
                to_email=request.user.email,
            )
            log_action(request.user, "recovery", "Refund requested", f"{refund.refund_id} for {booking.pnr}", request)
            messages.success(request, f"Refund request {refund.refund_id} submitted.")
            return redirect("recovery:recovery_page", booking_id=booking.id)
    else:
        form = RefundRequestForm(initial={"requested_amount": booking.payment_amount})
    return render(request, "recovery/refund_form.html", {"form": form, "booking": booking})


@login_required
@require_POST
def request_voucher(request, booking_id, voucher_type):
    booking = get_object_or_404(Booking, pk=booking_id)
    if booking.passenger_id != request.user.id:
        raise Http404

    disruption = booking.disruptions.order_by("-created_at").first()
    eligibility_map = {
        Voucher.TYPE_MEAL: "eligible_for_meal_voucher",
        Voucher.TYPE_HOTEL: "eligible_for_hotel_voucher",
        Voucher.TYPE_TRANSPORT: "eligible_for_transport_voucher",
    }
    field = eligibility_map.get(voucher_type)
    if not disruption or not field or not getattr(disruption, field, False):
        messages.error(request, "You are not eligible for this voucher.")
        return redirect("recovery:recovery_page", booking_id=booking.id)

    if booking.vouchers.filter(voucher_type=voucher_type, status=Voucher.STATUS_ACTIVE).exists():
        messages.info(request, "You already have an active voucher of this type for this booking.")
        return redirect("recovery:recovery_page", booking_id=booking.id)

    issue_voucher(booking, voucher_type, actor=request.user, request=request)
    messages.success(request, "Voucher generated and emailed to you.")
    return redirect("recovery:recovery_page", booking_id=booking.id)


# ---------------------------------------------------------------
# Staff: manage recovery requests
# ---------------------------------------------------------------

@staff_required
def staff_requests_dashboard(request):
    pending_rebookings = RebookingRequest.objects.filter(status=RebookingRequest.STATUS_PENDING).select_related(
        "original_booking", "requested_flight", "passenger")
    pending_refunds = RefundRequest.objects.filter(status=RefundRequest.STATUS_PENDING).select_related("booking", "passenger")
    # Shows the outcome of the last 10 approved/rejected rebooking requests,
    # so staff/admin can immediately confirm on this same page (including
    # after a refresh) that Approve/Reject actually persisted the correct
    # status, instead of the request simply vanishing from the pending list
    # with no visible confirmation.
    recently_processed_rebookings = RebookingRequest.objects.exclude(
        status=RebookingRequest.STATUS_PENDING
    ).select_related("original_booking", "requested_flight", "passenger", "processed_by").order_by("-processed_at")[:10]
    return render(request, "staff/requests_dashboard.html", {
        "pending_rebookings": pending_rebookings, "pending_refunds": pending_refunds,
        "recently_processed_rebookings": recently_processed_rebookings,
    })


@staff_required
@require_POST
@transaction.atomic
def staff_approve_rebooking(request, pk):
    """
    Approve a passenger's pending rebooking request. This is the fix for
    the previously-broken approval flow: the request's status now
    correctly becomes APPROVED (it was being set to COMPLETED, a status
    the "pending requests" dashboard never distinguished from "approved"
    in the UI, making it look like nothing had happened). The underlying
    booking move itself still runs through the existing
    bookings.services.rebook_booking_group(), unchanged.
    """
    rebooking_request = get_object_or_404(RebookingRequest, pk=pk, status=RebookingRequest.STATUS_PENDING)
    try:
        new_booking = rebook_booking_group(rebooking_request.original_booking, rebooking_request.requested_flight, actor=request.user, request=request)
        rebooking_request.status = RebookingRequest.STATUS_APPROVED
        rebooking_request.new_booking = new_booking
        from django.utils import timezone
        rebooking_request.processed_at = timezone.now()
        rebooking_request.processed_by = request.user
        rebooking_request.save()
        messages.success(request, f"Rebooking approved. New PNR {new_booking.pnr} generated and emailed to the passenger.")
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("recovery:staff_requests_dashboard")


@staff_required
@require_POST
def staff_reject_rebooking(request, pk):
    """
    Reject a passenger's pending rebooking request. Previously this saved
    the REJECTED status (correctly) but never actually emailed the
    passenger, unlike every other status-change flow in the app (refund
    updates, approvals, etc.) - this now sends the same kind of rejection
    email those other flows use.
    """
    rebooking_request = get_object_or_404(RebookingRequest, pk=pk, status=RebookingRequest.STATUS_PENDING)
    from django.utils import timezone
    rebooking_request.status = RebookingRequest.STATUS_REJECTED
    rebooking_request.staff_remarks = request.POST.get("remarks", "")
    rebooking_request.processed_at = timezone.now()
    rebooking_request.processed_by = request.user
    rebooking_request.save()

    Notification.objects.create(
        recipient=rebooking_request.passenger, notification_type=Notification.TYPE_REBOOKING,
        title="Rebooking Request Rejected",
        message=f"Your rebooking request for flight {rebooking_request.requested_flight.flight_number} was not approved.",
        related_booking=rebooking_request.original_booking,
    )
    send_templated_email(
        subject="Rebooking Request Rejected",
        template_name="rebooking_rejected",
        context={"rebooking_request": rebooking_request, "booking": rebooking_request.original_booking},
        to_email=rebooking_request.original_booking.contact_email or rebooking_request.passenger.email,
    )
    log_action(request.user, "recovery", "Rebooking rejected", rebooking_request.staff_remarks, request)
    messages.success(request, "Rebooking request rejected.")
    return redirect("recovery:staff_requests_dashboard")


@staff_required
@require_POST
def staff_update_refund(request, pk):
    refund = get_object_or_404(RefundRequest, pk=pk)
    form = RefundDecisionForm(request.POST)
    if form.is_valid():
        update_refund_status(refund, form.cleaned_data["status"], staff_user=request.user, remarks=form.cleaned_data["remarks"], request=request)
        messages.success(request, f"Refund {refund.refund_id} updated to {form.cleaned_data['status']}.")
    return redirect("recovery:staff_requests_dashboard")
