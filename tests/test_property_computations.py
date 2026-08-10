"""Property-based tests for powerpal_ble computation functions."""

from hypothesis import given, settings, assume
import hypothesis.strategies as st

from custom_components.powerpal_ble.computations import compute_power_w, compute_watt_hours


# Feature: esphome-cloud-upload, Property 1: Power computation formula
class TestComputePowerW:
    """Property tests for compute_power_w."""

    # **Validates: Requirements 1.1, 1.3**

    @settings(max_examples=100)
    @given(
        pulses=st.integers(min_value=0, max_value=10000),
        pulses_per_kwh=st.integers(min_value=1, max_value=10000),
        interval_seconds=st.floats(min_value=0.1, max_value=86400),
    )
    def test_power_formula_matches_spec(
        self, pulses: int, pulses_per_kwh: int, interval_seconds: float
    ):
        """For any valid inputs, result equals (pulses / pulses_per_kwh) * (3600000 / interval_seconds)."""
        result = compute_power_w(pulses, pulses_per_kwh, interval_seconds)
        expected = (pulses / pulses_per_kwh) * (3600000 / interval_seconds)
        assert result == expected


# Feature: esphome-cloud-upload, Property 2: Watt-hours computation accuracy
class TestComputeWattHours:
    """Property tests for compute_watt_hours."""

    # **Validates: Requirements 2.5, 6.1**

    @settings(max_examples=100)
    @given(
        pulses=st.integers(min_value=0, max_value=10000),
        pulses_per_kwh=st.integers(min_value=1, max_value=10000),
    )
    def test_watt_hours_formula_matches_spec(
        self, pulses: int, pulses_per_kwh: int
    ):
        """For any valid inputs, result equals (pulses / pulses_per_kwh) * 1000.0."""
        result = compute_watt_hours(pulses, pulses_per_kwh)
        expected = (pulses / pulses_per_kwh) * 1000.0
        assert result == expected

    @settings(max_examples=100)
    @given(
        pulses=st.integers(min_value=1, max_value=10000),
        pulses_per_kwh=st.integers(min_value=1, max_value=10000),
    )
    def test_fractional_pulses_produce_fractional_watt_hours(
        self, pulses: int, pulses_per_kwh: int
    ):
        """Fractional pulse-to-kwh ratios produce fractional watt-hour values
        (floating-point division is used, not integer division)."""
        assume(pulses % pulses_per_kwh != 0)  # ensure non-integer division
        result = compute_watt_hours(pulses, pulses_per_kwh)
        # Floating-point division means result differs from integer-division result
        integer_div_result = (pulses // pulses_per_kwh) * 1000.0
        assert result != integer_div_result
