from django.db import models
from django.conf import settings


class Notification(models.Model):
    TYPE_DELAY = "DELAY"
    TYPE_CANCELLATION = "CANCELLATION"
    TYPE_REBOOKING = "REBOOKING"
    TYPE_REFUND = "REFUND"
    TYPE_VOUCHER = "VOUCHER"
    TYPE_BOOKING = "BOOKING"
    TYPE_GENERAL = "GENERAL"
    TYPE_CHOICES = [
        (TYPE_DELAY, "Delay"),
        (TYPE_CANCELLATION, "Cancellation"),
        (TYPE_REBOOKING, "Rebooking"),
        (TYPE_REFUND, "Refund"),
        (TYPE_VOUCHER, "Voucher"),
        (TYPE_BOOKING, "Booking"),
        (TYPE_GENERAL, "General"),
    ]

    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    notification_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default=TYPE_GENERAL)
    title = models.CharField(max_length=150)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    related_booking = models.ForeignKey(
        "bookings.Booking", on_delete=models.SET_NULL, null=True, blank=True, related_name="notifications"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["recipient", "is_read"])]

    def __str__(self):
        return f"{self.title} -> {self.recipient}"
