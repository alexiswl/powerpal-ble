# Feature: powerpal-api-integration, Property 10: Historical Import Deduplication
"""Property-based tests for historical data import deduplication.

The _fetch_historical function delegates deduplication to HA's async_import_statistics,
which upserts records by start timestamp. This test verifies that:
1. For N records from the API, exactly N StatisticData entries are passed to
   async_import_statistics, each with a unique timestamp.
2. The function correctly delegates deduplication responsibility to HA's recorder.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Generate a list of measurement records with unique timestamps
measurement_record_strategy = st.fixed_dictionaries(
    {
        "timestamp": st.integers(min_value=1_000_000_000, max_value=2_000_000_000),
        "watt_hours": st.floats(
            min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False
        ),
    }
)

# Lists of records with unique timestamps (1 to 50 records)
records_strategy = st.lists(
    measurement_record_strategy,
    min_size=1,
    max_size=50,
    unique_by=lambda r: r["timestamp"],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeStatisticData:
    """Lightweight fake for StatisticData capturing kwargs."""

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class FakeStatisticMetaData:
    """Lightweight fake for StatisticMetaData capturing kwargs."""

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


def _make_mock_hass():
    """Create a minimal mock HomeAssistant instance."""
    return MagicMock()


def _make_mock_api_client(records: list[dict]):
    """Create a mock API client that returns the given records."""
    mock_client = MagicMock()
    mock_client.fetch_historical_readings = AsyncMock(return_value=records)
    return mock_client


def _make_mock_entry():
    """Create a mock config entry."""
    mock_entry = MagicMock()
    mock_entry.entry_id = "test_entry_id"
    mock_entry.title = "Test Powerpal"
    return mock_entry


# ---------------------------------------------------------------------------
# Property 10: Historical Import Deduplication
# ---------------------------------------------------------------------------


@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    deadline=None,
)
@given(records=records_strategy)
@pytest.mark.asyncio
async def test_historical_import_deduplication(records: list[dict]) -> None:
    """Property 10: Historical Import Deduplication.

    **Validates: Requirements 4.4**

    For any set of historical measurement records with unique timestamps,
    importing SHALL pass all records to async_import_statistics — the count
    of StatisticData entries SHALL equal the total number of records, and each
    entry SHALL have a unique start timestamp. HA's recorder handles the actual
    deduplication internally (upsert by start timestamp), so the integration
    correctly delegates this responsibility.
    """
    mock_hass = _make_mock_hass()
    mock_api_client = _make_mock_api_client(records)
    mock_entry = _make_mock_entry()

    # Set up fake recorder modules in sys.modules so that the local import
    # inside _fetch_historical resolves correctly.
    mock_import_statistics = MagicMock()

    recorder_stats_mod = MagicMock()
    recorder_stats_mod.async_import_statistics = mock_import_statistics

    recorder_models_mod = MagicMock()
    recorder_models_mod.StatisticData = FakeStatisticData
    recorder_models_mod.StatisticMetaData = FakeStatisticMetaData

    recorder_mod = MagicMock()

    with patch.dict(
        sys.modules,
        {
            "homeassistant.components.recorder": recorder_mod,
            "homeassistant.components.recorder.statistics": recorder_stats_mod,
            "homeassistant.components.recorder.models": recorder_models_mod,
        },
    ):
        from custom_components.powerpal_ble import _fetch_historical

        await _fetch_historical(mock_hass, mock_api_client, mock_entry)

    # Verify async_import_statistics was called once
    mock_import_statistics.assert_called_once()

    call_args = mock_import_statistics.call_args
    # async_import_statistics(hass, metadata, statistics_data)
    positional = call_args.args if call_args.args else ()
    assert len(positional) == 3, (
        f"Expected 3 positional args (hass, metadata, stats), got {len(positional)}"
    )

    _, _metadata, statistics_data = positional

    # Property: count of imported records equals count of input records
    assert len(statistics_data) == len(records), (
        f"Expected {len(records)} StatisticData entries, got {len(statistics_data)}"
    )

    # Property: all timestamps are unique (no duplicates passed to import)
    timestamps = [sd.start for sd in statistics_data]
    assert len(set(timestamps)) == len(timestamps), (
        f"Expected all unique timestamps, but found duplicates in {timestamps}"
    )

    # Property: timestamps correspond to the input records
    expected_timestamps = {
        datetime.fromtimestamp(r["timestamp"], tz=UTC) for r in records
    }
    actual_timestamps = set(timestamps)
    assert actual_timestamps == expected_timestamps, (
        f"Timestamp mismatch.\n"
        f"Expected: {sorted(expected_timestamps)}\n"
        f"Actual: {sorted(actual_timestamps)}"
    )
