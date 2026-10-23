/* ==========================================================================
   AeroFlow - app.js
   All site JavaScript lives in this one file (no external JS libraries,
   no Bootstrap bundle). Handles: navbar/dropdown/alert UI behaviour that
   Bootstrap's JS used to provide, AJAX notification read, AJAX flight
   search/seat checks, and the multi-passenger booking form builder.
   ========================================================================== */

document.addEventListener("DOMContentLoaded", function () {
  initNavbarToggle();
  initDropdowns();
  initAlertDismiss();
  initNotificationRead();
  initFlightSearch();
  initSeatCheck();
  initPassengerFormBuilder();
  initConfirmActions();
  initAircraftCategoryBuilder();
  initCascadingTerminalGateDropdowns();
});

/* ---------------------------------------------------------------
   Mobile navbar toggle (replaces data-bs-toggle="collapse")
   --------------------------------------------------------------- */
function initNavbarToggle() {
  document.querySelectorAll('[data-toggle="collapse"]').forEach(function (btn) {
    btn.addEventListener("click", function () {
      const target = document.querySelector(btn.dataset.target);
      if (target) target.classList.toggle("show");
    });
  });
}

/* ---------------------------------------------------------------
   Dropdown menus (replaces data-bs-toggle="dropdown")
   --------------------------------------------------------------- */
function initDropdowns() {
  document.querySelectorAll('[data-toggle="dropdown"]').forEach(function (toggle) {
    toggle.addEventListener("click", function (e) {
      e.preventDefault();
      const menu = toggle.parentElement.querySelector(".dropdown-menu");
      const isOpen = menu.classList.contains("show");
      closeAllDropdowns();
      if (!isOpen) menu.classList.add("show");
    });
  });

  document.addEventListener("click", function (e) {
    if (!e.target.closest(".dropdown")) closeAllDropdowns();
  });

  function closeAllDropdowns() {
    document.querySelectorAll(".dropdown-menu.show").forEach((m) => m.classList.remove("show"));
  }
}

/* ---------------------------------------------------------------
   Dismissible alerts (replaces data-bs-dismiss="alert")
   --------------------------------------------------------------- */
function initAlertDismiss() {
  document.querySelectorAll('[data-dismiss="alert"]').forEach(function (btn) {
    btn.addEventListener("click", function () {
      const alertEl = btn.closest(".alert");
      if (!alertEl) return;
      alertEl.classList.remove("show");
      setTimeout(() => alertEl.remove(), 150);
    });
  });
}

/* ---------------------------------------------------------------
   Notifications: mark-as-read via AJAX
   --------------------------------------------------------------- */
function initNotificationRead() {
  document.querySelectorAll(".mark-notif-read").forEach(function (el) {
    el.addEventListener("click", function (e) {
      e.preventDefault();
      const url = el.dataset.url;
      fetch(url, { method: "POST", headers: { "X-CSRFToken": getCookie("csrftoken") } })
        .then((r) => r.json())
        .then((data) => {
          if (data.success) {
            el.closest(".notification-item")?.classList.remove("bg-light");
            el.remove();
          }
        });
    });
  });
}

/* ---------------------------------------------------------------
   Live flight search filtering (AJAX, no full page reload)
   --------------------------------------------------------------- */
function initFlightSearch() {
  const searchForm = document.getElementById("flight-search-form");
  if (!searchForm) return;

  searchForm.addEventListener("submit", function (e) {
    e.preventDefault();
    loadFlightResults();
  });
  searchForm.querySelectorAll("select").forEach((sel) => sel.addEventListener("change", loadFlightResults));

  function loadFlightResults() {
    const params = new URLSearchParams(new FormData(searchForm));
    fetch(searchForm.action + "?" + params.toString(), { headers: { "X-Requested-With": "XMLHttpRequest" } })
      .then((r) => r.text())
      .then((html) => {
        const target = document.getElementById("flight-results");
        if (target) target.innerHTML = html;
      });
  }
}

/* ---------------------------------------------------------------
   Live seat-availability check (rebooking / recovery pages)
   --------------------------------------------------------------- */
