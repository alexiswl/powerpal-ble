"""Unit tests for coordinator bonding behavior.

Validates: Requirements 2.1, 2.2, 2.3, 2.5, 6.1, 6.2, 6.3
"""
from __future__ import annotations

import logging
import struct
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bleak import BleakError

# Mock homeassistant modules before importing coordinator
_ha_mocks = {}
for mod_name in (
    "homeassistant",
    "homeassistant.components",
    "homeassistant.components.bluetooth",
    "homeassistant.config_entries",
    "homeassistant.const",
    "homeassistant.core",
):
    if mod_name not in sys.modules:
        _ha_mocks[mod_name] = MagicMock()
        sys.modules[mod_name] = _ha_mocks[mod_name]

# Mock bleak_retry_connector
if "bleak_retry_connector" not in sys.modules:
    mock_retry = MagicMock()
    mock_retry.establish_connection = AsyncMock()
    sys.modules["bleak_retry_connector"] = mock_retry
    _ha_mocks["bleak_retry_connector"] = mock_retry

from custom_components.powerpal_ble.const import (
    CHAR_PAIRING_CODE_UUID,
    CONF_BLUEZ_BONDING,
    CONF_MAC_ADDRESS,
    CONF_NOTIFICATION_INTERVAL,
    CONF_PAIRING_CODE,
    CONF_PULSES_PER_KWH,
)
from custom_components.powerpal_ble.coordinator import PowerpalCoordinator


def _make_coordinator(bluez_bonding: bool | None = None) -> PowerpalCoordinator:
    """Create a PowerpalCoordinator with mocked hass and config entry."""
    hass = MagicMock()
    hass.loop = MagicMock()

    entry = MagicMock()
    entry_data = {
        CONF_MAC_ADDRESS: "AA:BB:CC:DD:EE:FF",
        CONF_PAIRING_CODE: 123456,
        CONF_PULSES_PER_KWH: 1000,
        CONF_NOTIFICATION_INTERVAL: 1,
    }
    if bluez_bonding is not None:
        entry_data[CONF_BLUEZ_BONDING] = bluez_bonding
    entry.data = entry_data

    return PowerpalCoordinator(hass, entry)


def _mock_services():
    """Create a mock services object that mimics BleakGATTServiceCollection."""
    mock_char = MagicMock()
    mock_char.properties = ["write", "notify"]

    services = MagicMock()
    services.get_characteristic = MagicMock(return_value=mock_char)
    # Make it iterable (for the service logging loop)
    mock_service = MagicMock()
    mock_service.uuid = "59daabcd-12f4-25a6-7d4f-55961dce4205"
    mock_service.characteristics = [mock_char]
    services.__iter__ = MagicMock(return_value=iter([mock_service]))
    return services


@pytest.fixture
def mock_connect_deps():
    """Mock all external dependencies used by _connect()."""
    with (
        patch(
            "custom_components.powerpal_ble.coordinator.bluetooth"
        ) as mock_bt,
        patch(
            "custom_components.powerpal_ble.coordinator.establish_connection",
            new_callable=AsyncMock,
        ) as mock_establish,
    ):
        # bluetooth.async_ble_device_from_address returns a mock device
        mock_device = MagicMock()
        mock_device.name = "Powerpal"
        mock_bt.async_ble_device_from_address = MagicMock(return_value=mock_device)

        # bluetooth.async_last_service_info returns None (skip diagnostics)
        mock_bt.async_last_service_info = MagicMock(return_value=None)

        # establish_connection returns a mock BleakClient
        mock_client = AsyncMock()
        services = _mock_services()
        mock_client.services = services
        mock_client.get_services = AsyncMock(return_value=services)
        mock_client.write_gatt_char = AsyncMock()
        mock_client.start_notify = AsyncMock()
        mock_client.stop_notify = AsyncMock()
        mock_client.read_gatt_char = AsyncMock(return_value=b"\x00" * 16)
        mock_establish.return_value = mock_client

        yield {
            "bluetooth": mock_bt,
            "establish_connection": mock_establish,
            "client": mock_client,
            "services": services,
        }


@pytest.mark.asyncio
async def test_coordinator_calls_bonding_when_enabled(mock_connect_deps):
    """Test coordinator calls bonding methods when bluez_bonding is True."""
    coordinator = _make_coordinator(bluez_bonding=True)

    with patch.object(
        coordinator, "_check_bluez_bonded", new_callable=AsyncMock, return_value=True
    ) as mock_check_bonded, patch.object(
        coordinator, "_bluez_pair", new_callable=AsyncMock
    ) as mock_pair:
        await coordinator._connect()

    mock_check_bonded.assert_called_once()
    # Since _check_bluez_bonded returns True (already bonded), _bluez_pair should NOT be called
    mock_pair.assert_not_called()


@pytest.mark.asyncio
async def test_coordinator_skips_bonding_when_disabled(mock_connect_deps):
    """Test coordinator skips bonding methods when bluez_bonding is False."""
    coordinator = _make_coordinator(bluez_bonding=False)

    with patch.object(
        coordinator, "_check_bluez_bonded", new_callable=AsyncMock
    ) as mock_check_bonded, patch.object(
        coordinator, "_bluez_pair", new_callable=AsyncMock
    ) as mock_pair:
        await coordinator._connect()

    mock_check_bonded.assert_not_called()
    mock_pair.assert_not_called()


