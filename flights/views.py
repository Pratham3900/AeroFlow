from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST, require_GET

from core.utils import staff_required, admin_required, log_action
from .models import Flight, Airport, Aircraft, SeatCategory, Terminal, Gate
from .forms import (
    FlightForm, DelayUpdateForm, CancellationForm, GateTerminalUpdateForm,
    AirportForm, AircraftForm, SeatCategoryQuickForm, TerminalForm, GateForm,
)
from .services import generate_seats_for_aircraft
from recovery.services import process_flight_delay, process_flight_cancellation, process_gate_terminal_change


@login_required
def flight_search(request):
    """Public-ish flight search / status lookup, available to any logged-in role."""
    flights = Flight.objects.select_related("origin", "destination").all()

    q = request.GET.get("q", "").strip()
    origin = request.GET.get("origin", "")
    destination = request.GET.get("destination", "")
    status = request.GET.get("status", "")

    if q:
        flights = flights.filter(flight_number__icontains=q)
    if origin:
        flights = flights.filter(origin__code=origin)
    if destination:
        flights = flights.filter(destination__code=destination)
    if status:
        flights = flights.filter(status=status)

    paginator = Paginator(flights, 15)
    page_obj = paginator.get_page(request.GET.get("page"))

    context = {
        "page_obj": page_obj,
        "airports": Airport.objects.filter(is_active=True),
        "status_choices": Flight.STATUS_CHOICES,
        "q": q,
    }
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return render(request, "flights/_flight_table.html", context)
    return render(request, "flights/search.html", context)


@login_required
def flight_detail(request, pk):
    flight = get_object_or_404(Flight.objects.select_related("origin", "destination", "aircraft"), pk=pk)
    from .services import available_categories_for_flight
    return render(request, "flights/detail.html", {
        "flight": flight, "categories": available_categories_for_flight(flight),
    })


# ---------------------------------------------------------------
# Staff: flight management (CRUD + automated status workflow)
# ---------------------------------------------------------------

@staff_required
def staff_flight_list(request):
    flights = Flight.objects.select_related("origin", "destination").all()
    status = request.GET.get("status", "")
    if status:
        flights = flights.filter(status=status)
    paginator = Paginator(flights, 20)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(request, "staff/flight_list.html", {
        "page_obj": page_obj, "status_choices": Flight.STATUS_CHOICES, "status": status,
    })


@staff_required
def staff_flight_add(request):
    if request.method == "POST":
        form = FlightForm(request.POST)
        if form.is_valid():
            flight = form.save()
            log_action(request.user, "flights", "Flight created", f"{flight.flight_number}", request)
            messages.success(request, f"Flight {flight.flight_number} created.")
            return redirect("flights:staff_flight_list")
    else:
        form = FlightForm(initial={"status": Flight.STATUS_SCHEDULED})
    return render(request, "staff/flight_form.html", {"form": form, "title": "Add Flight"})


@staff_required
def staff_flight_edit(request, pk):
    flight = get_object_or_404(Flight, pk=pk)
    if request.method == "POST":
        form = FlightForm(request.POST, instance=flight)
        if form.is_valid():
            form.save()
            log_action(request.user, "flights", "Flight updated", f"{flight.flight_number}", request)
            messages.success(request, f"Flight {flight.flight_number} updated.")
            return redirect("flights:staff_flight_list")
    else:
        form = FlightForm(instance=flight)
    return render(request, "staff/flight_form.html", {"form": form, "title": f"Edit {flight.flight_number}", "flight": flight})


@staff_required
@require_POST
def staff_flight_delete(request, pk):
    flight = get_object_or_404(Flight, pk=pk)
    number = flight.flight_number
    flight.delete()
    log_action(request.user, "flights", "Flight deleted", number, request)
    messages.success(request, f"Flight {number} deleted.")
    return redirect("flights:staff_flight_list")


