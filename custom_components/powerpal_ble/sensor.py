"""Sensor platform for Powerpal BLE integration."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Union

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_CONNECTION_MODE,
    CONF_ESPHOME_POWER_ENTITY,
    CONF_ESPHOME_PULSE_ENTITY,
    CONF_MAC_ADDRESS,
    CONNECTION_MODE_ESPHOME,
    DEFAULT_CONNECTION_MODE,
    DOMAIN,
)

if TYPE_CHECKING:
    from .coordinator import PowerpalCoordinator
    from .esphome_coordinator import ESPHomeCoordinator

_LOGGER = logging.getLogger(__name__)

# Type alias for either coordinator
CoordinatorType = Union["PowerpalCoordinator", "ESPHomeCoordinator"]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Powerpal BLE sensors from a config entry."""
    coordinator: CoordinatorType = hass.data[DOMAIN][entry.entry_id]
    connection_mode = entry.data.get(CONF_CONNECTION_MODE, DEFAULT_CONNECTION_MODE)

    if connection_mode == CONNECTION_MODE_ESPHOME:
        # Use the ESPHome entity ID as the device identifier
        # Check CONF_ESPHOME_POWER_ENTITY first, fall back to
        # CONF_ESPHOME_PULSE_ENTITY for backward compatibility
        source_entity = entry.data.get(
            CONF_ESPHOME_POWER_ENTITY,
            entry.data.get(CONF_ESPHOME_PULSE_ENTITY, ""),
        )
        device_id = f"esphome_{source_entity}"
        device_name = f"Powerpal ({source_entity})"
    else:
        mac_address = entry.data[CONF_MAC_ADDRESS]
        device_id = mac_address
        device_name = f"Powerpal {mac_address[-8:].replace(':', '')}"

    entities = [
        PowerpalPowerSensor(coordinator, device_id, device_name),
        PowerpalEnergyTotalSensor(coordinator, device_id, device_name),
        PowerpalDailyEnergySensor(coordinator, device_id, device_name),
    ]
    async_add_entities(entities)


class PowerpalSensorBase(SensorEntity):
    """Base class for Powerpal sensors."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: CoordinatorType,
        device_id: str,
        device_name: str,
    ) -> None:
        """Initialize the sensor."""
        self._coordinator = coordinator
        self._device_id = device_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=device_name,
            manufacturer="Powerpal",
            model="Powerpal",
        )

    async def async_added_to_hass(self) -> None:
        """Register listener when entity is added."""
        self.async_on_remove(
            self._coordinator.async_add_listener(self._handle_update)
        )

    @callback
    def _handle_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()


class PowerpalPowerSensor(PowerpalSensorBase):
    """Sensor for instantaneous power reading."""

    _attr_name = "Power"
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: CoordinatorType,
        device_id: str,
        device_name: str,
    ) -> None:
        """Initialize the power sensor."""
        super().__init__(coordinator, device_id, device_name)
        self._attr_unique_id = f"{device_id}_power"

    @property
    def native_value(self) -> float | None:
        """Return the current power in watts."""
        return self._coordinator.power


class PowerpalEnergyTotalSensor(PowerpalSensorBase):
    """Sensor for total energy consumption."""

    _attr_name = "Total Energy"
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(
        self,
        coordinator: CoordinatorType,
        device_id: str,
        device_name: str,
    ) -> None:
        """Initialize the total energy sensor."""
        super().__init__(coordinator, device_id, device_name)
        self._attr_unique_id = f"{device_id}_energy_total"

    @property
    def native_value(self) -> float | None:
        """Return total energy in kWh."""
        return self._coordinator.energy_total_kwh


class PowerpalDailyEnergySensor(PowerpalSensorBase):
    """Sensor for daily energy consumption."""

    _attr_name = "Daily Energy"
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(
        self,
        coordinator: CoordinatorType,
        device_id: str,
        device_name: str,
    ) -> None:
        """Initialize the daily energy sensor."""
        super().__init__(coordinator, device_id, device_name)
        self._attr_unique_id = f"{device_id}_energy_daily"

    @property
    def native_value(self) -> float | None:
        """Return daily energy in kWh."""
        return self._coordinator.daily_energy_kwh
