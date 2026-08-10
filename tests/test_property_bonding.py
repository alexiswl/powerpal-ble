# Feature: optional-bluez-bonding, Property 1: Backward-compatible default resolution
"""Property-based tests for the optional BlueZ bonding feature."""

import sys
from unittest.mock import MagicMock

from hypothesis import given, settings
from hypothesis import strategies as st

# Stub out homeassistant dependencies so we can import const.py directly
# without needing the full Home Assistant package installed.
_ha_stub = MagicMock()
sys.modules.setdefault("homeassistant", _ha_stub)
sys.modules.setdefault("homeassistant.config_entries", _ha_stub)
sys.modules.setdefault("homeassistant.const", _ha_stub)
sys.modules.setdefault("homeassistant.core", _ha_stub)
sys.modules.setdefault("homeassistant.components", _ha_stub)
sys.modules.setdefault("homeassistant.components.bluetooth", _ha_stub)
sys.modules.setdefault("homeassistant.helpers", _ha_stub)
sys.modules.setdefault("bleak", _ha_stub)
sys.modules.setdefault("bleak_retry_connector", _ha_stub)
sys.modules.setdefault("bluetooth_adapters", _ha_stub)

from custom_components.powerpal_ble.const import (
    CONF_BLUEZ_BONDING,
    DEFAULT_BLUEZ_BONDING,
)

# Strategy: generate config entry data dicts with required keys but WITHOUT bluez_bonding
config_entry_data_without_bonding = st.fixed_dictionaries(
    {
        "mac_address": st.from_regex(
            r"[0-9A-F]{2}:[0-9A-F]{2}:[0-9A-F]{2}:[0-9A-F]{2}:[0-9A-F]{2}:[0-9A-F]{2}",
            fullmatch=True,
        ),
        "pairing_code": st.integers(min_value=100000, max_value=999999),
        "pulses_per_kwh": st.integers(min_value=1, max_value=10000),
        "notification_interval": st.integers(min_value=1, max_value=15),
    }
)


@settings(max_examples=100)
@given(data=config_entry_data_without_bonding)
def test_backward_compatible_default_resolution(data: dict) -> None:
    """Property 1: Config entries without bluez_bonding key resolve to True.

    Validates: Requirements 1.5, 2.4

    For any valid config entry data dictionary that contains the required keys
    (mac_address, pairing_code, pulses_per_kwh, notification_interval) but does
    NOT contain a bluez_bonding key, resolving via
    data.get(CONF_BLUEZ_BONDING, DEFAULT_BLUEZ_BONDING) shall return True.
    """
    # Ensure the key is truly absent
    assert CONF_BLUEZ_BONDING not in data

    # The resolution must always return True for backward compatibility
    result = data.get(CONF_BLUEZ_BONDING, DEFAULT_BLUEZ_BONDING)
    assert result is True


# Feature: optional-bluez-bonding, Property 2: Bonding setting determines bonding call execution
import struct
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from custom_components.powerpal_ble.const import (
    CHAR_PAIRING_CODE_UUID,
)

# Strategy: generate config entry data dicts WITH bluez_bonding as a boolean
config_entry_data_with_bonding = st.fixed_dictionaries(
    {
        "mac_address": st.from_regex(
            r"[0-9A-F]{2}:[0-9A-F]{2}:[0-9A-F]{2}:[0-9A-F]{2}:[0-9A-F]{2}:[0-9A-F]{2}",
            fullmatch=True,
        ),
        "pairing_code": st.integers(min_value=100000, max_value=999999),
        "pulses_per_kwh": st.integers(min_value=1, max_value=10000),
        "notification_interval": st.integers(min_value=1, max_value=15),
        "bluez_bonding": st.booleans(),
    }
)


def _make_mock_service_info():
    """Create a mock BLE service info with sensible defaults."""
    import time

    service_info = MagicMock()
    service_info.rssi = -60
    service_info.source = "local"
    service_info.connectable = True
    service_info.time = time.time()
    return service_info


