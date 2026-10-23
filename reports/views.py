import io
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.db.models import Q
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm

from core.utils import staff_required
from flights.models import Flight
from recovery.models import RebookingRequest, RefundRequest, DisruptionRecord
from vouchers.models import Voucher


def _daily_stats(target_date):
    flights = Flight.objects.filter(departure_date=target_date)
    disrupted_bookings = (
        DisruptionRecord.objects.filter(created_at__date=target_date)
        .values_list("booking_id", flat=True).distinct()
    )
    from bookings.models import Booking
    affected_passenger_count = sum(
        b.passenger_count for b in Booking.objects.filter(id__in=disrupted_bookings).prefetch_related("booking_passengers")
    )
    return {
        "date": target_date,
        "total_flights": flights.count(),
        "delayed_flights": flights.filter(status=Flight.STATUS_DELAYED).count(),
        "cancelled_flights": flights.filter(status=Flight.STATUS_CANCELLED).count(),
        "completed_flights": flights.filter(status=Flight.STATUS_COMPLETED).count(),
        "affected_passengers": affected_passenger_count,
        "rebookings": RebookingRequest.objects.filter(requested_at__date=target_date).count(),
        "refunds": RefundRequest.objects.filter(request_date__date=target_date).count(),
        "vouchers": Voucher.objects.filter(issue_date__date=target_date).count(),
    }


@staff_required
def daily_report(request):
    date_str = request.GET.get("date")
    target_date = timezone.datetime.strptime(date_str, "%Y-%m-%d").date() if date_str else timezone.now().date()
    stats = _daily_stats(target_date)

    flight_ops = {
        "total_flights": Flight.objects.count(),
        "delayed": Flight.objects.filter(status=Flight.STATUS_DELAYED).count(),
        "cancelled": Flight.objects.filter(status=Flight.STATUS_CANCELLED).count(),
        "completed": Flight.objects.filter(status=Flight.STATUS_COMPLETED).count(),
    }
    passenger_recovery = {
        "rebooking_requests": RebookingRequest.objects.count(),
        "refund_requests": RefundRequest.objects.count(),
        "voucher_usage": Voucher.objects.filter(status=Voucher.STATUS_USED).count(),
        "vouchers_active": Voucher.objects.filter(status=Voucher.STATUS_ACTIVE).count(),
    }

    return render(request, "reports/daily_report.html", {
        "stats": stats, "flight_ops": flight_ops, "passenger_recovery": passenger_recovery,
    })


@staff_required
def daily_report_pdf(request):
    date_str = request.GET.get("date")
    target_date = timezone.datetime.strptime(date_str, "%Y-%m-%d").date() if date_str else timezone.now().date()
    stats = _daily_stats(target_date)

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    c.setFont("Helvetica-Bold", 16)
    c.drawString(20 * mm, height - 20 * mm, "AeroFlow - Daily Operational Report")
    c.setFont("Helvetica", 10)
    c.drawString(20 * mm, height - 28 * mm, f"Date: {stats['date'].strftime('%d %B %Y')}")

    rows = [
        ("Total Flights", stats["total_flights"]),
        ("Delayed Flights", stats["delayed_flights"]),
        ("Cancelled Flights", stats["cancelled_flights"]),
        ("Completed Flights", stats["completed_flights"]),
        ("Affected Passengers", stats["affected_passengers"]),
        ("Rebookings", stats["rebookings"]),
        ("Refunds", stats["refunds"]),
        ("Vouchers Issued", stats["vouchers"]),
    ]

    y = height - 45 * mm
    c.setFont("Helvetica-Bold", 11)
    c.drawString(20 * mm, y, "Metric")
    c.drawString(120 * mm, y, "Value")
    c.line(20 * mm, y - 2 * mm, 180 * mm, y - 2 * mm)
    y -= 8 * mm
    c.setFont("Helvetica", 10)
    for label, value in rows:
        c.drawString(20 * mm, y, label)
        c.drawString(120 * mm, y, str(value))
        y -= 7 * mm

    c.showPage()
    c.save()
    buffer.seek(0)
    response = HttpResponse(buffer.read(), content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="aeroflow_daily_report_{stats["date"]}.pdf"'
    return response
