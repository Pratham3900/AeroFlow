from django import forms
from .models import Flight, Airport, Aircraft, SeatCategory, Terminal, Gate


class FlightForm(forms.ModelForm):
    class Meta:
        model = Flight
        fields = [
            "flight_number", "airline_name", "origin", "destination",
            "departure_date", "departure_time", "arrival_date", "arrival_time",
            "origin_terminal", "origin_gate", "destination_terminal", "destination_gate",
            "boarding_time", "aircraft", "status",
        ]
        widgets = {
            "departure_date": forms.DateInput(attrs={"type": "date"}),
            "arrival_date": forms.DateInput(attrs={"type": "date"}),
            "departure_time": forms.TimeInput(attrs={"type": "time"}),
            "arrival_time": forms.TimeInput(attrs={"type": "time"}),
            "boarding_time": forms.TimeInput(attrs={"type": "time"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["aircraft"].queryset = Aircraft.objects.filter(is_active=True)
        self.fields["origin"].queryset = Airport.objects.filter(is_active=True)
        self.fields["destination"].queryset = Airport.objects.filter(is_active=True)

        # The terminal/gate dropdowns are filtered to the right airport/terminal
        # live in the browser (static/js/app.js - initCascadingTerminalGateDropdowns),
        # since which airport/terminal is selected can change before submit. The
        # querysets here stay unrestricted so whatever the JS-filtered dropdown
        # submits still validates; clean() below is what actually enforces that
        # a terminal belongs to its airport and a gate belongs to its terminal,
        # so this can never be bypassed by tampering with the submitted value.
        self.fields["origin_terminal"].queryset = Terminal.objects.select_related("airport")
        self.fields["origin_gate"].queryset = Gate.objects.select_related("terminal")
        self.fields["destination_terminal"].queryset = Terminal.objects.select_related("airport")
        self.fields["destination_gate"].queryset = Gate.objects.select_related("terminal")
        for field_name in ("origin_terminal", "origin_gate", "destination_terminal", "destination_gate"):
            self.fields[field_name].required = False

    def clean(self):
        cleaned = super().clean()
        origin = cleaned.get("origin")
        destination = cleaned.get("destination")
        if origin and destination and origin == destination:
            raise forms.ValidationError("Origin and destination airports must be different.")

        origin_terminal = cleaned.get("origin_terminal")
        origin_gate = cleaned.get("origin_gate")
        destination_terminal = cleaned.get("destination_terminal")
        destination_gate = cleaned.get("destination_gate")

        if origin_terminal and origin and origin_terminal.airport_id != origin.id:
            self.add_error("origin_terminal", "This terminal does not belong to the selected origin airport.")
        if origin_gate and origin_terminal and origin_gate.terminal_id != origin_terminal.id:
            self.add_error("origin_gate", "This gate does not belong to the selected origin terminal.")
        if destination_terminal and destination and destination_terminal.airport_id != destination.id:
            self.add_error("destination_terminal", "This terminal does not belong to the selected destination airport.")
        if destination_gate and destination_terminal and destination_gate.terminal_id != destination_terminal.id:
            self.add_error("destination_gate", "This gate does not belong to the selected destination terminal.")

        return cleaned


class DelayUpdateForm(forms.Form):
    """
    The value entered here is always the ADDITIONAL delay being added on
    top of whatever cumulative delay the flight already has - see
    flights.services.add_flight_delay(), which does the addition. It is
    never treated as a new total.
    """
    additional_delay_minutes = forms.IntegerField(min_value=1, label="Additional Delay (minutes)")
    delay_reason = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), label="Reason for this delay")


class CancellationForm(forms.Form):
    cancellation_reason = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), label="Reason for cancellation")