@pytest.mark.asyncio
async def test_coordinator_writes_pairing_code_when_bonding_enabled(mock_connect_deps):
    """Test coordinator writes pairing code to GATT char when bonding is enabled."""
    coordinator = _make_coordinator(bluez_bonding=True)
    mock_client = mock_connect_deps["client"]

    with patch.object(
        coordinator, "_check_bluez_bonded", new_callable=AsyncMock, return_value=True
    ), patch.object(coordinator, "_bluez_pair", new_callable=AsyncMock):
        await coordinator._connect()

    # Verify write_gatt_char was called with the pairing code UUID
    expected_pairing_bytes = struct.pack("<I", 123456)
    calls = mock_client.write_gatt_char.call_args_list
    pairing_write_calls = [
        c for c in calls if c[0][0] == CHAR_PAIRING_CODE_UUID
    ]
    assert len(pairing_write_calls) >= 1
    assert pairing_write_calls[0][0][1] == expected_pairing_bytes


@pytest.mark.asyncio
async def test_coordinator_writes_pairing_code_when_bonding_disabled(mock_connect_deps):
    """Test coordinator writes pairing code to GATT char when bonding is disabled."""
    coordinator = _make_coordinator(bluez_bonding=False)
    mock_client = mock_connect_deps["client"]

    with patch.object(
        coordinator, "_check_bluez_bonded", new_callable=AsyncMock
    ), patch.object(coordinator, "_bluez_pair", new_callable=AsyncMock):
        await coordinator._connect()

    # Verify write_gatt_char was called with the pairing code UUID
    expected_pairing_bytes = struct.pack("<I", 123456)
    calls = mock_client.write_gatt_char.call_args_list
    pairing_write_calls = [
        c for c in calls if c[0][0] == CHAR_PAIRING_CODE_UUID
    ]
    assert len(pairing_write_calls) >= 1
    assert pairing_write_calls[0][0][1] == expected_pairing_bytes


@pytest.mark.asyncio
async def test_auth_error_logs_warning_when_bonding_disabled(
    mock_connect_deps, caplog
):
    """Test auth error with bonding disabled logs a warning."""
    coordinator = _make_coordinator(bluez_bonding=False)
    mock_client = mock_connect_deps["client"]

    # Make write_gatt_char raise a BleakError with "authentication" in the message
    mock_client.write_gatt_char = AsyncMock(
        side_effect=BleakError("authentication failed")
    )

    with patch.object(
        coordinator, "_check_bluez_bonded", new_callable=AsyncMock
    ), patch.object(coordinator, "_bluez_pair", new_callable=AsyncMock):
        with caplog.at_level(logging.WARNING):
            with pytest.raises(BleakError):
                await coordinator._connect()

    # Verify warning about authentication error with bonding disabled
    warning_messages = [
        r.message for r in caplog.records if r.levelno == logging.WARNING
    ]
    auth_warnings = [
        m
        for m in warning_messages
        if "authentication" in m.lower() or "encryption" in m.lower()
    ]
    assert len(auth_warnings) >= 1
    assert "bonding disabled" in auth_warnings[0].lower() or "BlueZ bonding" in auth_warnings[0]


@pytest.mark.asyncio
async def test_info_log_when_bonding_skipped(mock_connect_deps, caplog):
    """Test INFO log emitted when bonding is skipped (bluez_bonding=False)."""
    coordinator = _make_coordinator(bluez_bonding=False)

    with patch.object(
        coordinator, "_check_bluez_bonded", new_callable=AsyncMock
    ), patch.object(coordinator, "_bluez_pair", new_callable=AsyncMock):
        with caplog.at_level(logging.DEBUG):
            await coordinator._connect()

    # Find INFO-level records about bonding being skipped
    info_messages = [
        r.message for r in caplog.records if r.levelno == logging.INFO
    ]
    bonding_skipped_msgs = [
        m for m in info_messages if "skipping bonding check" in m.lower()
    ]
    assert len(bonding_skipped_msgs) >= 1
    # Should include the MAC address
    assert "AA:BB:CC:DD:EE:FF" in bonding_skipped_msgs[0]


@pytest.mark.asyncio
async def test_debug_log_when_bonding_enabled(mock_connect_deps, caplog):
    """Test DEBUG log emitted when bonding is enabled (bluez_bonding=True)."""
    coordinator = _make_coordinator(bluez_bonding=True)

    with patch.object(
        coordinator, "_check_bluez_bonded", new_callable=AsyncMock, return_value=True
    ), patch.object(coordinator, "_bluez_pair", new_callable=AsyncMock):
        with caplog.at_level(logging.DEBUG):
            await coordinator._connect()

    # Find DEBUG-level records about bonding being enabled
    debug_messages = [
        r.message for r in caplog.records if r.levelno == logging.DEBUG
    ]
    bonding_enabled_msgs = [
        m for m in debug_messages if "bonding enabled" in m.lower()
    ]
    assert len(bonding_enabled_msgs) >= 1
    # Should include the MAC address
    assert "AA:BB:CC:DD:EE:FF" in bonding_enabled_msgs[0]