function initSeatCheck() {
  document.querySelectorAll(".check-seats-btn").forEach(function (btn) {
    btn.addEventListener("click", function () {
      const url = btn.dataset.url;
      const target = document.querySelector(btn.dataset.target);
      fetch(url)
        .then((r) => r.json())
        .then((data) => {
          target.textContent = data.has_seats ? `${data.available_seats} seat(s) available` : "No seats available";
          target.className = data.has_seats ? "text-success small" : "text-danger small";
        });
    });
  });
}

/* ---------------------------------------------------------------
   Confirm dialogs for destructive actions (data-confirm="message")
   --------------------------------------------------------------- */
function initConfirmActions() {
  document.querySelectorAll("[data-confirm]").forEach(function (el) {
    el.addEventListener("submit", function (e) {
      if (!window.confirm(el.dataset.confirm)) e.preventDefault();
    });
  });
}

/* ---------------------------------------------------------------
   Multi-passenger booking form builder + interactive seat map.

   Reads Adults/Children/Infants counts and generates one passenger
   details fieldset per passenger. Each passenger must then pick a seat
   from the seat map (fetched live from the server, reflecting real
   occupancy) before the booking can be submitted - the server
   independently re-validates every seat choice, this is purely UX.
   --------------------------------------------------------------- */
let aeroflowSeatState = {
  seats: [],          // [{seat_number, row, column, category, category_code, color, status}]
  categories: [],      // [{code, name, color, multiplier}]
  assignments: {},     // { passengerIndex: seatNumber }
  activePassenger: null,
};

