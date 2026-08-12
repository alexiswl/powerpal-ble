"""Unit tests for ESPHomeCoordinator edge cases.

Validates: Requirements 3.1, 3.2, 3.3, 3.5, 4.4
"""

from __future__ import annotations

import importlib
import sys
from unittest.mock import MagicMock, patch

# Ensure homeassistant.core.callback is a pass-through decorator so that
# decorated methods in ESPHomeCoordinator remain callable functions.
_ha_core_mock = sys.modules.get("homeassistant.core")
if _ha_core_mock is not None:
    _ha_core_mock.callback = lambda f: f

# Force reimport of the coordinator module so it picks up the fixed callback
if "custom_components.powerpal_ble.esphome_coordinator" in sys.modules:
    importlib.reload(sys.modules["custom_components.powerpal_ble.esphome_coordinator"])

from custom_components.powerpal_ble.const import (
    CONF_CONNECTION_MODE,
    CONF_ESPHOME_POWER_ENTITY,
    CONF_ESPHOME_PULSE_ENTITY,
    CONNECTION_MODE_ESPHOME,
)
from custom_components.powerpal_ble.esphome_coordinator import ESPHomeCoordinator

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_hass():
    """Create a mocked hass object that captures event bus listeners."""
    hass = MagicMock()
    hass.bus.async_listen = MagicMock(return_value=MagicMock())
    return hass


def _make_entry(data: dict):
    """Create a mocked config entry with the given data."""
    entry = MagicMock()
    entry.data = data
    return entry


def _make_state_event(entity_id: str, state_value: str):
    """Create a mocked state_changed event."""
    event = MagicMock()
    event.data = {
        "entity_id": entity_id,
        "new_state": MagicMock(state=state_value),
    }
    return event


def _make_state_event_no_new_state(entity_id: str):
    """Create a state_changed event with new_state=None."""
    event = MagicMock()
    event.data = {
        "entity_id": entity_id,
        "new_state": None,
    }
    return event


def _start_coordinator(hass, entry):
    """Create and start a coordinator, returning (coordinator, callback, cancel)."""
    coordinator = ESPHomeCoordinator(hass, entry)
    with patch(
        "custom_components.powerpal_ble.esphome_coordinator.async_track_time_change"
    ):
        cancel = coordinator.async_start()
    callback_fn = hass.bus.async_listen.call_args[0][1]
    return coordinator, callback_fn, cancel


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFirstReading:
    """Test first reading sets power without energy accumulation.

    Validates: Requirements 3.1, 3.3
    """

    def test_first_reading_sets_power(self):
        """First state change sets power to the received value."""
        hass = _make_hass()
        entry = _make_entry(
            {
                CONF_CONNECTION_MODE: CONNECTION_MODE_ESPHOME,
                CONF_ESPHOME_POWER_ENTITY: "sensor.powerpal_power",
            }
        )
        coordinator, callback_fn, cancel = _start_coordinator(hass, entry)

        with patch(
            "custom_components.powerpal_ble.esphome_coordinator.time"
        ) as mock_time:
            mock_time.time.return_value = 1000.0
            mock_time.localtime.return_value = MagicMock(tm_yday=1)
            event = _make_state_event("sensor.powerpal_power", "350.5")
            callback_fn(event)

        assert coordinator.power == 350.5
        cancel()

    def test_first_reading_no_energy_accumulation(self):
        """First state change does NOT accumulate energy (no prior time reference)."""
        hass = _make_hass()
        entry = _make_entry(
            {
                CONF_CONNECTION_MODE: CONNECTION_MODE_ESPHOME,
                CONF_ESPHOME_POWER_ENTITY: "sensor.powerpal_power",
            }
        )
        coordinator, callback_fn, cancel = _start_coordinator(hass, entry)

        with patch(
            "custom_components.powerpal_ble.esphome_coordinator.time"
        ) as mock_time:
            mock_time.time.return_value = 5000.0
            mock_time.localtime.return_value = MagicMock(tm_yday=1)
            event = _make_state_event("sensor.powerpal_power", "1200.0")
            callback_fn(event)

        assert coordinator.energy_total_kwh == 0.0
        assert coordinator.daily_energy_kwh == 0.0
        cancel()


