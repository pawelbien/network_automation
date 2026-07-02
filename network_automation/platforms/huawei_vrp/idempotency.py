# network_automation/platforms/huawei_vrp/idempotency.py

"""
Huawei VRP idempotency checks: before each state-changing step, check
whether it has already been completed, so re-running upgrade() after an
interruption is safe.

Each check is a Tier-1 style helper (no connect/disconnect) called from
upgrade.py immediately before the step it guards. Every skip must be
logged and recorded by the caller in result.metadata["skipped_steps"].
"""

from pathlib import Path

from network_automation.platforms.huawei_vrp.cli_errors import CLIError
from network_automation.platforms.huawei_vrp.info import get_file_md5, get_info, get_patch_info
from network_automation.platforms.huawei_vrp.upload import compute_local_md5
from network_automation.platforms.huawei_vrp.version import parse_patch_version


def file_already_on_flash(client, path: Path) -> tuple[bool, dict]:
    """
    Check whether `path.name` already exists on flash with content matching
    the local file (by MD5). Returns (already_present, md5_result), where
    md5_result has the same shape as upgrade.verify_md5()'s return value —
    this check doubles as that file's MD5 verification when upload is
    skipped, since re-verifying an MD5 we just computed would be redundant.

    A missing file (get_file_md5 raises CLIError, e.g. "Error: file does
    not exist") means "not yet uploaded", not a failure — returns
    (False, ...) rather than propagating.

    Note: only checks MD5, not file size — a `dir` listing (Faza 7) would
    let this skip the MD5 command entirely when the size already disagrees,
    but MD5 alone is already sufficient proof of a byte-identical file.
    """
    expected_md5 = compute_local_md5(path)

    try:
        actual_md5 = get_file_md5(client, path.name)
    except CLIError:
        return False, {"expected_md5": expected_md5, "actual_md5": None, "match": False}

    match = actual_md5 == expected_md5
    return match, {"expected_md5": expected_md5, "actual_md5": actual_md5, "match": match}


def patch_already_active(client, expected_patch_version: str) -> bool:
    """
    Check whether `expected_patch_version` is already the active, running
    patch, so apply_patch() can be skipped.
    """
    patch_info = get_patch_info(client)

    if (patch_info["state"] or "").lower() != "running":
        return False

    current = patch_info["patch_version"]
    if current is None:
        return False

    return parse_patch_version(current) == parse_patch_version(expected_patch_version)


def already_running_target(
    client,
    target_firmware: str,
    target_patch: str | None,
) -> bool:
    """
    Fresh check of whether the device is already running target_firmware
    (and target_patch, if requested), so reboot() can be skipped and the
    workflow can proceed straight to post-reboot validation. Always does a
    live re-read (not reused from earlier in the run) since this guards
    the single most disruptive step (reboot) against external interference
    or a previously-interrupted run that already completed it.
    """
    info = get_info(client)
    current_firmware = info["units"][0]["software_version"]

    if current_firmware != target_firmware:
        return False

    if target_patch:
        current_patch = get_patch_info(client)["patch_version"]
        if current_patch is None or parse_patch_version(current_patch) != parse_patch_version(target_patch):
            return False

    return True
