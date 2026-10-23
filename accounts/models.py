from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """
    Custom user model extending Django's built-in auth user with a `role`
    field. Django's authentication (login, password hashing, sessions,
    permissions) is used as-is; we only add role-based routing on top.
    """
    ROLE_PASSENGER = "passenger"
    ROLE_STAFF = "staff"
    ROLE_ADMIN = "admin"
    ROLE_CHOICES = [
        (ROLE_PASSENGER, "Passenger"),
        (ROLE_STAFF, "Airline Staff"),
        (ROLE_ADMIN, "System Administrator"),
    ]

    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_PASSENGER)
    phone_number = models.CharField(max_length=20, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.get_full_name() or self.username} ({self.role})"

    @property
    def is_passenger_role(self):
        return self.role == self.ROLE_PASSENGER

    @property
    def is_staff_role(self):
        return self.role == self.ROLE_STAFF or self.is_superuser

    @property
    def is_admin_role(self):
        return self.role == self.ROLE_ADMIN or self.is_superuser


class PassengerProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="passenger_profile")
    date_of_birth = models.DateField(null=True, blank=True)
    passport_number = models.CharField(max_length=30, blank=True)
    nationality = models.CharField(max_length=60, blank=True)
    address = models.CharField(max_length=255, blank=True)
    frequent_flyer_number = models.CharField(max_length=30, blank=True, unique=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Passenger: {self.user.get_full_name() or self.user.username}"


class StaffProfile(models.Model):
    DEPARTMENT_CHOICES = [
        ("operations", "Flight Operations"),
        ("customer_service", "Customer Service"),
        ("ground_handling", "Ground Handling"),
    ]
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="staff_profile")
    employee_id = models.CharField(max_length=20, unique=True)
    department = models.CharField(max_length=30, choices=DEPARTMENT_CHOICES, default="operations")
    designation = models.CharField(max_length=60, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Staff: {self.user.get_full_name() or self.user.username} ({self.employee_id})"
