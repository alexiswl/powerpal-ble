# Feature: esphome-config-flow-option, Property 1: Bluetooth discovery address preservation
"""Property-based tests for address preservation through connection_mode routing."""
from unittest.mock import MagicMock

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from custom_components.powerpal_ble.config_flow import PowerpalBLEConfigFlow
from custom_components.powerpal_ble.const import (
    CONF_CONNECTION_MODE,
    CONNECTION_MODE_BLE,
)

# Strategy: generate valid MAC addresses (uppercase hex, colon-separated)
mac_address_strategy = st.from_regex(
    r"[0-9A-F]{2}:[0-9A-F]{2}:[0-9A-F]{2}:[0-9A-F]{2}:[0-9A-F]{2}:[0-9A-F]{2}",
    fullmatch=True,
)


def _patch_flow_for_testing(flow: PowerpalBLEConfigFlow) -> PowerpalBLEConfigFlow:
    """Patch the flow instance so async_show_form behaves synchronously.

    In real Home Assistant, async_show_form is a synchronous helper that returns
    a dict. The test conftest mocks it as async, which causes coroutine issues.
    We override it with a plain sync function to match HA's real behavior.
    """

    def sync_show_form(**kwargs):
        return {"type": "form", **kwargs}

    flow.async_show_form = sync_show_form
    return flow


@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    deadline=None,
)
@given(address=mac_address_strategy)
@pytest.mark.asyncio
async def test_address_preserved_through_connection_mode_routing(address: str) -> None:
    """Property 1: Bluetooth discovery address preservation through connection mode routing.

    **Validates: Requirements 1.4**

    For any valid Bluetooth MAC address discovered during async_step_bluetooth,
    when the user selects Direct BLE in the connection mode step and proceeds to
    the pairing step, the _discovered_address field SHALL equal the originally
    discovered address AND the pairing form's description_placeholders SHALL
    contain that address.
    """
    # Create the flow instance with patched async_show_form
    flow = _patch_flow_for_testing(PowerpalBLEConfigFlow())

    # Create a mock BluetoothServiceInfoBleak with the generated address
    mock_discovery_info = MagicMock()
    mock_discovery_info.address = address

    # Step 1: Simulate async_step_bluetooth
    result = await flow.async_step_bluetooth(mock_discovery_info)

    # After bluetooth step, we should have the connection_mode form
    assert result["type"] == "form"
    assert result["step_id"] == "connection_mode"

    # Verify _discovered_address is set to the original address
    assert flow._discovered_address == address

    # Verify the connection_mode form's description_placeholders contain the address
    assert result.get("description_placeholders", {}).get("address") == address

    # Step 2: Submit connection_mode with BLE selection
    result = await flow.async_step_connection_mode(
        {CONF_CONNECTION_MODE: CONNECTION_MODE_BLE}
    )

    # Should route to the pairing form
    assert result["type"] == "form"
    assert result["step_id"] == "pairing"

    # Verify _discovered_address is STILL the original address after routing
    assert flow._discovered_address == address

    # Verify the pairing form's description_placeholders contain the address
    assert result.get("description_placeholders", {}).get("address") == address
