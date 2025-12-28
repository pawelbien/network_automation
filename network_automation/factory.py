"""
Device client factory.
"""

from network_automation.vendors.mikrotik.client import Mikrotik


def get_client(platform: str, **kwargs):
    """Return device client for given platform."""
    platform = platform.lower()

    if platform == "mikrotik":
        return Mikrotik(**kwargs)

    raise ValueError(f"Unsupported platform: {platform}")
