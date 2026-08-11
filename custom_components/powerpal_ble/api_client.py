"""Async client for the Powerpal readings API."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)


class PowerpalApiClient:
    """Async client for the Powerpal readings API."""

    BASE_URL = "https://readings.powerpal.net/api/v1/"
    DEFAULT_TIMEOUT = 30  # seconds per request
    UPLOAD_TIMEOUT = 10  # seconds for upload specifically

    def __init__(
        self,
        session: aiohttp.ClientSession,
        api_key: str,
        device_id: str,
    ) -> None:
        """Initialize the API client.

        Args:
            session: An aiohttp client session (typically HA's shared session).
            api_key: The Powerpal API key used for Authorization header.
            device_id: The Powerpal device identifier.
        """
        self._session = session
        self._api_key = api_key
        self._device_id = device_id
        self._disabled = False
        self._headers = {"Authorization": api_key}

    @property
    def disabled(self) -> bool:
        """True if client received 401 and should stop uploading."""
        return self._disabled

    async def upload_reading(self, timestamp: int, watt_hours: float) -> bool:  # pylint: disable=too-many-return-statements
        """Upload a single measurement. Returns True on success.

        Non-blocking from caller's perspective (caller uses create_task).
        Handles 401 by setting self.disabled = True.
        Handles 429 with retry-after backoff (max 3 retries).
        Logs warnings on other failures, never raises.
        """
        if self._disabled:
            return False

        try:
            url = f"{self.BASE_URL}meter_reading/{self._device_id}"
            payload = [
                {
                    "timestamp": timestamp,
                    "watt_hours": watt_hours,
                    "cost": 0,
                    "is_peak": False,
                }
            ]
            timeout = aiohttp.ClientTimeout(total=self.UPLOAD_TIMEOUT)

            max_retries = 3
            for attempt in range(max_retries + 1):
                try:
                    async with self._session.post(
                        url,
                        json=payload,
                        headers=self._headers,
                        timeout=timeout,
                    ) as resp:
                        if 200 <= resp.status < 300:
                            return True

                        if resp.status == 401:
                            _LOGGER.error(
                                "Powerpal API returned 401 Unauthorized. "
                                "API key may be invalid. Disabling uploads"
                            )
                            self._disabled = True
                            return False

                        if resp.status == 429:
                            if attempt >= max_retries:
                                _LOGGER.warning(
                                    "Powerpal API rate limited (429) after %d retries. "
                                    "Discarding measurement",
                                    max_retries,
                                )
                                return False
                            retry_after = resp.headers.get("Retry-After")
                            try:
                                wait_seconds = int(retry_after)
                            except (TypeError, ValueError):
                                wait_seconds = 60
                            _LOGGER.debug(
                                "Powerpal API rate limited (429). "
                                "Retrying after %d seconds (attempt %d/%d)",
                                wait_seconds,
                                attempt + 1,
                                max_retries,
                            )
                            await asyncio.sleep(wait_seconds)
                            continue

                        # Other 4xx/5xx errors
                        body = await resp.text()
                        _LOGGER.warning(
                            "Powerpal API upload failed with status %d: %s",
                            resp.status,
                            body[:500],
                        )
                        return False

                except (TimeoutError, aiohttp.ClientError) as err:
                    _LOGGER.warning(
                        "Powerpal API upload failed due to network error: %s",
                        err,
                    )
                    return False

        except Exception as err:  # noqa: BLE001  # pylint: disable=broad-exception-caught
            _LOGGER.warning("Unexpected error during Powerpal API upload: %s", err)
            return False

        return False

    async def fetch_historical_readings(self, days: int = 365) -> list[dict[str, Any]]:  # pylint: disable=too-many-return-statements
        """Fetch historical readings for the past N days.

        Returns list of {"timestamp": int, "watt_hours": float} dicts.
        Returns empty list on any failure (logs warning).
        """
        try:
            end = datetime.now(tz=UTC)
            start = end - timedelta(days=days)

            url = f"{self.BASE_URL}device/{self._device_id}/readings"
            params = {
                "start": start.isoformat(),
                "end": end.isoformat(),
            }
            timeout = aiohttp.ClientTimeout(total=self.DEFAULT_TIMEOUT)

            async with self._session.get(
                url,
                headers=self._headers,
                params=params,
                timeout=timeout,
            ) as resp:
                if resp.status in (401, 403):
                    _LOGGER.warning(
                        "Powerpal API returned %s fetching historical data: "
                        "invalid or expired credentials",
                        resp.status,
                    )
                    return []

                if resp.status >= 500:
                    _LOGGER.warning(
                        "Powerpal API server error %s fetching historical data",
                        resp.status,
                    )
                    return []

                if resp.status >= 200 and resp.status < 300:
                    if not (data := await resp.json()):
                        return []
                    return [
                        {
                            "timestamp": int(record["timestamp"]),
                            "watt_hours": float(record["watt_hours"]),
                        }
                        for record in data
                    ]

                # Other non-success status codes
                _LOGGER.warning(
                    "Powerpal API returned unexpected status %s "
                    "fetching historical data",
                    resp.status,
                )
                return []

        except (TimeoutError, aiohttp.ClientError) as err:
            _LOGGER.warning("Network error fetching Powerpal historical data: %s", err)
            return []
        except Exception as err:  # noqa: BLE001  # pylint: disable=broad-exception-caught
            _LOGGER.warning(
                "Unexpected error fetching Powerpal historical data: %s", err
            )
            return []
