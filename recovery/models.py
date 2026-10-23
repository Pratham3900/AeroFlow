from django.db import models
from django.conf import settings


class DisruptionRecord(models.Model):
    """
    Created automatically whenever a flight is marked DELAYED or CANCELLED.
    One record per affected booking - this is what drives the passenger's
    "Recovery" page and the eligibility calculations.
    """
    TYPE_DELAY = "DELAY"
    TYPE_CANCELLATION = "CANCELLATION"
    TYPE_CHOICES = [(TYPE_DELAY, "Delay"), (TYPE_CANCELLATION, "Cancellation")]

    booking = models.ForeignKey("bookings.Booking", on_delete=models.CASCADE, related_name="disruptions")
    flight = models.ForeignKey("flights.Flight", on_delete=models.CASCADE, related_name="disruptions")
    disruption_type = models.CharField(max_length=15, choices=TYPE_CHOICES)
    delay_minutes = models.PositiveIntegerField(default=0)
    reason = models.CharField(max_length=255, blank=True)

    eligible_for_recovery = models.BooleanField(default=False)
    eligible_for_rebooking = models.BooleanField(default=False)
    eligible_for_refund = models.BooleanField(default=False)
    eligible_for_meal_voucher = models.BooleanField(default=False)
    eligible_for_hotel_voucher = models.BooleanField(default=False)
    eligible_for_transport_voucher = models.BooleanField(default=False)

    resolved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_disruption_type_display()} - {self.booking.pnr}"


class PassengerFacility(models.Model):
    """
    Tracks, per booking and facility type, whether that facility is
    ELIGIBLE (unlocked by the cumulative delay but not yet claimed) or
    ISSUED (an actual Voucher has been generated). This is updated in
    place - never duplicated - as a flight's cumulative delay grows and
    crosses further thresholds (see flights.services.calculate_facility_eligibility,
    the single centralized eligibility rule used everywhere).
    """
    TYPE_MEAL = "MEAL"
    TYPE_HOTEL = "HOTEL"
    TYPE_TRANSPORT = "TRANSPORT"
    TYPE_CHOICES = [(TYPE_MEAL, "Meal"), (TYPE_HOTEL, "Hotel"), (TYPE_TRANSPORT, "Transportation")]

    STATUS_ELIGIBLE = "ELIGIBLE"
    STATUS_ISSUED = "ISSUED"
    STATUS_CHOICES = [(STATUS_ELIGIBLE, "Eligible"), (STATUS_ISSUED, "Issued")]

    booking = models.ForeignKey("bookings.Booking", on_delete=models.CASCADE, related_name="facilities")
    facility_type = models.CharField(max_length=12, choices=TYPE_CHOICES)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_ELIGIBLE)
    voucher = models.OneToOneField(
        "vouchers.Voucher", on_delete=models.SET_NULL, null=True, blank=True, related_name="facility_record"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["booking", "facility_type"]
        unique_together = [("booking", "facility_type")]
        verbose_name_plural = "Passenger facilities"

    def __str__(self):
        return f"{self.booking.pnr}: {self.get_facility_type_display()} ({self.get_status_display()})"


class RebookingRequest(models.Model):
    STATUS_PENDING = "PENDING"
    STATUS_APPROVED = "APPROVED"
    STATUS_REJECTED = "REJECTED"
    STATUS_COMPLETED = "COMPLETED"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
        (STATUS_COMPLETED, "Completed"),
    ]

    original_booking = models.ForeignKey(
        "bookings.Booking", on_delete=models.CASCADE, related_name="rebooking_requests"
    )
    requested_flight = models.ForeignKey(
        "flights.Flight", on_delete=models.CASCADE, related_name="rebooking_requests"
    )
    passenger = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="rebooking_requests")
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_PENDING)
    staff_remarks = models.TextField(blank=True)
    new_booking = models.OneToOneField(
        "bookings.Booking", on_delete=models.SET_NULL, null=True, blank=True, related_name="rebooking_source"
    )
    requested_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    processed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="rebookings_processed"
    )

    class Meta:
        ordering = ["-requested_at"]

    def __str__(self):
        return f"Rebooking {self.original_booking.pnr} -> {self.requested_flight.flight_number}"


class RefundRequest(models.Model):
    STATUS_PENDING = "PENDING"
    STATUS_APPROVED = "APPROVED"
    STATUS_PROCESSING = "PROCESSING"
    STATUS_COMPLETED = "COMPLETED"
    STATUS_REJECTED = "REJECTED"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_PROCESSING, "Processing"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_REJECTED, "Rejected"),
    ]

    refund_id = models.CharField(max_length=16, unique=True, editable=False)
    booking = models.ForeignKey("bookings.Booking", on_delete=models.CASCADE, related_name="refund_requests")
    passenger = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="refund_requests")
    reason = models.TextField()
    requested_amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_PENDING)
    staff_remarks = models.TextField(blank=True)
    request_date = models.DateTimeField(auto_now_add=True)
    processed_date = models.DateTimeField(null=True, blank=True)
    processed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="refunds_processed"
    )

    class Meta:
        ordering = ["-request_date"]

    def save(self, *args, **kwargs):
        if not self.refund_id:
            from core.models import generate_reference
            self.refund_id = generate_reference("RF", 6)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.refund_id} - {self.booking.pnr}"
