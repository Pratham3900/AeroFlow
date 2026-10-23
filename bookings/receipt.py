"""
Booking Receipt PDF - generated immediately when a booking is confirmed.

This is deliberately a different document, both visually and in content,
from the Boarding Pass (bookings/pdf.py), which is only ever generated
later, once the flight's status reaches BOARDING (see
flights.views.staff_flight_mark_boarding). A receipt lists every
passenger and the full fare breakdown; a boarding pass is one-per-passenger
and only exists once boarding opens.
"""
import io
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor, white
from reportlab.pdfgen import canvas

BRAND_NAVY = HexColor("#0b3d91")
LIGHT_GREY = HexColor("#f2f4f7")
TEXT_DARK = HexColor("#111111")
TEXT_MUTED = HexColor("#666666")


def build_booking_receipt_pdf(booking) -> bytes:
    flight = booking.flight
    passengers = list(booking.booking_passengers.all())

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    margin = 18 * mm

    # Header
    c.setFillColor(BRAND_NAVY)
    c.rect(0, height - 30 * mm, width, 30 * mm, fill=1, stroke=0)
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 20)
    c.drawString(margin, height - 15 * mm, f"{flight.airline_name}")
    c.setFont("Helvetica", 11)
    c.drawString(margin, height - 23 * mm, "FLIGHT BOOKING CONFIRMATION / RECEIPT")
    c.setFont("Helvetica-Bold", 12)
    c.drawRightString(width - margin, height - 15 * mm, f"PNR: {booking.pnr}")
    c.setFont("Helvetica", 9)
    c.drawRightString(width - margin, height - 23 * mm, f"Booking ID: {booking.id}")

    y = height - 42 * mm
    c.setFillColor(TEXT_DARK)

    def label_value(label, value, x, y, width_hint=90 * mm, size=10):
        c.setFont("Helvetica", 7.5)
        c.setFillColor(TEXT_MUTED)
        c.drawString(x, y + 4 * mm, label.upper())
        c.setFont("Helvetica-Bold", size)
        c.setFillColor(TEXT_DARK)
        c.drawString(x, y, str(value)[:60])

    def section_header(text, y):
        c.setFillColor(LIGHT_GREY)
        c.rect(margin, y - 6 * mm, width - 2 * margin, 8 * mm, fill=1, stroke=0)
        c.setFillColor(BRAND_NAVY)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(margin + 2 * mm, y - 4 * mm, text)
        return y - 13 * mm

    y = section_header("FLIGHT DETAILS", y)
    label_value("Flight Number", flight.flight_number, margin, y)
    label_value("Aircraft", flight.aircraft.name if flight.aircraft else "-", margin + 95 * mm, y)
    y -= 12 * mm
    label_value("Origin", f"{flight.origin.city} ({flight.origin.code}) - Terminal {flight.origin_terminal or 'TBD'}, Gate {flight.origin_gate or 'TBD'}", margin, y)
    y -= 12 * mm
    label_value("Destination", f"{flight.destination.city} ({flight.destination.code}) - Terminal {flight.destination_terminal or 'TBD'}, Gate {flight.destination_gate or 'TBD'}", margin, y)
    y -= 12 * mm
    label_value("Departure", f"{flight.departure_date} at {flight.departure_time}", margin, y)
    label_value("Arrival", f"{flight.arrival_date} at {flight.arrival_time}", margin + 95 * mm, y)
    y -= 12 * mm
    label_value("Boarding Time", flight.boarding_time.strftime("%H:%M") if flight.boarding_time else "To be announced", margin, y)
    label_value("Flight Status", flight.get_status_display(), margin + 95 * mm, y)

    y -= 18 * mm
    y = section_header(f"PASSENGERS ({len(passengers)})", y)
    c.setFont("Helvetica-Bold", 8)
    c.setFillColor(TEXT_MUTED)
    c.drawString(margin, y, "NAME")
    c.drawString(margin + 65 * mm, y, "TYPE")
    c.drawString(margin + 95 * mm, y, "SEAT")
    c.drawString(margin + 120 * mm, y, "CATEGORY")
    c.drawString(margin + 155 * mm, y, "FARE")
    y -= 6 * mm
    c.setFont("Helvetica", 9)
    c.setFillColor(TEXT_DARK)
    for p in passengers:
        if y < 40 * mm:
            c.showPage()
            y = height - margin
        c.drawString(margin, y, p.full_name()[:35])
        c.drawString(margin + 65 * mm, y, p.get_passenger_type_display())
        c.drawString(margin + 95 * mm, y, p.seat_number or "TBD")
        c.drawString(margin + 120 * mm, y, p.seat_category.name if p.seat_category else booking.travel_class)
        c.drawString(margin + 155 * mm, y, f"Rs. {p.fare}")
        y -= 6 * mm

    y -= 10 * mm
    y = section_header("PAYMENT SUMMARY", y)
    label_value("Total Fare", f"Rs. {booking.payment_amount}", margin, y)
    label_value("Payment Status", booking.get_payment_status_display(), margin + 95 * mm, y)
    y -= 12 * mm
    label_value("Booking Date", booking.booking_date.strftime("%d %b %Y, %H:%M"), margin, y)
    label_value("Booking Status", booking.get_status_display(), margin + 95 * mm, y)

    y -= 18 * mm
    c.setFillColor(HexColor("#fff3cd"))
    c.rect(margin, y - 14 * mm, width - 2 * margin, 16 * mm, fill=1, stroke=0)
    c.setFillColor(HexColor("#664d03"))
    c.setFont("Helvetica-Bold", 9)
    c.drawString(margin + 3 * mm, y - 5 * mm, "Your booking is confirmed.")
    c.setFont("Helvetica", 9)
    c.drawString(margin + 3 * mm, y - 10 * mm, "Your boarding pass will be generated automatically when the airline changes the flight status to Boarding,")
    c.drawString(margin + 3 * mm, y - 13.5 * mm, "and emailed to you / made available in your AeroFlow dashboard at that time.")

    y -= 24 * mm
    y = section_header("CANCELLATION / REFUND POLICY", y)
    c.setFont("Helvetica", 8.5)
    c.setFillColor(TEXT_DARK)
    policy_lines = [
        "- Cancellations made 24 hours or more before scheduled departure are eligible for a refund.",
        "- Cancellations made less than 24 hours before scheduled departure are not eligible for a refund.",
        "- If the airline delays this flight by more than 120 minutes (cumulative), you become eligible for a",
        "  meal voucher; 240 minutes or more makes you eligible for meal + hotel + transportation facilities.",
        "- If the airline cancels this flight, you may choose rebooking, a full refund, or applicable vouchers.",
    ]
    for line in policy_lines:
        c.drawString(margin, y, line)
        y -= 5 * mm

    c.setFont("Helvetica", 7)
    c.setFillColor(TEXT_MUTED)
    c.drawString(margin, 12 * mm, "This is a booking receipt, not a boarding pass. It cannot be used to board the aircraft.")

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer.read()