class GateTerminalUpdateForm(forms.Form):
    """
    Staff can update gate/terminal/boarding time independently of a status
    change - passengers are notified automatically. Unlike FlightForm, the
    flight's origin/destination airports are fixed here (this form never
    changes them), so the terminal querysets can be safely restricted
    server-side to that flight's actual airports; only the gate dropdowns
    need the live terminal->gate JS cascade (static/js/app.js), since which
    terminal is selected can change before submit.
    """
    origin_terminal = forms.ModelChoiceField(queryset=Terminal.objects.none(), required=False, label="Origin Terminal")
    origin_gate = forms.ModelChoiceField(queryset=Gate.objects.none(), required=False, label="Origin Gate")
    destination_terminal = forms.ModelChoiceField(queryset=Terminal.objects.none(), required=False, label="Destination Terminal")
    destination_gate = forms.ModelChoiceField(queryset=Gate.objects.none(), required=False, label="Destination Gate")
    boarding_time = forms.TimeField(required=False, widget=forms.TimeInput(attrs={"type": "time"}), label="Boarding Time")

    def __init__(self, *args, flight=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.flight = flight
        if flight is not None:
            self.fields["origin_terminal"].queryset = Terminal.objects.filter(airport=flight.origin)
            self.fields["destination_terminal"].queryset = Terminal.objects.filter(airport=flight.destination)
            # Gate choices are scoped to whichever terminal is currently
            # selected on the flight; static/js/app.js repopulates these
            # live if the user picks a different terminal before submitting.
            if flight.origin_terminal_id:
                self.fields["origin_gate"].queryset = Gate.objects.filter(terminal_id=flight.origin_terminal_id)
            if flight.destination_terminal_id:
                self.fields["destination_gate"].queryset = Gate.objects.filter(terminal_id=flight.destination_terminal_id)
        else:
            # Fallback (form used without a bound flight): accept any gate,
            # cross-checked in clean() instead.
            self.fields["origin_gate"].queryset = Gate.objects.all()
            self.fields["destination_gate"].queryset = Gate.objects.all()

    def clean(self):
        cleaned = super().clean()
        origin_terminal = cleaned.get("origin_terminal")
        origin_gate = cleaned.get("origin_gate")
        destination_terminal = cleaned.get("destination_terminal")
        destination_gate = cleaned.get("destination_gate")

        if origin_gate and origin_terminal and origin_gate.terminal_id != origin_terminal.id:
            self.add_error("origin_gate", "This gate does not belong to the selected origin terminal.")
        if destination_gate and destination_terminal and destination_gate.terminal_id != destination_terminal.id:
            self.add_error("destination_gate", "This gate does not belong to the selected destination terminal.")
        return cleaned


class AirportForm(forms.ModelForm):
    class Meta:
        model = Airport
        fields = [
            "code", "name", "city", "state", "country", "address",
            "contact_phone", "contact_email", "checkin_info", "boarding_info", "is_active",
        ]


class TerminalForm(forms.ModelForm):
    """Used by the 'Add Terminal' feature on the airport edit page."""
    class Meta:
        model = Terminal
        fields = ["name"]
        widgets = {"name": forms.TextInput(attrs={"placeholder": "e.g. Terminal 1"})}


class GateForm(forms.ModelForm):
    """Used by the 'Add Gate' feature inside a terminal, on the airport edit page."""
    class Meta:
        model = Gate
        fields = ["name"]
        widgets = {"name": forms.TextInput(attrs={"placeholder": "e.g. Gate 1"})}


class AircraftForm(forms.ModelForm):
    class Meta:
        model = Aircraft
        fields = ["name", "model", "is_active"]


class SeatCategoryQuickForm(forms.Form):
    """One row of the 'configure seat categories' formset used when creating
    an aircraft - see static/js/app.js's aircraft-category builder and
    flights.views.staff_aircraft_add. Not a ModelForm because rows are
    built dynamically client-side, same pattern as passenger forms."""
    name = forms.CharField(max_length=60)
    code = forms.SlugField(max_length=30)
    rows = forms.IntegerField(min_value=1, max_value=60)
    seats_per_row = forms.IntegerField(min_value=1, max_value=10, initial=6)
    price_multiplier = forms.DecimalField(max_digits=4, decimal_places=2, initial=1.0, min_value=0.1)
    color = forms.CharField(max_length=20, initial="#1e88e5", required=False)
