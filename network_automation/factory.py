"""
Device client factory.
"""

from network_automation.platforms.mikrotik_routeros.client import MikrotikRouterOS


def get_client(platform: str, **kwargs):
    """Return device client for given platform."""
    platform = platform.lower()

    if platform == "mikrotik_routeros":
        return MikrotikRouterOS(**kwargs)

    raise ValueError(f"Unsupported platform: {platform}")
