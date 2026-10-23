from django.urls import path
from . import views

app_name = "flights"

urlpatterns = [
    path("", views.flight_search, name="search"),
    path("<int:pk>/", views.flight_detail, name="detail"),
    path("<int:pk>/seats/", views.ajax_seat_check, name="ajax_seat_check"),

    # Staff: flight management
    path("staff/manage/", views.staff_flight_list, name="staff_flight_list"),
    path("staff/add/", views.staff_flight_add, name="staff_flight_add"),
    path("staff/<int:pk>/edit/", views.staff_flight_edit, name="staff_flight_edit"),
    path("staff/<int:pk>/delete/", views.staff_flight_delete, name="staff_flight_delete"),
    path("staff/<int:pk>/", views.staff_flight_manage, name="staff_flight_manage"),
    path("staff/<int:pk>/mark-delayed/", views.staff_flight_mark_delayed, name="staff_flight_mark_delayed"),
    path("staff/<int:pk>/cancel/", views.staff_flight_cancel, name="staff_flight_cancel"),
    path("staff/<int:pk>/mark-boarding/", views.staff_flight_mark_boarding, name="staff_flight_mark_boarding"),
    path("staff/<int:pk>/status/", views.staff_flight_restore_on_time, name="staff_flight_status"),
    path("staff/<int:pk>/gate/", views.staff_flight_update_gate, name="staff_flight_update_gate"),

    # Staff: airport management
    path("staff/airports/", views.staff_airport_list, name="staff_airport_list"),
    path("staff/airports/add/", views.staff_airport_add, name="staff_airport_add"),
    path("staff/airports/<int:pk>/edit/", views.staff_airport_edit, name="staff_airport_edit"),
    path("staff/airports/<int:pk>/toggle/", views.staff_airport_toggle_active, name="staff_airport_toggle_active"),
    path("staff/airports/<int:airport_pk>/terminals/add/", views.staff_terminal_add, name="staff_terminal_add"),
    path("staff/terminals/<int:terminal_pk>/gates/add/", views.staff_gate_add, name="staff_gate_add"),

    # AJAX: cascading terminal/gate dropdowns
    path("ajax/terminals/", views.ajax_terminals_for_airport, name="ajax_terminals_for_airport"),
    path("ajax/gates/", views.ajax_gates_for_terminal, name="ajax_gates_for_terminal"),

    # Staff: aircraft & seat-map management
    path("staff/aircraft/", views.staff_aircraft_list, name="staff_aircraft_list"),
    path("staff/aircraft/add/", views.staff_aircraft_add, name="staff_aircraft_add"),
    path("staff/aircraft/<int:pk>/toggle/", views.staff_aircraft_toggle_active, name="staff_aircraft_toggle_active"),
]
