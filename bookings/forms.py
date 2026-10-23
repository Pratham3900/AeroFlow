"""
Booking forms.

Passenger detail entry uses a small amount of manually-parsed POST data
(driven by the dynamic form builder in static/js/app.js) rather than a
Django FormSet, so the number of passenger fieldsets can grow/shrink
client-side purely with JavaScript. `parse_passenger_forms()` below is the
server-side counterpart that validates whatever was submitted, including
each passenger's chosen seat (picked from the interactive seat map).
"""
from django import forms
from .models import Booking, BookingPassenger


class PassengerCountForm(forms.Form):
    """Step 1: how many travellers. Seat category is no longer chosen here -
    it's implied by whichever seat each passenger picks on the seat map,
    since categories are entirely admin-defined per aircraft, not a fixed list."""
    adults = forms.ChoiceField(choices=[(i, i) for i in range(1, 10)], initial=1)
    children = forms.ChoiceField(choices=[(i, i) for i in range(0, 9)], initial=0)
    infants = forms.ChoiceField(choices=[(i, i) for i in range(0, 9)], initial=0)

    def clean(self):
        cleaned = super().clean()
        adults = int(cleaned.get("adults", 0) or 0)
        children = int(cleaned.get("children", 0) or 0)
        infants = int(cleaned.get("infants", 0) or 0)
        total = adults + children + infants
        if total < 1:
            raise forms.ValidationError("At least one passenger is required.")
        if total > 9:
            raise forms.ValidationError("A single booking supports a maximum of 9 passengers.")
        if infants > adults:
            raise forms.ValidationError("Each infant must be accompanied by an adult.")
        cleaned["total"] = total
        return cleaned


class BookingContactForm(forms.Form):
    """Booking contact details, pre-filled from the logged-in user but editable."""
    name = forms.CharField(max_length=150, label="Contact Name")
    email = forms.EmailField(label="Contact Email")
    phone = forms.CharField(max_length=20, label="Contact Phone")


REQUIRED_PASSENGER_FIELDS = ["first_name", "last_name"]
VALID_PASSENGER_TYPES = {BookingPassenger.TYPE_ADULT, BookingPassenger.TYPE_CHILD, BookingPassenger.TYPE_INFANT}
VALID_GENDERS = {"M", "F", "O", ""}


def parse_passenger_forms(post_data, total: int):
    """
    Pull `passenger-{i}-<field>` values out of a raw POST QueryDict for
    i in range(total), validate the minimum required fields (including
    that a seat was actually picked on the seat map), and return
    (passengers_data, errors) where errors is a dict of {index: [msgs]}.

    Seat availability/double-booking is NOT checked here - that happens
    transactionally in bookings.services.create_booking(), which is the
    only place that can safely lock seats against a race condition.
    """
    passengers_data = []
    errors = {}
    seen_seats = set()

    for i in range(total):
        prefix = f"passenger-{i}-"
        row_errors = []

        first_name = post_data.get(prefix + "first_name", "").strip()
        last_name = post_data.get(prefix + "last_name", "").strip()
        middle_name = post_data.get(prefix + "middle_name", "").strip()
        dob = post_data.get(prefix + "date_of_birth", "").strip()
        gender = post_data.get(prefix + "gender", "").strip().upper()
        nationality = post_data.get(prefix + "nationality", "").strip()
        email = post_data.get(prefix + "email", "").strip()
        phone = post_data.get(prefix + "phone_number", "").strip()
        passenger_type = post_data.get(prefix + "passenger_type", BookingPassenger.TYPE_ADULT).strip().upper()
        seat_number = post_data.get(prefix + "seat_number", "").strip().upper()

        if not first_name:
            row_errors.append("First name is required.")
        if not last_name:
            row_errors.append("Last name is required.")
        if not seat_number:
            row_errors.append("Please select a seat on the seat map.")
        elif seat_number in seen_seats:
            row_errors.append(f"Seat {seat_number} was selected for more than one passenger.")
        else:
            seen_seats.add(seat_number)

        if passenger_type not in VALID_PASSENGER_TYPES:
            passenger_type = BookingPassenger.TYPE_ADULT
        if gender not in VALID_GENDERS:
            gender = ""

        parsed_dob = None
        if dob:
            from datetime import datetime
            try:
                parsed_dob = datetime.strptime(dob, "%Y-%m-%d").date()
            except ValueError:
                row_errors.append("Invalid date of birth.")

        if row_errors:
            errors[i] = row_errors
        else:
            passengers_data.append({
                "first_name": first_name, "middle_name": middle_name, "last_name": last_name,
                "date_of_birth": parsed_dob, "gender": gender, "nationality": nationality,
                "email": email, "phone_number": phone, "passenger_type": passenger_type,
                "is_primary": i == 0, "seat_number": seat_number,
            })

    return passengers_data, errors


class CancelBookingForm(forms.Form):
    reason = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), required=False, label="Reason (optional)")


class RescheduleSearchForm(forms.Form):
    departure_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
