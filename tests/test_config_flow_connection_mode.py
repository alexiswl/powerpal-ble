"""Unit tests for async_step_connection_mode.

Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 5.1, 5.2
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.powerpal_ble.config_flow import PowerpalBLEConfigFlow
from custom_components.powerpal_ble.const import (
    CONF_CONNECTION_MODE,
    CONNECTION_MODE_BLE,
    CONNECTION_MODE_ESPHOME,
)


class TestConnectionModeFormDisplay:
    """Tests that connection_mode step shows the correct form."""

    @pytest.mark.asyncio
    async def test_no_input_returns_form_with_step_id_connection_mode(self):
        """Calling async_step_connection_mode with no user_input returns a form
        with step_id='connection_mode'.

        Validates: Requirement 1.1
        """
        flow = PowerpalBLEConfigFlow()
        flow._discovered_address = "AA:BB:CC:DD:EE:FF"

        result = await flow.async_step_connection_mode(user_input=None)

        assert result["type"] == "form"
        assert result["step_id"] == "connection_mode"

    @pytest.mark.asyncio
    async def test_form_schema_contains_connection_mode_field(self):
        """The form schema contains CONF_CONNECTION_MODE with default CONNECTION_MODE_BLE.

        Validates: Requirements 1.2, 1.3
        """
        flow = PowerpalBLEConfigFlow()
        flow._discovered_address = "AA:BB:CC:DD:EE:FF"

        result = await flow.async_step_connection_mode(user_input=None)

        schema = result["data_schema"]
        # Extract key names from the voluptuous schema
        key_names = [str(k) for k in schema.schema]
        assert CONF_CONNECTION_MODE in key_names

        # Check that the default is CONNECTION_MODE_BLE
        for key in schema.schema:
            if str(key) == CONF_CONNECTION_MODE:
                assert key.default() == CONNECTION_MODE_BLE
                break


class TestConnectionModeRouting:
    """Tests that submitting connection_mode routes to the correct next step."""

    @pytest.mark.asyncio
    async def test_ble_mode_routes_to_pairing_step(self):
        """Submitting with CONNECTION_MODE_BLE routes to async_step_pairing.

        Validates: Requirement 1.4
        """
        flow = PowerpalBLEConfigFlow()
        flow._discovered_address = "AA:BB:CC:DD:EE:FF"

        result = await flow.async_step_connection_mode(
            user_input={CONF_CONNECTION_MODE: CONNECTION_MODE_BLE}
        )

        assert result["type"] == "form"
        assert result["step_id"] == "pairing"

    @pytest.mark.asyncio
    async def test_esphome_mode_routes_to_esphome_step(self):
        """Submitting with CONNECTION_MODE_ESPHOME routes to async_step_esphome.

        Validates: Requirement 1.5
        """
        flow = PowerpalBLEConfigFlow()
        flow._discovered_address = "AA:BB:CC:DD:EE:FF"

        # async_step_esphome needs self.hass with hass.states
        mock_hass = MagicMock()
        mock_hass.states = MagicMock()
        flow.hass = mock_hass

        result = await flow.async_step_connection_mode(
            user_input={CONF_CONNECTION_MODE: CONNECTION_MODE_ESPHOME}
        )

        assert result["type"] == "form"
        assert result["step_id"] == "esphome"


class TestBluetoothDiscoveryRoutesToConnectionMode:
    """Tests that async_step_bluetooth routes to connection_mode step."""

    @pytest.mark.asyncio
    async def test_bluetooth_step_routes_to_connection_mode(self):
        """async_step_bluetooth now routes to connection_mode step.

        Validates: Requirement 1.1
        """
        flow = PowerpalBLEConfigFlow()
        flow._discovered_address = None

        # Create a mock BluetoothServiceInfoBleak with an address attribute
        discovery_info = MagicMock()
        discovery_info.address = "11:22:33:44:55:66"

        result = await flow.async_step_bluetooth(discovery_info)

        assert result["type"] == "form"
        assert result["step_id"] == "connection_mode"


class TestUserStepUnchanged:
    """Tests that async_step_user remains unchanged and does NOT go through connection_mode."""

    @pytest.mark.asyncio
    async def test_user_step_returns_user_form(self):
        """async_step_user still returns a form with step_id='user'.

        Validates: Requirements 5.1, 5.2
        """
        flow = PowerpalBLEConfigFlow()

        result = await flow.async_step_user(user_input=None)

        assert result["type"] == "form"
        assert result["step_id"] == "user"

    @pytest.mark.asyncio
    async def test_user_step_does_not_route_to_connection_mode(self):
        """async_step_user does NOT go through connection_mode step.

        Validates: Requirements 5.1, 5.2
        """
        flow = PowerpalBLEConfigFlow()

        result = await flow.async_step_user(user_input=None)

        # The user step should show its own form, not connection_mode
        assert result["step_id"] == "user"
        assert result["step_id"] != "connection_mode"
