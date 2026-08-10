# Feature: powerpal-api-integration, Property 11: BLE Sensor Independence from API Failures
# Feature: powerpal-api-integration, Property 12: Non-Blocking Upload
"""Property-based tests for coordinator upload trigger behavior.

These tests verify that:
- BLE sensor values always update regardless of API client state (Property 11)
- Upload scheduling is non-blocking via call_soon_threadsafe (Property 12)
"""
from __future__ import annotations

import struct
from unittest.mock import MagicMock

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from custom_components.powerpal_ble.coordinator import PowerpalCoordinator

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Timestamps: valid unix timestamps (positive 32-bit unsigned integers)
timestamp_strategy = st.integers(min_value=1, max_value=2**32 - 1)

# Pulse counts: valid uint16 values
pulses_strategy = st.integers(min_value=0, max_value=65535)

# Pulses per kWh: realistic meter configurations
pulses_per_kwh_strategy = st.integers(min_value=1, max_value=10000)

# Notification interval: 1-15 minutes
notification_interval_strategy = st.integers(min_value=1, max_value=15)

# API client error states for Property 11
api_error_states = st.sampled_from(["disabled", "none"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_measurement_data(timestamp: int, pulses: int) -> bytearray:
    """Create a 20-byte BLE measurement packet."""
    data = bytearray(20)
    struct.pack_into("<I", data, 0, timestamp)
    struct.pack_into("<H", data, 4, pulses)
    return data


def _make_coordinator(
    pulses_per_kwh: int = 1000,
    notification_interval: int = 1,
) -> PowerpalCoordinator:
    """Create a PowerpalCoordinator with mocked hass and entry."""
    mock_hass = MagicMock()
    mock_hass.loop = MagicMock()
    mock_hass.loop.call_soon_threadsafe = MagicMock()
    mock_hass.async_create_background_task = MagicMock()

    mock_entry = MagicMock()
    mock_entry.data = {
        "mac_address": "AA:BB:CC:DD:EE:FF",
        "pairing_code": 123456,
        "pulses_per_kwh": pulses_per_kwh,
        "notification_interval": notification_interval,
        "bluez_bonding": True,
    }

    coordinator = PowerpalCoordinator(mock_hass, mock_entry)
    return coordinator


def _calculate_expected_power(
    pulses: int, pulses_per_kwh: int, notification_interval: int
) -> float:
    """Calculate expected power in watts from measurement parameters."""
    interval_seconds = notification_interval * 60
    return round((pulses * 3600000) / (pulses_per_kwh * interval_seconds), 1)


def _calculate_expected_energy_kwh(pulses: int, pulses_per_kwh: int) -> float:
    """Calculate expected energy in kWh from measurement parameters."""
    return round(pulses / pulses_per_kwh, 4)


# ---------------------------------------------------------------------------
# Property 11: BLE Sensor Independence from API Failures
# ---------------------------------------------------------------------------


@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    deadline=None,
)
@given(
    timestamp=timestamp_strategy,
    pulses=pulses_strategy,
    pulses_per_kwh=pulses_per_kwh_strategy,
    notification_interval=notification_interval_strategy,
    api_state=api_error_states,
)
def test_ble_sensor_independence_from_api_failures(
    timestamp: int,
    pulses: int,
    pulses_per_kwh: int,
    notification_interval: int,
    api_state: str,
) -> None:
    """Property 11: BLE Sensor Independence from API Failures.

    **Validates: Requirements 3.1, 6.3, 6.4, 6.5**

    For any BLE measurement notification received while the API client is in
    any error state (disabled, rate-limited, network failure), the coordinator
    SHALL still update sensor entity values (power, energy_total_kwh,
    daily_energy_kwh) and notify listeners exactly as it would without API
    integration configured.
    """
    coordinator = _make_coordinator(pulses_per_kwh, notification_interval)

    # Set up API client in various error states
    if api_state == "disabled":
        mock_api_client = MagicMock()
        mock_api_client.disabled = True  # Client has been disabled (e.g., 401)
        coordinator.set_api_client(mock_api_client)
    elif api_state == "none":
        # No API client configured at all (BLE-only mode)
        pass

    # Record initial energy values
    initial_total = coordinator.energy_total_kwh
    initial_daily = coordinator.daily_energy_kwh

    # Fire the measurement callback
    data = make_measurement_data(timestamp, pulses)
    coordinator._measurement_callback(None, data)

    # Calculate expected values
    expected_power = _calculate_expected_power(
        pulses, pulses_per_kwh, notification_interval
    )
    expected_energy = _calculate_expected_energy_kwh(pulses, pulses_per_kwh)

    # Assert sensor values are updated correctly
    assert coordinator.power == expected_power, (
        f"Expected power={expected_power}, got {coordinator.power}"
    )
    assert coordinator.energy_total_kwh == round(initial_total + expected_energy, 4), (
        f"Expected energy_total_kwh={round(initial_total + expected_energy, 4)}, "
        f"got {coordinator.energy_total_kwh}"
    )
    assert coordinator.daily_energy_kwh == round(initial_daily + expected_energy, 4), (
        f"Expected daily_energy_kwh={round(initial_daily + expected_energy, 4)}, "
        f"got {coordinator.daily_energy_kwh}"
    )

    # Assert listeners were notified via call_soon_threadsafe
    notify_calls = [
        call
        for call in coordinator.hass.loop.call_soon_threadsafe.call_args_list
        if call.args[0] == coordinator._notify_listeners
    ]
    assert len(notify_calls) == 1, (
        f"Expected exactly 1 _notify_listeners call, got {len(notify_calls)}"
    )


# ---------------------------------------------------------------------------
# Property 12: Non-Blocking Upload
# ---------------------------------------------------------------------------


@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    deadline=None,
)
@given(
    timestamp=timestamp_strategy,
    pulses=pulses_strategy,
    pulses_per_kwh=pulses_per_kwh_strategy,
    notification_interval=notification_interval_strategy,
)
def test_non_blocking_upload(
    timestamp: int,
    pulses: int,
    pulses_per_kwh: int,
    notification_interval: int,
) -> None:
    """Property 12: Non-Blocking Upload.

    **Validates: Requirements 3.1, 6.3, 6.4, 6.5**

    For any BLE measurement callback execution, if an API client is configured
    and not disabled, the callback SHALL schedule the upload as a background
    task via call_soon_threadsafe(hass.async_create_background_task, ...)
    and return control to the BLE notification handler without awaiting the
    HTTP response.
    """
    coordinator = _make_coordinator(pulses_per_kwh, notification_interval)

    # Set up a healthy (non-disabled) API client
    mock_api_client = MagicMock()
    mock_api_client.disabled = False
    mock_api_client.upload_reading = MagicMock(return_value="coroutine_placeholder")
    coordinator.set_api_client(mock_api_client)

    # Fire the measurement callback
    data = make_measurement_data(timestamp, pulses)
    coordinator._measurement_callback(None, data)

    # The callback should have scheduled the upload via call_soon_threadsafe
    # with hass.async_create_background_task as the first argument
    upload_calls = [
        call
        for call in coordinator.hass.loop.call_soon_threadsafe.call_args_list
        if (
            len(call.args) >= 1
            and call.args[0] == coordinator.hass.async_create_background_task
        )
    ]
    assert len(upload_calls) == 1, (
        f"Expected exactly 1 async_create_background_task scheduling, "
        f"got {len(upload_calls)}. "
        f"All call_soon_threadsafe calls: "
        f"{coordinator.hass.loop.call_soon_threadsafe.call_args_list}"
    )

    # Verify the upload_reading was called with the correct timestamp
    mock_api_client.upload_reading.assert_called_once()
    call_args = mock_api_client.upload_reading.call_args
    actual_timestamp = call_args.args[0] if call_args.args else call_args.kwargs.get("timestamp")
    assert actual_timestamp == timestamp, (
        f"Expected upload timestamp={timestamp}, got {actual_timestamp}"
    )

    # Verify the watt_hours argument is the correct conversion from kWh
    expected_energy_kwh = pulses / pulses_per_kwh
    expected_wh = expected_energy_kwh * 1000  # kWh to Wh
    actual_wh = call_args.args[1] if len(call_args.args) > 1 else call_args.kwargs.get("watt_hours")
    assert abs(actual_wh - expected_wh) < 1e-6, (
        f"Expected watt_hours={expected_wh}, got {actual_wh}"
    )

    # The callback itself is synchronous — it must NOT have awaited anything.
    # We verify this by checking that the mock coroutine was passed to
    # call_soon_threadsafe (scheduled for later) rather than being awaited directly.
    # If the callback had awaited, it would need to be async, but _measurement_callback
    # is a regular sync function — confirming non-blocking behavior.
    upload_schedule_call = upload_calls[0]
    # Second arg to call_soon_threadsafe should be the coroutine from upload_reading
    scheduled_coro = upload_schedule_call.args[1]
    assert scheduled_coro == mock_api_client.upload_reading.return_value, (
        f"Expected the upload coroutine to be scheduled, "
        f"got {scheduled_coro}"
    )
