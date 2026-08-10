"""Coordinator for Powerpal BLE integration."""

from __future__ import annotations

import asyncio
import logging
import struct
import subprocess
import time
from collections.abc import Callable
from typing import Any

from bleak import BleakClient, BleakError
from bleak_retry_connector import establish_connection
from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .api_client import PowerpalApiClient
from .const import (
    CHAR_API_KEY_UUID,
    CHAR_MEASUREMENT_ACCESS_UUID,
    CHAR_MEASUREMENT_UUID,
    CHAR_PAIRING_CODE_UUID,
    CHAR_READING_BATCH_SIZE_UUID,
    CHAR_SERIAL_NUMBER_UUID,
    CHAR_TIME_UUID,
    CONF_API_KEY,
    CONF_BLUEZ_BONDING,
    CONF_DEVICE_ID,
    CONF_MAC_ADDRESS,
    CONF_NOTIFICATION_INTERVAL,
    CONF_PAIRING_CODE,
    CONF_PULSES_PER_KWH,
    DEFAULT_BLUEZ_BONDING,
)

_LOGGER = logging.getLogger(__name__)

RECONNECT_INTERVAL = 30  # seconds between reconnection attempts
MAX_RECONNECT_INTERVAL = 300  # max backoff: 5 minutes
BACKOFF_MULTIPLIER = 2  # double the interval on each consecutive failure


