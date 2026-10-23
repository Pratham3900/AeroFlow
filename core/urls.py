from django.urls import path
from . import views

app_name = "core"

urlpatterns = [
    path("passengers/", views.manage_passengers, name="manage_passengers"),
    path("passengers/<int:pk>/toggle/", views.toggle_passenger_active, name="toggle_passenger_active"),
    path("staff/", views.manage_staff, name="manage_staff"),
    path("staff/add/", views.add_staff, name="add_staff"),
    path("staff/<int:pk>/remove/", views.remove_staff, name="remove_staff"),
    path("settings/", views.system_settings, name="system_settings"),
    path("audit-logs/", views.audit_logs, name="audit_logs"),
]
