from django.db import models
from django.conf import settings
from django.utils import timezone


class Airport(models.Model):
    code = models.CharField(max_length=3, unique=True, help_text="IATA code, e.g. BOM")
    name = models.CharField(max_length=120)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100, blank=True)
    country = models.CharField(max_length=100, default="India")
    address = models.CharField(max_length=255, blank=True)
    contact_phone = models.CharField(max_length=30, blank=True)
    contact_email = models.EmailField(blank=True)
    checkin_info = models.CharField(max_length=255, blank=True, help_text="e.g. Check-in counters open 3 hours before departure")
    boarding_info = models.CharField(max_length=255, blank=True, help_text="e.g. Boarding gates close 20 minutes before departure")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} - {self.city}"


class Terminal(models.Model):
    """
    A terminal belonging to one Airport (e.g. "Terminal 1"). Dynamically
    managed by staff/admin from the airport edit page - see
    flights.views.staff_terminal_add. A flight's origin/destination
    terminal is a Terminal FK (flights.models.Flight), not free text, so
    the terminal dropdown shown when creating/editing a flight can never
    show a terminal that doesn't actually belong to the selected airport.
    """
    airport = models.ForeignKey(Airport, on_delete=models.CASCADE, related_name="terminals")
    name = models.CharField(max_length=60, help_text='e.g. "Terminal 1"')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["airport", "name"]
        # Prevents duplicate terminals for the same airport.
        unique_together = [("airport", "name")]

    def __str__(self):
        return self.name


class Gate(models.Model):
    """
    A gate belonging to one Terminal (e.g. "Gate 1" inside "Terminal 1").
    Dynamically managed by staff/admin - see flights.views.staff_gate_add.
    A flight's origin/destination gate is a Gate FK, so the gate dropdown
    shown when creating/editing a flight only ever lists gates that
    actually belong to the selected terminal.
    """
    terminal = models.ForeignKey(Terminal, on_delete=models.CASCADE, related_name="gates")
    name = models.CharField(max_length=60, help_text='e.g. "Gate 1"')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["terminal", "name"]
        # Prevents duplicate gates for the same terminal.
        unique_together = [("terminal", "name")]

    def __str__(self):
        return self.name


class Aircraft(models.Model):
    """
    An aircraft *type* (e.g. "Airbus A320") whose seat configuration is
    entirely admin-defined - see SeatCategory/Seat below. Multiple flights
    can be assigned the same Aircraft, reusing its seat map rather than
    duplicating seat data per flight.
    """
    name = models.CharField(max_length=100, help_text='e.g. "Airbus A320 - VT-AF101"')
    model = models.CharField(max_length=100, help_text='e.g. "Airbus A320"')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def total_capacity(self):
        return self.seats.filter(is_blocked=False).count()

    @property
    def category_breakdown(self):
        """Used by the admin UI and booking page: [(category, seat_count), ...]."""
        return [
            (cat, cat.seats.filter(is_blocked=False).count())
            for cat in self.seat_categories.all()
        ]


class SeatCategory(models.Model):
    """
    A seat category configured per-aircraft (Economy, Premium Economy,
    Business, First Class, or any custom name an admin creates). Seat
    categories are never hard-coded - only categories actually configured
    for a given aircraft are ever shown to passengers booking on it.
    """
    aircraft = models.ForeignKey(Aircraft, on_delete=models.CASCADE, related_name="seat_categories")
    name = models.CharField(max_length=60, help_text='e.g. "Economy", "Business", or any custom name')
    code = models.SlugField(max_length=30, help_text='Short code used internally, e.g. "economy"')
    display_order = models.PositiveIntegerField(default=0)
    price_multiplier = models.DecimalField(
        max_digits=4, decimal_places=2, default=1.0,
        help_text="Fare multiplier relative to the flight's base fare (e.g. 2.20 for Business).",
    )
    color = models.CharField(max_length=20, default="#1e88e5", help_text="Legend/seat-map colour (hex).")

    class Meta:
        ordering = ["aircraft", "display_order"]
        unique_together = [("aircraft", "code")]
        verbose_name_plural = "Seat categories"

    def __str__(self):
        return f"{self.aircraft.name} - {self.name}"

    @property
    def seat_count(self):
        return self.seats.filter(is_blocked=False).count()


