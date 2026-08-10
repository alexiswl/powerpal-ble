"""Property-based tests for ESPHome coordinator.

Uses Hypothesis to verify universal properties of the ESPHomeCoordinator class.
"""
from __future__ import annotations

import sys
import importlib

_ha_core_mock = sys.modules.get("homeassistant.core")
if _ha_core_mock is not None:
    _ha_core_mock.callback = lambda f: f
if "custom_components.powerpal_ble.esphome_coordinator" in sys.modules:
    importlib.reload(sys.modules["custom_components.powerpal_ble.esphome_coordinator"])

import math
from unittest.mock import MagicMock

from hypothesis import given, settings
from hypothesis import strategies as st

from custom_components.powerpal_ble.esphome_coordinator import ESPHomeCoordinator
from custom_components.powerpal_ble.const import CONF_ESPHOME_POWER_ENTITY


def _make_coordinator(entity_id: str = "sensor.powerpal_power") -> ESPHomeCoordinator:
    """Create a coordinator with mocked HA objects."""
    hass = MagicMock()
    entry = MagicMock()
    entry.data = {CONF_ESPHOME_POWER_ENTITY: entity_id}
    return ESPHomeCoordinator(hass, entry)


def _make_state_event(entity_id: str, state_value: str) -> MagicMock:
    """Create a mock state_changed event."""
    event = MagicMock()
    new_state = MagicMock()
    new_state.state = state_value
    event.data = {
        "entity_id": entity_id,
        "new_state": new_state,
    }
    return event


# Feature: esphome-cloud-upload, Property 4: Coordinator interprets state as power directly
# **Validates: Requirements 3.1, 3.2**
@settings(max_examples=100)
@given(
    power_value=st.floats(
        min_value=0, max_value=100000, allow_nan=False, allow_infinity=False
    ),
)
def test_coordinator_interprets_state_as_power_directly(power_value: float):
    """For any valid numeric state value, the coordinator's power attribute
    equals that value as a float without any transformation."""
    from unittest.mock import patch

    entity_id = "sensor.powerpal_power"
    coordinator = _make_coordinator(entity_id)

    # Fire a state_changed event with the numeric value as a string
    with patch("custom_components.powerpal_ble.esphome_coordinator.time") as mock_time:
        mock_time.time.return_value = 1000.0
        mock_time.localtime.return_value = MagicMock(tm_yday=1)
        event = _make_state_event(entity_id, str(power_value))
        coordinator._handle_state_change(event)

    assert coordinator.power == power_value, (
        f"Expected power={power_value}, got {coordinator.power}"
    )


# Feature: esphome-cloud-upload, Property 5: Energy integration accumulation
# **Validates: Requirements 3.3, 3.4**
@settings(max_examples=100)
@given(
    readings=st.lists(
        st.tuples(
            st.floats(min_value=0, max_value=10000, allow_nan=False, allow_infinity=False),
            st.floats(min_value=0.1, max_value=3600, allow_nan=False, allow_infinity=False),
        ),
        min_size=2,
        max_size=20,
    )
)
def test_energy_integration_accumulation(readings):
    """Energy total equals sum of (power_w * time_delta_seconds / 3_600_000) for each interval.

    The first reading establishes the baseline time (no energy accumulated).
    Subsequent readings accumulate energy based on the formula:
      energy_kwh = power_w * time_delta_seconds / 3_600_000
    """
    from unittest.mock import patch

    entity_id = "sensor.powerpal_power"
    coordinator = _make_coordinator(entity_id)

    # Build timestamps: first reading at t=1000, subsequent readings offset by time_delta
    base_time = 1000.0
    timestamps = [base_time]
    for i in range(1, len(readings)):
        timestamps.append(timestamps[-1] + readings[i][1])

    # Fire events, patching time.time() to control timestamps
    for i, (power_w, _time_delta) in enumerate(readings):
        with patch("custom_components.powerpal_ble.esphome_coordinator.time") as mock_time:
            mock_time.time.return_value = timestamps[i]
            mock_time.localtime.return_value = MagicMock(tm_yday=1)
            event = _make_state_event(entity_id, str(power_w))
            coordinator._handle_state_change(event)

    # Compute expected energy: first reading sets baseline, subsequent ones accumulate
    expected_energy = 0.0
    for i in range(1, len(readings)):
        power_w = readings[i][0]
        time_delta_seconds = timestamps[i] - timestamps[i - 1]
        expected_energy += power_w * time_delta_seconds / 3_600_000

    assert math.isclose(
        coordinator.energy_total_kwh, expected_energy, rel_tol=1e-9, abs_tol=1e-15
    ), (
        f"Expected energy_total_kwh={expected_energy}, "
        f"got {coordinator.energy_total_kwh}"
    )
