from django.db import models
from django.conf import settings
from core.models import generate_reference


class Booking(models.Model):
    """
    A Booking is the trip / PNR container. It belongs to one Django User
    account (the "primary booker" - the person who was logged in when the
    booking was made) but can carry multiple BookingPassenger records, so
    one account can book seats for a spouse, friends, children, etc. in a
    single reservation.
    """
    STATUS_CONFIRMED = "CONFIRMED"
    STATUS_REBOOKED = "REBOOKED"
    STATUS_RESCHEDULED = "RESCHEDULED"
    STATUS_CANCELLED = "CANCELLED"
    STATUS_REFUNDED = "REFUNDED"
    STATUS_COMPLETED = "COMPLETED"

    STATUS_CHOICES = [
        (STATUS_CONFIRMED, "Confirmed"),
        (STATUS_REBOOKED, "Rebooked"),
        (STATUS_RESCHEDULED, "Rescheduled"),
        (STATUS_CANCELLED, "Cancelled"),
        (STATUS_REFUNDED, "Refunded"),
        (STATUS_COMPLETED, "Completed"),
    ]

    PAYMENT_PENDING = "PENDING"
    PAYMENT_PAID = "PAID"
    PAYMENT_REFUNDED = "REFUNDED"
    PAYMENT_STATUS_CHOICES = [
        (PAYMENT_PENDING, "Pending"),
        (PAYMENT_PAID, "Paid"),
        (PAYMENT_REFUNDED, "Refunded"),
    ]

    pnr = models.CharField(max_length=10, unique=True, db_index=True, editable=False)

    # The account that made the booking - the "primary booker". They are
    # not necessarily a passenger themselves (see BookingPassenger.is_primary).
    passenger = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="bookings",
        help_text="The logged-in account that made this booking (the primary booker).",
    )
    flight = models.ForeignKey("flights.Flight", on_delete=models.PROTECT, related_name="bookings")

    # Booking contact details, shown on the booking summary/emails. Defaults
    # to the primary booker's own details but can be overridden per booking.
    contact_name = models.CharField(max_length=150, blank=True)
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=20, blank=True)

    # When a booking is rebooked (disruption) or rescheduled (voluntary)
    # onto a new flight, we keep the chain visible via this self-FK.
    rebooked_from = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="rebooked_to"
    )
    REBOOK_REASON_DISRUPTION = "DISRUPTION"
    REBOOK_REASON_VOLUNTARY = "VOLUNTARY"
    REBOOK_REASON_CHOICES = [
        (REBOOK_REASON_DISRUPTION, "Airline Disruption Recovery"),
        (REBOOK_REASON_VOLUNTARY, "Voluntary Reschedule"),
    ]
    rebook_reason = models.CharField(max_length=12, choices=REBOOK_REASON_CHOICES, blank=True)

    # NOT a fixed choices field: seat categories are entirely admin-defined
    # per aircraft (flights.models.SeatCategory), so this just stores the
    # resulting category name(s) for display (e.g. "Economy", "Business",
    # or "Mixed" if passengers in this booking hold seats in different
    # categories). Set automatically from the passengers' chosen seats -
    # see bookings.services.create_booking().
    travel_class = models.CharField(max_length=60, blank=True, default="Economy")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_CONFIRMED, db_index=True)

    payment_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    payment_status = models.CharField(max_length=10, choices=PAYMENT_STATUS_CHOICES, default=PAYMENT_PAID)

    # The Booking Receipt (generated immediately on confirmation) is a
    # different document from the Boarding Pass (generated only once the
    # flight reaches BOARDING status - see bookings/receipt.py and
    # flights.views.staff_flight_mark_boarding).
    receipt_pdf = models.FileField(upload_to="receipts/", blank=True, null=True)
    receipt_generated_at = models.DateTimeField(null=True, blank=True)

    booking_date = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-booking_date"]
        indexes = [models.Index(fields=["status"]), models.Index(fields=["pnr"]), models.Index(fields=["passenger", "status"])]

    def save(self, *args, **kwargs):
        if not self.pnr:
            self.pnr = generate_reference("PNR", 6)
        if not self.contact_name and self.passenger_id:
            self.contact_name = self.passenger.get_full_name() or self.passenger.username
            self.contact_email = self.contact_email or self.passenger.email
            self.contact_phone = self.contact_phone or self.passenger.phone_number
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.pnr} - {self.flight.flight_number}"

    @property
    def passenger_count(self):
        return self.booking_passengers.count()

    @property
    def is_group_booking(self):
        return self.passenger_count > 1

    @property
    def is_active(self):
        return self.status not in (self.STATUS_CANCELLED, self.STATUS_REFUNDED)


