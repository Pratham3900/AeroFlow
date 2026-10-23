"""Voucher issuance service: creates Voucher rows, PDFs, and emails them."""
from django.utils import timezone
from django.core.files.base import ContentFile

from core.utils import get_setting, log_action
from core.email_utils import send_templated_email
from .models import Voucher
from .pdf import build_voucher_pdf

VOUCHER_SETTINGS = {
    Voucher.TYPE_MEAL: ("meal_voucher_amount", "Present this voucher at any airport restaurant partner."),
    Voucher.TYPE_HOTEL: ("hotel_voucher_amount", "Present this voucher at the designated airport partner hotel desk."),
    Voucher.TYPE_TRANSPORT: ("transport_voucher_amount", "Present this voucher to the airport transportation desk."),
}


def issue_voucher(booking, voucher_type, actor=None, request=None) -> Voucher:
    amount_key, instructions = VOUCHER_SETTINGS[voucher_type]
    amount = get_setting(amount_key, default=500, cast=float)
    validity_days = get_setting("voucher_validity_days", default=30, cast=int)

    voucher = Voucher.objects.create(
        voucher_type=voucher_type,
        passenger=booking.passenger,
        booking=booking,
        amount=amount,
        expiry_date=timezone.now().date() + timezone.timedelta(days=validity_days),
        usage_instructions=instructions,
    )

    pdf_bytes = build_voucher_pdf(voucher)
    voucher.pdf_file.save(f"voucher_{voucher.voucher_code}.pdf", ContentFile(pdf_bytes), save=True)

    from notifications.models import Notification
    Notification.objects.create(
        recipient=voucher.passenger,
        notification_type=Notification.TYPE_VOUCHER,
        title=f"{voucher.get_voucher_type_display()} Issued",
        message=f"A {voucher.get_voucher_type_display().lower()} worth Rs. {amount} has been issued (code {voucher.voucher_code}).",
        related_booking=booking,
    )

    send_templated_email(
        subject=f"{voucher.get_voucher_type_display()} Issued",
        template_name="voucher_issued",
        context={"voucher": voucher, "booking": booking},
        to_email=voucher.passenger.email,
        attachments=[(f"voucher_{voucher.voucher_code}.pdf", pdf_bytes, "application/pdf")],
    )

    log_action(actor, "vouchers", f"{voucher.voucher_type} voucher generated", f"{voucher.voucher_code} for {booking.pnr}", request)

    # Mark the corresponding PassengerFacility row ISSUED (never duplicated -
    # this updates the existing ELIGIBLE row created by recovery.services).
    from recovery.models import PassengerFacility
    PassengerFacility.objects.filter(booking=booking, facility_type=voucher_type).update(
        status=PassengerFacility.STATUS_ISSUED, voucher=voucher,
    )

    return voucher
