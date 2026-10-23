"""Boarding pass PDF generation using ReportLab, with an embedded QR code.
One boarding pass is generated per BookingPassenger (not per booking)."""
import io
from reportlab.lib.pagesizes import landscape
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor, white
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

from core.qr_utils import qr_code_reader_bytes

BRAND_BLUE = HexColor("#0b3d91")
BRAND_ACCENT = HexColor("#1e88e5")
LIGHT_GREY = HexColor("#f2f4f7")


def build_boarding_pass_pdf(booking_passenger, boarding_pass) -> bytes:
    """
    Render a boarding-pass-style PDF for a single passenger, containing
    their details plus a QR code encoding the PNR, passenger name, flight
    number, date, and seat.
    """
    booking = booking_passenger.booking
    flight = booking.flight
    page_size = landscape((110 * mm, 220 * mm))
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=page_size)
    width, height = page_size

    # Header band
    c.setFillColor(BRAND_BLUE)
    c.rect(0, height - 22 * mm, width, 22 * mm, fill=1, stroke=0)
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(8 * mm, height - 14 * mm, flight.airline_name.upper())
    c.setFont("Helvetica", 9)
    c.drawRightString(width - 8 * mm, height - 14 * mm, "BOARDING PASS")

    y = height - 32 * mm
    c.setFillColor(HexColor("#111111"))

    def field(label, value, x, y, size=13, bold=True):
        c.setFont("Helvetica", 7)
        c.setFillColor(HexColor("#666666"))
        c.drawString(x, y + 4 * mm, label.upper())
        c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        c.setFillColor(HexColor("#111111"))
        c.drawString(x, y, str(value))

    field("Passenger", booking_passenger.full_name(), 8 * mm, y, 13)
    field("PNR", booking.pnr, width - 45 * mm, y, 13)

    y -= 14 * mm
    field("From", flight.origin.code, 8 * mm, y, 16)
    field("To", flight.destination.code, 40 * mm, y, 16)
    field("Flight", flight.flight_number, 72 * mm, y, 13)
    category_name = booking_passenger.seat_category.name if booking_passenger.seat_category else booking.travel_class
    field("Class", category_name, width - 30 * mm, y, 11)

    y -= 14 * mm
    field("Date", flight.departure_date.strftime("%d %b %Y"), 8 * mm, y, 11)
    field("Departure", flight.departure_time.strftime("%H:%M"), 40 * mm, y, 11)
    field("Boarding", boarding_pass.boarding_time.strftime("%H:%M") if boarding_pass.boarding_time else "--", 72 * mm, y, 11)
    field("Seat", booking_passenger.seat_number or "TBD", width - 30 * mm, y, 11)

    y -= 14 * mm
    field("Gate", flight.gate or "TBD", 8 * mm, y, 11)
    field("Terminal", flight.terminal or "-", 40 * mm, y, 11)
    field("Status", flight.get_status_display(), 72 * mm, y, 11)
    field("Type", booking_passenger.get_passenger_type_display(), width - 30 * mm, y, 11)

    # QR code
    qr_data = (
        f"PNR:{booking.pnr}|NAME:{booking_passenger.full_name()}|FLT:{flight.flight_number}"
        f"|DATE:{flight.departure_date}|SEAT:{booking_passenger.seat_number}"
    )
    qr_buffer = qr_code_reader_bytes(qr_data)
    qr_img = ImageReader(qr_buffer)
    qr_size = 32 * mm
    c.drawImage(qr_img, width - qr_size - 8 * mm, 8 * mm, qr_size, qr_size)

    c.setFont("Helvetica", 6)
    c.setFillColor(HexColor("#999999"))
    c.drawString(8 * mm, 6 * mm, "Please arrive at the gate at least 30 minutes before boarding time.")

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer.read()