class PowerpalCoordinator:
    """Manage BLE connection and data from Powerpal device."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        self.hass = hass
        self.entry = entry
        self._mac_address: str = entry.data[CONF_MAC_ADDRESS]
        self._pairing_code: int = entry.data[CONF_PAIRING_CODE]
        self._pulses_per_kwh: int = entry.data[CONF_PULSES_PER_KWH]
        self._notification_interval: int = entry.data[CONF_NOTIFICATION_INTERVAL]
        self._bluez_bonding: bool = entry.data.get(
            CONF_BLUEZ_BONDING, DEFAULT_BLUEZ_BONDING
        )

        self._client: BleakClient | None = None
        self._connected = False
        self._cancel_reconnect: asyncio.Task | None = None
        self._consecutive_failures: int = 0

        # Current sensor data
        self.power: float | None = None
        self.energy_total_kwh: float = 0.0
        self.daily_energy_kwh: float = 0.0
        self.battery_level: int | None = None
        self.api_key: str | None = None
        self.device_id: str | None = None
        self._total_pulses: int = 0
        self._last_timestamp: int = 0

        # API client (set later via set_api_client)
        self._api_client: PowerpalApiClient | None = None

        # Listeners
        self._listeners: list[Callable[[], None]] = []

    def set_api_client(self, client: PowerpalApiClient) -> None:
        """Attach an API client for measurement uploads."""
        self._api_client = client

    def async_add_listener(
        self, update_callback: Callable[[], None]
    ) -> Callable[[], None]:
        """Add a listener for data updates."""
        self._listeners.append(update_callback)

        def remove_listener() -> None:
            self._listeners.remove(update_callback)

        return remove_listener

    def _notify_listeners(self) -> None:
        """Notify all registered listeners."""
        for listener in self._listeners:
            listener()

    def async_start(self) -> Callable[[], None]:
        """Start the connection loop. Returns a callable to cancel."""
        self._cancel_reconnect = self.hass.async_create_background_task(
            self._connection_loop(),
            name=f"powerpal_ble_connection_loop_{self._mac_address}",
        )

        def cancel() -> None:
            if self._cancel_reconnect and not self._cancel_reconnect.done():
                self._cancel_reconnect.cancel()

        return cancel

    async def async_stop(self) -> None:
        """Stop the coordinator and disconnect."""
        if self._cancel_reconnect and not self._cancel_reconnect.done():
            self._cancel_reconnect.cancel()
            try:
                await self._cancel_reconnect
            except asyncio.CancelledError:
                pass
        self._cancel_reconnect = None
        # Clear API client reference to prevent any further upload scheduling
        self._api_client = None

    async def _connection_loop(self) -> None:
        """Main loop that maintains the BLE connection."""
        try:
            while True:
                try:
                    if not self._connected:
                        await self._connect()
                        # Reset backoff on successful connection
                        self._consecutive_failures = 0
                except asyncio.CancelledError:
                    raise
                except Exception as err:  # noqa: BLE001
                    self._consecutive_failures += 1
                    retry_interval = min(
                        RECONNECT_INTERVAL
                        * (BACKOFF_MULTIPLIER ** (self._consecutive_failures - 1)),
                        MAX_RECONNECT_INTERVAL,
                    )

                    # Get current RSSI for context in error messages
                    last_rssi = self._get_last_rssi()

                    # Detect slot exhaustion vs other errors and provide
                    # context-aware guidance
                    err_str = str(err)
                    if "connection slot" in err_str.lower():
                        if last_rssi is not None and last_rssi < -80:
                            _LOGGER.warning(
                                "Powerpal connection failed: %s (attempt %d). "
                                "The error reports 'connection slots exhausted' but "
                                "RSSI is %d dBm (weak signal). The real cause is "
                                "likely poor Bluetooth signal — the adapter cannot "
                                "maintain a stable connection at this distance. "
                                "Move the Bluetooth adapter closer to the Powerpal "
                                "device (use a USB extension cable if needed). "
                                "Retrying in %d seconds",
                                self._mac_address,
                                self._consecutive_failures,
                                last_rssi,
                                int(retry_interval),
                            )
                        else:
                            _LOGGER.warning(
                                "Powerpal connection failed: %s (attempt %d). "
                                "Adapter connection slots exhausted. RSSI=%s dBm. "
                                "Try restarting the Bluetooth integration "
                                "(Settings → Devices & Services → Bluetooth → ⋮ → Reload), "
                                "or unplug and re-plug the USB adapter. If the issue "
                                "persists, reboot Home Assistant from "
                                "Settings → System → Restart. "
                                "Retrying in %d seconds",
                                self._mac_address,
                                self._consecutive_failures,
                                last_rssi if last_rssi is not None else "unknown",
                                int(retry_interval),
                            )
                    else:
                        _LOGGER.warning(
                            "Powerpal connection error: %s: %s (attempt %d, "
                            "RSSI=%s dBm). Retrying in %d seconds",
                            self._mac_address,
                            err,
                            self._consecutive_failures,
                            last_rssi if last_rssi is not None else "unknown",
                            int(retry_interval),
                        )

                    await self._disconnect()
                    await asyncio.sleep(retry_interval)
                    continue

                await asyncio.sleep(RECONNECT_INTERVAL)
        except asyncio.CancelledError:
            _LOGGER.debug("Powerpal connection loop cancelled, disconnecting")
        finally:
            await self._disconnect()

    def _get_last_rssi(self) -> int | None:
        """Get the most recent RSSI reading for the device."""
        try:
            service_info = bluetooth.async_last_service_info(
                self.hass, self._mac_address, connectable=True
            )
            if service_info:
                return service_info.rssi
        except (AttributeError, TypeError):
            pass
        return None

    async def _connect(self) -> None:
        """Establish connection and subscribe to notifications.

        The Powerpal requires BLE-level encryption (bonding) before it
        allows writes to its custom GATT service. The pairing code
        provided during setup is the BLE passkey. We attempt to pair
        via BlueZ D-Bus if not already bonded.
        """
        _LOGGER.debug("Connecting to Powerpal at %s", self._mac_address)

        device = bluetooth.async_ble_device_from_address(
            self.hass, self._mac_address, connectable=True
        )
        if device is None:
            _LOGGER.debug("Powerpal device not found: %s", self._mac_address)
            raise BleakError(
                f"Device {self._mac_address} not found in connectable device list"
            )

        # Log device discovery details for diagnostics
        try:
            service_info = bluetooth.async_last_service_info(
                self.hass, self._mac_address, connectable=True
            )
        except (AttributeError, TypeError):
            service_info = None
            _LOGGER.debug(
                "bluetooth.async_last_service_info not available in this HA version"
            )
        if service_info:
            _LOGGER.info(
                "Powerpal BLE diagnostics: address=%s, rssi=%d dBm, "
                "adapter=%s (source=%s), connectable=%s, "
                "time_since_last_seen=%.1fs",
                self._mac_address,
                service_info.rssi,
                service_info.source,
                service_info.source,
                service_info.connectable,
                time.time() - service_info.time,
            )
            if service_info.rssi < -80:
                _LOGGER.warning(
                    "Powerpal RSSI is weak (%d dBm). Signal below -80 dBm "
                    "often causes connection failures. Consider moving the "
                    "Bluetooth adapter closer to the Powerpal device.",
                    service_info.rssi,
                )
        else:
            _LOGGER.warning(
                "Powerpal: no service info available for %s — device may "
                "not be advertising or is out of range",
                self._mac_address,
            )

        # Conditionally perform BlueZ bonding based on user configuration
        if self._bluez_bonding:
            _LOGGER.debug("BlueZ bonding enabled for %s", self._mac_address)
            is_bonded = await self._check_bluez_bonded()
            if not is_bonded:
                _LOGGER.info(
                    "Powerpal not bonded at BlueZ level. "
                    "Attempting to pair with passkey %d...",
                    self._pairing_code,
                )
                await self._bluez_pair()
        else:
            _LOGGER.info(
                "BlueZ bonding disabled for %s — skipping bonding check",
                self._mac_address,
            )

        _LOGGER.debug(
            "Attempting BLE connection to %s (device name: %s)",
            self._mac_address,
            device.name or "unknown",
        )

        self._client = await establish_connection(
            BleakClient, device, self._mac_address, max_attempts=3
        )

        _LOGGER.debug("Connected to Powerpal, discovering services")

        # Explicitly discover services and log what's available
        services = self._client.services
        if services is None:
            services = await self._client.get_services()

        # Log all discovered services and characteristics for diagnostics
        for service in services:
            char_uuids = [str(c.uuid) for c in service.characteristics]
            _LOGGER.debug(
                "Powerpal BLE service: %s, characteristics: %s",
                service.uuid,
                char_uuids,
            )

        # Verify our target characteristic exists before writing
        target_char = services.get_characteristic(CHAR_PAIRING_CODE_UUID)
        if target_char is None:
            all_chars = []
            for service in services:
                for char in service.characteristics:
                    all_chars.append(str(char.uuid))
            _LOGGER.error(
                "Pairing code characteristic %s not found on device. "
                "Available characteristics: %s",
                CHAR_PAIRING_CODE_UUID,
                all_chars,
            )
            raise BleakError(
                f"Characteristic {CHAR_PAIRING_CODE_UUID} not found. "
                f"Available: {all_chars}"
            )

        _LOGGER.debug("Pairing characteristic properties: %s", target_char.properties)

        _LOGGER.debug(
            "Writing pairing code to characteristic %s", CHAR_PAIRING_CODE_UUID
        )

        # The Powerpal authentication flow (from ESP32 reference):
        # 1. Write pairing code to characteristic
        # 2. Register for measurement notifications immediately
        # 3. Then set batch reading size
        # The device confirms auth by starting to send measurement data.

        # First, subscribe to notifications on the pairing code characteristic
        # to catch any authentication confirmation
        auth_confirmed = asyncio.Event()

        def _pairing_notify_callback(sender: Any, data: bytearray) -> None:
            _LOGGER.debug(
                "Received notification on pairing characteristic: %s",
                data.hex(),
            )
            auth_confirmed.set()

        # Subscribe to pairing code notifications before writing
        try:
            async with asyncio.timeout(5):
                await self._client.start_notify(
                    CHAR_PAIRING_CODE_UUID, _pairing_notify_callback
                )
            _LOGGER.debug("Subscribed to pairing code notifications")
        except (TimeoutError, BleakError) as err:
            _LOGGER.debug("Could not subscribe to pairing notifications: %s", err)

        # Write pairing code (convert to little-endian 4-byte array)
        pairing_bytes = struct.pack("<I", self._pairing_code)
        try:
            try:
                async with asyncio.timeout(10):
                    await self._client.write_gatt_char(
                        CHAR_PAIRING_CODE_UUID, pairing_bytes, response=False
                    )
            except TimeoutError:
                _LOGGER.warning(
                    "Pairing write without response timed out, retrying with response"
                )
                async with asyncio.timeout(10):
                    await self._client.write_gatt_char(
                        CHAR_PAIRING_CODE_UUID, pairing_bytes, response=True
                    )
        except BleakError as err:
            err_msg = str(err).lower()
            if not self._bluez_bonding and any(
                keyword in err_msg
                for keyword in ("authentication", "encryption", "security")
            ):
                _LOGGER.warning(
                    "Powerpal %s: BLE authentication/encryption error during "
                    "pairing code write with BlueZ bonding disabled. This "
                    "device may require BlueZ bonding to be enabled. Error: %s",
                    self._mac_address,
                    err,
                )
            raise

        _LOGGER.debug("Pairing code written successfully")

        # Wait briefly for auth confirmation notification
        try:
            async with asyncio.timeout(5):
                await auth_confirmed.wait()
            _LOGGER.info("Powerpal authentication confirmed via notification")
        except TimeoutError:
            _LOGGER.debug(
                "No auth confirmation notification received (may not be needed)"
            )

        # Unsubscribe from pairing notifications
        try:
            await self._client.stop_notify(CHAR_PAIRING_CODE_UUID)
        except (BleakError, Exception):  # noqa: BLE001
            _LOGGER.debug("Failed to stop pairing notifications (non-critical)")

        # Small delay to allow authentication to process
        await asyncio.sleep(1)

        # --- STEP 1: Write current time to the time characteristic (0004) ---
        # The Powerpal needs to know the current time so it can timestamp
        # measurements and know which readings to send.
        current_timestamp = int(time.time())
        time_bytes = struct.pack("<I", current_timestamp)
        _LOGGER.debug(
            "Writing current timestamp %d to time characteristic %s",
            current_timestamp,
            CHAR_TIME_UUID,
        )
        time_char = services.get_characteristic(CHAR_TIME_UUID)
        if time_char is None:
            _LOGGER.warning("Time characteristic %s not found", CHAR_TIME_UUID)
        else:
            _LOGGER.debug("Time characteristic properties: %s", time_char.properties)
            try:
                async with asyncio.timeout(10):
                    await self._client.write_gatt_char(
                        CHAR_TIME_UUID, time_bytes, response=False
                    )
                _LOGGER.info(
                    "Current timestamp written to device: %d", current_timestamp
                )
            except (TimeoutError, BleakError) as err:
                _LOGGER.warning("Could not write timestamp to device: %s", err)

        # --- STEP 2: Subscribe to measurement notifications on 0001 ---
        # The 0001 characteristic supports 'notify' and is where data arrives.
        _LOGGER.debug(
            "Subscribing to measurement notifications on %s",
            CHAR_MEASUREMENT_UUID,
        )
        meas_char = services.get_characteristic(CHAR_MEASUREMENT_UUID)
        if meas_char is None:
            _LOGGER.error(
                "Measurement characteristic %s not found!", CHAR_MEASUREMENT_UUID
            )
        else:
            _LOGGER.debug(
                "Measurement characteristic properties: %s", meas_char.properties
            )
            try:
                async with asyncio.timeout(10):
                    await self._client.start_notify(
                        CHAR_MEASUREMENT_UUID, self._measurement_callback
                    )
                _LOGGER.info(
                    "Subscribed to measurement notifications on %s",
                    CHAR_MEASUREMENT_UUID,
                )
            except (TimeoutError, BleakError) as err:
                _LOGGER.error(
                    "Could not subscribe to measurement notifications: %s", err
                )

        # Also subscribe to indications on 0002 (measurement access) in case
        # the device sends data there too
        meas_access_char = services.get_characteristic(CHAR_MEASUREMENT_ACCESS_UUID)
        if meas_access_char and (
            "indicate" in meas_access_char.properties
            or "notify" in meas_access_char.properties
        ):
            try:
                async with asyncio.timeout(10):
                    await self._client.start_notify(
                        CHAR_MEASUREMENT_ACCESS_UUID, self._measurement_callback
                    )
                _LOGGER.info(
                    "Subscribed to indications on measurement access %s",
                    CHAR_MEASUREMENT_ACCESS_UUID,
                )
            except (TimeoutError, BleakError) as err:
                _LOGGER.debug(
                    "Could not subscribe to measurement access indications: %s", err
                )

        # --- STEP 3: Write batch size / notification interval ---
        # Try writing as a single byte first (some firmware expects this),
        # then fall back to 4-byte uint32
        interval_val = max(self._notification_interval, 1)
        _LOGGER.debug(
            "Writing batch size / notification interval: %d to %s",
            interval_val,
            CHAR_READING_BATCH_SIZE_UUID,
        )

        batch_char = services.get_characteristic(CHAR_READING_BATCH_SIZE_UUID)
        if batch_char is None:
            _LOGGER.warning(
                "Batch size characteristic %s not found — skipping",
                CHAR_READING_BATCH_SIZE_UUID,
            )
        else:
            _LOGGER.debug(
                "Batch size characteristic properties: %s", batch_char.properties
            )
            # Try single byte first (most common for Powerpal)
            wrote_batch = False
            for payload, desc in [
                (struct.pack("<B", min(interval_val, 255)), "uint8"),
                (struct.pack("<I", interval_val), "uint32"),
            ]:
                try:
                    async with asyncio.timeout(10):
                        await self._client.write_gatt_char(
                            CHAR_READING_BATCH_SIZE_UUID, payload, response=False
                        )
                    _LOGGER.info(
                        "Batch size written successfully as %s: %s",
                        desc,
                        payload.hex(),
                    )
                    wrote_batch = True
                    break
                except (TimeoutError, BleakError) as err:
                    _LOGGER.debug("Batch size write as %s failed: %s", desc, err)

            if not wrote_batch:
                _LOGGER.warning(
                    "Could not write batch size to device. "
                    "Notifications may still arrive at the device's default interval."
                )

        # --- STEP 4: Write to measurement access (0002) to trigger data flow ---
        # The Powerpal requires a write to the measurement access characteristic
        # to start sending notifications. We write the current timestamp to tell
        # it "send me readings from now."
        _LOGGER.debug(
            "Writing measurement request to %s to trigger data flow",
            CHAR_MEASUREMENT_ACCESS_UUID,
        )
        if meas_access_char is not None and "write" in meas_access_char.properties:
            # Write current timestamp as the "start from" marker
            trigger_timestamp = struct.pack("<I", int(time.time()))
            try:
                async with asyncio.timeout(10):
                    await self._client.write_gatt_char(
                        CHAR_MEASUREMENT_ACCESS_UUID, trigger_timestamp, response=False
                    )
                _LOGGER.info(
                    "Measurement trigger written to %s (timestamp: %s)",
                    CHAR_MEASUREMENT_ACCESS_UUID,
                    trigger_timestamp.hex(),
                )
            except (TimeoutError, BleakError) as err:
                _LOGGER.warning(
                    "Could not write measurement trigger: %s. "
                    "Trying with response=True...",
                    err,
                )
                try:
                    async with asyncio.timeout(10):
                        await self._client.write_gatt_char(
                            CHAR_MEASUREMENT_ACCESS_UUID,
                            trigger_timestamp,
                            response=True,
                        )
                    _LOGGER.info("Measurement trigger written (with response)")
                except (TimeoutError, BleakError) as err2:
                    _LOGGER.error(
                        "Failed to write measurement trigger: %s. "
                        "Device may not send notifications.",
                        err2,
                    )
        else:
            _LOGGER.warning(
                "Measurement access characteristic not writable or not found. "
                "Cannot trigger data flow."
            )

        # Read API key and Device ID (optional — not critical for operation)
        await self._read_device_info()

        self._connected = True
        _LOGGER.info("Powerpal connected successfully. Device ID: %s", self.device_id)

    async def _check_bluez_bonded(self) -> bool:
        """Check if the device is already bonded in BlueZ."""
        try:
            # Use bluetoothctl to check if device is paired
            result = await asyncio.to_thread(
                subprocess.run,
                ["bluetoothctl", "info", self._mac_address],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0 and "Paired: yes" in result.stdout:
                _LOGGER.debug("Powerpal is already paired/bonded in BlueZ")
                return True
            _LOGGER.debug(
                "Powerpal not paired in BlueZ. bluetoothctl output: %s",
                result.stdout[:200] if result.stdout else "(empty)",
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as err:
            _LOGGER.debug("Could not check BlueZ bond status: %s", err)
        return False

    async def _bluez_pair(self) -> None:
        """Pair the Powerpal device via BlueZ using the pairing code as passkey.

        This sets up a BlueZ agent to provide the passkey, then initiates
        pairing. The Powerpal uses MITM-protected pairing where the
        6-digit code is the passkey.
        """
        _LOGGER.info(
            "Initiating BlueZ pairing for %s with passkey %d",
            self._mac_address,
            self._pairing_code,
        )

        try:
            # Remove any stale pairing first
            await asyncio.to_thread(
                subprocess.run,
                ["bluetoothctl", "remove", self._mac_address],
                capture_output=True,
                text=True,
                timeout=10,
            )
            _LOGGER.debug("Removed stale pairing info (if any)")
            await asyncio.sleep(2)

            # Use expect-style interaction with bluetoothctl to pair
            # We need to handle the passkey request interactively
            proc = await asyncio.create_subprocess_exec(
                "bluetoothctl",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            # Build the command sequence for bluetoothctl
            commands = (
                f"agent off\n"
                f"agent KeyboardDisplay\n"
                f"default-agent\n"
                f"pair {self._mac_address}\n"
            )

            _LOGGER.debug("Sending bluetoothctl pair commands")

            # Write initial commands
            proc.stdin.write(commands.encode())
            await proc.stdin.drain()

            # Wait for passkey request and provide it
            passkey_provided = False
            try:
                async with asyncio.timeout(30):
                    while True:
                        line = await proc.stdout.readline()
                        if not line:
                            break
                        line_str = line.decode(errors="replace").strip()
                        _LOGGER.debug("bluetoothctl: %s", line_str)

                        if (
                            "Passkey" in line_str
                            or "passkey" in line_str
                            or "PIN" in line_str
                        ):
                            # Provide the passkey
                            passkey_str = f"{self._pairing_code}\n"
                            proc.stdin.write(passkey_str.encode())
                            await proc.stdin.drain()
                            _LOGGER.info("Provided passkey to BlueZ")
                            passkey_provided = True

                        if "Pairing successful" in line_str:
                            _LOGGER.info("BlueZ pairing successful!")
                            break

                        if "Failed" in line_str or "error" in line_str.lower():
                            _LOGGER.warning("BlueZ pairing issue: %s", line_str)
                            # Don't break — sometimes there are non-fatal errors
                            if "Pairing" in line_str and "failed" in line_str.lower():
                                break

                        if passkey_provided and (
                            "Connected: yes" in line_str
                            or "ServicesResolved" in line_str
                        ):
                            # Pairing likely succeeded
                            _LOGGER.info("BlueZ pairing appears successful")
                            break

            except TimeoutError:
                _LOGGER.warning(
                    "BlueZ pairing timed out after 30 seconds. "
                    "This may mean the device didn't request a passkey "
                    "or the pairing mode is different than expected."
                )

            # Clean up
            proc.stdin.write(b"quit\n")
            await proc.stdin.drain()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except TimeoutError:
                proc.kill()

            # Give BlueZ time to settle after pairing
            await asyncio.sleep(3)

            # Verify pairing worked
            is_bonded = await self._check_bluez_bonded()
            if is_bonded:
                _LOGGER.info("Powerpal successfully bonded at BlueZ level")
            else:
                _LOGGER.warning(
                    "BlueZ pairing may not have completed. "
                    "Will attempt connection anyway — the device may "
                    "accept writes without full bonding on some firmware."
                )

        except (FileNotFoundError, OSError) as err:
            _LOGGER.warning(
                "Could not run bluetoothctl for pairing: %s. "
                "You may need to manually pair the device. Run: "
                "bluetoothctl pair %s  and enter passkey %d when prompted.",
                err,
                self._mac_address,
                self._pairing_code,
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Unexpected error during BlueZ pairing: %s", err)

    async def _read_device_info(self) -> None:
        """Read and decode the API key and Device ID from the Powerpal.

        These reads are optional — the integration works without them.
        Some devices reject reads on protected characteristics
        (error 0x02: Read Not Permitted) if encryption negotiation
        didn't complete fully. In that case we fall back to any values
        provided in the config entry.
        """
        if self._client is None:
            return

        # Try reading from BLE first; fall back to config entry values
        # (user may have supplied them manually during setup).
        conf_api_key: str | None = self.entry.data.get(CONF_API_KEY)
        conf_device_id: str | None = self.entry.data.get(CONF_DEVICE_ID)

        try:
            # Read API Key (16 bytes, big-endian UUID)
            _LOGGER.debug("Reading API key from characteristic %s", CHAR_API_KEY_UUID)
            async with asyncio.timeout(10):
                api_key_data = await self._client.read_gatt_char(CHAR_API_KEY_UUID)
            if api_key_data and len(api_key_data) == 16:
                self.api_key = self._decode_api_key(api_key_data)
                _LOGGER.info("Powerpal API Key: %s", self.api_key)
            else:
                _LOGGER.debug(
                    "API key data unexpected length: %d",
                    len(api_key_data) if api_key_data else 0,
                )
        except TimeoutError:
            _LOGGER.debug("Timed out reading API key from BLE")
        except BleakError as err:
            _LOGGER.debug(
                "Could not read API key from BLE (device may require "
                "bonding for this characteristic): %s",
                err,
            )

        try:
            # Read Device ID (4 bytes, little-endian)
            _LOGGER.debug(
                "Reading device ID from characteristic %s", CHAR_SERIAL_NUMBER_UUID
            )
            async with asyncio.timeout(10):
                device_id_data = await self._client.read_gatt_char(
                    CHAR_SERIAL_NUMBER_UUID
                )
            if device_id_data and len(device_id_data) >= 4:
                self.device_id = self._decode_device_id(device_id_data[:4])
                _LOGGER.info("Powerpal Device ID: %s", self.device_id)
            else:
                _LOGGER.debug(
                    "Device ID data unexpected length: %d",
                    len(device_id_data) if device_id_data else 0,
                )
        except TimeoutError:
            _LOGGER.debug("Timed out reading device ID from BLE")
        except BleakError as err:
            _LOGGER.debug(
                "Could not read device ID from BLE (device may require "
                "bonding for this characteristic): %s",
                err,
            )

        # Fall back to config entry values if BLE reads failed
        if self.api_key is None and conf_api_key:
            self.api_key = conf_api_key
            _LOGGER.info("Using API key from configuration (BLE read not available)")
        if self.device_id is None and conf_device_id:
            self.device_id = conf_device_id
            _LOGGER.info("Using device ID from configuration (BLE read not available)")

    @staticmethod
    def _decode_api_key(data: bytes) -> str:
        """Decode 16 bytes into a UUID-formatted API key string."""
        hexmap = "0123456789abcdef"
        result = []
        for i, byte in enumerate(data):
            if i in (4, 6, 8, 10):
                result.append("-")
            result.append(hexmap[(byte & 0xF0) >> 4])
            result.append(hexmap[byte & 0x0F])
        return "".join(result)

    @staticmethod
    def _decode_device_id(data: bytes) -> str:
        """Decode 4 bytes (little-endian) into a hex device ID string."""
        hexmap = "0123456789abcdef"
        result = []
        for byte in reversed(data):
            result.append(hexmap[(byte & 0xF0) >> 4])
            result.append(hexmap[byte & 0x0F])
        return "".join(result)

    def _measurement_callback(self, sender: Any, data: bytearray) -> None:
        """Handle incoming measurement notifications from Powerpal.

        Observed packet format (20 bytes):
        - Bytes 0-3: Unix timestamp (uint32, little-endian)
        - Bytes 4-5: Pulse count in this interval (uint16, little-endian)
        - Bytes 6-19: Static device data (not measurement related)

        The Powerpal sends raw pulse counts (LED flashes detected on the
        meter). Power is derived using the configured pulses_per_kwh and
        the notification interval:
            power_watts = (pulses / pulses_per_kwh) * (3600 / interval_s) * 1000
        Energy per interval is simply:
            energy_kwh = pulses / pulses_per_kwh
        """
        _LOGGER.debug(
            "Raw measurement notification (%d bytes): %s",
            len(data),
            data.hex(),
        )

        if len(data) < 6:
            _LOGGER.warning(
                "Received short measurement data: %d bytes (%s)",
                len(data),
                data.hex(),
            )
            return

        # First 4 bytes: unix timestamp (little-endian)
        unix_time = struct.unpack_from("<I", data, 0)[0]

        # Bytes 4-5: pulse count in this notification interval (uint16, LE)
        pulses = struct.unpack_from("<H", data, 4)[0]

        # Convert pulses to instantaneous power (watts)
        # Each pulse represents (1 / pulses_per_kwh) kWh of energy.
        # The interval between notifications is notification_interval minutes.
        interval_seconds = self._notification_interval * 60
        power_watts = (pulses * 3600000) / (self._pulses_per_kwh * interval_seconds)

        _LOGGER.debug(
            "Parsed measurement: timestamp=%d, pulses=%d, "
            "calculated_power=%.1f W (pulses_per_kwh=%d, interval=%ds), "
            "extra_bytes=%s",
            unix_time,
            pulses,
            power_watts,
            self._pulses_per_kwh,
            interval_seconds,
            data[6:].hex() if len(data) > 6 else "none",
        )

        # Calculate energy consumed in this interval
        # Each pulse = 1/pulses_per_kwh kWh
        energy_kwh = pulses / self._pulses_per_kwh

        # Log timestamp diagnostics
        current_time = int(time.time())
        time_diff = current_time - unix_time
        if abs(time_diff) > 86400:
            _LOGGER.warning(
                "Powerpal timestamp significantly out of sync: device=%d, "
                "system=%d, diff=%d seconds. Device clock may need sync. "
                "Data will still be processed.",
                unix_time,
                current_time,
                time_diff,
            )

        self._last_timestamp = unix_time
        self.power = round(power_watts, 1)
        self.energy_total_kwh = round(self.energy_total_kwh + energy_kwh, 4)
        self.daily_energy_kwh = round(self.daily_energy_kwh + energy_kwh, 4)

        _LOGGER.info(
            "Powerpal measurement: pulses=%d, power=%.1f W, "
            "energy this interval: %.4f kWh, total: %.4f kWh, daily: %.4f kWh",
            pulses,
            self.power,
            energy_kwh,
            self.energy_total_kwh,
            self.daily_energy_kwh,
        )

        # Notify listeners on the event loop
        self.hass.loop.call_soon_threadsafe(self._notify_listeners)

        # Upload to API (non-blocking, scheduled on the event loop)
        if self._api_client and not self._api_client.disabled:
            energy_wh = energy_kwh * 1000  # Convert kWh to Wh
            self.hass.loop.call_soon_threadsafe(
                self.hass.async_create_background_task,
                self._api_client.upload_reading(unix_time, energy_wh),
                "powerpal_api_upload",
            )

    async def _disconnect(self) -> None:
        """Disconnect from the Powerpal."""
        self._connected = False
        if self._client:
            try:
                async with asyncio.timeout(5):
                    await self._client.disconnect()
            except (TimeoutError, BleakError, Exception):  # noqa: BLE001
                _LOGGER.debug("Error during disconnect (non-critical)")
            self._client = None

    def reset_daily_energy(self) -> None:
        """Reset the daily energy counter (called at midnight)."""
        self.daily_energy_kwh = 0.0
        self._notify_listeners()
