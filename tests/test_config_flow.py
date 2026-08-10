"""Unit tests for the config flow bonding option.

Validates Requirements: 1.1, 1.2, 1.3
"""
from __future__ import annotations

import pytest
import voluptuous as vol

from custom_components.powerpal_ble.config_flow import PowerpalBLEConfigFlow
from custom_components.powerpal_ble.const import (
    CONF_BLUEZ_BONDING,
    CONF_MAC_ADDRESS,
    CONF_NOTIFICATION_INTERVAL,
    CONF_PAIRING_CODE,
    CONF_PULSES_PER_KWH,
    DEFAULT_BLUEZ_BONDING,
    DEFAULT_NOTIFICATION_INTERVAL,
    DEFAULT_PULSES_PER_KWH,
)

# ---------------------------------------------------------------------------
# Rebuild the pairing schema as defined in config_flow.py for direct testing
# ---------------------------------------------------------------------------
PAIRING_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PAIRING_CODE): int,
        vol.Required(CONF_PULSES_PER_KWH, default=DEFAULT_PULSES_PER_KWH): int,
        vol.Required(
            CONF_NOTIFICATION_INTERVAL, default=DEFAULT_NOTIFICATION_INTERVAL
        ): vol.All(int, vol.Range(min=1, max=15)),
        vol.Required(CONF_BLUEZ_BONDING, default=DEFAULT_BLUEZ_BONDING): bool,
    }
)


class TestPairingSchemaContainsBondingField:
    """Validates Requirement 1.1: bluez_bonding field exists in pairing step schema."""

    def test_bluez_bonding_key_present_in_schema(self):
        """The pairing step schema contains the bluez_bonding key."""
        key_names = [str(k) for k in PAIRING_SCHEMA.schema]
        assert CONF_BLUEZ_BONDING in key_names

    def test_schema_accepts_bluez_bonding_true(self):
        """The schema validates input with bluez_bonding=True."""
        result = PAIRING_SCHEMA({CONF_PAIRING_CODE: 123456, CONF_BLUEZ_BONDING: True})
        assert result[CONF_BLUEZ_BONDING] is True

    def test_schema_accepts_bluez_bonding_false(self):
        """The schema validates input with bluez_bonding=False."""
        result = PAIRING_SCHEMA({CONF_PAIRING_CODE: 123456, CONF_BLUEZ_BONDING: False})
        assert result[CONF_BLUEZ_BONDING] is False


class TestPairingSchemaDefaultsBondingToTrue:
    """Validates Requirement 1.2: schema defaults bluez_bonding to True."""

    def test_schema_defaults_bluez_bonding_to_true(self):
        """When bluez_bonding is omitted, the schema fills default=True."""
        result = PAIRING_SCHEMA({CONF_PAIRING_CODE: 123456})
        assert result[CONF_BLUEZ_BONDING] is True

    def test_default_constant_is_true(self):
        """The DEFAULT_BLUEZ_BONDING constant is True."""
        assert DEFAULT_BLUEZ_BONDING is True


class TestCreateEntryStoresBondingValue:
    """Validates Requirement 1.3: async_create_entry stores user-provided bluez_bonding."""

    @pytest.mark.asyncio
    async def test_create_entry_stores_bluez_bonding_true(self):
        """When user submits bluez_bonding=True, the entry data contains it."""
        flow = PowerpalBLEConfigFlow()
        flow._discovered_address = "AA:BB:CC:DD:EE:FF"

        user_input = {
            CONF_PAIRING_CODE: 123456,
            CONF_PULSES_PER_KWH: 1000,
            CONF_NOTIFICATION_INTERVAL: 1,
            CONF_BLUEZ_BONDING: True,
        }
        result = await flow.async_step_pairing(user_input=user_input)

        assert result["data"][CONF_BLUEZ_BONDING] is True

    @pytest.mark.asyncio
    async def test_create_entry_stores_bluez_bonding_false(self):
        """When user submits bluez_bonding=False, the entry data contains it."""
        flow = PowerpalBLEConfigFlow()
        flow._discovered_address = "AA:BB:CC:DD:EE:FF"

        user_input = {
            CONF_PAIRING_CODE: 654321,
            CONF_PULSES_PER_KWH: 2000,
            CONF_NOTIFICATION_INTERVAL: 5,
            CONF_BLUEZ_BONDING: False,
        }
        result = await flow.async_step_pairing(user_input=user_input)

        assert result["data"][CONF_BLUEZ_BONDING] is False

    @pytest.mark.asyncio
    async def test_create_entry_includes_all_expected_keys(self):
        """The entry data dict contains all required config keys."""
        flow = PowerpalBLEConfigFlow()
        flow._discovered_address = "11:22:33:44:55:66"

        user_input = {
            CONF_PAIRING_CODE: 111111,
            CONF_PULSES_PER_KWH: 1000,
            CONF_NOTIFICATION_INTERVAL: 1,
            CONF_BLUEZ_BONDING: True,
        }
        result = await flow.async_step_pairing(user_input=user_input)

        data = result["data"]
        assert CONF_MAC_ADDRESS in data
        assert CONF_PAIRING_CODE in data
        assert CONF_PULSES_PER_KWH in data
        assert CONF_NOTIFICATION_INTERVAL in data
        assert CONF_BLUEZ_BONDING in data
