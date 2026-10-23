import uuid
from django.db import models
from django.conf import settings


class SystemSetting(models.Model):
    """
    Key/value configuration store so business rules (delay threshold,
    voucher amounts, etc.) are never hard-coded in application logic.
    Administrators can edit these from the Admin > System Settings page.
    """
    key = models.CharField(max_length=100, unique=True)
    value = models.CharField(max_length=255)
    description = models.CharField(max_length=255, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["key"]

    def __str__(self):
        return f"{self.key} = {self.value}"


class AuditLog(models.Model):
    """Immutable trail of important administrative / staff actions."""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="audit_logs",
    )
    module = models.CharField(max_length=50)
    action = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [models.Index(fields=["-timestamp"]), models.Index(fields=["module"])]

    def __str__(self):
        return f"[{self.timestamp:%Y-%m-%d %H:%M}] {self.module}: {self.action}"


def generate_reference(prefix: str, length: int = 8) -> str:
    """Generate a short, human-friendly unique reference code (PNR, voucher id, etc.)."""
    return f"{prefix}{uuid.uuid4().hex[:length].upper()}"