class BookingPassenger(models.Model):
    """
    One traveller within a Booking. A single Booking (one PNR) can have
    many BookingPassenger rows, so the primary booker can book for a
    spouse, friends, children, etc. in the same reservation.
    """
    TYPE_ADULT = "ADULT"
    TYPE_CHILD = "CHILD"
    TYPE_INFANT = "INFANT"
    TYPE_CHOICES = [
        (TYPE_ADULT, "Adult"),
        (TYPE_CHILD, "Child"),
        (TYPE_INFANT, "Infant"),
    ]

    GENDER_CHOICES = [("M", "Male"), ("F", "Female"), ("O", "Other")]

    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name="booking_passengers")

    first_name = models.CharField(max_length=100)
    middle_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100)
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=1, choices=GENDER_CHOICES, blank=True)
    nationality = models.CharField(max_length=60, blank=True)
    email = models.EmailField(blank=True)
    phone_number = models.CharField(max_length=20, blank=True)

    passenger_type = models.CharField(max_length=10, choices=TYPE_CHOICES, default=TYPE_ADULT)
    is_primary = models.BooleanField(
        default=False, help_text="True if this passenger row represents the logged-in primary booker themself."
    )

    seat_number = models.CharField(max_length=6, blank=True)
    seat_category = models.ForeignKey(
        "flights.SeatCategory", on_delete=models.SET_NULL, null=True, blank=True, related_name="booked_passengers",
        help_text="The seat category actually selected for this passenger (derived from their chosen seat).",
    )
    fare = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="This passenger's individual fare contribution.")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-is_primary", "id"]
        constraints = [
            models.UniqueConstraint(fields=["booking", "seat_number"], name="unique_seat_per_booking",
                                     condition=~models.Q(seat_number="")),
        ]

    def full_name(self):
        parts = [self.first_name, self.middle_name, self.last_name]
        return " ".join(p for p in parts if p)

    def __str__(self):
        return f"{self.full_name()} ({self.booking.pnr})"


class BoardingPass(models.Model):
    """One boarding pass per passenger, not per booking - a 3-passenger
    booking produces 3 separate boarding passes, each with its own QR code.
    Only ever generated once the flight's status reaches BOARDING - see
    flights.views.staff_flight_mark_boarding - never at booking time."""
    booking_passenger = models.OneToOneField(
        BookingPassenger, on_delete=models.CASCADE, related_name="boarding_pass"
    )
    boarding_pass_id = models.CharField(max_length=16, unique=True, editable=False)
    boarding_time = models.TimeField(null=True, blank=True)
    pdf_file = models.FileField(upload_to="boarding_passes/", blank=True, null=True)
    qr_code_data = models.TextField(blank=True)
    email_sent = models.BooleanField(default=False)
    generated_at = models.DateTimeField(auto_now_add=True)
    regenerated_count = models.PositiveIntegerField(default=0)

    def save(self, *args, **kwargs):
        if not self.boarding_pass_id:
            self.boarding_pass_id = generate_reference("BP", 8)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Boarding pass for {self.booking_passenger}"


class Cancellation(models.Model):
    """
    Snapshot of a passenger-initiated (voluntary) booking cancellation,
    kept as a permanent record distinct from the Booking row itself (whose
    status just flips to CANCELLED) so a proper Cancellation Receipt can
    always be regenerated. Refund eligibility is decided once, at the
    moment of cancellation, by the >=24h-before-departure rule - see
    bookings.services.cancel_booking().
    """
    booking = models.OneToOneField(Booking, on_delete=models.CASCADE, related_name="cancellation")
    reason = models.TextField(blank=True)
    cancelled_at = models.DateTimeField(auto_now_add=True)
    time_before_departure_minutes = models.IntegerField(help_text="Minutes between cancellation and scheduled departure (can be negative if past departure).")
    original_fare = models.DecimalField(max_digits=10, decimal_places=2)
    refund_eligible = models.BooleanField(default=False)
    pdf_file = models.FileField(upload_to="cancellations/", blank=True, null=True)

    def __str__(self):
        return f"Cancellation for {self.booking.pnr}"


class Refund(models.Model):
    """
    The refund arising directly from a *voluntary* cancellation (see
    Cancellation above). This is intentionally a separate, simpler model
    from recovery.RefundRequest, which drives the staff-approval queue for
    refunds arising from an *airline* delay/cancellation - the two refund
    origins are kept distinct per the project's workflow rules, even
    though both ultimately mark the booking PAYMENT_REFUNDED on completion.
    """
    STATUS_NOT_ELIGIBLE = "NOT_ELIGIBLE"
    STATUS_PROCESSING = "PROCESSING"
    STATUS_COMPLETED = "COMPLETED"
    STATUS_CHOICES = [
        (STATUS_NOT_ELIGIBLE, "Not Eligible"),
        (STATUS_PROCESSING, "Processing"),
        (STATUS_COMPLETED, "Completed"),
    ]

    cancellation = models.OneToOneField(Cancellation, on_delete=models.CASCADE, related_name="refund")
    amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default=STATUS_NOT_ELIGIBLE)
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Refund for {self.cancellation.booking.pnr} ({self.get_status_display()})"
