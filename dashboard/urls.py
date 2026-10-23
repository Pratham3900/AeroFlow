from django.urls import path
from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.home, name="home"),
    path("passenger/", views.passenger_dashboard, name="passenger_dashboard"),
    path("staff/", views.staff_dashboard, name="staff_dashboard"),
    path("admin/", views.admin_dashboard, name="admin_dashboard"),
]
