from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ValidationError
from .models import User, PassengerProfile


class PassengerRegistrationForm(UserCreationForm):
    """Public self-service registration form - always creates a passenger account."""
    first_name = forms.CharField(max_length=150, required=True)
    last_name = forms.CharField(max_length=150, required=True)
    email = forms.EmailField(required=True)
    phone_number = forms.CharField(max_length=20, required=True)
    passport_number = forms.CharField(max_length=30, required=False)
    nationality = forms.CharField(max_length=60, required=False)

    class Meta:
        model = User
        fields = [
            "username", "first_name", "last_name", "email", "phone_number",
            "passport_number", "nationality", "password1", "password2",
        ]

    def clean_email(self):
        email = self.cleaned_data["email"]
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("An account with this email already exists.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = User.ROLE_PASSENGER
        user.email = self.cleaned_data["email"]
        user.phone_number = self.cleaned_data["phone_number"]
        if commit:
            user.save()
            PassengerProfile.objects.create(
                user=user,
                passport_number=self.cleaned_data.get("passport_number", ""),
                nationality=self.cleaned_data.get("nationality", ""),
            )
        return user


class PassengerProfileForm(forms.ModelForm):
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150)
    email = forms.EmailField()
    phone_number = forms.CharField(max_length=20)

    class Meta:
        model = PassengerProfile
        fields = ["date_of_birth", "passport_number", "nationality", "address"]
        widgets = {
            "date_of_birth": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        if self.user:
            self.fields["first_name"].initial = self.user.first_name
            self.fields["last_name"].initial = self.user.last_name
            self.fields["email"].initial = self.user.email
            self.fields["phone_number"].initial = self.user.phone_number

    def save(self, commit=True):
        profile = super().save(commit=False)
        if self.user:
            self.user.first_name = self.cleaned_data["first_name"]
            self.user.last_name = self.cleaned_data["last_name"]
            self.user.email = self.cleaned_data["email"]
            self.user.phone_number = self.cleaned_data["phone_number"]
            if commit:
                self.user.save()
        if commit:
            profile.save()
        return profile


class StaffCreationForm(forms.ModelForm):
    """Used by administrators to add new airline staff accounts."""
    password1 = forms.CharField(label="Password", widget=forms.PasswordInput)
    employee_id = forms.CharField(max_length=20)
    department = forms.ChoiceField(choices=[
        ("operations", "Flight Operations"),
        ("customer_service", "Customer Service"),
        ("ground_handling", "Ground Handling"),
    ])
    designation = forms.CharField(max_length=60, required=False)

    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "email", "phone_number"]

    def save(self, commit=True):
        from .models import StaffProfile
        user = super().save(commit=False)
        user.role = User.ROLE_STAFF
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
            StaffProfile.objects.create(
                user=user,
                employee_id=self.cleaned_data["employee_id"],
                department=self.cleaned_data["department"],
                designation=self.cleaned_data.get("designation", ""),
            )
        return user
