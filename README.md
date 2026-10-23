# AeroFlow — Flight Disruption Recovery & Passenger Service Platform

AeroFlow is a full-stack Django web application that lets airline passengers book
flights for themselves and their travel party, and handle disruptions (delays and
cancellations) or their own voluntary changes (reschedule, cancel) without manually
contacting airline support. Airline staff and administrators get the tools to manage
flights, disruptions, and recovery end-to-end.

> **Note on this build**: This project was generated in an offline sandbox with no
> internet access, so Django could not be installed or run there. Every file below
> is real, complete, hand-written application code (not a mockup) — but you should
> run `python manage.py check` yourself the first time you set it up, and report
> back any issue so it can be fixed. Everything was syntax-checked with
> `py_compile`, and every `{% url %}` tag / view reference / icon reference was
> cross-checked against what's actually defined, before delivery.

---

## 1. No external frontend dependencies

This project loads **zero** external CSS/JS/icon CDNs. Specifically:

- **No Bootstrap CSS, no Bootstrap CDN.** All layout, components, and utilities
  (grid, buttons, cards, tables, forms, alerts, navbar, dropdown, pagination,
  badges) are hand-written in one file: `static/css/style.css`, built on CSS
  variables defined at the top of that file so the whole theme can be re-skinned
  by editing a handful of `:root` values.
- **No icon font CDN** (no Bootstrap Icons, no Font Awesome). Every icon is a small
  local inline SVG stored in `static/icons/*.svg` (52 icons), rendered through a
  custom `{% icon "name" %}` template tag (`core/templatetags/icons.py`) that
  inlines the SVG directly into the page so it inherits `currentColor` for
  theming and costs zero network requests.
- **No Bootstrap JS bundle.** The small set of interactive behaviors Bootstrap's
  JS used to provide — mobile navbar collapse, the account dropdown, dismissible
  alerts — are implemented by hand in `static/js/app.js`, the single JS file for
  the whole site (also home to the dynamic multi-passenger booking form builder,
  AJAX flight search, live seat checks, and notification read receipts).
- The only external services this project talks to are the ones that have to be
  external: SMTP for email, and (optionally) a real MySQL server.

## 2. Objectives

- Let passengers search flights, book seats for themselves **and their travel
  party** (spouse, friends, family, children) in a single reservation, and self
  -serve changes to that booking (voluntary reschedule, cancellation).
- Automatically recover disrupted bookings: when staff mark a flight delayed or
  cancelled, every affected booking (and every passenger in it) is found,
  eligibility is calculated, and recovery options (rebooking, refund, vouchers)
  are unlocked automatically — not manual CRUD.
- Give airline staff a single dashboard to manage flights, disruptions, and
  recovery requests.
- Give administrators oversight of staff, passengers, system configuration, and
  an audit trail of all sensitive actions.

## 3. Features

### Passenger
Register/login · search flights · **book for multiple passengers in one
reservation** (adults/children/infants, each with their own name, DOB, gender,
nationality, and seat) · unique PNR per booking · view "My Bookings" with
filters (all/upcoming/completed/cancelled/rebooked) and search by PNR, flight
number, or passenger name · booking detail page showing the full passenger list
· **voluntary cancellation** (with cancellation policy shown, history kept) ·
**voluntary reschedule** onto a different date/flight, with fare-difference
shown before confirming · automatic delay/cancellation notifications (in-app +
email) that list every affected passenger · request rebooking (the whole travel
party moves together), request refund, claim meal/hotel/transport vouchers ·
download a **separate PDF boarding pass per passenger** (each with its own QR
code) · download PDF vouchers (with QR code) · notification center.

### Airline Staff
Staff dashboard with live stats (including real affected-*passenger* headcounts,
not just affected bookings) · full flight CRUD · mark a flight **Delayed** (with
duration + reason) or **Cancelled** (with reason) — automatically creates
disruption records for every affected booking, calculates recovery eligibility,
sends notifications + emails listing every passenger, and unlocks recovery
options · flight management page shows every active booking and its full
passenger list · approve or reject rebooking requests (re-runs the seat-check →
booking-update → new boarding passes-per-passenger → confirmation email chain
for the **whole group** at once) · approve/reject/process refund requests ·
daily operational report (view + PDF export).

