from django.contrib import admin
from .models import Airport, Terminal, Gate, Aircraft, SeatCategory, Seat, Flight, DelayRecord


class TerminalInline(admin.TabularInline):
    model = Terminal
    extra = 0


@admin.register(Airport)
class AirportAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "city", "state", "country", "is_active")
    list_filter = ("country", "is_active")
    search_fields = ("code", "name", "city")
    inlines = [TerminalInline]


class GateInline(admin.TabularInline):
    model = Gate
    extra = 0


@admin.register(Terminal)
class TerminalAdmin(admin.ModelAdmin):
    list_display = ("name", "airport")
    list_filter = ("airport",)
    search_fields = ("name", "airport__code")
    inlines = [GateInline]


@admin.register(Gate)
class GateAdmin(admin.ModelAdmin):
    list_display = ("name", "terminal")
    list_filter = ("terminal__airport",)
    search_fields = ("name", "terminal__name")


class SeatCategoryInline(admin.TabularInline):
    model = SeatCategory
    extra = 1
    fields = ("name", "code", "display_order", "price_multiplier", "color")


@admin.register(Aircraft)
class AircraftAdmin(admin.ModelAdmin):
    list_display = ("name", "model", "total_capacity", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "model")
    inlines = [SeatCategoryInline]


@admin.register(SeatCategory)
class SeatCategoryAdmin(admin.ModelAdmin):
    list_display = ("aircraft", "name", "code", "seat_count", "price_multiplier")
    list_filter = ("aircraft",)


@admin.register(Seat)
class SeatAdmin(admin.ModelAdmin):
    list_display = ("aircraft", "seat_number", "category", "is_blocked")
    list_filter = ("aircraft", "category", "is_blocked")
    search_fields = ("seat_number",)


@admin.register(Flight)
class FlightAdmin(admin.ModelAdmin):
    list_display = ("flight_number", "origin", "destination", "departure_date", "departure_time", "aircraft", "status", "available_seats", "delay_minutes")
    list_filter = ("status", "origin", "destination")
    search_fields = ("flight_number",)


@admin.register(DelayRecord)
class DelayRecordAdmin(admin.ModelAdmin):
    list_display = ("flight", "previous_delay_minutes", "additional_delay_minutes", "total_delay_minutes", "facility_level", "created_at")
    list_filter = ("facility_level",)
    search_fields = ("flight__flight_number",)
    readonly_fields = [f.name for f in DelayRecord._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
