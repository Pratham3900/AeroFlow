"""Flight Cancellation Receipt PDF - generated when a passenger voluntarily
cancels their own booking (bookings.services.cancel_booking). Distinct
document from both the Booking Receipt and the Boarding Pass."""
import io
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor, white
from reportlab.pdfgen import canvas

BRAND_RED = HexColor("#b02a37")
TEXT_DARK = HexColor("#111111")
TEXT_MUTED = HexColor("#666666")


def build_cancellation_receipt_pdf(cancellation, refund) -> bytes:
    booking = cancellation.booking
    flight = booking.flight
    passengers = list(booking.booking_passengers.all())

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    margin = 18 * mm

    c.setFillColor(BRAND_RED)
    c.rect(0, height - 28 * mm, width, 28 * mm, fill=1, stroke=0)
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(margin, height - 14 * mm, "FLIGHT CANCELLATION RECEIPT")
    c.setFont("Helvetica", 10)
    c.drawString(margin, height - 21 * mm, f"{flight.airline_name}")
    c.setFont("Helvetica-Bold", 11)
    c.drawRightString(width - margin, height - 14 * mm, f"PNR: {booking.pnr}")
    c.drawRightString(width - margin, height - 21 * mm, f"Booking ID: {booking.id}")

    y = height - 40 * mm
    c.setFillColor(TEXT_DARK)

    def row(label, value, y):
        c.setFont("Helvetica", 8)
        c.setFillColor(TEXT_MUTED)
        c.drawString(margin, y, label.upper())
        c.setFont("Helvetica-Bold", 10)
        c.setFillColor(TEXT_DARK)
        c.drawString(margin + 65 * mm, y, str(value))
        return y - 7 * mm

    passenger_names = ", ".join(p.full_name() for p in passengers)
    y = row("Passenger(s)", passenger_names[:60], y)
    y = row("Flight Number", flight.flight_number, y)
    y = row("Route", flight.route_label, y)
    y = row("Scheduled Departure", f"{flight.departure_date} {flight.departure_time}", y)
    y = row("Seats", ", ".join(p.seat_number or "-" for p in passengers), y)
    y = row("Original Fare", f"Rs. {cancellation.original_fare}", y)
    y = row("Cancellation Date/Time", cancellation.cancelled_at.strftime("%d %b %Y, %H:%M"), y)
    y = row("Cancellation Reason", cancellation.reason or "-", y)

    hours = cancellation.time_before_departure_minutes // 60
    minutes = cancellation.time_before_departure_minutes % 60
    time_label = f"{hours}h {minutes}m before departure" if cancellation.time_before_departure_minutes >= 0 else "After scheduled departure"
    y = row("Time Before Departure", time_label, y)

    y -= 5 * mm
    c.setFillColor(HexColor("#d1e7dd") if cancellation.refund_eligible else HexColor("#f8d7da"))
    c.rect(margin, y - 24 * mm, width - 2 * margin, 26 * mm, fill=1, stroke=0)
    c.setFillColor(HexColor("#0f5132") if cancellation.refund_eligible else HexColor("#842029"))
    c.setFont("Helvetica-Bold", 11)
    c.drawString(margin + 3 * mm, y - 6 * mm, "Refund Eligibility: " + ("ELIGIBLE" if cancellation.refund_eligible else "NOT ELIGIBLE"))
    c.setFont("Helvetica", 9)
    c.drawString(margin + 3 * mm, y - 13 * mm, f"Refund Amount: Rs. {refund.amount}")
    c.drawString(margin + 3 * mm, y - 19 * mm, f"Refund Status: {refund.get_status_display()}")
    if not cancellation.refund_eligible:
        c.setFont("Helvetica", 8)
        c.drawString(margin + 3 * mm, y - 23.5 * mm, "(Cancelled less than 24 hours before scheduled departure)")

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer.read()
