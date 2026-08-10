# Feature: powerpal-api-integration, Property 4: Upload Request Construction
# Feature: powerpal-api-integration, Property 5: Fetch Request Construction
"""Property-based tests for API client request construction."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from custom_components.powerpal_ble.api_client import PowerpalApiClient

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Generate UUID-format hex strings using builds (faster than from_regex)
_hex_chars = st.sampled_from("0123456789abcdef")


def _hex_block(length: int):
    """Generate a fixed-length hex string."""
    return st.text(_hex_chars, min_size=length, max_size=length)


api_key_strategy = st.builds(
    lambda a, b, c, d, e: f"{a}-{b}-{c}-{d}-{e}",
    _hex_block(8),
    _hex_block(4),
    _hex_block(4),
    _hex_block(4),
    _hex_block(12),
)

# Non-empty alphanumeric device IDs (4-16 chars)
_alnum_chars = st.sampled_from("0123456789abcdefghijklmnopqrstuvwxyz")
device_id_strategy = st.text(_alnum_chars, min_size=4, max_size=16)

timestamp_strategy = st.integers(min_value=1, max_value=2**31)

watt_hours_strategy = st.floats(
    min_value=0.0, max_value=10000.0, allow_nan=False, allow_infinity=False
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_session():
    """Create a mock aiohttp session that captures request details."""
    mock_session = MagicMock()

    # Mock response for POST (upload)
    mock_post_response = MagicMock()
    mock_post_response.status = 200
    mock_post_response.__aenter__ = AsyncMock(return_value=mock_post_response)
    mock_post_response.__aexit__ = AsyncMock(return_value=False)
    mock_session.post = MagicMock(return_value=mock_post_response)

    # Mock response for GET (fetch)
    mock_get_response = MagicMock()
    mock_get_response.status = 200
    mock_get_response.json = AsyncMock(return_value=[])
    mock_get_response.__aenter__ = AsyncMock(return_value=mock_get_response)
    mock_get_response.__aexit__ = AsyncMock(return_value=False)
    mock_session.get = MagicMock(return_value=mock_get_response)

    return mock_session


# ---------------------------------------------------------------------------
# Property 4: Upload Request Construction
# ---------------------------------------------------------------------------


@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    deadline=None,
)
@given(
    api_key=api_key_strategy,
    device_id=device_id_strategy,
    timestamp=timestamp_strategy,
    watt_hours=watt_hours_strategy,
)
@pytest.mark.asyncio
async def test_upload_request_construction(
    api_key: str,
    device_id: str,
    timestamp: int,
    watt_hours: float,
) -> None:
    """Property 4: Upload Request Construction.

    **Validates: Requirements 3.2, 3.3, 3.4, 5.2, 5.3, 5.4**

    For any valid API key, device ID, timestamp (positive integer), and
    watt_hours value (float >= 0), the upload request SHALL:
    - use the URL https://readings.powerpal.net/api/v1/meter_reading/{device_id}
    - set the Authorization header to the exact API key string
    - use HTTP POST method
    - include a JSON body as an array containing a reading object with
      timestamp as an integer and watt_hours as a numeric value.
    """
    mock_session = _make_mock_session()

    client = PowerpalApiClient(
        session=mock_session,
        api_key=api_key,
        device_id=device_id,
    )

    result = await client.upload_reading(timestamp, watt_hours)

    # Should succeed with 200 mock
    assert result is True

    # Verify POST was called exactly once
    mock_session.post.assert_called_once()

    call_kwargs = mock_session.post.call_args
    args = call_kwargs.args if call_kwargs.args else ()
    kwargs = call_kwargs.kwargs if call_kwargs.kwargs else {}

    # URL: first positional arg or 'url' kwarg
    actual_url = args[0] if args else kwargs.get("url")
    expected_url = f"https://readings.powerpal.net/api/v1/meter_reading/{device_id}"
    assert actual_url == expected_url, f"Expected URL {expected_url}, got {actual_url}"

    # Authorization header must be the exact API key
    actual_headers = kwargs.get("headers", {})
    assert "Authorization" in actual_headers, (
        f"Authorization header missing. Headers: {actual_headers}"
    )
    assert actual_headers["Authorization"] == api_key, (
        f"Expected Authorization '{api_key}', got '{actual_headers['Authorization']}'"
    )

    # JSON body must be an array with a reading containing timestamp and watt_hours
    actual_json = kwargs.get("json", [])
    assert isinstance(actual_json, list), (
        f"JSON body should be a list, got {type(actual_json)}"
    )
    assert len(actual_json) == 1, f"Expected 1 reading in array, got {len(actual_json)}"
    reading = actual_json[0]
    assert "timestamp" in reading, "JSON reading missing 'timestamp' field"
    assert "watt_hours" in reading, "JSON reading missing 'watt_hours' field"
    assert reading["timestamp"] == timestamp, (
        f"Expected timestamp {timestamp}, got {reading['timestamp']}"
    )
    assert isinstance(reading["timestamp"], int), (
        f"timestamp should be int, got {type(reading['timestamp'])}"
    )
    assert reading["watt_hours"] == watt_hours, (
        f"Expected watt_hours {watt_hours}, got {reading['watt_hours']}"
    )
    assert isinstance(reading["watt_hours"], (int, float)), (
        f"watt_hours should be numeric, got {type(reading['watt_hours'])}"
    )


# ---------------------------------------------------------------------------
# Property 5: Fetch Request Construction
# ---------------------------------------------------------------------------


@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    deadline=None,
)
@given(
    api_key=api_key_strategy,
    device_id=device_id_strategy,
)
@pytest.mark.asyncio
async def test_fetch_request_construction(
    api_key: str,
    device_id: str,
) -> None:
    """Property 5: Fetch Request Construction.

    **Validates: Requirements 5.5**

    For any valid device ID and date range, the historical fetch request SHALL:
    - use the URL https://readings.powerpal.net/api/v1/device/{device_id}/readings
      with start and end query parameters
    - set the Authorization header to the API key
    - use HTTP GET method.
    """
    mock_session = _make_mock_session()

    client = PowerpalApiClient(
        session=mock_session,
        api_key=api_key,
        device_id=device_id,
    )

    result = await client.fetch_historical_readings(days=365)

    # Should return empty list from the mock (200 with empty JSON array)
    assert result == []

    # Verify GET was called exactly once
    mock_session.get.assert_called_once()

    call_kwargs = mock_session.get.call_args
    args = call_kwargs.args if call_kwargs.args else ()
    kwargs = call_kwargs.kwargs if call_kwargs.kwargs else {}

    # URL: first positional arg or 'url' kwarg
    actual_url = args[0] if args else kwargs.get("url")
    expected_url = f"https://readings.powerpal.net/api/v1/device/{device_id}/readings"
    assert actual_url == expected_url, f"Expected URL {expected_url}, got {actual_url}"

    # Authorization header must be the exact API key
    actual_headers = kwargs.get("headers", {})
    assert "Authorization" in actual_headers, (
        f"Authorization header missing. Headers: {actual_headers}"
    )
    assert actual_headers["Authorization"] == api_key, (
        f"Expected Authorization '{api_key}', got '{actual_headers['Authorization']}'"
    )

    # Query parameters must include 'start' and 'end'
    actual_params = kwargs.get("params", {})
    assert "start" in actual_params, (
        f"Query params missing 'start'. Params: {actual_params}"
    )
    assert "end" in actual_params, (
        f"Query params missing 'end'. Params: {actual_params}"
    )

    # start and end should be non-empty strings (ISO 8601 format)
    assert (
        isinstance(actual_params["start"], str) and len(actual_params["start"]) > 0
    ), f"'start' param should be a non-empty string, got: {actual_params['start']}"
    assert isinstance(actual_params["end"], str) and len(actual_params["end"]) > 0, (
        f"'end' param should be a non-empty string, got: {actual_params['end']}"
    )


# ---------------------------------------------------------------------------
# Feature: powerpal-api-integration, Property 6: 401 Response Disables Further Uploads
# Feature: powerpal-api-integration, Property 7: Non-Retryable HTTP Errors Are Logged and Discarded
# Feature: powerpal-api-integration, Property 8: 2xx Responses Mark Operations Successful
# ---------------------------------------------------------------------------

import logging

# ---------------------------------------------------------------------------
# Helpers for error handling tests
# ---------------------------------------------------------------------------


def _make_error_mock_session(status_code: int, headers=None, body: str = ""):
    """Create a mock aiohttp session returning a specific status code."""
    mock_session = MagicMock()
    mock_response = MagicMock()
    mock_response.status = status_code
    mock_response.headers = headers or {}
    mock_response.text = AsyncMock(return_value=body)
    mock_response.json = AsyncMock(return_value=[])
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=False)
    mock_session.post = MagicMock(return_value=mock_response)
    mock_session.get = MagicMock(return_value=mock_response)
    return mock_session


# ---------------------------------------------------------------------------
# Additional strategies for error handling tests
# ---------------------------------------------------------------------------

# Number of subsequent upload attempts after 401
subsequent_attempts = st.integers(min_value=1, max_value=5)

# Non-retryable HTTP error codes (excluding 401 and 429)
non_retryable_status_codes = st.sampled_from(
    [
        400,
        402,
        403,
        404,
        405,
        406,
        407,
        408,
        409,
        410,
        411,
        412,
        413,
        414,
        415,
        416,
        417,
        418,
        422,
        423,
        424,
        425,
        426,
        427,
        428,
        430,
        431,
        451,
        500,
        501,
        502,
        503,
        504,
        505,
        506,
        507,
        508,
        510,
        511,
    ]
)

# 2xx success status codes
success_status_codes = st.integers(min_value=200, max_value=299)


# ---------------------------------------------------------------------------
# Property 6: 401 Response Disables Further Uploads
# ---------------------------------------------------------------------------


@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    deadline=None,
)
@given(
    api_key=api_key_strategy,
    device_id=device_id_strategy,
    timestamp=timestamp_strategy,
    wh=watt_hours_strategy,
    num_subsequent=subsequent_attempts,
)
@pytest.mark.asyncio
async def test_401_response_disables_further_uploads(
    api_key: str,
    device_id: str,
    timestamp: int,
    wh: float,
    num_subsequent: int,
) -> None:
    """Property 6: 401 Response Disables Further Uploads.

    **Validates: Requirements 3.6**

    For any sequence of upload attempts where the API returns HTTP 401,
    the client SHALL set disabled = True after the first 401 response,
    and all subsequent calls to upload_reading SHALL return immediately
    without making HTTP requests.
    """
    # Create client with a session that returns 401
    session_401 = _make_error_mock_session(401)
    client = PowerpalApiClient(session_401, api_key, device_id)

    # First upload triggers the 401
    result = await client.upload_reading(timestamp, wh)

    # After 401, client must be disabled
    assert client.disabled is True
    assert result is False

    # Record the call count after first 401
    post_calls_after_401 = session_401.post.call_count

    # Now make subsequent upload attempts - they should NOT make HTTP calls
    for i in range(num_subsequent):
        result = await client.upload_reading(timestamp + i + 1, wh)
        assert result is False

    # No additional HTTP calls should have been made
    assert session_401.post.call_count == post_calls_after_401


# ---------------------------------------------------------------------------
# Property 7: Non-Retryable HTTP Errors Are Logged and Discarded
# ---------------------------------------------------------------------------


@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    deadline=None,
)
@given(
    api_key=api_key_strategy,
    device_id=device_id_strategy,
    timestamp=timestamp_strategy,
    wh=watt_hours_strategy,
    status_code=non_retryable_status_codes,
)
@pytest.mark.asyncio
async def test_non_retryable_http_errors_logged_and_discarded(
    api_key: str,
    device_id: str,
    timestamp: int,
    wh: float,
    status_code: int,
    caplog,
) -> None:
    """Property 7: Non-Retryable HTTP Errors Are Logged and Discarded.

    **Validates: Requirements 3.8, 5.6**

    For any HTTP response status code in the set {400, 402, 403, 404, ...428,
    430..499, 500..599} (excluding 401 and 429), the API client SHALL log a
    warning containing the status code and SHALL not retry the operation.
    """
    session = _make_error_mock_session(status_code, body=f"Error {status_code}")
    client = PowerpalApiClient(session, api_key, device_id)

    with caplog.at_level(logging.WARNING):
        result = await client.upload_reading(timestamp, wh)

    # Operation should fail (not successful)
    assert result is False

    # Client should NOT be disabled (only 401 disables)
    assert client.disabled is False

    # Should have logged a warning containing the status code
    assert any(str(status_code) in record.message for record in caplog.records), (
        f"Expected a log message containing status code {status_code}, "
        f"but got: {[r.message for r in caplog.records]}"
    )

    # Should NOT have retried - only 1 POST call made
    assert session.post.call_count == 1


# ---------------------------------------------------------------------------
# Property 8: 2xx Responses Mark Operations Successful
# ---------------------------------------------------------------------------


@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    deadline=None,
)
@given(
    api_key=api_key_strategy,
    device_id=device_id_strategy,
    timestamp=timestamp_strategy,
    wh=watt_hours_strategy,
    status_code=success_status_codes,
)
@pytest.mark.asyncio
async def test_2xx_responses_mark_operations_successful(
    api_key: str,
    device_id: str,
    timestamp: int,
    wh: float,
    status_code: int,
) -> None:
    """Property 8: 2xx Responses Mark Operations Successful.

    **Validates: Requirements 5.8**

    For any HTTP response with a status code in the range 200-299,
    the API client SHALL treat the operation as successful
    (upload_reading returns True).
    """
    session = _make_error_mock_session(status_code)
    client = PowerpalApiClient(session, api_key, device_id)

    result = await client.upload_reading(timestamp, wh)

    # Any 2xx should be treated as success
    assert result is True

    # Client should not be disabled
    assert client.disabled is False

    # Exactly one POST call should have been made
    assert session.post.call_count == 1
