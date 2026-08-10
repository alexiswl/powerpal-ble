"""Unit tests for graceful degradation (BLE-only mode).

Validates Requirements 6.1, 6.2, 6.3, 6.4, 6.5:
- BLE-only mode makes no HTTP calls when no API credentials are configured
- BLE-only mode produces clean logs (no API warnings/errors)
- BLE sensors continue updating regardless of API client state
"""
from __future__ import annotations

import logging
import struct
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.powerpal_ble import async_setup_entry
from custom_components.powerpal_ble.coordinator import PowerpalCoordinator

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_hass():
    """Create a mock HomeAssistant instance with required attributes."""
    mock_hass = MagicMock()
    mock_hass.data = {}
    mock_hass.loop = MagicMock()
    mock_hass.loop.call_soon_threadsafe = MagicMock()
    mock_hass.async_create_background_task = MagicMock()
    mock_hass.config_entries = MagicMock()
    mock_hass.config_entries.async_forward_entry_setups = AsyncMock()
    return mock_hass


def _make_mock_entry(entry_data: dict):
    """Create a mock ConfigEntry with the given data."""
    mock_entry = MagicMock()
    mock_entry.entry_id = "test_entry"
    mock_entry.data = entry_data
    mock_entry.async_on_unload = MagicMock()
    return mock_entry


def _base_entry_data_no_api():
    """Return config entry data for BLE-only setup (no API fields)."""
    return {
        "connection_mode": "ble",
        "mac_address": "AA:BB:CC:DD:EE:FF",
        "pairing_code": 123456,
        "pulses_per_kwh": 1000,
        "notification_interval": 1,
        "bluez_bonding": True,
        # NO api_key or device_id
    }


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
    mock_hass = _make_mock_hass()

    mock_entry = MagicMock()
    mock_entry.entry_id = "test_entry"
    mock_entry.data = {
        "mac_address": "AA:BB:CC:DD:EE:FF",
        "pairing_code": 123456,
        "pulses_per_kwh": pulses_per_kwh,
        "notification_interval": notification_interval,
        "bluez_bonding": True,
    }

    coordinator = PowerpalCoordinator(mock_hass, mock_entry)
    return coordinator


# ---------------------------------------------------------------------------
# Test 1: BLE-only mode makes no HTTP calls
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ble_only_mode_no_http_calls():
    """When no API credentials are configured, no HTTP calls should be made.

    Validates: Requirements 6.1
    """
    mock_hass = _make_mock_hass()
    entry_data = _base_entry_data_no_api()
    mock_entry = _make_mock_entry(entry_data)

    mock_coordinator = MagicMock()
    mock_coordinator.async_start = MagicMock(return_value=MagicMock())

    mock_session_fn = MagicMock()

    with (
        patch(
            "custom_components.powerpal_ble.coordinator.PowerpalCoordinator",
            return_value=mock_coordinator,
        ),
        patch(
            "custom_components.powerpal_ble.async_get_clientsession",
            mock_session_fn,
        ),
        patch(
            "custom_components.powerpal_ble.PowerpalApiClient",
        ) as mock_api_cls,
    ):
        result = await async_setup_entry(mock_hass, mock_entry)

    assert result is True

    # async_get_clientsession should NOT be called when no API credentials
    mock_session_fn.assert_not_called()

    # PowerpalApiClient should NOT be instantiated
    mock_api_cls.assert_not_called()

    # set_api_client should NOT be called on the coordinator
    mock_coordinator.set_api_client.assert_not_called()

    # No background tasks for historical fetch should be created
    mock_hass.async_create_background_task.assert_not_called()


# ---------------------------------------------------------------------------
# Test 2: BLE-only mode has clean logs (no API warnings/errors)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ble_only_mode_clean_logs(caplog):
    """When no API credentials are configured, no API-related log messages appear.

    Validates: Requirements 6.2
    """
    mock_hass = _make_mock_hass()
    entry_data = _base_entry_data_no_api()
    mock_entry = _make_mock_entry(entry_data)

    mock_coordinator = MagicMock()
    mock_coordinator.async_start = MagicMock(return_value=MagicMock())

    with (
        patch(
            "custom_components.powerpal_ble.coordinator.PowerpalCoordinator",
            return_value=mock_coordinator,
        ),
        patch(
            "custom_components.powerpal_ble.async_get_clientsession",
            return_value=MagicMock(),
        ),
        caplog.at_level(logging.DEBUG),
    ):
        result = await async_setup_entry(mock_hass, mock_entry)

    assert result is True

    # No log records should mention "API" at WARNING or ERROR level
    api_warnings_or_errors = [
        record
        for record in caplog.records
        if record.levelno >= logging.WARNING and "API" in record.message.upper()
    ]
    assert api_warnings_or_errors == [], (
        f"Expected no API-related WARNING/ERROR logs, but got: "
        f"{[(r.levelname, r.message) for r in api_warnings_or_errors]}"
    )

    # Also verify no INFO-level messages containing "API Key" are emitted
    api_info_logs = [
        record
        for record in caplog.records
        if record.levelno == logging.INFO and "API" in record.message.upper()
    ]
    assert api_info_logs == [], (
        f"Expected no API-related INFO logs in BLE-only mode, but got: "
        f"{[(r.levelname, r.message) for r in api_info_logs]}"
    )


