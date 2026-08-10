"""Shared fixtures and test setup for powerpal_ble tests.

Mocks the homeassistant package at import time so tests can import
custom_components.powerpal_ble modules without a full HA installation.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Mock homeassistant and related modules before any test collects imports
# from custom_components.powerpal_ble (which triggers __init__.py -> HA imports).
# ---------------------------------------------------------------------------

_HA_MODULES = [
    "homeassistant",
    "homeassistant.config_entries",
    "homeassistant.const",
    "homeassistant.core",
    "homeassistant.components",
    "homeassistant.components.bluetooth",
    "homeassistant.components.sensor",
    "homeassistant.helpers",
    "homeassistant.helpers.aiohttp_client",
    "homeassistant.helpers.entity",
    "homeassistant.helpers.entity_platform",
    "homeassistant.helpers.entity_registry",
    "homeassistant.helpers.event",
    "homeassistant.helpers.update_coordinator",
    "homeassistant.loader",
    "bleak",
    "bleak.exc",
    "bleak_retry_connector",
    "bluetooth_adapters",
]


def _install_ha_mocks():
    """Insert mock modules for homeassistant and BLE libraries into sys.modules."""
    for mod_name in _HA_MODULES:
        if mod_name not in sys.modules:
            mock = MagicMock()
            # Ensure ConfigFlow subclassing works
            if mod_name == "homeassistant.config_entries":
                # ConfigFlow needs to be a real class so subclassing works
                class _FakeConfigFlow:
                    def __init_subclass__(cls, *, domain: str = "", **kwargs):
                        pass

                    def async_create_entry(self, **kwargs):
                        return {"type": "create_entry", **kwargs}

                    async def async_set_unique_id(self, uid):
                        pass

                    def _abort_if_unique_id_configured(self):
                        pass

                    def async_show_form(self, **kwargs):
                        return {"type": "form", **kwargs}

                mock.ConfigFlow = _FakeConfigFlow
                mock.ConfigFlowResult = dict

            if mod_name == "homeassistant.const":
                mock.CONF_ADDRESS = "address"
                mock.EVENT_STATE_CHANGED = "state_changed"
                mock.STATE_UNAVAILABLE = "unavailable"
                mock.STATE_UNKNOWN = "unknown"
                mock.Platform = MagicMock()
                mock.Platform.SENSOR = "sensor"
                mock.UnitOfEnergy = MagicMock()
                mock.UnitOfEnergy.KILO_WATT_HOUR = "kWh"
                mock.UnitOfPower = MagicMock()
                mock.UnitOfPower.WATT = "W"

            if mod_name == "homeassistant.components.bluetooth":
                mock.BluetoothServiceInfoBleak = MagicMock
                mock.async_discovered_service_info = MagicMock(return_value=[])

            if mod_name == "homeassistant.helpers.entity_registry":
                mock.async_get = MagicMock(return_value=MagicMock())

            if mod_name == "bleak":
                mock.BleakClient = MagicMock
                mock.BleakError = Exception

            if mod_name == "bleak.exc":
                mock.BleakError = Exception

            sys.modules[mod_name] = mock


# Install mocks immediately at conftest load time (before collection)
_install_ha_mocks()


@pytest.fixture
def mock_bleak_client():
    """Provide a mocked BleakClient for unit tests."""
    with patch("custom_components.powerpal_ble.coordinator.BleakClient") as mock:
        yield mock


@pytest.fixture
def mock_bluetooth():
    """Mock the HA bluetooth integration helpers."""
    with patch("custom_components.powerpal_ble.coordinator.bluetooth") as mock:
        yield mock