class Seat(models.Model):
    """
    One physical seat on an Aircraft type. Seat *numbers* (e.g. "12A") are
    generated by the admin when configuring the aircraft (see
    flights.services.generate_seats_for_aircraft), never hard-coded in
    templates or views. `is_blocked` marks a seat permanently unavailable
    (e.g. removed for maintenance) independent of any particular flight's
    bookings - per-flight occupancy is derived from BookingPassenger rows.
    """
    aircraft = models.ForeignKey(Aircraft, on_delete=models.CASCADE, related_name="seats")
    category = models.ForeignKey(SeatCategory, on_delete=models.CASCADE, related_name="seats")
    seat_number = models.CharField(max_length=6, help_text='e.g. "12A"')
    row_number = models.PositiveIntegerField()
    column_letter = models.CharField(max_length=1)
    is_blocked = models.BooleanField(default=False, help_text="Permanently unavailable (e.g. maintenance), on every flight using this aircraft.")

    class Meta:
        ordering = ["row_number", "column_letter"]
        unique_together = [("aircraft", "seat_number")]
        indexes = [models.Index(fields=["aircraft", "seat_number"])]

    def __str__(self):
        return f"{self.aircraft.name} - {self.seat_number}"


class Flight(models.Model):
    STATUS_SCHEDULED = "SCHEDULED"
    STATUS_ON_TIME = "ON_TIME"
    STATUS_DELAYED = "DELAYED"
    STATUS_CANCELLED = "CANCELLED"
    STATUS_BOARDING = "BOARDING"
    STATUS_DEPARTED = "DEPARTED"
    STATUS_COMPLETED = "COMPLETED"

    STATUS_CHOICES = [
        (STATUS_SCHEDULED, "Scheduled"),
        (STATUS_ON_TIME, "On Time"),
        (STATUS_DELAYED, "Delayed"),
        (STATUS_BOARDING, "Boarding"),
        (STATUS_DEPARTED, "Departed"),
        (STATUS_CANCELLED, "Cancelled"),
        (STATUS_COMPLETED, "Completed"),
    ]
    # Statuses that represent the flight still being on its original schedule
    # (i.e. not disrupted, not yet boarding/departed/completed/cancelled).
    NON_DISRUPTED_STATUSES = (STATUS_SCHEDULED, STATUS_ON_TIME, STATUS_BOARDING, STATUS_DEPARTED, STATUS_COMPLETED)

    flight_number = models.CharField(max_length=10, unique=True, db_index=True)
    airline_name = models.CharField(max_length=100, default="AeroFlow Airlines")
    origin = models.ForeignKey(Airport, on_delete=models.PROTECT, related_name="departures")
    destination = models.ForeignKey(Airport, on_delete=models.PROTECT, related_name="arrivals")

    departure_date = models.DateField()
    departure_time = models.TimeField()
    arrival_date = models.DateField()
    arrival_time = models.TimeField()

    # Populated automatically once a delay is recorded; original values preserved.
    original_departure_datetime = models.DateTimeField(null=True, blank=True)
    updated_departure_datetime = models.DateTimeField(null=True, blank=True)
    # Cumulative total delay in minutes - see flights.services.add_flight_delay().
    # Every staff update ADDS to this value; it is never overwritten/reset.
    delay_minutes = models.PositiveIntegerField(default=0)
    delay_reason = models.CharField(max_length=255, blank=True)
    cancellation_reason = models.CharField(max_length=255, blank=True)

    # Origin/destination airport-side operational details, editable independently
    # and changeable after creation (gate/terminal changes trigger notifications).
    origin_terminal = models.ForeignKey(
        Terminal, on_delete=models.SET_NULL, null=True, blank=True, related_name="departing_flights",
        help_text="Must belong to the selected origin airport.",
    )
    origin_gate = models.ForeignKey(
        Gate, on_delete=models.SET_NULL, null=True, blank=True, related_name="departing_flights",
        help_text="Must belong to the selected origin terminal.",
    )
    destination_terminal = models.ForeignKey(
        Terminal, on_delete=models.SET_NULL, null=True, blank=True, related_name="arriving_flights",
        help_text="Must belong to the selected destination airport.",
    )
    destination_gate = models.ForeignKey(
        Gate, on_delete=models.SET_NULL, null=True, blank=True, related_name="arriving_flights",
        help_text="Must belong to the selected destination terminal.",
    )
    boarding_time = models.TimeField(null=True, blank=True)

    # Set once the automatic boarding-pass batch has run for this flight
    # (triggered by the ON_TIME/DELAYED -> BOARDING transition). Prevents
    # duplicate boarding-pass generation/emails if staff edit the flight
    # again afterward (e.g. a late gate change).
    boarding_passes_generated_at = models.DateTimeField(null=True, blank=True)

    aircraft = models.ForeignKey(Aircraft, on_delete=models.PROTECT, related_name="flights", null=True, blank=True)

    seat_capacity = models.PositiveIntegerField(default=180)
    available_seats = models.PositiveIntegerField(default=180)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_SCHEDULED, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["departure_date", "departure_time"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["origin", "destination", "departure_date"]),
        ]

    def save(self, *args, **kwargs):
        # Keep capacity/available_seats in sync with the assigned aircraft the
        # first time it's set, without clobbering seats already sold.
        if self.aircraft_id and not self.pk:
            self.seat_capacity = self.aircraft.total_capacity
            self.available_seats = self.aircraft.total_capacity
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.flight_number} ({self.origin.code} → {self.destination.code})"

    @property
    def departure_datetime(self):
        dt = timezone.datetime.combine(self.departure_date, self.departure_time)
        return timezone.make_aware(dt) if timezone.is_naive(dt) else dt

    @property
    def is_disrupted(self):
        return self.status in (self.STATUS_DELAYED, self.STATUS_CANCELLED)

    @property
    def route_label(self):
        return f"{self.origin.code} → {self.destination.code}"

    # Backwards-compatible aliases: earlier revisions of this project had a
    # single `gate`/`terminal` field that implicitly meant "departure gate".
    @property
    def gate(self):
        return self.origin_gate

    @property
    def terminal(self):
        return self.origin_terminal