function initPassengerFormBuilder() {
  const countsForm = document.getElementById("passenger-counts-form");
  const container = document.getElementById("passenger-forms-container");
  const template = document.getElementById("passenger-form-template");
  if (!countsForm || !container || !template) return;

  function totalPassengers() {
    const adults = parseInt(countsForm.querySelector('[name="adults"]').value || "0", 10);
    const children = parseInt(countsForm.querySelector('[name="children"]').value || "0", 10);
    const infants = parseInt(countsForm.querySelector('[name="infants"]').value || "0", 10);
    return { adults, children, infants, total: adults + children + infants };
  }

  function passengerType(index, adults, children) {
    if (index < adults) return "ADULT";
    if (index < adults + children) return "CHILD";
    return "INFANT";
  }

  function render() {
    const { adults, children, infants, total } = totalPassengers();
    container.innerHTML = "";
    aeroflowSeatState.assignments = {};

    if (total < 1) {
      container.innerHTML = '<p class="text-muted small">Select at least one passenger.</p>';
      renderSeatMap();
      return;
    }
    if (total > 9) {
      container.innerHTML = '<p class="text-danger small">A single booking supports up to 9 passengers. Please split larger groups into multiple bookings.</p>';
      renderSeatMap();
      return;
    }

    for (let i = 0; i < total; i++) {
      const type = passengerType(i, adults, children);
      const clone = template.content.cloneNode(true);
      const fieldset = clone.querySelector("fieldset");
      fieldset.dataset.passengerIndex = i;
      fieldset.querySelectorAll("[data-field]").forEach((input) => {
        const field = input.dataset.field;
        input.name = `passenger-${i}-${field}`;
        input.id = `id_passenger-${i}-${field}`;
      });
      const label = clone.querySelector(".passenger-form-label");
      if (label) {
        const typeLabel = type === "ADULT" ? "Adult" : type === "CHILD" ? "Child" : "Infant";
        label.textContent = `Passenger ${i + 1} (${typeLabel})${i === 0 ? " - Primary Booker" : ""}`;
      }
      const typeField = clone.querySelector('[data-field="passenger_type"]');
      if (typeField) typeField.value = type;

      const seatBtn = clone.querySelector(".select-seat-btn");
      if (seatBtn) {
        seatBtn.dataset.passengerIndex = i;
        seatBtn.addEventListener("click", () => {
          aeroflowSeatState.activePassenger = i;
          renderSeatMap();
          document.getElementById("seat-map-panel")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
        });
      }
      container.appendChild(clone);
    }

    aeroflowSeatState.activePassenger = 0;
    renderSeatMap();
    updateFareEstimate();
  }

  function updateFareEstimate() {
    const estimateEl = document.getElementById("fare-estimate");
    if (!estimateEl || !estimateEl.dataset.fareUrl) return;
    const seatNumbers = [];
    const types = [];
    document.querySelectorAll("#passenger-forms-container fieldset").forEach((fs) => {
      const idx = fs.dataset.passengerIndex;
      const seat = aeroflowSeatState.assignments[idx];
      if (seat) {
        seatNumbers.push(seat);
        types.push(fs.querySelector('[data-field="passenger_type"]').value);
      }
    });
    if (!seatNumbers.length) {
      estimateEl.textContent = "select seats to see fare";
      return;
    }
    const params = new URLSearchParams({ seats: seatNumbers.join(","), types: types.join(",") });
    fetch(estimateEl.dataset.fareUrl + "?" + params.toString())
      .then((r) => r.json())
      .then((data) => {
        estimateEl.textContent = `Rs. ${data.total_fare} (${data.passenger_count} pax)`;
      })
      .catch(() => {
        estimateEl.textContent = "unavailable";
      });
  }

  function renderSeatMap() {
    const mapEl = document.getElementById("seat-map");
    const legendEl = document.getElementById("seat-map-legend");
    if (!mapEl) return;

    if (!aeroflowSeatState.seats.length) {
      mapEl.innerHTML = '<p class="text-muted small">No seat map available for this flight.</p>';
      return;
    }

    // Group seats by row
    const rows = {};
    aeroflowSeatState.seats.forEach((seat) => {
      rows[seat.row] = rows[seat.row] || [];
      rows[seat.row].push(seat);
    });

    const assignedSeats = new Set(Object.values(aeroflowSeatState.assignments));

    let html = '<div class="seat-map-grid">';
    Object.keys(rows).sort((a, b) => a - b).forEach((rowNum) => {
      html += `<div class="seat-row"><span class="seat-row-label">${rowNum}</span>`;
      rows[rowNum].forEach((seat) => {
        let cls = "seat";
        if (assignedSeats.has(seat.seat_number)) {
          const idx = Object.keys(aeroflowSeatState.assignments).find((k) => aeroflowSeatState.assignments[k] === seat.seat_number);
          cls += idx == aeroflowSeatState.activePassenger ? " seat-selected-active" : " seat-selected";
        } else if (seat.status === "occupied") {
          cls += " seat-occupied";
        } else if (seat.status === "unavailable") {
          cls += " seat-unavailable";
        } else {
          cls += " seat-available";
        }
        html += `<button type="button" class="${cls}" style="--seat-color:${seat.color}" data-seat="${seat.seat_number}" title="${seat.seat_number} (${seat.category})" ${seat.status === "occupied" || seat.status === "unavailable" ? "disabled" : ""}>${seat.column}</button>`;
      });
      html += "</div>";
    });
    html += "</div>";
    mapEl.innerHTML = html;

    mapEl.querySelectorAll(".seat[data-seat]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const seatNumber = btn.dataset.seat;
        const idx = aeroflowSeatState.activePassenger;
        if (idx === null || idx === undefined) return;

        // Deselect if clicking the seat already assigned to the active passenger.
        if (aeroflowSeatState.assignments[idx] === seatNumber) {
          delete aeroflowSeatState.assignments[idx];
        } else {
          // Free this seat from anyone else who had it, then assign to active passenger.
          Object.keys(aeroflowSeatState.assignments).forEach((k) => {
            if (aeroflowSeatState.assignments[k] === seatNumber) delete aeroflowSeatState.assignments[k];
          });
          aeroflowSeatState.assignments[idx] = seatNumber;
        }

        // Write the chosen seat into that passenger's hidden field.
        const fieldset = document.querySelector(`#passenger-forms-container fieldset[data-passenger-index="${idx}"]`);
        if (fieldset) {
          const hiddenInput = fieldset.querySelector('[data-field="seat_number"]');
          if (hiddenInput) hiddenInput.value = aeroflowSeatState.assignments[idx] || "";
          const display = fieldset.querySelector(".passenger-seat-display");
          if (display) display.textContent = aeroflowSeatState.assignments[idx] || "No seat selected";
        }

        // Auto-advance to the next passenger without a seat.
        const fieldsets = [...document.querySelectorAll("#passenger-forms-container fieldset")];
        const next = fieldsets.find((fs) => !aeroflowSeatState.assignments[fs.dataset.passengerIndex]);
        aeroflowSeatState.activePassenger = next ? parseInt(next.dataset.passengerIndex, 10) : idx;

        renderSeatMap();
        updateFareEstimate();
      });
    });

    if (legendEl && aeroflowSeatState.categories.length) {
      legendEl.innerHTML = aeroflowSeatState.categories.map(
        (c) => `<span class="seat-legend-item"><span class="seat-legend-swatch" style="background:${c.color}"></span>${c.name} (x${c.multiplier})</span>`
      ).join("") + '<span class="seat-legend-item"><span class="seat-legend-swatch seat-legend-occupied"></span>Occupied</span>'
        + '<span class="seat-legend-item"><span class="seat-legend-swatch seat-legend-unavailable"></span>Unavailable</span>'
        + '<span class="seat-legend-item"><span class="seat-legend-swatch seat-legend-selected"></span>Selected</span>';
    }
  }

  const seatMapEl = document.getElementById("seat-map");
  if (seatMapEl && seatMapEl.dataset.seatMapUrl) {
    fetch(seatMapEl.dataset.seatMapUrl)
      .then((r) => r.json())
      .then((data) => {
        aeroflowSeatState.seats = data.seats || [];
        aeroflowSeatState.categories = data.categories || [];
        render();
      });
  } else {
    render();
  }

  countsForm.querySelectorAll("select, input[type=number]").forEach((el) => el.addEventListener("change", render));
}

