"""Integration tests for ESPHome coordinator end-to-end.

Validates: Requirements 3.1, 3.3, 3.4, 4.4
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


def _make_hass():
    """Create a mocked hass object that captures event bus listeners."""
    hass = MagicMock()
    # Capture the callback registered via hass.bus.async_listen
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


class TestESPHomeCoordinatorEndToEnd:
    """End-to-end tests for the ESPHome coordinator flow."""

    def test_coordinator_starts_and_receives_state_changes(self):
        """Test coordinator starts, receives mocked state changes with watt values,
        and correctly populates power, energy_total_kwh, daily_energy_kwh.

        Validates: Requirements 3.1, 3.3, 3.4
        """
        hass = _make_hass()
        entry = _make_entry(
            {
                CONF_CONNECTION_MODE: CONNECTION_MODE_ESPHOME,
                CONF_ESPHOME_POWER_ENTITY: "sensor.powerpal_power",
            }
        )

        coordinator = ESPHomeCoordinator(hass, entry)

        # Start the coordinator — this registers the event listener
        with patch(
            "custom_components.powerpal_ble.esphome_coordinator.async_track_time_change"
        ):
            cancel = coordinator.async_start()

        # Grab the callback that was registered on the event bus
        hass.bus.async_listen.assert_called_once()
        callback = hass.bus.async_listen.call_args[0][1]

        # Simulate first reading at t=1000.0 with 500W
        with patch(
            "custom_components.powerpal_ble.esphome_coordinator.time"
        ) as mock_time:
            mock_time.time.return_value = 1000.0
            mock_time.localtime.return_value = MagicMock(tm_yday=1)
            event1 = _make_state_event("sensor.powerpal_power", "500.0")
            callback(event1)

        # First reading: power should be set, but no energy accumulated
        assert coordinator.power == 500.0
        assert coordinator.energy_total_kwh == 0.0
        assert coordinator.daily_energy_kwh == 0.0

        # Simulate second reading at t=1060.0 (60s later) with 500W
        with patch(
            "custom_components.powerpal_ble.esphome_coordinator.time"
        ) as mock_time:
            mock_time.time.return_value = 1060.0
            mock_time.localtime.return_value = MagicMock(tm_yday=1)
            event2 = _make_state_event("sensor.powerpal_power", "500.0")
            callback(event2)

        # Energy: 500W * 60s / 3_600_000 = 0.008333... kWh
        expected_energy = 500.0 * 60.0 / 3_600_000
        assert coordinator.power == 500.0
        assert abs(coordinator.energy_total_kwh - expected_energy) < 1e-9
        assert abs(coordinator.daily_energy_kwh - expected_energy) < 1e-9

        # Cleanup
        cancel()

    def test_multiple_readings_accumulate_energy(self):
        """Test that multiple state changes with time passing accumulate energy correctly.

        Validates: Requirements 3.3, 3.4
        """
        hass = _make_hass()
        entry = _make_entry(
            {
                CONF_CONNECTION_MODE: CONNECTION_MODE_ESPHOME,
                CONF_ESPHOME_POWER_ENTITY: "sensor.powerpal_power",
            }
        )

        coordinator = ESPHomeCoordinator(hass, entry)

        with patch(
            "custom_components.powerpal_ble.esphome_coordinator.async_track_time_change"
        ):
            cancel = coordinator.async_start()

        callback = hass.bus.async_listen.call_args[0][1]

        # Define a sequence of readings: (time, power_watts)
        readings = [
            (1000.0, 100.0),  # First reading — no energy
            (1060.0, 200.0),  # 60s at 200W
            (1120.0, 300.0),  # 60s at 300W
            (1180.0, 150.0),  # 60s at 150W
            (1300.0, 400.0),  # 120s at 400W
        ]

        for t, power in readings:
            with patch(
                "custom_components.powerpal_ble.esphome_coordinator.time"
            ) as mock_time:
                mock_time.time.return_value = t
                mock_time.localtime.return_value = MagicMock(tm_yday=1)
                event = _make_state_event("sensor.powerpal_power", str(power))
                callback(event)

        # Expected energy (skip first reading — no prior time):
        # 200W * 60s / 3_600_000 = 0.003333...
        # 300W * 60s / 3_600_000 = 0.005
        # 150W * 60s / 3_600_000 = 0.0025
        # 400W * 120s / 3_600_000 = 0.013333...
        expected_total = (
            200.0 * 60.0 / 3_600_000
            + 300.0 * 60.0 / 3_600_000
            + 150.0 * 60.0 / 3_600_000
            + 400.0 * 120.0 / 3_600_000
        )

        assert coordinator.power == 400.0
        assert abs(coordinator.energy_total_kwh - expected_total) < 1e-9
        assert abs(coordinator.daily_energy_kwh - expected_total) < 1e-9

        cancel()

    def test_backward_compatibility_pulse_entity_key(self):
        """Test that entry with old esphome_pulse_entity key still initializes coordinator.

        Validates: Requirement 4.4
        """
        hass = _make_hass()
        # Use the OLD config key — no esphome_power_entity present
        entry = _make_entry(
            {
                CONF_CONNECTION_MODE: CONNECTION_MODE_ESPHOME,
                CONF_ESPHOME_PULSE_ENTITY: "sensor.powerpal_pulses",
            }
        )

        coordinator = ESPHomeCoordinator(hass, entry)

        # Verify it initialized with the old entity as the source
        assert coordinator._source_entity == "sensor.powerpal_pulses"

        with patch(
            "custom_components.powerpal_ble.esphome_coordinator.async_track_time_change"
        ):
            cancel = coordinator.async_start()

        callback = hass.bus.async_listen.call_args[0][1]

        # Fire an event for the old entity — should be processed
        with patch(
            "custom_components.powerpal_ble.esphome_coordinator.time"
        ) as mock_time:
            mock_time.time.return_value = 2000.0
            mock_time.localtime.return_value = MagicMock(tm_yday=1)
            event = _make_state_event("sensor.powerpal_pulses", "750.0")
            callback(event)

        assert coordinator.power == 750.0

        # Fire a second event to verify energy accumulation works
        with patch(
            "custom_components.powerpal_ble.esphome_coordinator.time"
        ) as mock_time:
            mock_time.time.return_value = 2060.0
            mock_time.localtime.return_value = MagicMock(tm_yday=1)
            event = _make_state_event("sensor.powerpal_pulses", "750.0")
            callback(event)

        expected_energy = 750.0 * 60.0 / 3_600_000
        assert abs(coordinator.energy_total_kwh - expected_energy) < 1e-9
        assert abs(coordinator.daily_energy_kwh - expected_energy) < 1e-9

        cancel()

    def test_new_power_entity_key_takes_precedence(self):
        """Test that when both keys are present, esphome_power_entity takes precedence.

        Validates: Requirement 4.4
        """
        hass = _make_hass()
        entry = _make_entry(
            {
                CONF_CONNECTION_MODE: CONNECTION_MODE_ESPHOME,
                CONF_ESPHOME_POWER_ENTITY: "sensor.powerpal_power",
                CONF_ESPHOME_PULSE_ENTITY: "sensor.powerpal_pulses",
            }
        )

        coordinator = ESPHomeCoordinator(hass, entry)

        # The new key should take precedence
        assert coordinator._source_entity == "sensor.powerpal_power"

        with patch(
            "custom_components.powerpal_ble.esphome_coordinator.async_track_time_change"
        ):
            cancel = coordinator.async_start()

        callback = hass.bus.async_listen.call_args[0][1]

        # Event for the new entity should be processed
        with patch(
            "custom_components.powerpal_ble.esphome_coordinator.time"
        ) as mock_time:
            mock_time.time.return_value = 3000.0
            mock_time.localtime.return_value = MagicMock(tm_yday=1)
            event = _make_state_event("sensor.powerpal_power", "250.0")
            callback(event)

        assert coordinator.power == 250.0

        # Event for the OLD entity should be ignored
        with patch(
            "custom_components.powerpal_ble.esphome_coordinator.time"
        ) as mock_time:
            mock_time.time.return_value = 3060.0
            mock_time.localtime.return_value = MagicMock(tm_yday=1)
            event = _make_state_event("sensor.powerpal_pulses", "999.0")
            callback(event)

        # Power should NOT change to 999 since the old entity doesn't match
        assert coordinator.power == 250.0

        cancel()