@staff_required
def staff_flight_manage(request, pk):
    """Single page for staff to change status / record delay / cancel / open boarding / update gate."""
    flight = get_object_or_404(Flight.objects.select_related("origin", "destination", "aircraft"), pk=pk)
    delay_form = DelayUpdateForm()
    cancel_form = CancellationForm()
    gate_form = GateTerminalUpdateForm(flight=flight, initial={
        "origin_terminal": flight.origin_terminal_id, "origin_gate": flight.origin_gate_id,
        "destination_terminal": flight.destination_terminal_id, "destination_gate": flight.destination_gate_id,
        "boarding_time": flight.boarding_time,
    })
    from bookings.models import Booking
    bookings = Booking.objects.filter(flight=flight).exclude(
        status__in=[Booking.STATUS_CANCELLED, Booking.STATUS_REFUNDED]
    ).select_related("passenger").prefetch_related("booking_passengers")
    affected_passenger_count = sum(b.passenger_count for b in bookings)
    return render(request, "staff/flight_manage.html", {
        "flight": flight, "delay_form": delay_form, "cancel_form": cancel_form, "gate_form": gate_form,
        "bookings": bookings, "affected_passenger_count": affected_passenger_count,
        "delay_records": flight.delay_records.all(),
    })


@staff_required
@require_POST
def staff_flight_mark_delayed(request, pk):
    """
    Triggers the automatic cumulative-delay workflow. The value submitted
    is always an ADDITIONAL delay added on top of whatever the flight
    already has - see recovery.services.process_flight_delay /
    flights.services.add_flight_delay, which never overwrite the previous
    total.
    """
    flight = get_object_or_404(Flight, pk=pk)
    form = DelayUpdateForm(request.POST)
    if form.is_valid():
        process_flight_delay(
            flight,
            additional_minutes=form.cleaned_data["additional_delay_minutes"],
            reason=form.cleaned_data["delay_reason"],
            actor=request.user,
            request=request,
        )
        messages.success(request, f"Flight {flight.flight_number}: additional delay recorded. Affected passengers notified automatically with their updated facility eligibility.")
    else:
        messages.error(request, "Please provide a valid additional delay duration and reason.")
    return redirect("flights:staff_flight_manage", pk=pk)


@staff_required
@require_POST
def staff_flight_cancel(request, pk):
    """Triggers the automatic cancellation recovery workflow."""
    flight = get_object_or_404(Flight, pk=pk)
    form = CancellationForm(request.POST)
    if form.is_valid():
        process_flight_cancellation(
            flight, reason=form.cleaned_data["cancellation_reason"], actor=request.user, request=request,
        )
        messages.success(request, f"Flight {flight.flight_number} cancelled. Recovery options are now available to affected passengers.")
    else:
        messages.error(request, "Please provide a cancellation reason.")
    return redirect("flights:staff_flight_manage", pk=pk)


@staff_required
@require_POST
def staff_flight_mark_boarding(request, pk):
    """
    The ONLY path that transitions a flight to BOARDING and, in the same
    action, automatically generates + emails every passenger's boarding
    pass (bookings.services.generate_boarding_passes_for_flight). Kept as
    its own explicit action (rather than folded into the generic status
    dropdown) so this important trigger can never be fired by accident.
    """
    from bookings.services import generate_boarding_passes_for_flight
    flight = get_object_or_404(Flight, pk=pk)
    if flight.status == Flight.STATUS_CANCELLED:
        messages.error(request, "A cancelled flight cannot be moved to Boarding.")
        return redirect("flights:staff_flight_manage", pk=pk)

    old_status = flight.status
    flight.status = Flight.STATUS_BOARDING
    flight.save(update_fields=["status"])
    boarding_passes = generate_boarding_passes_for_flight(flight, actor=request.user, request=request)
    log_action(request.user, "flights", "Flight status changed", f"{flight.flight_number}: {old_status} -> BOARDING", request)
    messages.success(request, f"Flight {flight.flight_number} is now Boarding. {len(boarding_passes)} boarding pass(es) generated and emailed automatically.")
    return redirect("flights:staff_flight_manage", pk=pk)


@staff_required
@require_POST
def staff_flight_restore_on_time(request, pk):
    """Simple status transitions that don't require the delay/cancellation/boarding workflows."""
    flight = get_object_or_404(Flight, pk=pk)
    new_status = request.POST.get("status")
    valid = dict(Flight.STATUS_CHOICES)
    if new_status in valid and new_status not in (Flight.STATUS_DELAYED, Flight.STATUS_CANCELLED, Flight.STATUS_BOARDING):
        old_status = flight.status
        flight.status = new_status
        flight.save(update_fields=["status"])
        log_action(request.user, "flights", "Flight status changed", f"{flight.flight_number}: {old_status} -> {new_status}", request)
        messages.success(request, f"Flight {flight.flight_number} status set to {valid[new_status]}.")
    return redirect("flights:staff_flight_manage", pk=pk)