### System Administrator
Manage staff (add/remove) · manage passengers (suspend/reactivate) · configure
system settings (delay-recovery threshold, voucher amounts, voucher validity —
nothing hard-coded) · view the full audit log · platform-wide statistics
dashboard. Also available through the standard Django admin at `/django-admin/`.

## 4. Automated Business Workflow (the important part)

This is **not** a plain CRUD app. When a staff member changes a flight's status:

```
ON_TIME → DELAYED
    1. Delay details saved on the Flight (minutes, reason, updated departure time)
    2. Every active booking on that flight is found (each may have 1-9 passengers)
    3. Eligibility is calculated against the configurable delay_recovery_threshold_minutes
    4. A DisruptionRecord is created per booking
    5. An in-app Notification is created for the booking's primary booker
    6. A delay email is sent, listing every passenger on that booking
    7. Recovery options light up automatically on the booking's recovery page

ON_TIME → CANCELLED
    1. Flight marked cancelled with a reason
    2. Every active booking becomes eligible for rebooking + refund + all vouchers
    3. DisruptionRecord, Notification, and cancellation email (with passenger list)
       created for each booking
    4. Alternative flights (same route, future departure, enough seats for the
       WHOLE travel party, not cancelled) are surfaced automatically

Rebooking approval (disruption-triggered, whole group moves together)
    1. Staff approves a pending RebookingRequest
    2. Seat availability is re-checked and locked (select_for_update, inside a DB
       transaction) for the full passenger count on that booking
    3. Seats are moved: -N on the new flight, +N back on the old flight (N = party size)
    4. A new Booking + PNR is created with every original passenger copied over
       and re-seated; the old booking is marked REBOOKED
    5. A new boarding pass PDF (with QR code) is generated PER PASSENGER
    6. A confirmation email with every passenger's boarding pass attached is sent

Voluntary reschedule (passenger-initiated, kept as a separate code path from
disruption rebooking so the two workflows can never be confused)
    Same seat-locking / new-PNR / per-passenger-boarding-pass mechanics as above,
    but initiated by the passenger from "My Bookings", with any fare difference
    shown before they confirm.
```

See `recovery/services.py` (disruption automation) and `bookings/services.py`
(booking creation, voluntary cancel/reschedule, and disruption group-rebooking)
for the implementation.

## 4b. This Revision: Receipt-First Booking, Dynamic Seats & Cumulative Delay

This revision changed several core workflows. All of it builds on the existing
project (same auth, same dashboards, same email system) rather than replacing it.

**Booking no longer produces a boarding pass.** Confirming a booking now
generates and emails a **Booking Receipt** (`bookings/receipt.py`) - a
different-looking PDF with a "your boarding pass will be generated
automatically once boarding opens" notice, the cancellation policy, and (if
the flight is delayed) the facility policy. The **Boarding Pass** (one per
passenger, still `bookings/pdf.py`) is only ever generated when staff move a
flight's status to **Boarding** - see `flights.views.staff_flight_mark_boarding`
→ `bookings.services.generate_boarding_passes_for_flight()`, which is
idempotent at both the flight level (`Flight.boarding_passes_generated_at`)
and the passenger level, so it can never fire twice or send duplicate emails.
Until then, the passenger dashboard shows a locked "Not Available Yet" state.

**Dynamic aircraft & seat maps.** `Aircraft` / `SeatCategory` / `Seat`
(`flights/models.py`) let staff define any seat layout with any category
names (Economy, Premium, Business, custom names, whatever an aircraft
actually has) via **Staff → Aircraft → Add Aircraft**, which builds the
category rows client-side (same dynamic-fieldset pattern as passenger forms)
and calls `flights.services.generate_seats_for_aircraft()` to generate the
real `Seat` rows. Booking a flight now shows a live, clickable seat map
(`bookings:seat_map_data`, rendered in `static/js/app.js`) built from that
flight's actual aircraft and current occupancy - a flight with only Economy
seats only ever shows Economy, nothing hard-coded. Seat selection is
re-validated transactionally at booking time (`bookings.services.create_booking`)
so two passengers can never be sold the same seat, even under concurrent
requests.

