# network_automation/platforms/huawei_vrp/version.py

"""
Huawei VRP firmware version parsing and comparison.

Scope: firmware version only ("V300R024C00SPC100" style strings). Patch
version parsing ("SPH1b0" style) and the full operation-type decision matrix
are out of scope for this pass — see
engineering_handbook/tmp/huawei_vrp_update.txt for the target algorithm.
"""

import re

_FIRMWARE_RE = re.compile(r'^V(\d+)R(\d+)C\d+SPC(\d+)$', re.IGNORECASE)


def parse_firmware_version(software_version: str) -> tuple[int, int, int]:
    """
    Parse a VRP firmware version string into a comparable (major, release, spc) tuple.

    Example: "V300R024C00SPC100" -> (300, 24, 100)

    Versions are never compared as raw strings — raises ValueError on any
    string that doesn't match the expected format, rather than falling back
    to a best-effort comparison.
    """
    if not software_version:
        raise ValueError("Firmware version string is empty.")

    m = _FIRMWARE_RE.match(software_version.strip())
    if not m:
        raise ValueError(f"Unparseable firmware version: {software_version!r}")

    major, release, spc = m.groups()
    return (int(major), int(release), int(spc))


def is_firmware_newer(current: str, target: str) -> bool:
    """Return True if target firmware is strictly newer than current."""
    return parse_firmware_version(target) > parse_firmware_version(current)