@staff_required
@require_POST
def staff_flight_update_gate(request, pk):
    """Dynamic gate/terminal/boarding-time updates - passengers are notified automatically on change."""
    flight = get_object_or_404(Flight, pk=pk)
    form = GateTerminalUpdateForm(request.POST, flight=flight)
    if form.is_valid():
        process_gate_terminal_change(flight, form.cleaned_data, actor=request.user, request=request)
        messages.success(request, f"Flight {flight.flight_number} gate/terminal information updated. Passengers notified.")
    else:
        messages.error(request, "Please correct the errors below.")
    return redirect("flights:staff_flight_manage", pk=pk)


@login_required
@require_GET
def ajax_seat_check(request, pk):
    """AJAX: check live seat availability for a flight (used during rebooking)."""
    flight = get_object_or_404(Flight, pk=pk)
    return JsonResponse({
        "flight_number": flight.flight_number,
        "available_seats": flight.available_seats,
        "status": flight.status,
        "has_seats": flight.available_seats > 0,
    })


# ---------------------------------------------------------------
# Staff/Admin: Airport management
# ---------------------------------------------------------------

@staff_required
def staff_airport_list(request):
    airports = Airport.objects.all()
    return render(request, "staff/airport_list.html", {"airports": airports})


@staff_required
def staff_airport_add(request):
    if request.method == "POST":
        form = AirportForm(request.POST)
        if form.is_valid():
            airport = form.save()
            log_action(request.user, "flights", "Airport added", airport.code, request)
            messages.success(request, f"Airport {airport.code} added.")
            return redirect("flights:staff_airport_list")
    else:
        form = AirportForm()
    return render(request, "staff/airport_form.html", {"form": form, "title": "Add Airport"})


@staff_required
def staff_airport_edit(request, pk):
    airport = get_object_or_404(Airport, pk=pk)
    if request.method == "POST":
        form = AirportForm(request.POST, instance=airport)
        if form.is_valid():
            form.save()
            log_action(request.user, "flights", "Airport updated", airport.code, request)
            messages.success(request, f"Airport {airport.code} updated.")
            return redirect("flights:staff_airport_list")
    else:
        form = AirportForm(instance=airport)

    terminals = airport.terminals.prefetch_related("gates")
    return render(request, "staff/airport_form.html", {
        "form": form, "title": f"Edit {airport.code}", "airport": airport,
        "terminals": terminals, "terminal_form": TerminalForm(), "gate_form": GateForm(),
    })


@staff_required
@require_POST
def staff_terminal_add(request, airport_pk):
    """'Add Terminal' feature - creates one Terminal for this airport, refusing duplicates (case-insensitive)."""
    airport = get_object_or_404(Airport, pk=airport_pk)
    form = TerminalForm(request.POST)
    if form.is_valid():
        name = form.cleaned_data["name"].strip()
        if Terminal.objects.filter(airport=airport, name__iexact=name).exists():
            messages.error(request, f'Terminal "{name}" already exists for {airport.code}.')
        else:
            Terminal.objects.create(airport=airport, name=name)
            log_action(request.user, "flights", "Terminal added", f"{airport.code}: {name}", request)
            messages.success(request, f'Terminal "{name}" added to {airport.code}.')
    else:
        messages.error(request, "Please enter a terminal name.")
    return redirect("flights:staff_airport_edit", pk=airport_pk)


@staff_required
@require_POST
def staff_gate_add(request, terminal_pk):
    """'Add Gate' feature (inside a terminal) - creates one Gate for this terminal, refusing duplicates (case-insensitive)."""
    terminal = get_object_or_404(Terminal, pk=terminal_pk)
    form = GateForm(request.POST)
    if form.is_valid():
        name = form.cleaned_data["name"].strip()
        if Gate.objects.filter(terminal=terminal, name__iexact=name).exists():
            messages.error(request, f'Gate "{name}" already exists for {terminal.name}.')
        else:
            Gate.objects.create(terminal=terminal, name=name)
            log_action(request.user, "flights", "Gate added", f"{terminal.airport.code} {terminal.name}: {name}", request)
            messages.success(request, f'Gate "{name}" added to {terminal.name}.')
    else:
        messages.error(request, "Please enter a gate name.")
    return redirect("flights:staff_airport_edit", pk=terminal.airport_id)


@login_required
@require_GET
def ajax_terminals_for_airport(request):
    """AJAX: terminals belonging to a given airport - used by the cascading
    dropdowns on the flight add/edit form and the gate-update form."""
    airport_id = request.GET.get("airport_id")
    terminals = Terminal.objects.filter(airport_id=airport_id).order_by("name") if airport_id else Terminal.objects.none()
    return JsonResponse({"terminals": [{"id": t.id, "name": t.name} for t in terminals]})


