from django.db import models
from django.conf import settings
from django.utils import timezone
from core.models import generate_reference


class Voucher(models.Model):
    TYPE_MEAL = "MEAL"
    TYPE_HOTEL = "HOTEL"
    TYPE_TRANSPORT = "TRANSPORT"
    TYPE_CHOICES = [
        (TYPE_MEAL, "Meal Voucher"),
        (TYPE_HOTEL, "Hotel Voucher"),
        (TYPE_TRANSPORT, "Transportation Voucher"),
    ]

    STATUS_ACTIVE = "ACTIVE"
    STATUS_USED = "USED"
    STATUS_EXPIRED = "EXPIRED"
    STATUS_CANCELLED = "CANCELLED"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_USED, "Used"),
        (STATUS_EXPIRED, "Expired"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    voucher_code = models.CharField(max_length=16, unique=True, editable=False, db_index=True)
    voucher_type = models.CharField(max_length=12, choices=TYPE_CHOICES)
    passenger = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="vouchers")
    booking = models.ForeignKey("bookings.Booking", on_delete=models.CASCADE, related_name="vouchers")

    amount = models.DecimalField(max_digits=10, decimal_places=2)
    issue_date = models.DateTimeField(auto_now_add=True)
    expiry_date = models.DateField()
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    usage_instructions = models.TextField(blank=True)
    pdf_file = models.FileField(upload_to="vouchers/", blank=True, null=True)

    class Meta:
        ordering = ["-issue_date"]

    def save(self, *args, **kwargs):
        if not self.voucher_code:
            self.voucher_code = generate_reference("VCH", 8)
        super().save(*args, **kwargs)

    @property
    def is_expired(self):
        return timezone.now().date() > self.expiry_date

    def __str__(self):
        return f"{self.voucher_code} ({self.get_voucher_type_display()})"
