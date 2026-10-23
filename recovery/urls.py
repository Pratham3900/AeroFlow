from django.urls import path
from . import views

app_name = "recovery"

urlpatterns = [
    path("booking/<int:booking_id>/", views.recovery_page, name="recovery_page"),
    path("booking/<int:booking_id>/rebook/", views.request_rebooking, name="request_rebooking"),
    path("booking/<int:booking_id>/refund/", views.submit_refund_request, name="submit_refund_request"),
    path("booking/<int:booking_id>/voucher/<str:voucher_type>/", views.request_voucher, name="request_voucher"),

    path("staff/requests/", views.staff_requests_dashboard, name="staff_requests_dashboard"),
    path("staff/rebooking/<int:pk>/approve/", views.staff_approve_rebooking, name="staff_approve_rebooking"),
    path("staff/rebooking/<int:pk>/reject/", views.staff_reject_rebooking, name="staff_reject_rebooking"),
    path("staff/refund/<int:pk>/update/", views.staff_update_refund, name="staff_update_refund"),
]
