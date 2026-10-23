from django.contrib import admin
from .models import Voucher


@admin.register(Voucher)
class VoucherAdmin(admin.ModelAdmin):
    list_display = ("voucher_code", "voucher_type", "passenger", "booking", "amount", "status", "expiry_date")
    list_filter = ("voucher_type", "status")
