from django.contrib import admin
from .models import Booking, BookingPassenger, BoardingPass, Cancellation, Refund


class BookingPassengerInline(admin.TabularInline):
    model = BookingPassenger
    extra = 0
    fields = ("first_name", "last_name", "passenger_type", "seat_number", "is_primary")


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ("pnr", "passenger", "flight", "passenger_count", "travel_class", "status", "payment_status", "booking_date")
    list_filter = ("status", "payment_status", "travel_class")
    search_fields = ("pnr", "passenger__username", "flight__flight_number", "contact_name", "contact_email")
    inlines = [BookingPassengerInline]

    @admin.display(description="Passengers")
    def passenger_count(self, obj):
        return obj.passenger_count


@admin.register(BookingPassenger)
class BookingPassengerAdmin(admin.ModelAdmin):
    list_display = ("first_name", "last_name", "booking", "passenger_type", "seat_number", "is_primary")
    search_fields = ("first_name", "last_name", "booking__pnr")
    list_filter = ("passenger_type",)


@admin.register(BoardingPass)
class BoardingPassAdmin(admin.ModelAdmin):
    list_display = ("boarding_pass_id", "booking_passenger", "boarding_time", "email_sent", "generated_at")
    search_fields = ("boarding_pass_id", "booking_passenger__first_name", "booking_passenger__last_name")


@admin.register(Cancellation)
class CancellationAdmin(admin.ModelAdmin):
    list_display = ("booking", "cancelled_at", "refund_eligible", "time_before_departure_minutes")
    list_filter = ("refund_eligible",)
    search_fields = ("booking__pnr",)


@admin.register(Refund)
class RefundAdmin(admin.ModelAdmin):
    list_display = ("cancellation", "amount", "status", "created_at", "processed_at")
    list_filter = ("status",)