@login_required
@require_GET
def ajax_gates_for_terminal(request):
    """AJAX: gates belonging to a given terminal - used by the cascading dropdowns."""
    terminal_id = request.GET.get("terminal_id")
    gates = Gate.objects.filter(terminal_id=terminal_id).order_by("name") if terminal_id else Gate.objects.none()
    return JsonResponse({"gates": [{"id": g.id, "name": g.name} for g in gates]})


@staff_required
@require_POST
def staff_airport_toggle_active(request, pk):
    airport = get_object_or_404(Airport, pk=pk)
    airport.is_active = not airport.is_active
    airport.save(update_fields=["is_active"])
    log_action(request.user, "flights", "Airport status toggled", f"{airport.code} active={airport.is_active}", request)
    messages.success(request, f"Airport {airport.code} is now {'active' if airport.is_active else 'inactive'}.")
    return redirect("flights:staff_airport_list")


# ---------------------------------------------------------------
# Staff/Admin: Aircraft & dynamic seat-map management
# ---------------------------------------------------------------

@staff_required
def staff_aircraft_list(request):
    aircraft = Aircraft.objects.prefetch_related("seat_categories")
    return render(request, "staff/aircraft_list.html", {"aircraft": aircraft})


@staff_required
def staff_aircraft_add(request):
    """
    Add an aircraft AND configure its seat categories/layout in one page.
    Category rows are built dynamically client-side (static/js/app.js),
    the same JS pattern used for passenger forms, then parsed server-side
    and used to generate the actual Seat rows via
    flights.services.generate_seats_for_aircraft - nothing about
    categories/counts/layout is hard-coded.
    """
    if request.method == "POST":
        form = AircraftForm(request.POST)
        total_categories = int(request.POST.get("total_categories", 0) or 0)

        category_rows = []
        errors = []
        for i in range(total_categories):
            prefix = f"category-{i}-"
            name = request.POST.get(prefix + "name", "").strip()
            code = request.POST.get(prefix + "code", "").strip().lower()
            rows = request.POST.get(prefix + "rows", "").strip()
            seats_per_row = request.POST.get(prefix + "seats_per_row", "6").strip()
            price_multiplier = request.POST.get(prefix + "price_multiplier", "1.0").strip()
            color = request.POST.get(prefix + "color", "#1e88e5").strip()
            if not name or not code or not rows:
                continue
            try:
                category_rows.append({
                    "name": name, "code": code, "rows": int(rows),
                    "seats_per_row": int(seats_per_row or 6),
                    "price_multiplier": price_multiplier or "1.0", "color": color or "#1e88e5",
                })
            except ValueError:
                errors.append(f"Invalid numbers for category '{name}'.")

        if form.is_valid() and category_rows and not errors:
            aircraft = form.save()
            built_categories = []
            for entry in category_rows:
                cat = SeatCategory.objects.create(
                    aircraft=aircraft, name=entry["name"], code=entry["code"],
                    display_order=len(built_categories), price_multiplier=entry["price_multiplier"], color=entry["color"],
                )
                built_categories.append({"category": cat, "rows": entry["rows"], "seats_per_row": entry["seats_per_row"]})
            generate_seats_for_aircraft(aircraft, built_categories)
            log_action(request.user, "flights", "Aircraft added", f"{aircraft.name} ({aircraft.total_capacity} seats)", request)
            messages.success(request, f"Aircraft {aircraft.name} created with {aircraft.total_capacity} seats across {len(built_categories)} categories.")
            return redirect("flights:staff_aircraft_list")
        elif not category_rows:
            messages.error(request, "Please configure at least one seat category.")
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = AircraftForm()

    return render(request, "staff/aircraft_form.html", {"form": form})


@staff_required
@require_POST
def staff_aircraft_toggle_active(request, pk):
    aircraft = get_object_or_404(Aircraft, pk=pk)
    aircraft.is_active = not aircraft.is_active
    aircraft.save(update_fields=["is_active"])
    log_action(request.user, "flights", "Aircraft status toggled", f"{aircraft.name} active={aircraft.is_active}", request)
    messages.success(request, f"Aircraft {aircraft.name} is now {'active' if aircraft.is_active else 'inactive'}.")
    return redirect("flights:staff_aircraft_list")
