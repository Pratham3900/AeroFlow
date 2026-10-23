from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, Http404, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.db.models import Q

from flights.models import Flight
from flights.services import get_seat_map, available_categories_for_flight
from .models import Booking, BookingPassenger, BoardingPass, Cancellation
from .forms import PassengerCountForm, BookingContactForm, parse_passenger_forms, CancelBookingForm, RescheduleSearchForm
from .services import (
    create_booking, calculate_fare_for_seat_category,
    cancel_booking, reschedule_booking,
)


# ---------------------------------------------------------------
# Booking creation: search -> select flight -> seat map -> passengers -> confirm
# ---------------------------------------------------------------

@login_required
def book_flight(request, flight_id):
    """
    Single-page booking flow: contact details + passenger counts are chosen
    here; static/js/app.js dynamically builds one fieldset per passenger
    AND drives the interactive seat map, writing each passenger's chosen
    seat into a hidden `passenger-{i}-seat_number` field. On POST, the
    server independently re-validates everything (never trusts the client
    -side count or seat choice) before creating the booking inside a DB
    transaction with real seat locking.
    """
    flight = get_object_or_404(Flight.objects.select_related("origin", "destination", "aircraft"), pk=flight_id)
    categories = available_categories_for_flight(flight)

    if request.method == "POST":
        count_form = PassengerCountForm(request.POST)
        contact_form = BookingContactForm(request.POST)

        if count_form.is_valid() and contact_form.is_valid():
            total = count_form.cleaned_data["total"]
            passengers_data, errors = parse_passenger_forms(request.POST, total)

            if errors:
                messages.error(request, "Please correct the highlighted passenger details, including selecting a seat for every passenger.")
            elif flight.available_seats < total:
                messages.error(request, f"Only {flight.available_seats} seat(s) left on this flight.")
            else:
                try:
                    booking = create_booking(
                        user=request.user,
                        flight=flight,
                        passengers_data=passengers_data,
                        contact=contact_form.cleaned_data,
                        actor=request.user,
                        request=request,
                    )
                    messages.success(request, f"Booking confirmed! Your PNR is {booking.pnr}. A booking receipt has been emailed to you - your boarding pass will follow once the airline opens boarding.")
                    return redirect("bookings:detail", booking.pk)
                except ValueError as exc:
                    messages.error(request, str(exc))
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        count_form = PassengerCountForm(initial={"adults": 1, "children": 0, "infants": 0})
        contact_form = BookingContactForm(initial={
            "name": request.user.get_full_name() or request.user.username,
            "email": request.user.email,
            "phone": request.user.phone_number,
        })

    return render(request, "bookings/book_flight.html", {
        "flight": flight, "count_form": count_form, "contact_form": contact_form,
        "categories": categories,
    })


@login_required
def seat_map_data(request, flight_id):
    """AJAX: the live seat map for this flight (available/occupied/blocked/category per seat)."""
    flight = get_object_or_404(Flight, pk=flight_id)
    return JsonResponse({
        "seats": get_seat_map(flight),
        "categories": [
            {"code": c.code, "name": c.name, "color": c.color, "multiplier": str(c.price_multiplier)}
            for c in available_categories_for_flight(flight)
        ],
    })


@login_required
def fare_estimate(request, flight_id):
    """AJAX: compute the live total fare for a specific set of chosen seats + passenger types."""
    flight = get_object_or_404(Flight, pk=flight_id)
    seat_numbers = [s for s in request.GET.get("seats", "").split(",") if s]
    passenger_types = [t for t in request.GET.get("types", "").split(",") if t]

    seat_lookup = {}
    if flight.aircraft_id and seat_numbers:
        from flights.models import Seat
        seat_lookup = {s.seat_number: s for s in Seat.objects.filter(aircraft_id=flight.aircraft_id, seat_number__in=seat_numbers).select_related("category")}

    total = 0
    for i, seat_no in enumerate(seat_numbers):
        seat = seat_lookup.get(seat_no)
        ptype = passenger_types[i] if i < len(passenger_types) else BookingPassenger.TYPE_ADULT
        total += calculate_fare_for_seat_category(seat.category if seat else None, ptype)

    return JsonResponse({"total_fare": str(total), "passenger_count": len(seat_numbers)})