# ---------------------------------------------------------------------------
# Test 3: BLE sensors continue updating with disabled API client
# ---------------------------------------------------------------------------


def test_ble_sensors_update_with_disabled_api():
    """BLE sensors update correctly even when API client is disabled.

    Validates: Requirements 6.3, 6.4, 6.5
    """
    coordinator = _make_coordinator(pulses_per_kwh=1000, notification_interval=1)

    # Set up a disabled API client (e.g., after receiving 401)
    mock_api_client = MagicMock()
    mock_api_client.disabled = True
    coordinator.set_api_client(mock_api_client)

    # Record initial energy values
    initial_total = coordinator.energy_total_kwh
    initial_daily = coordinator.daily_energy_kwh

    # Fire a measurement: 100 pulses at timestamp 1700000000
    timestamp = 1700000000
    pulses = 100
    data = make_measurement_data(timestamp, pulses)
    coordinator._measurement_callback(None, data)

    # Calculate expected values
    # power = (100 * 3600000) / (1000 * 60) = 6000 W
    expected_power = round((pulses * 3600000) / (1000 * 60), 1)
    # energy = 100 / 1000 = 0.1 kWh
    expected_energy = round(pulses / 1000, 4)

    # Assert sensor values are updated correctly
    assert coordinator.power == expected_power
    assert coordinator.energy_total_kwh == round(initial_total + expected_energy, 4)
    assert coordinator.daily_energy_kwh == round(initial_daily + expected_energy, 4)

    # Assert listeners were notified via call_soon_threadsafe
    notify_calls = [
        call
        for call in coordinator.hass.loop.call_soon_threadsafe.call_args_list
        if call.args[0] == coordinator._notify_listeners
    ]
    assert len(notify_calls) == 1, (
        f"Expected exactly 1 _notify_listeners call, got {len(notify_calls)}"
    )

    # Since API client is disabled, no upload should be scheduled
    upload_calls = [
        call
        for call in coordinator.hass.loop.call_soon_threadsafe.call_args_list
        if (
            len(call.args) >= 1
            and call.args[0] == coordinator.hass.async_create_background_task
        )
    ]
    assert len(upload_calls) == 0, (
        f"Expected no upload scheduling when API is disabled, "
        f"but got {len(upload_calls)} calls"
    )


# ---------------------------------------------------------------------------
# Test 4: BLE sensors continue updating without any API client
# ---------------------------------------------------------------------------


def test_ble_sensors_update_without_api():
    """BLE sensors update correctly when no API client is configured.

    Validates: Requirements 6.1, 6.3, 6.5
    """
    coordinator = _make_coordinator(pulses_per_kwh=1000, notification_interval=1)

    # DON'T set any API client — pure BLE-only mode
    assert coordinator._api_client is None

    # Record initial energy values
    initial_total = coordinator.energy_total_kwh
    initial_daily = coordinator.daily_energy_kwh

    # Fire a measurement: 50 pulses at timestamp 1700001000
    timestamp = 1700001000
    pulses = 50
    data = make_measurement_data(timestamp, pulses)
    coordinator._measurement_callback(None, data)

    # Calculate expected values
    # power = (50 * 3600000) / (1000 * 60) = 3000 W
    expected_power = round((pulses * 3600000) / (1000 * 60), 1)
    # energy = 50 / 1000 = 0.05 kWh
    expected_energy = round(pulses / 1000, 4)

    # Assert sensor values are updated correctly
    assert coordinator.power == expected_power
    assert coordinator.energy_total_kwh == round(initial_total + expected_energy, 4)
    assert coordinator.daily_energy_kwh == round(initial_daily + expected_energy, 4)

    # Assert listeners were notified
    notify_calls = [
        call
        for call in coordinator.hass.loop.call_soon_threadsafe.call_args_list
        if call.args[0] == coordinator._notify_listeners
    ]
    assert len(notify_calls) == 1, (
        f"Expected exactly 1 _notify_listeners call, got {len(notify_calls)}"
    )

    # No upload calls should happen without an API client
    upload_calls = [
        call
        for call in coordinator.hass.loop.call_soon_threadsafe.call_args_list
        if (
            len(call.args) >= 1
            and call.args[0] == coordinator.hass.async_create_background_task
        )
    ]
    assert len(upload_calls) == 0, (
        f"Expected no upload scheduling without API client, "
        f"but got {len(upload_calls)} calls"
    )