/* ---------------------------------------------------------------
   Utilities
   --------------------------------------------------------------- */
function getCookie(name) {
  let cookieValue = null;
  if (document.cookie && document.cookie !== "") {
    const cookies = document.cookie.split(";");
    for (let i = 0; i < cookies.length; i++) {
      const cookie = cookies[i].trim();
      if (cookie.substring(0, name.length + 1) === name + "=") {
        cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
        break;
      }
    }
  }
  return cookieValue;
}

/* ---------------------------------------------------------------
   Aircraft seat-category builder (staff "Add Aircraft" page).
   Lets staff add any number of custom seat categories (name, code,
   rows, seats/row, price multiplier, colour) with no categories
   hard-coded anywhere - see flights.views.staff_aircraft_add, which
   parses these rows and calls flights.services.generate_seats_for_aircraft.
   --------------------------------------------------------------- */
function initAircraftCategoryBuilder() {
  const container = document.getElementById("category-rows-container");
  const template = document.getElementById("category-row-template");
  const addBtn = document.getElementById("add-category-row-btn");
  const totalInput = document.getElementById("id_total_categories");
  const summaryEl = document.getElementById("category-summary");
  if (!container || !template || !addBtn) return;

  let rowCount = 0;

  function addRow() {
    const index = rowCount++;
    const clone = template.content.cloneNode(true);
    const wrapper = clone.querySelector(".category-row");
    wrapper.dataset.index = index;
    wrapper.querySelectorAll("[data-field]").forEach((input) => {
      const field = input.dataset.field;
      input.name = `category-${index}-${field}`;
    });
    wrapper.querySelector(".remove-category-row-btn").addEventListener("click", () => {
      wrapper.remove();
      updateSummary();
    });
    wrapper.querySelectorAll("input").forEach((input) => input.addEventListener("input", updateSummary));
    container.appendChild(clone);
    updateSummary();
  }

  function updateSummary() {
    if (totalInput) totalInput.value = container.querySelectorAll(".category-row").length;
    if (!summaryEl) return;
    let totalSeats = 0;
    container.querySelectorAll(".category-row").forEach((row) => {
      const rows = parseInt(row.querySelector('[data-field="rows"]').value || "0", 10);
      const perRow = parseInt(row.querySelector('[data-field="seats_per_row"]').value || "0", 10);
      totalSeats += rows * perRow;
    });
    summaryEl.textContent = `${totalSeats} total seat(s) across ${container.querySelectorAll(".category-row").length} categor${container.querySelectorAll(".category-row").length === 1 ? "y" : "ies"}`;
  }

  addBtn.addEventListener("click", addRow);
  addRow(); // start with one row so the form isn't empty
}

