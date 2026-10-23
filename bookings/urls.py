from django.urls import path
from . import views

app_name = "bookings"

urlpatterns = [
    path("", views.my_bookings, name="my_bookings"),
    path("new/<int:flight_id>/", views.book_flight, name="book_flight"),
    path("new/<int:flight_id>/seat-map/", views.seat_map_data, name="seat_map_data"),
    path("new/<int:flight_id>/fare-estimate/", views.fare_estimate, name="fare_estimate"),
    path("<int:pk>/", views.booking_detail, name="detail"),
    path("<int:pk>/receipt/", views.download_receipt, name="receipt"),
    path("<int:pk>/cancellation-receipt/", views.download_cancellation_receipt, name="cancellation_receipt"),
    path("<int:pk>/cancel/", views.cancel_booking_view, name="cancel"),
    path("<int:pk>/reschedule/", views.reschedule_search, name="reschedule_search"),
    path("<int:pk>/reschedule/<int:flight_id>/", views.reschedule_confirm, name="reschedule_confirm"),
    path("passenger/<int:passenger_id>/boarding-pass/", views.download_boarding_pass, name="boarding_pass"),
]
