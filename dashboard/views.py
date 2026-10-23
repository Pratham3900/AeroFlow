from datetime import timedelta
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.utils import timezone
from django.db.models import Count, Sum

from accounts.models import User
from flights.models import Flight
from bookings.models import Booking
from recovery.models import RebookingRequest, RefundRequest, DisruptionRecord
from vouchers.models import Voucher
from core.utils import is_admin, is_staff_member, is_passenger, staff_required, admin_required


@login_required
def home(request):
    """Role-aware landing page: routes to the right dashboard."""
    user = request.user
    if is_admin(user):
        return admin_dashboard(request)
    if is_staff_member(user):
        return staff_dashboard(request)
    return passenger_dashboard(request)


@login_required
def passenger_dashboard(request):
    user = request.user
    bookings = Booking.objects.filter(passenger=user).select_related(
        "flight", "flight__origin", "flight__destination"
    ).prefetch_related("booking_passengers")
    today = timezone.now().date()

    upcoming = bookings.filter(flight__departure_date__gte=today).exclude(status__in=[Booking.STATUS_CANCELLED, Booking.STATUS_REFUNDED])
    completed = bookings.filter(status=Booking.STATUS_COMPLETED)
    delayed = bookings.filter(flight__status=Flight.STATUS_DELAYED)
    cancelled_flights = bookings.filter(status=Booking.STATUS_CANCELLED)
    pending_requests = (
        RebookingRequest.objects.filter(passenger=user, status=RebookingRequest.STATUS_PENDING).count()
        + RefundRequest.objects.filter(passenger=user, status=RefundRequest.STATUS_PENDING).count()
    )
    active_vouchers = Voucher.objects.filter(passenger=user, status=Voucher.STATUS_ACTIVE)
    next_booking = upcoming.order_by("flight__departure_date", "flight__departure_time").first()

    context = {
        "upcoming_count": upcoming.count(),
        "completed_count": completed.count(),
        "delayed_count": delayed.count(),
        "cancelled_count": cancelled_flights.count(),
        "pending_requests_count": pending_requests,
        "active_vouchers_count": active_vouchers.count(),
        "next_booking": next_booking,
        "recent_bookings": bookings[:6],
        "notifications": user.notifications.all()[:5],
    }
    return render(request, "passenger/dashboard.html", context)


@staff_required
def staff_dashboard(request):
    today = timezone.now().date()
    flights_today = Flight.objects.filter(departure_date=today)

    unresolved_bookings = Booking.objects.filter(
        disruptions__resolved=False
    ).distinct().prefetch_related("booking_passengers")
    affected_passenger_count = sum(b.passenger_count for b in unresolved_bookings)

    context = {
        "total_flights": Flight.objects.count(),
        "todays_flights": flights_today.count(),
        "delayed_flights": Flight.objects.filter(status=Flight.STATUS_DELAYED).count(),
        "cancelled_flights": Flight.objects.filter(status=Flight.STATUS_CANCELLED).count(),
        "affected_passengers": affected_passenger_count,
        "pending_rebookings": RebookingRequest.objects.filter(status=RebookingRequest.STATUS_PENDING).count(),
        "pending_refunds": RefundRequest.objects.filter(status=RefundRequest.STATUS_PENDING).count(),
        "active_vouchers": Voucher.objects.filter(status=Voucher.STATUS_ACTIVE).count(),
        "recent_disruptions": DisruptionRecord.objects.select_related("booking", "flight")[:8],
    }
    return render(request, "staff/dashboard.html", context)


@admin_required
def admin_dashboard(request):
    context = {
        "total_passengers": User.objects.filter(role=User.ROLE_PASSENGER).count(),
        "total_staff": User.objects.filter(role=User.ROLE_STAFF).count(),
        "total_flights": Flight.objects.count(),
        "total_bookings": Booking.objects.count(),
        "total_disruptions": DisruptionRecord.objects.count(),
        "total_refunds": RefundRequest.objects.count(),
        "total_rebookings": RebookingRequest.objects.count(),
        "total_vouchers": Voucher.objects.count(),
        "flight_status_breakdown": Flight.objects.values("status").annotate(count=Count("id")),
    }
    return render(request, "admin/dashboard.html", context)
