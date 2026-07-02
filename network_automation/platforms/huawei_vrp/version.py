# network_automation/platforms/huawei_vrp/version.py

"""
Huawei VRP firmware and patch version parsing, comparison, and the
operation-type decision matrix — see
engineering_handbook/tmp/huawei_vrp_update.txt for the target algorithm.
"""

import re

_FIRMWARE_RE = re.compile(r'^V(\d+)R(\d+)C\d+SPC(\d+)$', re.IGNORECASE)

# Patch version is embedded in a larger device-reported string (e.g. the raw
# "ARV300R023SPH1b0" from `display patch-information`), so this searches for
# the SPH<branch><letter><number> substring rather than anchoring the whole
# string like _FIRMWARE_RE does.
_PATCH_RE = re.compile(r'SPH(\d+)([A-Za-z])(\d+)', re.IGNORECASE)

OPERATION_NONE = "NONE"
OPERATION_PATCH_ONLY = "PATCH_ONLY"
OPERATION_FIRMWARE_ONLY = "FIRMWARE_ONLY"
OPERATION_FIRMWARE_AND_PATCH = "FIRMWARE_AND_PATCH"


class DowngradeRejectedError(RuntimeError):
    """
    Raised by determine_operation_type() when a target firmware or patch
    version is older than what's currently running, and force_downgrade
    was not set. Subclasses RuntimeError for consistency with CLIError/
    DeviceBusyError; kept distinct so callers can special-case "downgrade
    attempted without explicit consent".
    """


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


def is_firmware_older(current: str, target: str) -> bool:
    """Return True if target firmware is strictly older than current (a downgrade)."""
    return parse_firmware_version(target) < parse_firmware_version(current)


def parse_patch_version(patch_version: str) -> tuple[int, int, int]:
    """
    Parse a VRP patch version string into a comparable
    (branch, build_letter_as_ordinal, build_number) tuple.

    Example: "SPH1b0" -> (1, 1, 0); the letter ordinal is 0-based (a=0, b=1, ...).

    The input may be the raw device-reported string, which embeds a release
    train prefix (e.g. "ARV300R023SPH1b0") — the SPH<branch><letter><number>
    substring is located anywhere in the string, not anchored.

    Versions are never compared as raw strings — raises ValueError on any
    string that doesn't contain a matching pattern, rather than falling back
    to a best-effort comparison.
    """
    if not patch_version:
        raise ValueError("Patch version string is empty.")

    m = _PATCH_RE.search(patch_version.strip())
    if not m:
        raise ValueError(f"Unparseable patch version: {patch_version!r}")

    branch, letter, number = m.groups()
    return (int(branch), ord(letter.lower()) - ord('a'), int(number))


def is_patch_newer(current: str | None, target: str) -> bool:
    """
    Return True if target patch is strictly newer than current.

    current=None means no patch is currently installed, which is always
    considered older than any parseable target.
    """
    if current is None:
        parse_patch_version(target)  # validate target; raises on bad format
        return True

    return parse_patch_version(target) > parse_patch_version(current)


def is_patch_older(current: str | None, target: str) -> bool:
    """
    Return True if target patch is strictly older than current (a downgrade).

    current=None means no patch is currently installed, which can never be
    a downgrade target — any parseable target is treated as new.
    """
    if current is None:
        parse_patch_version(target)  # validate target; raises on bad format
        return False

    return parse_patch_version(target) < parse_patch_version(current)


def determine_operation_type(
    current_firmware: str,
    target_firmware: str | None,
    current_patch: str | None,
    target_patch: str | None,
    *,
    force_downgrade: bool = False,
) -> str:
    """
    Decide which upgrade operation is required by comparing current vs.
    target firmware and patch versions.

    Decision matrix:
        firmware newer + patch newer  -> FIRMWARE_AND_PATCH
        firmware newer + no patch     -> FIRMWARE_ONLY
        same firmware + patch newer   -> PATCH_ONLY
        nothing newer, nothing older  -> NONE

    target_patch=None means no patch upgrade was requested — the patch
    comparison is skipped entirely (no ValueError from an unset target).

    A target that's strictly older than current (a downgrade) is never
    silently folded into NONE: it raises DowngradeRejectedError unless
    force_downgrade=True, in which case it's treated the same as "newer"
    for the purpose of deciding which operation to run.
    """
    fw_changed = False
    if target_firmware:
        if is_firmware_newer(current_firmware, target_firmware):
            fw_changed = True
        elif is_firmware_older(current_firmware, target_firmware):
            if not force_downgrade:
                raise DowngradeRejectedError(
                    f"Target firmware {target_firmware!r} is older than "
                    f"current {current_firmware!r}; refusing downgrade "
                    "unless force_downgrade=True."
                )
            fw_changed = True

    patch_changed = False
    if target_patch:
        if is_patch_newer(current_patch, target_patch):
            patch_changed = True
        elif is_patch_older(current_patch, target_patch):
            if not force_downgrade:
                raise DowngradeRejectedError(
                    f"Target patch {target_patch!r} is older than current "
                    f"{current_patch!r}; refusing downgrade unless "
                    "force_downgrade=True."
                )
            patch_changed = True

    if fw_changed and patch_changed:
        return OPERATION_FIRMWARE_AND_PATCH
    if fw_changed:
        return OPERATION_FIRMWARE_ONLY
    if patch_changed:
        return OPERATION_PATCH_ONLY
    return OPERATION_NONE
