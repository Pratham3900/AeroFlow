"""QR code generation helpers, used by boarding passes and vouchers."""
import io
import qrcode
from django.core.files.base import ContentFile


def generate_qr_code_file(data: str, filename: str) -> ContentFile:
    """
    Build a QR code PNG encoding `data` and return it as a Django
    ContentFile ready to be saved to an ImageField or streamed into a PDF.
    """
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=2,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    return ContentFile(buffer.read(), name=filename)


def qr_code_reader_bytes(data: str) -> io.BytesIO:
    """Return an in-memory PNG buffer (no file save) - handy for embedding directly in a PDF."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=2,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer
