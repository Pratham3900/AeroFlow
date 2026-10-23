from django.contrib import admin
from .models import DisruptionRecord, RebookingRequest, RefundRequest


@admin.register(DisruptionRecord)
class DisruptionRecordAdmin(admin.ModelAdmin):
    list_display = ("booking", "flight", "disruption_type", "delay_minutes", "eligible_for_recovery", "created_at")
    list_filter = ("disruption_type", "eligible_for_recovery")


@admin.register(RebookingRequest)
class RebookingRequestAdmin(admin.ModelAdmin):
    list_display = ("original_booking", "requested_flight", "passenger", "status", "requested_at")
    list_filter = ("status",)


@admin.register(RefundRequest)
class RefundRequestAdmin(admin.ModelAdmin):
    list_display = ("refund_id", "booking", "passenger", "requested_amount", "status", "request_date")
    list_filter = ("status",)
