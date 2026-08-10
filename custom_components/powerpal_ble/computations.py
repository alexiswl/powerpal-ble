"""Pure computation functions for Powerpal energy calculations."""


def compute_power_w(pulses: int, pulses_per_kwh: int, interval_seconds: float) -> float:
    """Compute instantaneous power in watts.

    Formula: (pulses / pulses_per_kwh) * (3600000 / interval_seconds)

    Args:
        pulses: Number of pulses in the interval (>= 0).
        pulses_per_kwh: Device calibration value (> 0).
        interval_seconds: Time interval in seconds (> 0).

    Returns:
        Power in watts.
    """
    return (pulses / pulses_per_kwh) * (3600000 / interval_seconds)


def compute_watt_hours(pulses: int, pulses_per_kwh: int) -> float:
    """Compute energy in watt-hours from pulse count.

    Formula: (pulses / pulses_per_kwh) * 1000.0

    Args:
        pulses: Number of pulses (>= 0).
        pulses_per_kwh: Device calibration value (> 0).

    Returns:
        Energy in watt-hours.
    """
    return (pulses / pulses_per_kwh) * 1000.0