class TestNonNumericStates:
    """Test that non-numeric state values are ignored.

    Validates: Requirements 3.1, 3.2
    """

    def test_non_numeric_state_ignored_no_prior_reading(self):
        """Non-numeric state with no prior reading leaves power as None."""
        hass = _make_hass()
        entry = _make_entry(
            {
                CONF_CONNECTION_MODE: CONNECTION_MODE_ESPHOME,
                CONF_ESPHOME_POWER_ENTITY: "sensor.powerpal_power",
            }
        )
        coordinator, callback_fn, cancel = _start_coordinator(hass, entry)

        with patch(
            "custom_components.powerpal_ble.esphome_coordinator.time"
        ) as mock_time:
            mock_time.time.return_value = 1000.0
            mock_time.localtime.return_value = MagicMock(tm_yday=1)
            event = _make_state_event("sensor.powerpal_power", "abc")
            callback_fn(event)

        assert coordinator.power is None
        assert coordinator.energy_total_kwh == 0.0
        assert coordinator.daily_energy_kwh == 0.0
        cancel()

    def test_non_numeric_state_preserves_previous_power(self):
        """Non-numeric state after a valid reading preserves the previous power value."""
        hass = _make_hass()
        entry = _make_entry(
            {
                CONF_CONNECTION_MODE: CONNECTION_MODE_ESPHOME,
                CONF_ESPHOME_POWER_ENTITY: "sensor.powerpal_power",
            }
        )
        coordinator, callback_fn, cancel = _start_coordinator(hass, entry)

        # First: valid reading
        with patch(
            "custom_components.powerpal_ble.esphome_coordinator.time"
        ) as mock_time:
            mock_time.time.return_value = 1000.0
            mock_time.localtime.return_value = MagicMock(tm_yday=1)
            event = _make_state_event("sensor.powerpal_power", "500.0")
            callback_fn(event)

        assert coordinator.power == 500.0

        # Second: non-numeric — power should stay at 500.0
        with patch(
            "custom_components.powerpal_ble.esphome_coordinator.time"
        ) as mock_time:
            mock_time.time.return_value = 1060.0
            mock_time.localtime.return_value = MagicMock(tm_yday=1)
            event = _make_state_event("sensor.powerpal_power", "not_a_number")
            callback_fn(event)

        assert coordinator.power == 500.0
        # Energy should not have increased from the invalid reading
        assert coordinator.energy_total_kwh == 0.0
        cancel()

    def test_empty_string_state_ignored(self):
        """Empty string state is treated as non-numeric and ignored."""
        hass = _make_hass()
        entry = _make_entry(
            {
                CONF_CONNECTION_MODE: CONNECTION_MODE_ESPHOME,
                CONF_ESPHOME_POWER_ENTITY: "sensor.powerpal_power",
            }
        )
        coordinator, callback_fn, cancel = _start_coordinator(hass, entry)

        with patch(
            "custom_components.powerpal_ble.esphome_coordinator.time"
        ) as mock_time:
            mock_time.time.return_value = 1000.0
            mock_time.localtime.return_value = MagicMock(tm_yday=1)
            event = _make_state_event("sensor.powerpal_power", "")
            callback_fn(event)

        assert coordinator.power is None
        cancel()


