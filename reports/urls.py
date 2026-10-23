from django.urls import path
from . import views

app_name = "reports"

urlpatterns = [
    path("daily/", views.daily_report, name="daily_report"),
    path("daily/pdf/", views.daily_report_pdf, name="daily_report_pdf"),
]