**Airports carry full operational detail** (terminal, gate, address, contact,
check-in/boarding info - `flights.models.Airport`), and flights track origin
*and* destination terminal/gate independently plus their own boarding time.
Staff can update gate/terminal/boarding time at any point
(**Staff → Manage Flights → a flight → Gate/Terminal**), which automatically
notifies every affected passenger in-app and by email
(`recovery.services.process_gate_terminal_change`).

**Cumulative, never-overwritten delay.** Every time staff add a delay
(`flights.services.add_flight_delay`), the value entered is always an
*additional* delay on top of whatever the flight already has - never a new
total - and a full `DelayRecord` history is kept per flight (visible on the
flight-management page). Facility eligibility is driven by **one centralized
function**, `flights.services.calculate_facility_eligibility()`, used
identically everywhere (dashboard, receipt, delay page, admin, email):
0-120 minutes → nothing; **strictly more than** 120 and under 240 → Meal
Voucher; 240+ → Meal + Hotel + Transportation. `recovery.models.PassengerFacility`
tracks each booking's eligibility/issued state per facility type and is
updated in place as delay grows, never duplicated.

**Voluntary cancellation follows one rule**: `bookings.services.cancel_booking()`
checks the time remaining before scheduled departure at the moment of
cancellation - 24 hours or more is refund-eligible, anything closer is not -
and creates a permanent `Cancellation` snapshot + `Refund` record plus a
Cancellation Receipt PDF (`bookings/receipt_cancellation.py`), distinct from
both the Booking Receipt and any airline-triggered `recovery.RefundRequest`
(which still drives the separate staff-approval queue for delay/cancellation
-by-airline refunds).

## 5. Technology Stack

- **Backend**: Python 3.10+, Django, Django ORM, Django Authentication (custom
  `User` model with a `role` field: passenger / staff / admin)
- **Database**: SQLite by default (zero setup); switches to MySQL (via
  `mysqlclient`) with one `.env` change, no code changes needed
- **Frontend**: HTML5 + Django templates, one custom `static/css/style.css`
  (CSS variables, hand-written grid/components), one `static/js/app.js`
  (vanilla JS, no frameworks), local inline SVG icons — **no CDNs at all**
- **PDF generation**: ReportLab (boarding passes — one per passenger, vouchers,
  daily report)
- **QR codes**: `qrcode` + Pillow, generated locally and embedded directly into
  the PDFs (no external QR API)
- **Email**: Django's email framework; console backend for local dev, SMTP for
  production, credentials always from environment variables

## 6. Data Model: how multi-passenger bookings work

```
User (primary booker / account holder)
   │
   └── Booking (one PNR, one flight, one travel class, one payment)
          │  contact_name / contact_email / contact_phone (booking contact)
          │
          ├── BookingPassenger (1..9 rows - one per traveller)
          │      first/middle/last name, DOB, gender, nationality,
          │      passenger_type (ADULT/CHILD/INFANT), seat_number,
          │      is_primary (True for the row representing the account holder)
          │      │
          │      └── BoardingPass (one-to-one - one PDF+QR per passenger)
          │
          ├── DisruptionRecord (created automatically on delay/cancellation)
          ├── RebookingRequest (disruption recovery - moves the whole group)
          ├── RefundRequest
          └── Voucher (per booking)
```

A single account can therefore book seats for themself, a spouse, friends,
children, etc. in one reservation with one PNR, while each traveller keeps their
own name, seat, and boarding pass. `Booking.rebook_reason` distinguishes a
disruption-triggered move (`DISRUPTION`) from a passenger-initiated one
(`VOLUNTARY`), and `Booking.rebooked_from` keeps the full chain of history
visible — nothing is ever deleted, only superseded.

## 7. Project Structure