def _make_mock_bleak_client():
    """Create a mock BleakClient with all methods needed by _connect()."""
    client = AsyncMock()

    # Create mock characteristic with properties
    mock_char = MagicMock()
    mock_char.properties = ["write", "notify"]

    # Mock services object
    mock_services = MagicMock()
    mock_services.get_characteristic.return_value = mock_char
    mock_services.__iter__ = MagicMock(return_value=iter([]))

    client.services = mock_services
    client.write_gatt_char = AsyncMock()
    client.start_notify = AsyncMock()
    client.stop_notify = AsyncMock()
    client.read_gatt_char = AsyncMock(return_value=b"\x00" * 16)
    client.get_services = AsyncMock(return_value=mock_services)

    return client


@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    deadline=None,
)
@given(data=config_entry_data_with_bonding)
@pytest.mark.asyncio
async def test_bonding_setting_determines_bonding_call_execution(data: dict) -> None:
    """Property 2: Bonding setting determines bonding call execution.

    Validates: Requirements 2.1, 2.2, 2.3

    For any valid config entry data dictionary containing a bluez_bonding key
    with a boolean value, the coordinator SHALL call the bonding methods
    (_check_bluez_bonded, _bluez_pair) if and only if the value is True.
    The application-level pairing code write to 59da0011 SHALL occur regardless
    of the bonding setting.
    """
    from custom_components.powerpal_ble.coordinator import PowerpalCoordinator

    # Set up mock HomeAssistant
    mock_hass = MagicMock()
    mock_hass.async_create_background_task = MagicMock()

    # Set up mock ConfigEntry with generated data
    mock_entry = MagicMock()
    mock_entry.data = data

    # Create the coordinator
    coordinator = PowerpalCoordinator(mock_hass, mock_entry)

    # Set up mocks for the connection flow
    mock_device = MagicMock()
    mock_device.name = "Powerpal"
    mock_service_info = _make_mock_service_info()
    mock_client = _make_mock_bleak_client()

    with (
        patch(
            "custom_components.powerpal_ble.coordinator.bluetooth.async_ble_device_from_address",
            return_value=mock_device,
        ),
        patch(
            "custom_components.powerpal_ble.coordinator.bluetooth.async_last_service_info",
            return_value=mock_service_info,
        ),
        patch(
            "custom_components.powerpal_ble.coordinator.establish_connection",
            new_callable=AsyncMock,
            return_value=mock_client,
        ),
        patch.object(
            coordinator,
            "_check_bluez_bonded",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_check_bonded,
        patch.object(
            coordinator,
            "_bluez_pair",
            new_callable=AsyncMock,
        ) as mock_bluez_pair,
        patch.object(
            coordinator,
            "_read_device_info",
            new_callable=AsyncMock,
        ),
    ):
        # Run _connect()
        await coordinator._connect()

        bluez_bonding = data["bluez_bonding"]

        # Property assertion: bonding methods called iff bluez_bonding is True
        if bluez_bonding:
            mock_check_bonded.assert_called()
        else:
            mock_check_bonded.assert_not_called()
            mock_bluez_pair.assert_not_called()

        # Property assertion: pairing code write always occurs regardless of bonding setting
        pairing_code = data["pairing_code"]
        expected_bytes = struct.pack("<I", pairing_code)

        # Check that write_gatt_char was called with CHAR_PAIRING_CODE_UUID
        write_calls = mock_client.write_gatt_char.call_args_list
        pairing_write_found = any(
            call.args[0] == CHAR_PAIRING_CODE_UUID and call.args[1] == expected_bytes
            for call in write_calls
            if len(call.args) >= 2
        )
        assert pairing_write_found, (
            f"Expected write_gatt_char to be called with "
            f"CHAR_PAIRING_CODE_UUID={CHAR_PAIRING_CODE_UUID} and "
            f"pairing_code bytes={expected_bytes.hex()}, "
            f"but got calls: {write_calls}"
        )
