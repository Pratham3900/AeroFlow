from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, PassengerProfile, StaffProfile


@admin.register(User)
class AeroFlowUserAdmin(UserAdmin):
    list_display = ("username", "email", "first_name", "last_name", "role", "is_active")
    list_filter = ("role", "is_active", "is_staff")
    fieldsets = UserAdmin.fieldsets + (
        ("AeroFlow", {"fields": ("role", "phone_number")}),
    )


@admin.register(PassengerProfile)
class PassengerProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "nationality", "frequent_flyer_number")
    search_fields = ("user__username", "user__email", "passport_number")


@admin.register(StaffProfile)
class StaffProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "employee_id", "department", "designation")
    search_fields = ("user__username", "employee_id")