class DelayRecord(models.Model):
    """
    One row per delay UPDATE (never overwritten/deleted), so every flight
    keeps a complete, auditable delay history. `additional_delay_minutes`
    is what staff enters each time; `total_delay_minutes` is the running
    cumulative total after that update - see flights.services.add_flight_delay().
    """
    FACILITY_NONE = "NONE"
    FACILITY_MEAL = "MEAL"
    FACILITY_MEAL_HOTEL_TRANSPORT = "MEAL_HOTEL_TRANSPORT"
    FACILITY_CHOICES = [
        (FACILITY_NONE, "No facility"),
        (FACILITY_MEAL, "Meal Voucher"),
        (FACILITY_MEAL_HOTEL_TRANSPORT, "Meal + Hotel + Transportation"),
    ]

    flight = models.ForeignKey(Flight, on_delete=models.CASCADE, related_name="delay_records")
    previous_delay_minutes = models.PositiveIntegerField()
    additional_delay_minutes = models.PositiveIntegerField()
    total_delay_minutes = models.PositiveIntegerField()
    facility_level = models.CharField(max_length=25, choices=FACILITY_CHOICES, default=FACILITY_NONE)
    reason = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="delay_updates"
    )

    class Meta:
        ordering = ["flight", "created_at"]

    def __str__(self):
        return f"{self.flight.flight_number}: +{self.additional_delay_minutes}min -> {self.total_delay_minutes}min total"
