from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import render, redirect, get_object_or_404

from accounts.models import User, StaffProfile
from accounts.forms import StaffCreationForm
from core.utils import admin_required, log_action
from .models import SystemSetting, AuditLog


@admin_required
def manage_passengers(request):
    passengers = User.objects.filter(role=User.ROLE_PASSENGER).select_related("passenger_profile")
    q = request.GET.get("q", "")
    if q:
        passengers = passengers.filter(username__icontains=q) | passengers.filter(email__icontains=q)
    paginator = Paginator(passengers, 20)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(request, "admin/manage_passengers.html", {"page_obj": page_obj, "q": q})


@admin_required
def toggle_passenger_active(request, pk):
    passenger = get_object_or_404(User, pk=pk, role=User.ROLE_PASSENGER)
    passenger.is_active = not passenger.is_active
    passenger.save(update_fields=["is_active"])
    log_action(request.user, "accounts", "Passenger status toggled", f"{passenger.username} active={passenger.is_active}", request)
    messages.success(request, f"{passenger.username} is now {'active' if passenger.is_active else 'suspended'}.")
    return redirect("core:manage_passengers")


@admin_required
def manage_staff(request):
    staff = User.objects.filter(role=User.ROLE_STAFF).select_related("staff_profile")
    return render(request, "admin/manage_staff.html", {"staff": staff})


@admin_required
def add_staff(request):
    if request.method == "POST":
        form = StaffCreationForm(request.POST)
        if form.is_valid():
            staff = form.save()
            log_action(request.user, "accounts", "Staff added", staff.username, request)
            messages.success(request, f"Staff member {staff.username} created.")
            return redirect("core:manage_staff")
    else:
        form = StaffCreationForm()
    return render(request, "admin/staff_form.html", {"form": form})


@admin_required
def remove_staff(request, pk):
    staff = get_object_or_404(User, pk=pk, role=User.ROLE_STAFF)
    username = staff.username
    staff.delete()
    log_action(request.user, "accounts", "Staff removed", username, request)
    messages.success(request, f"Staff member {username} removed.")
    return redirect("core:manage_staff")


@admin_required
def system_settings(request):
    if request.method == "POST":
        for key, value in request.POST.items():
            if key.startswith("setting_"):
                setting_key = key.replace("setting_", "", 1)
                SystemSetting.objects.update_or_create(key=setting_key, defaults={"value": value})
        log_action(request.user, "settings", "System settings updated", "", request)
        messages.success(request, "System settings saved.")
        return redirect("core:system_settings")

    # Ensure defaults exist so the form always has rows to show/edit
    from django.conf import settings as dj_settings
    for key, value in dj_settings.AEROFLOW_DEFAULTS.items():
        SystemSetting.objects.get_or_create(key=key, defaults={"value": str(value)})

    settings_qs = SystemSetting.objects.all()
    return render(request, "admin/system_settings.html", {"settings_qs": settings_qs})


@admin_required
def audit_logs(request):
    logs = AuditLog.objects.select_related("user").all()
    module = request.GET.get("module", "")
    if module:
        logs = logs.filter(module=module)
    paginator = Paginator(logs, 30)
    page_obj = paginator.get_page(request.GET.get("page"))
    modules = AuditLog.objects.values_list("module", flat=True).distinct()
    return render(request, "admin/audit_logs.html", {"page_obj": page_obj, "modules": modules, "module": module})
