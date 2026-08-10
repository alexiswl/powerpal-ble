# Feature: powerpal-api-integration, Property 1: Config Flow Credential Storage Round-Trip
# Feature: powerpal-api-integration, Property 2: Config Flow Validation Rejects Invalid Credentials
"""Property-based tests for config flow credential handling."""
from __future__ import annotations

import re
from unittest.mock import MagicMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from custom_components.powerpal_ble.config_flow import PowerpalBLEConfigFlow


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Valid UUID-format API keys (lowercase hex)
valid_api_keys = st.from_regex(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    fullmatch=True,
)

# Valid device IDs: non-empty, non-whitespace strings
valid_device_ids = st.from_regex(r"[0-9a-z]{1,20}", fullmatch=True)

# Other required fields for user_input
pairing_codes = st.integers(min_value=100000, max_value=999999)
pulses_per_kwh_values = st.integers(min_value=1, max_value=10000)
notification_intervals = st.integers(min_value=1, max_value=15)
bluez_bonding_values = st.booleans()

# Invalid API keys: strings that don't match UUID format
invalid_api_keys = st.text(min_size=1, max_size=50).filter(
    lambda s: not re.match(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        s,
        re.IGNORECASE,
    )
)

# Invalid device IDs: whitespace-only strings
invalid_device_ids = st.from_regex(r"[ \t\n]+", fullmatch=True)


# ---------------------------------------------------------------------------
# Property 1: Config Flow Credential Storage Round-Trip
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    api_key=valid_api_keys,
    device_id=valid_device_ids,
    pairing_code=pairing_codes,
    pulses_per_kwh=pulses_per_kwh_values,
    notification_interval=notification_intervals,
    bluez_bonding=bluez_bonding_values,
)
@pytest.mark.asyncio
async def test_config_flow_credential_storage_round_trip(
    api_key: str,
    device_id: str,
    pairing_code: int,
    pulses_per_kwh: int,
    notification_interval: int,
    bluez_bonding: bool,
) -> None:
    """Property 1: Config Flow Credential Storage Round-Trip.

    Validates: Requirements 1.2

    For any valid API key (UUID-format string) and device ID (non-empty string),
    when submitted through the config flow pairing step, both values SHALL appear
    unchanged in the resulting config entry data.
    """
    # Set up the config flow
    flow = PowerpalBLEConfigFlow()
    flow._discovered_address = "AA:BB:CC:DD:EE:FF"
    flow.hass = MagicMock()

    user_input = {
        "pairing_code": pairing_code,
        "pulses_per_kwh": pulses_per_kwh,
        "notification_interval": notification_interval,
        "bluez_bonding": bluez_bonding,
        "api_key": api_key,
        "device_id": device_id,
    }

    result = await flow.async_step_pairing(user_input=user_input)

    # The result should be a create_entry (not a form with errors)
    assert result["type"] == "create_entry", (
        f"Expected create_entry but got {result['type']} with errors: "
        f"{result.get('errors', {})}"
    )

    # Both credentials should appear unchanged in the entry data
    assert result["data"]["api_key"] == api_key
    assert result["data"]["device_id"] == device_id


# ---------------------------------------------------------------------------
# Property 2: Config Flow Validation Rejects Invalid Credentials
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    api_key=invalid_api_keys,
    pairing_code=pairing_codes,
    pulses_per_kwh=pulses_per_kwh_values,
    notification_interval=notification_intervals,
    bluez_bonding=bluez_bonding_values,
)
@pytest.mark.asyncio
async def test_config_flow_rejects_invalid_api_key(
    api_key: str,
    pairing_code: int,
    pulses_per_kwh: int,
    notification_interval: int,
    bluez_bonding: bool,
) -> None:
    """Property 2a: Config Flow Validation Rejects Invalid API Key.

    Validates: Requirements 1.4

    For any string that does not match UUID format when provided as an API key,
    the config flow SHALL reject the input.
    """
    flow = PowerpalBLEConfigFlow()
    flow._discovered_address = "AA:BB:CC:DD:EE:FF"
    flow.hass = MagicMock()

    user_input = {
        "pairing_code": pairing_code,
        "pulses_per_kwh": pulses_per_kwh,
        "notification_interval": notification_interval,
        "bluez_bonding": bluez_bonding,
        "api_key": api_key,
        "device_id": "valid_device_id",
    }

    result = await flow.async_step_pairing(user_input=user_input)

    # The result should be a form with an error on api_key
    assert result["type"] == "form", (
        f"Expected form (rejection) but got {result['type']} for api_key={api_key!r}"
    )
    assert "api_key" in result.get("errors", {}), (
        f"Expected error on 'api_key' field but got errors: {result.get('errors', {})}"
    )


@settings(max_examples=100)
@given(
    device_id=invalid_device_ids,
    pairing_code=pairing_codes,
    pulses_per_kwh=pulses_per_kwh_values,
    notification_interval=notification_intervals,
    bluez_bonding=bluez_bonding_values,
)
@pytest.mark.asyncio
async def test_config_flow_rejects_whitespace_only_device_id(
    device_id: str,
    pairing_code: int,
    pulses_per_kwh: int,
    notification_interval: int,
    bluez_bonding: bool,
) -> None:
    """Property 2b: Config Flow Validation Rejects Whitespace-Only Device ID.

    Validates: Requirements 1.5

    For any whitespace-only string provided as a device ID (when non-empty input
    is expected), the config flow SHALL reject the input.
    """
    flow = PowerpalBLEConfigFlow()
    flow._discovered_address = "AA:BB:CC:DD:EE:FF"
    flow.hass = MagicMock()

    # Use a valid API key so the only validation failure is the device_id
    user_input = {
        "pairing_code": pairing_code,
        "pulses_per_kwh": pulses_per_kwh,
        "notification_interval": notification_interval,
        "bluez_bonding": bluez_bonding,
        "api_key": "abcdef01-2345-6789-abcd-ef0123456789",
        "device_id": device_id,
    }

    result = await flow.async_step_pairing(user_input=user_input)

    # The result should be a form with an error on device_id
    assert result["type"] == "form", (
        f"Expected form (rejection) but got {result['type']} for device_id={device_id!r}"
    )
    assert "device_id" in result.get("errors", {}), (
        f"Expected error on 'device_id' field but got errors: {result.get('errors', {})}"
    )
