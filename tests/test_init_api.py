# Feature: powerpal-api-integration, Property 3: Startup Logging Contains Configured Credentials
"""Property-based tests for startup logging behavior."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from custom_components.powerpal_ble import async_setup_entry

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# UUID-format API keys (lowercase hex)
_hex_chars = st.sampled_from("0123456789abcdef")


def _hex_block(length: int):
    """Generate a fixed-length hex string."""
    return st.text(_hex_chars, min_size=length, max_size=length)


api_key_strategy = st.builds(
    lambda a, b, c, d, e: f"{a}-{b}-{c}-{d}-{e}",
    _hex_block(8),
    _hex_block(4),
    _hex_block(4),
    _hex_block(4),
    _hex_block(12),
)

# Non-empty alphanumeric device IDs (4-16 chars)
_alnum_chars = st.sampled_from("0123456789abcdefghijklmnopqrstuvwxyz")
device_id_strategy = st.text(_alnum_chars, min_size=4, max_size=16)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_hass():
    """Create a mock HomeAssistant instance with required attributes."""
    mock_hass = MagicMock()
    mock_hass.data = {}
    mock_hass.config_entries = MagicMock()
    mock_hass.config_entries.async_forward_entry_setups = AsyncMock()
    return mock_hass


def _make_mock_entry(entry_data: dict):
    """Create a mock ConfigEntry with the given data."""
    mock_entry = MagicMock()
    mock_entry.entry_id = "test_entry_123"
    mock_entry.data = entry_data
    mock_entry.async_on_unload = MagicMock()
    return mock_entry


def _base_entry_data():
    """Return base config entry data for BLE setup (without API fields)."""
    return {
        "connection_mode": "ble",
        "mac_address": "AA:BB:CC:DD:EE:FF",
        "pairing_code": 123456,
        "pulses_per_kwh": 1000,
        "notification_interval": 1,
        "bluez_bonding": True,
    }


# ---------------------------------------------------------------------------
# Property 3: Startup Logging Contains Configured Credentials
# (Case 1: api_key present WITH device_id)
# ---------------------------------------------------------------------------


@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    deadline=None,
)
@given(
    api_key=api_key_strategy,
    device_id=device_id_strategy,
)
@pytest.mark.asyncio
async def test_startup_logging_with_api_key_and_device_id(
    api_key: str,
    device_id: str,
    caplog,
) -> None:
    """Property 3a: Startup Logging Contains Configured Credentials (with device_id).

    **Validates: Requirements 2.1, 2.3**

    For any config entry containing an API key and device ID, calling
    async_setup_entry SHALL produce an INFO-level log message containing
    the exact API key string and the device ID.
    """
    mock_hass = _make_mock_hass()
    entry_data = _base_entry_data()
    entry_data["api_key"] = api_key
    entry_data["device_id"] = device_id
    mock_entry = _make_mock_entry(entry_data)

    mock_coordinator = MagicMock()
    mock_coordinator.async_start = MagicMock(return_value=MagicMock())
    mock_coordinator.set_api_client = MagicMock()

    with (
        patch(
            "custom_components.powerpal_ble.coordinator.PowerpalCoordinator",
            return_value=mock_coordinator,
        ),
        patch(
            "custom_components.powerpal_ble.async_get_clientsession",
            return_value=MagicMock(),
        ),
        patch(
            "custom_components.powerpal_ble.PowerpalApiClient",
            return_value=MagicMock(),
        ),
        caplog.at_level(logging.INFO),
    ):
        result = await async_setup_entry(mock_hass, mock_entry)

    assert result is True

    # Must contain an INFO-level log message with the exact API key
    info_records = [r for r in caplog.records if r.levelno == logging.INFO]
    assert any(api_key in r.message for r in info_records), (
        f"Expected an INFO log containing API key '{api_key}', "
        f"but got: {[r.message for r in info_records]}"
    )

    # Must also contain the device_id
    assert any(device_id in r.message for r in info_records), (
        f"Expected an INFO log containing device_id '{device_id}', "
        f"but got: {[r.message for r in info_records]}"
    )


# ---------------------------------------------------------------------------
# Property 3: Startup Logging Contains Configured Credentials
# (Case 2: api_key present WITHOUT device_id)
# ---------------------------------------------------------------------------


@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    deadline=None,
)
@given(
    api_key=api_key_strategy,
)
@pytest.mark.asyncio
async def test_startup_logging_with_api_key_without_device_id(
    api_key: str,
    caplog,
) -> None:
    """Property 3b: Startup Logging Contains Configured Credentials (without device_id).

    **Validates: Requirements 2.1, 2.3**

    For any config entry containing an API key but with no device ID (empty
    string or absent), calling async_setup_entry SHALL produce an INFO-level
    log message containing the exact API key string and a "not configured"
    indicator for the device ID.
    """
    mock_hass = _make_mock_hass()
    entry_data = _base_entry_data()
    entry_data["api_key"] = api_key
    entry_data["device_id"] = ""  # absent / empty
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
        caplog.at_level(logging.INFO),
    ):
        result = await async_setup_entry(mock_hass, mock_entry)

    assert result is True

    # Must contain an INFO-level log message with the exact API key
    info_records = [r for r in caplog.records if r.levelno == logging.INFO]
    assert any(api_key in r.message for r in info_records), (
        f"Expected an INFO log containing API key '{api_key}', "
        f"but got: {[r.message for r in info_records]}"
    )

    # Must contain "(not configured)" indicator for absent device_id
    assert any("(not configured)" in r.message for r in info_records), (
        f"Expected an INFO log containing '(not configured)' for absent device_id, "
        f"but got: {[r.message for r in info_records]}"
    )
