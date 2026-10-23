"""Voucher PDF generation using ReportLab, with an embedded QR code."""
import io
from reportlab.lib.pagesizes import A5, landscape
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor, white
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

from core.qr_utils import qr_code_reader_bytes

TYPE_COLORS = {
    "MEAL": HexColor("#e67e22"),
    "HOTEL": HexColor("#2c3e50"),
    "TRANSPORT": HexColor("#16a085"),
}


def build_voucher_pdf(voucher) -> bytes:
    page_size = landscape(A5)
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=page_size)
    width, height = page_size

    color = TYPE_COLORS.get(voucher.voucher_type, HexColor("#0b3d91"))
    c.setFillColor(color)
    c.rect(0, height - 28 * mm, width, 28 * mm, fill=1, stroke=0)
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(10 * mm, height - 15 * mm, "AeroFlow Airlines")
    c.setFont("Helvetica-Bold", 13)
    c.drawString(10 * mm, height - 23 * mm, f"{voucher.get_voucher_type_display().upper()}")

    y = height - 42 * mm
    c.setFillColor(HexColor("#111111"))
    c.setFont("Helvetica", 10)
    c.drawString(10 * mm, y, f"Voucher Code: {voucher.voucher_code}")
    y -= 7 * mm
    c.drawString(10 * mm, y, f"Passenger: {voucher.passenger.get_full_name() or voucher.passenger.username}")
    y -= 7 * mm
    c.drawString(10 * mm, y, f"Booking PNR: {voucher.booking.pnr}")
    y -= 7 * mm
    c.drawString(10 * mm, y, f"Value: Rs. {voucher.amount}")
    y -= 7 * mm
    c.drawString(10 * mm, y, f"Issued: {voucher.issue_date.strftime('%d %b %Y')}   Expiry: {voucher.expiry_date.strftime('%d %b %Y')}")
    y -= 7 * mm
    c.drawString(10 * mm, y, f"Status: {voucher.get_status_display()}")

    y -= 10 * mm
    c.setFont("Helvetica-Oblique", 8)
    instructions = voucher.usage_instructions or "Present this voucher (or its QR code) to the airline representative or partner vendor."
    c.drawString(10 * mm, y, instructions[:95])

    qr_data = f"VOUCHER:{voucher.voucher_code}|TYPE:{voucher.voucher_type}|PNR:{voucher.booking.pnr}|AMT:{voucher.amount}"
    qr_buffer = qr_code_reader_bytes(qr_data)
    qr_img = ImageReader(qr_buffer)
    qr_size = 30 * mm
    c.drawImage(qr_img, width - qr_size - 10 * mm, 10 * mm, qr_size, qr_size)

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer.read()