/* ---------------------------------------------------------------
   Cascading Terminal -> Gate dropdowns (and, where an airport selector
   is present, Airport -> Terminal too), used on the flight add/edit form
   and the flight-manage "Gate/Terminal" update form. Both forms use the
   same field ids (id_origin_terminal, id_origin_gate, etc.) so one
   generic function wires both; it simply does nothing on pages that
   don't have these fields.
   --------------------------------------------------------------- */
function initCascadingTerminalGateDropdowns() {
  wireAirportTerminalGate("origin");
  wireAirportTerminalGate("destination");

  function wireAirportTerminalGate(prefix) {
    const terminalSelect = document.getElementById(`id_${prefix}_terminal`);
    const gateSelect = document.getElementById(`id_${prefix}_gate`);
    if (!terminalSelect || !gateSelect) return;

    const airportSelect = document.getElementById(`id_${prefix === "origin" ? "origin" : "destination"}`);

    function loadGates(terminalId, preserveValue) {
      const currentValue = preserveValue !== undefined ? preserveValue : gateSelect.value;
      if (!terminalId) {
        gateSelect.innerHTML = '<option value="">---------</option>';
        return;
      }
      fetch(`/flights/ajax/gates/?terminal_id=${encodeURIComponent(terminalId)}`)
        .then((r) => r.json())
        .then((data) => {
          gateSelect.innerHTML = '<option value="">---------</option>' + data.gates.map(
            (g) => `<option value="${g.id}">${g.name}</option>`
          ).join("");
          if (currentValue && data.gates.some((g) => String(g.id) === String(currentValue))) {
            gateSelect.value = currentValue;
          }
        });
    }

    function loadTerminals(airportId, preserveTerminal, preserveGate) {
      const currentTerminal = preserveTerminal !== undefined ? preserveTerminal : terminalSelect.value;
      const currentGate = preserveGate !== undefined ? preserveGate : gateSelect.value;
      if (!airportId) {
        terminalSelect.innerHTML = '<option value="">---------</option>';
        loadGates(null);
        return;
      }
      fetch(`/flights/ajax/terminals/?airport_id=${encodeURIComponent(airportId)}`)
        .then((r) => r.json())
        .then((data) => {
          terminalSelect.innerHTML = '<option value="">---------</option>' + data.terminals.map(
            (t) => `<option value="${t.id}">${t.name}</option>`
          ).join("");
          if (currentTerminal && data.terminals.some((t) => String(t.id) === String(currentTerminal))) {
            terminalSelect.value = currentTerminal;
            loadGates(currentTerminal, currentGate);
          } else {
            loadGates(null);
          }
        });
    }

    if (airportSelect) {
      // Full cascade: Airport -> Terminal -> Gate (flight add/edit form).
      const initialAirport = airportSelect.value;
      const initialTerminal = terminalSelect.value;
      const initialGate = gateSelect.value;
      if (initialAirport) loadTerminals(initialAirport, initialTerminal, initialGate);

      airportSelect.addEventListener("change", function () {
        loadTerminals(airportSelect.value, "", "");
      });
      terminalSelect.addEventListener("change", function () {
        loadGates(terminalSelect.value, "");
      });
    } else {
      // Airport is fixed (flight-manage gate-update form): the terminal
      // dropdown is already server-filtered to the right airport, so we
      // only need the Terminal -> Gate cascade here.
      terminalSelect.addEventListener("change", function () {
        loadGates(terminalSelect.value, "");
      });
    }
  }
}
