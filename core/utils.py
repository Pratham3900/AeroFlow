"""
Shared helper utilities: reading configurable business settings,
role-check decorators/mixins, and audit logging.
"""
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.contrib.auth.mixins import UserPassesTestMixin
from functools import wraps


def get_setting(key, default=None, cast=str):
    """
    Read a business-rule value from the SystemSetting table, falling back
    to AEROFLOW_DEFAULTS in settings.py, and finally to `default`.
    This is how the delay-recovery threshold and voucher amounts stay
    configurable at runtime instead of being hard-coded.
    """
    from core.models import SystemSetting  # local import avoids app-loading issues

    try:
        setting = SystemSetting.objects.get(key=key)
        raw = setting.value
    except SystemSetting.DoesNotExist:
        raw = settings.AEROFLOW_DEFAULTS.get(key, default)

    if raw is None:
        return default
    try:
        return cast(raw)
    except (TypeError, ValueError):
        return default


def log_action(user, module, action, description="", request=None):
    """Write an AuditLog entry. Safe to call from anywhere (views, signals, commands)."""
    from core.models import AuditLog

    ip = None
    if request is not None:
        xff = request.META.get("HTTP_X_FORWARDED_FOR")
        ip = xff.split(",")[0].strip() if xff else request.META.get("REMOTE_ADDR")

    AuditLog.objects.create(
        user=user if getattr(user, "is_authenticated", False) else None,
        module=module,
        action=action,
        description=description,
        ip_address=ip,
    )


# ---------------------------------------------------------------
# Role helpers. accounts.models.User has a `role` field with values
# "passenger" | "staff" | "admin" (Django superusers are also treated
# as admins). These are used to protect views by role.
# ---------------------------------------------------------------

def is_admin(user):
    return user.is_authenticated and (user.is_superuser or getattr(user, "role", None) == "admin")


def is_staff_member(user):
    return user.is_authenticated and (is_admin(user) or getattr(user, "role", None) == "staff")


def is_passenger(user):
    return user.is_authenticated and getattr(user, "role", None) == "passenger"


class StaffRequiredMixin(UserPassesTestMixin):
    """Restrict a class-based view to airline staff or admins."""
    def test_func(self):
        return is_staff_member(self.request.user)

    def handle_no_permission(self):
        raise PermissionDenied("Staff access only.")


class AdminRequiredMixin(UserPassesTestMixin):
    """Restrict a class-based view to administrators."""
    def test_func(self):
        return is_admin(self.request.user)

    def handle_no_permission(self):
        raise PermissionDenied("Administrator access only.")


def staff_required(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not is_staff_member(request.user):
            raise PermissionDenied("Staff access only.")
        return view_func(request, *args, **kwargs)
    return _wrapped


def admin_required(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not is_admin(request.user):
            raise PermissionDenied("Administrator access only.")
        return view_func(request, *args, **kwargs)
    return _wrapped


def passenger_required(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not is_passenger(request.user):
            raise PermissionDenied("Passenger access only.")
        return view_func(request, *args, **kwargs)
    return _wrapped
