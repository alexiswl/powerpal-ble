"""Smoke test to verify test infrastructure works."""

from custom_components.powerpal_ble.const import DOMAIN


def test_domain_constant():
    """Verify the integration domain is correct."""
    assert DOMAIN == "powerpal_ble"
