from django.contrib.auth import login as auth_login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView
from django.contrib import messages
from django.shortcuts import render, redirect
from django.urls import reverse_lazy

from core.utils import log_action, is_admin, is_staff_member
from core.email_utils import send_templated_email
from .forms import PassengerRegistrationForm, PassengerProfileForm
from .models import PassengerProfile


def register_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard:home")

    if request.method == "POST":
        form = PassengerRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            log_action(user, "accounts", "Passenger registered", f"New passenger account: {user.username}", request)
            send_templated_email(
                subject="Welcome to AeroFlow",
                template_name="welcome",
                context={"user": user},
                to_email=user.email,
            )
            auth_login(request, user)
            messages.success(request, "Welcome to AeroFlow! Your account has been created.")
            return redirect("dashboard:home")
    else:
        form = PassengerRegistrationForm()
    return render(request, "accounts/register.html", {"form": form})


class RoleAwareLoginView(LoginView):
    template_name = "accounts/login.html"
    redirect_authenticated_user = True

    def get_success_url(self):
        return reverse_lazy("dashboard:home")


class AeroFlowLogoutView(LogoutView):
    next_page = reverse_lazy("accounts:login")


@login_required
def profile_view(request):
    user = request.user
    if user.is_passenger_role:
        profile, _ = PassengerProfile.objects.get_or_create(user=user)
        if request.method == "POST":
            form = PassengerProfileForm(request.POST, instance=profile, user=user)
            if form.is_valid():
                form.save()
                messages.success(request, "Profile updated successfully.")
                return redirect("accounts:profile")
        else:
            form = PassengerProfileForm(instance=profile, user=user)
        return render(request, "accounts/profile.html", {"form": form})

    # Staff / admin: simple read-only profile view
    return render(request, "accounts/profile_staff.html", {"user_obj": user})
