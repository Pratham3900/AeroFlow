"""
Centralized, reusable email sending. All AeroFlow notification emails
(welcome, delay, cancellation, rebooking, refund, voucher, boarding pass)
go through `send_templated_email` so templates stay consistent and
credentials stay in environment variables (see aeroflow/settings.py).
"""
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.conf import settings


def send_templated_email(subject: str, template_name: str, context: dict, to_email: str, attachments=None):
    """
    Render templates/emails/<template_name>.html with `context`, send it as
    HTML with a plain-text fallback. `attachments` is an optional list of
    (filename, content_bytes, mimetype) tuples (e.g. a boarding pass PDF).
    """
    if not to_email:
        return False

    html_body = render_to_string(f"emails/{template_name}.html", context)
    text_body = strip_tags(html_body)

    msg = EmailMultiAlternatives(
        subject=f"AeroFlow - {subject}",
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[to_email],
    )
    msg.attach_alternative(html_body, "text/html")

    for attachment in attachments or []:
        filename, content, mimetype = attachment
        msg.attach(filename, content, mimetype)

    msg.send(fail_silently=True)
    return True
