"""ESPHome-sourced coordinator for Powerpal BLE integration.

This coordinator listens to state changes from an ESPHome sensor entity
(power in watts) and derives energy values by integrating power over time.
It provides the same interface as the BLE coordinator so sensor entities
work with either backend.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    EVENT_STATE_CHANGED,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_change

from .const import (
    CONF_ESPHOME_POWER_ENTITY,
    CONF_ESPHOME_PULSE_ENTITY,
)

_LOGGER = logging.getLogger(__name__)


class ESPHomeCoordinator:
    """Derive power/energy from an ESPHome power sensor entity."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the ESPHome coordinator."""
        self.hass = hass
        self.entry = entry
        # Check CONF_ESPHOME_POWER_ENTITY first, fall back to
        # CONF_ESPHOME_PULSE_ENTITY for backward compatibility
        self._source_entity: str = entry.data.get(
            CONF_ESPHOME_POWER_ENTITY,
            entry.data.get(CONF_ESPHOME_PULSE_ENTITY, ""),
        )

        # Current sensor data (same interface as PowerpalCoordinator)
        self.power: float | None = None
        self.energy_total_kwh: float = 0.0
        self.daily_energy_kwh: float = 0.0

        # Internal state for energy integration
        self._last_reading_time: float | None = None
        self._daily_reset_day: int | None = None

        # API client (set later via set_api_client)
        self._api_client: object | None = None

        # Listeners
        self._listeners: list[Callable[[], None]] = []
        self._unsub_state: Callable[[], None] | None = None
        self._unsub_midnight: Callable[[], None] | None = None

    def set_api_client(self, client: object) -> None:
        """Attach an API client for measurement uploads."""
        self._api_client = client

    def async_add_listener(
        self, update_callback: Callable[[], None]
    ) -> Callable[[], None]:
        """Add a listener for data updates."""
        self._listeners.append(update_callback)

        def remove_listener() -> None:
            if update_callback in self._listeners:
                self._listeners.remove(update_callback)

        return remove_listener

    def _notify_listeners(self) -> None:
        """Notify all registered listeners."""
        for listener in self._listeners:
            listener()

    def async_start(self) -> Callable[[], None]:
        """Start listening to the source entity. Returns a cancel callable."""
        self._unsub_state = self.hass.bus.async_listen(
            EVENT_STATE_CHANGED, self._handle_state_change
        )

        # Track the current day for daily energy resets
        self._daily_reset_day = time.localtime().tm_yday

        # Register a midnight reset via HA's time tracking
        self._unsub_midnight = async_track_time_change(
            self.hass, self._handle_midnight, hour=0, minute=0, second=0
        )

        _LOGGER.info(
            "ESPHome coordinator started, listening to %s", self._source_entity
        )

        def cancel() -> None:
            if self._unsub_state:
                self._unsub_state()
                self._unsub_state = None
            if self._unsub_midnight:
                self._unsub_midnight()
                self._unsub_midnight = None

        return cancel

    async def async_stop(self) -> None:
        """Stop listening."""
        if self._unsub_state:
            self._unsub_state()
            self._unsub_state = None
        if self._unsub_midnight:
            self._unsub_midnight()
            self._unsub_midnight = None
        # Clear API client reference to prevent any further upload scheduling
        self._api_client = None

    @callback
    def _handle_midnight(self, _now: object) -> None:
        """Reset daily energy at midnight."""
        self.daily_energy_kwh = 0.0
        self._daily_reset_day = time.localtime().tm_yday
        _LOGGER.debug("Daily energy reset at midnight")
        self._notify_listeners()

    @callback
    def _handle_state_change(self, event: Event) -> None:
        """Handle state change events from the source entity."""
        if event.data.get("entity_id") != self._source_entity:
            return

        new_state = event.data.get("new_state")
        if new_state is None:
            return

        state_value = new_state.state
        if state_value in (None, STATE_UNKNOWN, STATE_UNAVAILABLE):
            return

        try:
            power_w = float(state_value)
        except (ValueError, TypeError):
            _LOGGER.debug(
                "Could not parse power value from %s: %s",
                self._source_entity,
                state_value,
            )
            return

        now = time.time()

        # Check if daily reset is needed (handles timezone edge cases)
        current_day = time.localtime().tm_yday
        if self._daily_reset_day is not None and current_day != self._daily_reset_day:
            self.daily_energy_kwh = 0.0
            self._daily_reset_day = current_day

        # Set power directly from state value (already in watts)
        self.power = power_w

        # Compute energy increment if we have a previous reading time
        if self._last_reading_time is not None:
            time_delta_seconds = now - self._last_reading_time
            if time_delta_seconds > 0:
                # Convert W·s to kWh: power_w * seconds / 3_600_000
                energy_kwh = power_w * time_delta_seconds / 3_600_000
                self.energy_total_kwh += energy_kwh
                self.daily_energy_kwh += energy_kwh

        # Store timestamp for next delta calculation
        self._last_reading_time = now

        _LOGGER.debug(
            "ESPHome power update: power=%.1f W, total=%.4f kWh, daily=%.4f kWh",
            self.power,
            self.energy_total_kwh,
            self.daily_energy_kwh,
        )

        self._notify_listeners()