# ---------------------------------------------------------------
# My Bookings / detail / boarding passes / receipts
# ---------------------------------------------------------------

@login_required
def my_bookings(request):
    bookings = Booking.objects.filter(passenger=request.user).select_related(
        "flight", "flight__origin", "flight__destination"
    ).prefetch_related("booking_passengers")

    status_filter = request.GET.get("status", "")
    today = timezone.now().date()
    if status_filter == "upcoming":
        bookings = bookings.filter(flight__departure_date__gte=today, status__in=[Booking.STATUS_CONFIRMED, Booking.STATUS_REBOOKED, Booking.STATUS_RESCHEDULED])
    elif status_filter == "completed":
        bookings = bookings.filter(status=Booking.STATUS_COMPLETED)
    elif status_filter == "cancelled":
        bookings = bookings.filter(status=Booking.STATUS_CANCELLED)
    elif status_filter == "rebooked":
        bookings = bookings.filter(status__in=[Booking.STATUS_REBOOKED, Booking.STATUS_RESCHEDULED])

    q = request.GET.get("q", "").strip()
    if q:
        bookings = bookings.filter(
            Q(pnr__icontains=q) | Q(flight__flight_number__icontains=q)
            | Q(booking_passengers__first_name__icontains=q) | Q(booking_passengers__last_name__icontains=q)
        ).distinct()

    return render(request, "passenger/bookings.html", {
        "bookings": bookings, "status": status_filter, "q": q,
    })


@login_required
def booking_detail(request, pk):
    booking = get_object_or_404(
        Booking.objects.select_related("flight", "flight__origin", "flight__destination").prefetch_related("booking_passengers"),
        pk=pk,
    )
    if booking.passenger_id != request.user.id and not (request.user.is_staff_role or request.user.is_admin_role):
        raise Http404

    disruption = booking.disruptions.order_by("-created_at").first()
    facilities = booking.facilities.all()
    boarding_open = booking.flight.boarding_passes_generated_at is not None
    return render(request, "passenger/booking_detail.html", {
        "booking": booking, "disruption": disruption, "facilities": facilities, "boarding_open": boarding_open,
    })


