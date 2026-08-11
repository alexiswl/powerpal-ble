"""The Powerpal BLE integration."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api_client import PowerpalApiClient
from .const import (
    CONF_API_KEY,
    CONF_CONNECTION_MODE,
    CONF_DEVICE_ID,
    CONNECTION_MODE_ESPHOME,
    DEFAULT_CONNECTION_MODE,
    DOMAIN,
)

PLATFORMS: list[Platform] = [Platform.SENSOR]

_LOGGER = logging.getLogger(__name__)


async def _fetch_historical(
    hass: HomeAssistant,
    api_client: PowerpalApiClient,
    entry: ConfigEntry,
) -> None:
    """Fetch historical data from Powerpal API and import to HA statistics."""
    try:
        if not (records := await api_client.fetch_historical_readings(days=365)):
            _LOGGER.info("Powerpal historical fetch: no records returned from API")
            return

        _LOGGER.info("Powerpal historical fetch: received %d records", len(records))

        # Import into HA long-term statistics
        statistic_id = f"{DOMAIN}:{entry.entry_id}_energy_total"

        try:
            from homeassistant.components.recorder.models import (  # pylint: disable=import-outside-toplevel
                StatisticData,
                StatisticMetaData,
            )
            from homeassistant.components.recorder.statistics import (  # pylint: disable=import-outside-toplevel
                async_import_statistics,
            )
        except ImportError:
            _LOGGER.warning(
                "Powerpal: recorder component not available, "
                "cannot import historical statistics"
            )
            return

        metadata = StatisticMetaData(
            has_mean=False,
            has_sum=True,
            name=f"Powerpal Energy ({entry.title})",
            source=DOMAIN,
            statistic_id=statistic_id,
            unit_of_measurement="kWh",
        )

        # Convert records to StatisticData, sorted by timestamp
        statistics_data: list[StatisticData] = []
        cumulative_energy = 0.0
        for record in sorted(records, key=lambda r: r["timestamp"]):
            cumulative_energy += record["watt_hours"] / 1000  # Wh to kWh
            statistics_data.append(
                StatisticData(
                    start=datetime.fromtimestamp(record["timestamp"], tz=UTC),
                    sum=cumulative_energy,
                )
            )

        # async_import_statistics replaces statistics at the same start
        # timestamp, so deduplication is handled internally by HA
        async_import_statistics(hass, metadata, statistics_data)
        _LOGGER.info(
            "Powerpal: imported %d historical statistics records",
            len(statistics_data),
        )

    except (OSError, ValueError, KeyError, TypeError, AttributeError) as err:
        _LOGGER.warning("Powerpal historical data fetch failed: %s", err)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Powerpal BLE from a config entry."""
    connection_mode = entry.data.get(CONF_CONNECTION_MODE, DEFAULT_CONNECTION_MODE)

    if connection_mode == CONNECTION_MODE_ESPHOME:
        from .esphome_coordinator import (
            ESPHomeCoordinator,  # pylint: disable=import-outside-toplevel
        )

        coordinator = ESPHomeCoordinator(hass, entry)
    else:
        from .coordinator import (
            PowerpalCoordinator,  # pylint: disable=import-outside-toplevel
        )

        coordinator = PowerpalCoordinator(hass, entry)

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # Log API key if present and create API client
    api_key = entry.data.get(CONF_API_KEY)
    device_id = entry.data.get(CONF_DEVICE_ID)
    if api_key:
        _LOGGER.info(
            "Powerpal API Key: %s, Device ID: %s",
            api_key,
            device_id or "(not configured)",
        )

    # Create API client if both credentials are present
    if api_key and device_id:
        session = async_get_clientsession(hass)
        api_client = PowerpalApiClient(session, api_key, device_id)
        coordinator.set_api_client(api_client)

        # Schedule historical data fetch (once per integration reload)
        hass.async_create_background_task(
            _fetch_historical(hass, api_client, entry),
            name=f"powerpal_historical_fetch_{device_id}",
        )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Start the connection/listener loop
    entry.async_on_unload(coordinator.async_start())
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        coordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_stop()
    return unload_ok