```
aeroflow/
├── manage.py
├── aeroflow/            # settings, urls, wsgi/asgi
├── accounts/            # custom User, PassengerProfile, StaffProfile, auth views
├── flights/              # Airport, Flight, search, staff flight management
├── bookings/            # Booking, BookingPassenger, BoardingPass; booking flow
│                          # (search->select->passenger forms->confirm), voluntary
│                          # cancel/reschedule, per-passenger PDF generation
├── recovery/             # DisruptionRecord, RebookingRequest, RefundRequest,
│                          # and the automation "services.py" engine
├── vouchers/             # Voucher model, PDF generation, issuance service
├── notifications/       # In-app Notification model, AJAX mark-as-read
├── reports/              # Daily operational report (HTML + PDF)
├── dashboard/            # Role-aware dashboards (passenger / staff / admin)
├── core/                 # SystemSetting, AuditLog, shared utils, admin panel
│                          # views, and the local icon template tag
├── templates/            # All HTML templates (custom CSS, no framework classes
│                          # beyond ones this project defines itself)
├── static/
│   ├── css/style.css      # the ONE stylesheet for the whole project
│   ├── js/app.js          # the ONE JavaScript file for the whole project
│   └── icons/*.svg        # 52 local icon files, no icon CDN
├── media/                 # Generated PDFs (boarding passes, vouchers) at runtime
├── requirements.txt
├── .env.example
└── README.md
```

## 8. Installation & Setup

### 8.1 Prerequisites
- Python 3.10+
- `pip` and `venv`
- No database server needed — SQLite is the default and ships with Python.

### 8.2 Steps

```bash
# 1. Create and activate a virtual environment
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment variables
cp .env.example .env
# The defaults in .env.example already point at SQLite (db.sqlite3), so this
# works with no further edits. Set SECRET_KEY to something random for anything
# beyond local testing, and fill in EMAIL_* if you want real emails sent
# (otherwise emails just print to the console).

# 4. Run migrations (creates db.sqlite3 automatically)
python manage.py makemigrations
python manage.py migrate

# 5. Create a superuser (optional — seed_demo_data also creates an admin)
python manage.py createsuperuser

# 6. Load demo data: airports, flights (one pre-delayed, one pre-cancelled),
#    users, single-passenger bookings, and a 3-passenger GROUP booking so you
#    can see the multi-passenger + group-disruption-recovery flow immediately
python manage.py seed_demo_data

# 7. Run the development server
python manage.py runserver
```

Visit **http://127.0.0.1:8000/**.

### 8.3 Switching to MySQL

The project defaults to SQLite so it runs with zero external setup. To use MySQL
instead:

```bash
pip install mysqlclient   # uncomment it in requirements.txt too
```

Then in `.env`, comment out the SQLite line and uncomment the MySQL block:

```
DB_ENGINE=django.db.backends.mysql
DB_NAME=aeroflow_db
DB_USER=aeroflow_user
DB_PASSWORD=change-me
DB_HOST=127.0.0.1
DB_PORT=3306
```

Create the database first:

```sql
CREATE DATABASE aeroflow_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'aeroflow_user'@'localhost' IDENTIFIED BY 'change-me';
GRANT ALL PRIVILEGES ON aeroflow_db.* TO 'aeroflow_user'@'localhost';
FLUSH PRIVILEGES;
```

Then run `python manage.py migrate` as usual — no application code needs to
change, since the whole app talks to the database only through the Django ORM.

## 9. Demo Credentials (created by `seed_demo_data`)

| Role      | Username     | Password       |
|-----------|--------------|----------------|
| Admin     | `admin1`     | `AeroFlow@123` |
| Staff     | `staff1`     | `AeroFlow@123` |
| Passenger | `passenger1` | `AeroFlow@123` |
| Passenger | `passenger2` | `AeroFlow@123` |

`passenger1` owns a **3-passenger group booking** (herself, her spouse, her
child) on the flight the seed data cancels, so logging in as `passenger1` and
opening "My Bookings" is the fastest way to see the multi-passenger disruption
recovery flow end-to-end. `passenger2` has a booking on flight **AF401**,
which the seed data moves straight to **Boarding** status, so their boarding
pass already exists - open "My Bookings" as `passenger2` to see the unlocked
boarding-pass state. Flight **AF102** is delayed twice in the seed data (120
+ 120 minutes) specifically to demonstrate the cumulative rule crossing from
"no facility" to "Meal + Hotel + Transportation" - see its Delay History on
**Staff → Manage Flights → AF102**. No real personal information is used
anywhere in the seed data.

