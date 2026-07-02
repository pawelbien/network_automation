# network_automation/platforms/huawei_vrp/validation.py

"""
Huawei VRP pre-upload input validation: firmware/patch filename format,
firmware-hardware compatibility, patch-firmware release compatibility, and
forced-downgrade warnings — see engineering_handbook/tmp/huawei_vrp_update.txt,
"Input validation" and "Forced downgrade".

Runs after determine_operation_type() has decided an operation is needed,
and before any upload. Pure checks against filenames/strings already known
to the caller — no connect/disconnect, no new device commands.
"""

import re
from pathlib import Path

from network_automation.platforms.huawei_vrp.version import (
    OPERATION_FIRMWARE_AND_PATCH,
    OPERATION_FIRMWARE_ONLY,
    OPERATION_PATCH_ONLY,
    is_firmware_older,
    is_patch_older,
    parse_firmware_version,
)

_FIRMWARE_FILENAME_RE = re.compile(r'.+\.cc$', re.IGNORECASE)
_PATCH_FILENAME_RE = re.compile(r'.+\.pat$', re.IGNORECASE)

# Matches the '<platform>_V<major>R<release>C<counter>SPC<spc>.cc' naming
# convention (e.g. "AR650A_V300R024C00SPC200.cc"); filenames that don't
# follow it skip the hardware-compatibility check entirely rather than
# failing on an unrecognized scheme.
_FIRMWARE_STRUCTURED_RE = re.compile(
    r'^([A-Za-z0-9]+)_V\d+R\d+C\d+SPC\d+\.cc$', re.IGNORECASE
)

# Matches '<platform>_V<major>R<release>SPH<branch><letter><number>.pat'
# (e.g. "AR650A_V300R024SPH1b0.pat"); same best-effort skip otherwise.
_PATCH_STRUCTURED_RE = re.compile(
    r'^[A-Za-z0-9]+_V(\d+)R(\d+)SPH\d+[A-Za-z]\d+\.pat$', re.IGNORECASE
)

_LEADING_ALPHA_RE = re.compile(r'^[A-Za-z]+')


def _validate_firmware_filename(filename: str) -> None:
    """Raise ValueError unless filename ends in '.cc'."""
    if not _FIRMWARE_FILENAME_RE.match(filename):
        raise ValueError(
            f"Invalid firmware filename: {filename!r}; expected a '*.cc' file."
        )


def _validate_patch_filename(filename: str) -> None:
    """Raise ValueError unless filename ends in '.pat'."""
    if not _PATCH_FILENAME_RE.match(filename):
        raise ValueError(
            f"Invalid patch filename: {filename!r}; expected a '*.pat' file."
        )


def _platform_family(token: str) -> str | None:
    """Leading alphabetic run of `token`, e.g. 'AR650A' -> 'AR'. None if none."""
    m = _LEADING_ALPHA_RE.match(token)
    return m.group(0).upper() if m else None


def validate_firmware_hardware_compatibility(firmware_filename: str, unit_model: str) -> None:
    """
    Best-effort check that `firmware_filename` was built for the same
    hardware family as `unit_model` (e.g. firmware "AR650A_..." vs. unit
    model "AR651" -> family "AR" on both sides — same platform line, so
    compatible even though the specific SKU digits differ). Only runs when
    the filename matches the expected naming convention; otherwise there's
    nothing to compare and the check is skipped, not failed.

    Raises ValueError when the extracted platform families disagree.
    """
    m = _FIRMWARE_STRUCTURED_RE.match(firmware_filename)
    if not m:
        return

    fw_family = _platform_family(m.group(1))
    model_family = _platform_family(unit_model)

    if fw_family and model_family and fw_family != model_family:
        raise ValueError(
            f"Firmware {firmware_filename!r} appears built for hardware "
            f"family {fw_family!r}, but target unit reports model "
            f"{unit_model!r} (family {model_family!r})."
        )


def validate_patch_firmware_compatibility(patch_filename: str, target_firmware: str) -> None:
    """
    Best-effort check that a patch's embedded release train (major, release)
    matches the target firmware's. Only runs when the patch filename matches
    the expected naming convention and the target firmware version is
    parseable; otherwise skipped.

    Raises ValueError on a release-train mismatch.
    """
    m = _PATCH_STRUCTURED_RE.match(patch_filename)
    if not m:
        return

    patch_major, patch_release = int(m.group(1)), int(m.group(2))

    try:
        fw_major, fw_release, _ = parse_firmware_version(target_firmware)
    except ValueError:
        return

    if (patch_major, patch_release) != (fw_major, fw_release):
        raise ValueError(
            f"Patch {patch_filename!r} is built for release train "
            f"V{patch_major}R{patch_release}, but target firmware is "
            f"{target_firmware!r}."
        )


def validate_upgrade_inputs(client, *, unit_model: str, operation_type: str) -> None:
    """
    Run all pre-upload input validation for the files determine_operation_type
    decided are needed. Raises ValueError on any failure. Never touches the
    device — pure filename/string checks against already-known data.
    """
    needs_firmware = operation_type in (OPERATION_FIRMWARE_ONLY, OPERATION_FIRMWARE_AND_PATCH)
    needs_patch = operation_type in (OPERATION_PATCH_ONLY, OPERATION_FIRMWARE_AND_PATCH)

    if needs_firmware:
        firmware_filename = Path(client.firmware_file).name
        _validate_firmware_filename(firmware_filename)
        validate_firmware_hardware_compatibility(firmware_filename, unit_model)

    if needs_patch:
        patch_filename = Path(client.patch_file).name
        _validate_patch_filename(patch_filename)
        validate_patch_firmware_compatibility(patch_filename, client.firmware_version)


def warn_if_downgrade(
    client,
    current_firmware: str,
    target_firmware: str | None,
    current_patch: str | None,
    target_patch: str | None,
) -> bool:
    """
    Detect whether the operation determine_operation_type just approved is
    actually a downgrade — only reachable here if client.force_downgrade
    allowed it through instead of raising DowngradeRejectedError. Logs a
    warning (higher severity, per spec) and a best-effort note that
    configuration compatibility with the older release hasn't been
    automatically verified. Returns True if a downgrade was detected.
    """
    fw_downgrade = bool(target_firmware) and is_firmware_older(current_firmware, target_firmware)
    patch_downgrade = bool(target_patch) and is_patch_older(current_patch, target_patch)

    if not (fw_downgrade or patch_downgrade):
        return False

    client.logger.warning(
        "FORCED DOWNGRADE: current firmware=%s patch=%s -> target "
        "firmware=%s patch=%s. Configuration compatibility with the older "
        "release has not been automatically verified.",
        current_firmware, current_patch, target_firmware, target_patch,
    )
    return True
