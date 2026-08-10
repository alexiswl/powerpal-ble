"""Config flow for Powerpal BLE integration."""
from __future__ import annotations

import logging
import re
from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_API_KEY,
    CONF_BLUEZ_BONDING,
    CONF_CONNECTION_MODE,
    CONF_DEVICE_ID,
    CONF_ESPHOME_POWER_ENTITY,
    CONF_ESPHOME_PULSE_ENTITY,
    CONF_MAC_ADDRESS,
    CONF_NOTIFICATION_INTERVAL,
    CONF_PAIRING_CODE,
    CONF_PULSES_PER_KWH,
    CONNECTION_MODE_BLE,
    CONNECTION_MODE_ESPHOME,
    DEFAULT_BLUEZ_BONDING,
    DEFAULT_NOTIFICATION_INTERVAL,
    DEFAULT_PULSES_PER_KWH,
    DOMAIN,
    SERVICE_UUID,
)

_LOGGER = logging.getLogger(__name__)

API_KEY_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


class PowerpalBLEConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Powerpal BLE."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        self._discovered_address: str | None = None

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle the Bluetooth discovery step."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._discovery_info = discovery_info
        self._discovered_address = discovery_info.address
        return await self.async_step_connection_mode()

    async def async_step_connection_mode(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle connection mode selection after Bluetooth discovery."""
        if user_input is not None:
            mode = user_input[CONF_CONNECTION_MODE]
            if mode == CONNECTION_MODE_ESPHOME:
                return await self.async_step_esphome()
            return await self.async_step_pairing()

        return self.async_show_form(
            step_id="connection_mode",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_CONNECTION_MODE, default=CONNECTION_MODE_BLE
                    ): vol.In(
                        {
                            CONNECTION_MODE_BLE: "Direct BLE (local Bluetooth adapter)",
                            CONNECTION_MODE_ESPHOME: "ESPHome device (ESP32 handles BLE)",
                        }
                    ),
                }
            ),
            description_placeholders={"address": self._discovered_address},
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the user step — choose connection mode."""
        if user_input is not None:
            mode = user_input[CONF_CONNECTION_MODE]
            if mode == CONNECTION_MODE_ESPHOME:
                return await self.async_step_esphome()
            return await self.async_step_ble_device()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_CONNECTION_MODE, default=CONNECTION_MODE_BLE
                    ): vol.In(
                        {
                            CONNECTION_MODE_BLE: "Direct BLE (local Bluetooth adapter)",
                            CONNECTION_MODE_ESPHOME: "ESPHome device (ESP32 handles BLE)",
                        }
                    ),
                }
            ),
        )

    async def async_step_ble_device(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle BLE device selection."""
        if user_input is not None:
            self._discovered_address = user_input[CONF_MAC_ADDRESS]
            await self.async_set_unique_id(self._discovered_address)
            self._abort_if_unique_id_configured()
            return await self.async_step_pairing()

        # Look for Powerpal devices that are already discovered
        discovered_devices: list[BluetoothServiceInfoBleak] = []
        for info in async_discovered_service_info(self.hass, connectable=True):
            if SERVICE_UUID.lower() in [s.lower() for s in info.service_uuids]:
                discovered_devices.append(info)

        if discovered_devices:
            addresses = {
                info.address: f"{info.name or 'Powerpal'} ({info.address})"
                for info in discovered_devices
            }
            return self.async_show_form(
                step_id="ble_device",
                data_schema=vol.Schema(
                    {vol.Required(CONF_MAC_ADDRESS): vol.In(addresses)}
                ),
            )

        # No devices found, allow manual entry
        return self.async_show_form(
            step_id="ble_device",
            data_schema=vol.Schema({vol.Required(CONF_MAC_ADDRESS): str}),
        )

    async def async_step_pairing(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle pairing code and configuration entry for BLE mode."""
        errors: dict[str, str] = {}

        if user_input is not None:
            raw_api_key = user_input.get(CONF_API_KEY, "")
            api_key = raw_api_key.strip()
            device_id = user_input.get(CONF_DEVICE_ID, "").strip()

            # Validate API key format if user provided any input
            if raw_api_key and not API_KEY_PATTERN.match(api_key):
                errors[CONF_API_KEY] = "invalid_api_key"

            # Validate device ID is non-whitespace when non-empty
            if user_input.get(CONF_DEVICE_ID, "") and not device_id:
                errors[CONF_DEVICE_ID] = "invalid_device_id"

            if not errors:
                data = {
                    CONF_CONNECTION_MODE: CONNECTION_MODE_BLE,
                    CONF_MAC_ADDRESS: self._discovered_address,
                    CONF_PAIRING_CODE: user_input[CONF_PAIRING_CODE],
                    CONF_PULSES_PER_KWH: user_input[CONF_PULSES_PER_KWH],
                    CONF_NOTIFICATION_INTERVAL: user_input[CONF_NOTIFICATION_INTERVAL],
                    CONF_BLUEZ_BONDING: user_input[CONF_BLUEZ_BONDING],
                    CONF_API_KEY: api_key,
                    CONF_DEVICE_ID: device_id,
                }

                return self.async_create_entry(
                    title=f"Powerpal ({self._discovered_address})",
                    data=data,
                )

        return self.async_show_form(
            step_id="pairing",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PAIRING_CODE): int,
                    vol.Required(
                        CONF_PULSES_PER_KWH, default=DEFAULT_PULSES_PER_KWH
                    ): int,
                    vol.Required(
                        CONF_NOTIFICATION_INTERVAL,
                        default=DEFAULT_NOTIFICATION_INTERVAL,
                    ): vol.All(int, vol.Range(min=1, max=15)),
                    vol.Required(
                        CONF_BLUEZ_BONDING, default=DEFAULT_BLUEZ_BONDING
                    ): bool,
                    vol.Optional(CONF_API_KEY, default=""): str,
                    vol.Optional(CONF_DEVICE_ID, default=""): str,
                }
            ),
            errors=errors,
            description_placeholders={
                "address": self._discovered_address,
            },
        )

    async def async_step_esphome(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle ESPHome power entity configuration."""
        errors: dict[str, str] = {}

        if user_input is not None:
            entity_id = user_input[CONF_ESPHOME_POWER_ENTITY]
            raw_api_key = user_input.get(CONF_API_KEY, "")
            api_key = raw_api_key.strip()
            device_id = user_input.get(CONF_DEVICE_ID, "").strip()

            # Validate the entity exists
            registry = er.async_get(self.hass)
            entity_entry = registry.async_get(entity_id)
            state = self.hass.states.get(entity_id)

            if entity_entry is None and state is None:
                errors[CONF_ESPHOME_POWER_ENTITY] = "entity_not_found"

            # Validate API key format if user provided any input
            if raw_api_key and not API_KEY_PATTERN.match(api_key):
                errors[CONF_API_KEY] = "invalid_api_key"

            # Validate device ID is non-whitespace when non-empty
            if user_input.get(CONF_DEVICE_ID, "") and not device_id:
                errors[CONF_DEVICE_ID] = "invalid_device_id"

            if not errors:
                # Use entity_id as unique_id for ESPHome-sourced entries
                await self.async_set_unique_id(f"esphome_{entity_id}")
                self._abort_if_unique_id_configured()

                data = {
                    CONF_CONNECTION_MODE: CONNECTION_MODE_ESPHOME,
                    CONF_ESPHOME_POWER_ENTITY: entity_id,
                    CONF_API_KEY: api_key,
                    CONF_DEVICE_ID: device_id,
                }

                return self.async_create_entry(
                    title=f"Powerpal (ESPHome: {entity_id})",
                    data=data,
                )

        return self.async_show_form(
            step_id="esphome",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ESPHOME_POWER_ENTITY): str,
                    vol.Optional(CONF_API_KEY, default=""): str,
                    vol.Optional(CONF_DEVICE_ID, default=""): str,
                }
            ),
            errors=errors,
        )