## 10. Configuration Highlights

- **Delay recovery threshold**: `SystemSetting` key `delay_recovery_threshold_minutes`
  (default 120), editable at Admin → System Settings, with a code-level fallback in
  `aeroflow/settings.py` (`AEROFLOW_DEFAULTS`). Nothing is hard-coded — see
  `core/utils.get_setting()`.
- **Voucher amounts & validity**: `meal_voucher_amount`, `hotel_voucher_amount`,
  `transport_voucher_amount`, `voucher_validity_days` — same mechanism.
- **Fares by class/passenger-type**: `Booking.CLASS_FARE_MULTIPLIER` and
  `bookings/services.py::PASSENGER_TYPE_FARE_FACTOR` are the single place fare
  rules live, rather than being scattered through views/templates.
- **Email credentials**: always read from `.env` (`EMAIL_HOST_USER`,
  `EMAIL_HOST_PASSWORD`, etc.) — never hard-coded, never committed.
- **Theming**: every color, radius, and shadow used across `style.css` is a
  `:root` CSS variable at the top of that file (`--af-navy`, `--af-blue`,
  `--af-success`, etc.) — change the palette in one place.

## 11. Security

- Django authentication + PBKDF2 password hashing
- CSRF protection on every form
- Role-based authorization via `core/utils.py` (`staff_required`, `admin_required`,
  `passenger_required` decorators and matching class-based mixins) — a passenger
  can't reach staff/admin dashboards, and staff can't reach admin-only pages
- All queries go through the Django ORM (no raw SQL)
- Booking/seat updates wrapped in DB transactions with `select_for_update()` to
  avoid race conditions on seat counts, including when locking seats for an
  entire multi-passenger group at once
- Custom 403/404/500 error pages (`core/error_views.py`) so raw tracebacks are
  never shown in production (`DEBUG=False`)

## 12. Performance notes

- List views (`my_bookings`, staff flight management, recovery requests
  dashboard, etc.) use `select_related()` / `prefetch_related()` to avoid N+1
  queries when displaying a booking's flight and its full passenger list.
- Indexes are defined on the fields that get filtered/searched most: `Booking.pnr`,
  `Booking.status`, `Booking.passenger`, `Flight.flight_number`, `Flight.status`,
  `AuditLog.timestamp`/`module`, `Notification.recipient`/`is_read`.
- The one stylesheet and one script file mean the whole site's frontend is two
  HTTP requests (plus per-page inline SVG icons that cost none), instead of
  pulling in a CDN framework bundle.

## 13. Migrations note

Because `Booking`/`BookingPassenger`/`BoardingPass` changed shape in this
revision (seats and travel class moved off `Booking` onto `BookingPassenger`,
and `BoardingPass` now points at a passenger instead of a booking), this needs
a **fresh set of migrations** rather than an incremental one if you had an older
version of this project already migrated. If you're starting fresh, `migrate`
just works. If you have an existing database from an earlier version of this
project, delete `db.sqlite3` (or drop/recreate the MySQL schema) and re-run
`makemigrations` + `migrate` + `seed_demo_data`.

## 14. Screenshots

_(Add screenshots here after running the app locally — e.g. `docs/screenshots/`.)_

## 15. Future Enhancements

- Payment gateway integration for real refund processing
- SMS notifications alongside email/in-app
- Per-passenger vouchers (currently issued per booking, covering the whole party)
- Multi-airline support with per-airline branding
- Seat-map visual picker instead of automatic seat assignment
- WebSocket-based real-time flight status updates

---

Built to demonstrate the complete passenger journey: **Register → Search Flight →
Select Passengers (self + family/friends) → Enter Passenger Details → Confirm
Booking → PNR → Boarding Passes → My Bookings → (Travel normally, or Reschedule/
Cancel voluntarily, or receive automatic Delay/Cancellation recovery → Rebook/
Refund/Voucher) → Updated Boarding Passes → Email Notification**, end-to-end.