class TestUnavailableUnknownStates:
    """Test that unavailable/unknown states are completely ignored.

    Validates: Requirements 3.1, 3.2
    """

    def test_unavailable_state_ignored(self):
        """STATE_UNAVAILABLE is ignored, power stays unchanged."""
        hass = _make_hass()
        entry = _make_entry(
            {
                CONF_CONNECTION_MODE: CONNECTION_MODE_ESPHOME,
                CONF_ESPHOME_POWER_ENTITY: "sensor.powerpal_power",
            }
        )
        coordinator, callback_fn, cancel = _start_coordinator(hass, entry)

        # Set initial power
        with patch(
            "custom_components.powerpal_ble.esphome_coordinator.time"
        ) as mock_time:
            mock_time.time.return_value = 1000.0
            mock_time.localtime.return_value = MagicMock(tm_yday=1)
            event = _make_state_event("sensor.powerpal_power", "200.0")
            callback_fn(event)

        assert coordinator.power == 200.0

        # Send unavailable — should be ignored
        with patch(
            "custom_components.powerpal_ble.esphome_coordinator.time"
        ) as mock_time:
            mock_time.time.return_value = 1060.0
            mock_time.localtime.return_value = MagicMock(tm_yday=1)
            event = _make_state_event("sensor.powerpal_power", "unavailable")
            callback_fn(event)

        assert coordinator.power == 200.0
        assert coordinator.energy_total_kwh == 0.0
        cancel()

    def test_unknown_state_ignored(self):
        """STATE_UNKNOWN is ignored, power stays unchanged."""
        hass = _make_hass()
        entry = _make_entry(
            {
                CONF_CONNECTION_MODE: CONNECTION_MODE_ESPHOME,
                CONF_ESPHOME_POWER_ENTITY: "sensor.powerpal_power",
            }
        )
        coordinator, callback_fn, cancel = _start_coordinator(hass, entry)

        # Set initial power
        with patch(
            "custom_components.powerpal_ble.esphome_coordinator.time"
        ) as mock_time:
            mock_time.time.return_value = 2000.0
            mock_time.localtime.return_value = MagicMock(tm_yday=1)
            event = _make_state_event("sensor.powerpal_power", "750.0")
            callback_fn(event)

        assert coordinator.power == 750.0

        # Send unknown — should be ignored
        with patch(
            "custom_components.powerpal_ble.esphome_coordinator.time"
        ) as mock_time:
            mock_time.time.return_value = 2060.0
            mock_time.localtime.return_value = MagicMock(tm_yday=1)
            event = _make_state_event("sensor.powerpal_power", "unknown")
            callback_fn(event)

        assert coordinator.power == 750.0
        assert coordinator.energy_total_kwh == 0.0
        cancel()

    def test_unavailable_does_not_advance_last_reading_time(self):
        """After unavailable, the next valid reading computes energy from the
        ORIGINAL time, not the time of the unavailable event."""
        hass = _make_hass()
        entry = _make_entry(
            {
                CONF_CONNECTION_MODE: CONNECTION_MODE_ESPHOME,
                CONF_ESPHOME_POWER_ENTITY: "sensor.powerpal_power",
            }
        )
        coordinator, callback_fn, cancel = _start_coordinator(hass, entry)

        # First valid reading at t=1000
        with patch(
            "custom_components.powerpal_ble.esphome_coordinator.time"
        ) as mock_time:
            mock_time.time.return_value = 1000.0
            mock_time.localtime.return_value = MagicMock(tm_yday=1)
            event = _make_state_event("sensor.powerpal_power", "600.0")
            callback_fn(event)

        # Unavailable at t=1030 — should be ignored entirely
        with patch(
            "custom_components.powerpal_ble.esphome_coordinator.time"
        ) as mock_time:
            mock_time.time.return_value = 1030.0
            mock_time.localtime.return_value = MagicMock(tm_yday=1)
            event = _make_state_event("sensor.powerpal_power", "unavailable")
            callback_fn(event)

        # Next valid reading at t=1060 — delta should be 60s from t=1000
        with patch(
            "custom_components.powerpal_ble.esphome_coordinator.time"
        ) as mock_time:
            mock_time.time.return_value = 1060.0
            mock_time.localtime.return_value = MagicMock(tm_yday=1)
            event = _make_state_event("sensor.powerpal_power", "600.0")
            callback_fn(event)

        # Energy: 600W * 60s / 3_600_000 = 0.01 kWh
        expected_energy = 600.0 * 60.0 / 3_600_000
        assert abs(coordinator.energy_total_kwh - expected_energy) < 1e-9
        cancel()


