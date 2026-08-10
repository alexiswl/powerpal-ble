"""Unit tests for the ESPHome config flow step (async_step_esphome).

Validates: Requirements 4.1, 4.2, 4.3
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from custom_components.powerpal_ble.config_flow import PowerpalBLEConfigFlow
from custom_components.powerpal_ble.const import (
    CONF_CONNECTION_MODE,
    CONF_ESPHOME_POWER_ENTITY,
    CONF_ESPHOME_PULSE_ENTITY,
    CONF_PULSES_PER_KWH,
    CONNECTION_MODE_ESPHOME,
)


def _make_flow_with_hass() -> PowerpalBLEConfigFlow:
    """Create a config flow instance with a mocked hass object."""
    flow = PowerpalBLEConfigFlow()
    mock_hass = MagicMock()
    mock_hass.states = MagicMock()
    flow.hass = mock_hass
    return flow


class TestEsphomeFormPresentsCorrectFields:
    """Tests that async_step_esphome form shows the correct fields.

    Validates: Requirement 4.1
    """

    @pytest.mark.asyncio
    async def test_no_input_returns_form_with_step_id_esphome(self):
        """Calling async_step_esphome with no user_input returns a form
        with step_id='esphome'."""
        flow = _make_flow_with_hass()

        result = await flow.async_step_esphome(user_input=None)

        assert result["type"] == "form"
        assert result["step_id"] == "esphome"

    @pytest.mark.asyncio
    async def test_form_schema_contains_esphome_power_entity_field(self):
        """The form schema contains the CONF_ESPHOME_POWER_ENTITY field.

        Validates: Requirement 4.1
        """
        flow = _make_flow_with_hass()

        result = await flow.async_step_esphome(user_input=None)

        schema = result["data_schema"]
        key_names = [str(k) for k in schema.schema]
        assert CONF_ESPHOME_POWER_ENTITY in key_names

    @pytest.mark.asyncio
    async def test_form_schema_does_not_contain_pulses_per_kwh(self):
        """The ESPHome step form does NOT include pulses_per_kwh field.

        Validates: Requirement 4.3
        """
        flow = _make_flow_with_hass()

        result = await flow.async_step_esphome(user_input=None)

        schema = result["data_schema"]
        key_names = [str(k) for k in schema.schema]
        assert CONF_PULSES_PER_KWH not in key_names

    @pytest.mark.asyncio
    async def test_form_schema_does_not_contain_esphome_pulse_entity(self):
        """The ESPHome step form does NOT include the old esphome_pulse_entity field.

        Validates: Requirement 4.1
        """
        flow = _make_flow_with_hass()

        result = await flow.async_step_esphome(user_input=None)

        schema = result["data_schema"]
        key_names = [str(k) for k in schema.schema]
        assert CONF_ESPHOME_PULSE_ENTITY not in key_names


class TestEsphomeEntryStoresPowerEntityKey:
    """Tests that submitting the ESPHome form stores esphome_power_entity.

    Validates: Requirement 4.2
    """

    @pytest.mark.asyncio
    async def test_create_entry_stores_esphome_power_entity(self):
        """When a valid entity is submitted, the entry data contains
        CONF_ESPHOME_POWER_ENTITY."""
        flow = _make_flow_with_hass()

        # Mock entity registry to return an entry for the entity_id
        mock_registry = MagicMock()
        mock_registry.async_get.return_value = MagicMock()  # entity exists

        entity_id = "sensor.powerpal_power"
        with patch(
            "custom_components.powerpal_ble.config_flow.er.async_get",
            return_value=mock_registry,
        ):
            result = await flow.async_step_esphome(
                user_input={CONF_ESPHOME_POWER_ENTITY: entity_id}
            )

        assert result["type"] == "create_entry"
        assert result["data"][CONF_ESPHOME_POWER_ENTITY] == entity_id

    @pytest.mark.asyncio
    async def test_create_entry_stores_connection_mode_esphome(self):
        """The entry data contains connection_mode set to 'esphome'."""
        flow = _make_flow_with_hass()

        mock_registry = MagicMock()
        mock_registry.async_get.return_value = MagicMock()  # entity exists

        entity_id = "sensor.powerpal_power"
        with patch(
            "custom_components.powerpal_ble.config_flow.er.async_get",
            return_value=mock_registry,
        ):
            result = await flow.async_step_esphome(
                user_input={CONF_ESPHOME_POWER_ENTITY: entity_id}
            )

        assert result["type"] == "create_entry"
        assert result["data"][CONF_CONNECTION_MODE] == CONNECTION_MODE_ESPHOME

    @pytest.mark.asyncio
    async def test_create_entry_does_not_contain_pulses_per_kwh(self):
        """The entry data for ESPHome mode does NOT contain pulses_per_kwh.

        Validates: Requirement 4.3
        """
        flow = _make_flow_with_hass()

        mock_registry = MagicMock()
        mock_registry.async_get.return_value = MagicMock()  # entity exists

        entity_id = "sensor.powerpal_power"
        with patch(
            "custom_components.powerpal_ble.config_flow.er.async_get",
            return_value=mock_registry,
        ):
            result = await flow.async_step_esphome(
                user_input={CONF_ESPHOME_POWER_ENTITY: entity_id}
            )

        assert result["type"] == "create_entry"
        assert CONF_PULSES_PER_KWH not in result["data"]


class TestEsphomeFormValidation:
    """Tests that entity validation works correctly.

    Validates: Requirements 4.1, 4.2
    """

    @pytest.mark.asyncio
    async def test_entity_not_found_error_when_entity_does_not_exist(self):
        """When submitted entity is not in registry and has no state,
        the form returns with entity_not_found error."""
        flow = _make_flow_with_hass()

        # Mock entity registry to return None (entity not found)
        mock_registry = MagicMock()
        mock_registry.async_get.return_value = None

        # Mock states.get to return None (no state either)
        flow.hass.states.get.return_value = None

        entity_id = "sensor.nonexistent_entity"
        with patch(
            "custom_components.powerpal_ble.config_flow.er.async_get",
            return_value=mock_registry,
        ):
            result = await flow.async_step_esphome(
                user_input={CONF_ESPHOME_POWER_ENTITY: entity_id}
            )

        assert result["type"] == "form"
        assert result["errors"][CONF_ESPHOME_POWER_ENTITY] == "entity_not_found"

    @pytest.mark.asyncio
    async def test_entity_found_via_registry_creates_entry(self):
        """When entity exists in the entity registry, entry is created
        even if states.get returns None."""
        flow = _make_flow_with_hass()

        mock_registry = MagicMock()
        mock_registry.async_get.return_value = MagicMock()  # found in registry

        # No state available
        flow.hass.states.get.return_value = None

        entity_id = "sensor.powerpal_power"
        with patch(
            "custom_components.powerpal_ble.config_flow.er.async_get",
            return_value=mock_registry,
        ):
            result = await flow.async_step_esphome(
                user_input={CONF_ESPHOME_POWER_ENTITY: entity_id}
            )

        assert result["type"] == "create_entry"
        assert result["data"][CONF_ESPHOME_POWER_ENTITY] == entity_id

    @pytest.mark.asyncio
    async def test_entity_found_via_state_creates_entry(self):
        """When entity has a state (even if not in registry), entry is created."""
        flow = _make_flow_with_hass()

        mock_registry = MagicMock()
        mock_registry.async_get.return_value = None  # NOT in registry

        # But it has a state
        flow.hass.states.get.return_value = MagicMock()  # state exists

        entity_id = "sensor.powerpal_power"
        with patch(
            "custom_components.powerpal_ble.config_flow.er.async_get",
            return_value=mock_registry,
        ):
            result = await flow.async_step_esphome(
                user_input={CONF_ESPHOME_POWER_ENTITY: entity_id}
            )

        assert result["type"] == "create_entry"
        assert result["data"][CONF_ESPHOME_POWER_ENTITY] == entity_id