@login_required
def download_receipt(request, pk):
    booking = get_object_or_404(Booking, pk=pk)
    if booking.passenger_id != request.user.id and not (request.user.is_staff_role or request.user.is_admin_role):
        raise Http404
    if not booking.receipt_pdf:
        raise Http404("Receipt not yet generated.")
    response = HttpResponse(booking.receipt_pdf.read(), content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="receipt_{booking.pnr}.pdf"'
    return response


@login_required
def download_boarding_pass(request, passenger_id):
    """
    Boarding passes are ONLY ever generated once the flight reaches
    BOARDING status (see flights.views.staff_flight_mark_boarding). If it
    doesn't exist yet, this is not an error - it means boarding simply
    hasn't opened, so we redirect back with a clear message instead of
    generating one early (which would break the whole point of this
    workflow change).
    """
    booking_passenger = get_object_or_404(BookingPassenger.objects.select_related("booking"), pk=passenger_id)
    booking = booking_passenger.booking
    if booking.passenger_id != request.user.id and not (request.user.is_staff_role or request.user.is_admin_role):
        raise Http404

    boarding_pass = getattr(booking_passenger, "boarding_pass", None)
    if not boarding_pass or not boarding_pass.pdf_file:
        messages.info(request, "Your boarding pass will be generated automatically once the airline changes this flight's status to Boarding.")
        return redirect("bookings:detail", booking.pk)

    response = HttpResponse(boarding_pass.pdf_file.read(), content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="boarding_pass_{booking.pnr}_{booking_passenger.first_name}.pdf"'
    return response


@login_required
def download_cancellation_receipt(request, pk):
    cancellation = get_object_or_404(Cancellation.objects.select_related("booking", "refund"), booking__pk=pk)
    booking = cancellation.booking
    if booking.passenger_id != request.user.id and not (request.user.is_staff_role or request.user.is_admin_role):
        raise Http404
    if not cancellation.pdf_file:
        raise Http404
    response = HttpResponse(cancellation.pdf_file.read(), content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="cancellation_{booking.pnr}.pdf"'
    return response


# ---------------------------------------------------------------
# Voluntary cancellation
# ---------------------------------------------------------------

@login_required
def cancel_booking_view(request, pk):
    booking = get_object_or_404(Booking.objects.select_related("flight"), pk=pk)
    if booking.passenger_id != request.user.id:
        raise Http404
    if not booking.is_active:
        messages.info(request, "This booking is already cancelled.")
        return redirect("bookings:detail", pk)

    hours_to_departure = (booking.flight.departure_datetime - timezone.now()).total_seconds() / 3600
    refund_will_be_eligible = hours_to_departure >= 24

    if request.method == "POST":
        form = CancelBookingForm(request.POST)
        if form.is_valid():
            try:
                cancellation = cancel_booking(booking, actor=request.user, reason=form.cleaned_data["reason"], request=request)
                if cancellation.refund_eligible:
                    messages.success(request, f"Booking {booking.pnr} has been cancelled. You are eligible for a refund - see the cancellation receipt for details.")
                else:
                    messages.warning(request, f"Booking {booking.pnr} has been cancelled. This cancellation was made less than 24 hours before departure, so it is not eligible for a refund.")
                return redirect("bookings:detail", pk)
            except ValueError as exc:
                messages.error(request, str(exc))
    else:
        form = CancelBookingForm()

    return render(request, "bookings/cancel_booking.html", {
        "booking": booking, "form": form, "refund_will_be_eligible": refund_will_be_eligible, "hours_to_departure": round(hours_to_departure, 1),
    })


# ---------------------------------------------------------------
# Voluntary reschedule
# ---------------------------------------------------------------

@login_required
def reschedule_search(request, pk):
    booking = get_object_or_404(Booking.objects.select_related("flight"), pk=pk)
    if booking.passenger_id != request.user.id:
        raise Http404
    if not booking.is_active:
        messages.error(request, "This booking can't be rescheduled.")
        return redirect("bookings:detail", pk)

    alternatives = []
    form = RescheduleSearchForm(request.GET or {"departure_date": booking.flight.departure_date})
    if form.is_valid():
        alternatives = Flight.objects.filter(
            origin=booking.flight.origin, destination=booking.flight.destination,
            departure_date=form.cleaned_data["departure_date"],
            available_seats__gte=booking.passenger_count,
        ).exclude(id=booking.flight_id).exclude(status=Flight.STATUS_CANCELLED)

    return render(request, "bookings/reschedule_search.html", {
        "booking": booking, "form": form, "alternatives": alternatives,
    })


@login_required
def reschedule_confirm(request, pk, flight_id):
    booking = get_object_or_404(Booking, pk=pk)
    new_flight = get_object_or_404(Flight, pk=flight_id)
    if booking.passenger_id != request.user.id:
        raise Http404

    if request.method == "POST":
        try:
            new_booking = reschedule_booking(booking, new_flight, actor=request.user, request=request)
            messages.success(request, f"Your flight has been rescheduled. New PNR: {new_booking.pnr}.")
            return redirect("bookings:detail", new_booking.pk)
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect("bookings:reschedule_search", pk)

    from .services import seats_for_group_move, calculate_fare_for_seat_category
    seats = seats_for_group_move(new_flight, booking.passenger_count)
    passengers = list(booking.booking_passengers.all())
    estimated_new_total = sum(
        (calculate_fare_for_seat_category(cat, p.passenger_type) for (_, cat), p in zip(seats, passengers)),
    ) if len(seats) == len(passengers) else booking.payment_amount
    fare_difference = estimated_new_total - booking.payment_amount

    return render(request, "bookings/reschedule_confirm.html", {
        "booking": booking, "new_flight": new_flight, "fare_difference": fare_difference,
    })