class TestMidnightDailyEnergyReset:
    """Test that midnight reset zeroes daily energy but not total energy.

    Validates: Requirement 3.5
    """

    def test_midnight_resets_daily_energy_only(self):
        """_handle_midnight resets daily_energy_kwh to 0 but leaves energy_total_kwh."""
        hass = _make_hass()
        entry = _make_entry(
            {
                CONF_CONNECTION_MODE: CONNECTION_MODE_ESPHOME,
                CONF_ESPHOME_POWER_ENTITY: "sensor.powerpal_power",
            }
        )
        coordinator, callback_fn, cancel = _start_coordinator(hass, entry)

        # Simulate two readings to accumulate some energy
        with patch(
            "custom_components.powerpal_ble.esphome_coordinator.time"
        ) as mock_time:
            mock_time.time.return_value = 1000.0
            mock_time.localtime.return_value = MagicMock(tm_yday=1)
            event = _make_state_event("sensor.powerpal_power", "1000.0")
            callback_fn(event)

        with patch(
            "custom_components.powerpal_ble.esphome_coordinator.time"
        ) as mock_time:
            mock_time.time.return_value = 1060.0
            mock_time.localtime.return_value = MagicMock(tm_yday=1)
            event = _make_state_event("sensor.powerpal_power", "1000.0")
            callback_fn(event)

        # Energy: 1000W * 60s / 3_600_000 = 0.016667 kWh
        expected_energy = 1000.0 * 60.0 / 3_600_000
        assert coordinator.daily_energy_kwh > 0
        assert abs(coordinator.energy_total_kwh - expected_energy) < 1e-9

        # Trigger midnight reset
        with patch(
            "custom_components.powerpal_ble.esphome_coordinator.time"
        ) as mock_time:
            mock_time.localtime.return_value = MagicMock(tm_yday=2)
            coordinator._handle_midnight(None)

        # daily should be 0, total unchanged
        assert coordinator.daily_energy_kwh == 0.0
        assert abs(coordinator.energy_total_kwh - expected_energy) < 1e-9
        cancel()

    def test_midnight_notifies_listeners(self):
        """_handle_midnight notifies registered listeners."""
        hass = _make_hass()
        entry = _make_entry(
            {
                CONF_CONNECTION_MODE: CONNECTION_MODE_ESPHOME,
                CONF_ESPHOME_POWER_ENTITY: "sensor.powerpal_power",
            }
        )
        coordinator, _callback_fn, cancel = _start_coordinator(hass, entry)

        listener = MagicMock()
        coordinator.async_add_listener(listener)

        with patch(
            "custom_components.powerpal_ble.esphome_coordinator.time"
        ) as mock_time:
            mock_time.localtime.return_value = MagicMock(tm_yday=2)
            coordinator._handle_midnight(None)

        listener.assert_called_once()
        cancel()


class TestBackwardCompatibilityPulseEntity:
    """Test backward compatibility: coordinator works with esphome_pulse_entity config key.

    Validates: Requirement 4.4
    """

    def test_pulse_entity_key_used_as_source(self):
        """When only CONF_ESPHOME_PULSE_ENTITY is present, it is used as the source entity."""
        hass = _make_hass()
        entry = _make_entry(
            {
                CONF_CONNECTION_MODE: CONNECTION_MODE_ESPHOME,
                CONF_ESPHOME_PULSE_ENTITY: "sensor.powerpal_pulses",
            }
        )

        coordinator = ESPHomeCoordinator(hass, entry)
        assert coordinator._source_entity == "sensor.powerpal_pulses"

    def test_pulse_entity_processes_state_changes(self):
        """Coordinator with old config key processes state events for that entity."""
        hass = _make_hass()
        entry = _make_entry(
            {
                CONF_CONNECTION_MODE: CONNECTION_MODE_ESPHOME,
                CONF_ESPHOME_PULSE_ENTITY: "sensor.powerpal_pulses",
            }
        )
        coordinator, callback_fn, cancel = _start_coordinator(hass, entry)

        with patch(
            "custom_components.powerpal_ble.esphome_coordinator.time"
        ) as mock_time:
            mock_time.time.return_value = 1000.0
            mock_time.localtime.return_value = MagicMock(tm_yday=1)
            event = _make_state_event("sensor.powerpal_pulses", "425.0")
            callback_fn(event)

        assert coordinator.power == 425.0
        cancel()

    def test_power_entity_takes_precedence_over_pulse_entity(self):
        """When both keys exist, CONF_ESPHOME_POWER_ENTITY takes precedence."""
        hass = _make_hass()
        entry = _make_entry(
            {
                CONF_CONNECTION_MODE: CONNECTION_MODE_ESPHOME,
                CONF_ESPHOME_POWER_ENTITY: "sensor.powerpal_power",
                CONF_ESPHOME_PULSE_ENTITY: "sensor.powerpal_pulses",
            }
        )

        coordinator = ESPHomeCoordinator(hass, entry)
        assert coordinator._source_entity == "sensor.powerpal_power"
