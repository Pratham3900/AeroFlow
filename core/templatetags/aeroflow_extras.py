from django import template

register = template.Library()

STATUS_MAP = {
    "SCHEDULED": "secondary",
    "ON_TIME": "success",
    "CONFIRMED": "success",
    "COMPLETED": "secondary",
    "ACTIVE": "success",
    "APPROVED": "success",
    "ELIGIBLE": "warning",
    "ISSUED": "success",
    "NOT_ELIGIBLE": "danger",
    "DELAYED": "warning",
    "PENDING": "warning",
    "PROCESSING": "warning",
    "BOARDING": "info",
    "REBOOKED": "info",
    "RESCHEDULED": "info",
    "USED": "secondary",
    "CANCELLED": "danger",
    "REJECTED": "danger",
    "EXPIRED": "danger",
    "DEPARTED": "primary",
    "REFUNDED": "dark",
}


@register.filter
def status_badge(value):
    return STATUS_MAP.get(value, "secondary")
