# network_automation/platforms/huawei_vrp/flash.py

"""
Huawei VRP flash space calculation and cleanup.

Runs before the file transfer phase: computes required_space for the
target firmware/patch, and if free flash space is insufficient, deletes
delete-candidate files (orphaned .cc/.pat, backup image) to free room —
never protected files (startup_image, next_startup_image, startup_patch,
next_startup_patch of the current unit — this also covers the currently
running firmware/patch, since those are always the startup_image/
startup_patch) nor anything else.
"""

from pathlib import Path

from network_automation.platforms.huawei_vrp.cli_errors import _check_cli_output
from network_automation.platforms.huawei_vrp.debug_log import debug_log
from network_automation.platforms.huawei_vrp.info import get_flash_info
from network_automation.platforms.huawei_vrp.version import (
    OPERATION_FIRMWARE_AND_PATCH,
    OPERATION_FIRMWARE_ONLY,
    OPERATION_PATCH_ONLY,
)

DEFAULT_SAFETY_MARGIN = 50 * 1024 * 1024  # 50 MB, per spec minimum


def calculate_required_space(
    target_cc_size: int,
    target_pat_size: int,
    flash_files: list[dict],
    *,
    target_cc_name: str | None = None,
    target_pat_name: str | None = None,
    safety_margin: int = DEFAULT_SAFETY_MARGIN,
) -> int:
    """
    required_space = target_cc_size + target_pat_size + safety_margin +
    temporary_overwrite_margin.

    temporary_overwrite_margin accounts for a same-named file already on
    flash needing to coexist with the newly-uploaded one during transfer/
    verification — sized as the size of whichever target file(s) already
    exist on flash under the target's exact filename.
    """
    existing_by_name = {f["name"]: f["size"] for f in flash_files if not f["is_dir"]}

    overwrite_margin = 0
    if target_cc_name and target_cc_name in existing_by_name:
        overwrite_margin += existing_by_name[target_cc_name]
    if target_pat_name and target_pat_name in existing_by_name:
        overwrite_margin += existing_by_name[target_pat_name]

    return target_cc_size + target_pat_size + safety_margin + overwrite_margin


def _delete_file(client, filename: str) -> None:
    """
    Delete flash:/<filename>, confirming the interactive [Y/N] prompt.

    - no connect/disconnect
    - raises RuntimeError if VRP rejects the deletion (e.g. the file is
      still referenced by startup config: "Error: This is system startup
      file" — verified against real device output) or otherwise doesn't
      report success
    """
    command = f"delete flash:/{filename}"
    debug_log(client, "send_command_timing: %s", command)
    output = client.conn.send_command_timing(command)
    debug_log(client, "send_command_timing response: %s", output)

    for _ in range(3):
        if "y/n" not in output.lower():
            break
        debug_log(client, "send_command_timing: %s", "y")
        output = client.conn.send_command_timing("y")
        debug_log(client, "send_command_timing response: %s", output)

    if "succeeded" not in output.lower():
        raise RuntimeError(f"Failed to delete flash:/{filename}: {output!r}")


def cleanup_flash(
    client,
    *,
    flash_files: list[dict],
    protected_names: set[str],
    startup_image_name: str,
    backup_image_name: str | None,
) -> list[str]:
    """
    Free flash space by deleting delete-candidates: orphaned .cc/.pat files
    and the configured backup image, if any — never `protected_names`.

    Deleting a file still configured as "Backup system software for next
    startup" is rejected by VRP ("Error: This is system startup file"); to
    free it, first re-point the backup slot at the current startup image
    (`startup system-software <filename> backup` — bare filename, no
    flash:/ prefix, verified against real device output; the device
    reports this as a multi-minute operation), which is always safe since
    that file is itself protected. Then delete the now-unreferenced old
    backup file like any other candidate.

    - no connect/disconnect
    - raises RuntimeError if any delete is rejected
    - returns the list of filenames actually deleted, in deletion order
      (Faza 13 — feeds result.metadata["deleted_files"] for the operation
      report)
    """
    candidates = [
        f["name"] for f in flash_files
        if not f["is_dir"]
        and f["name"] not in protected_names
        and (f["name"].endswith(".cc") or f["name"].endswith(".pat"))
    ]

    if backup_image_name and backup_image_name in candidates:
        command = f"startup system-software {startup_image_name} backup"
        debug_log(client, "send_command: %s", command)
        ack = client.conn.send_command(command, read_timeout=300)
        debug_log(client, "send_command response: %s", ack)
        _check_cli_output(command, ack)

    for filename in candidates:
        _delete_file(client, filename)

    debug_log(client, "send_command_timing: %s", "reset recycle-bin")
    output = client.conn.send_command_timing("reset recycle-bin")
    debug_log(client, "send_command_timing response: %s", output)
    for _ in range(3):
        if "y/n" not in output.lower():
            break
        debug_log(client, "send_command_timing: %s", "y")
        output = client.conn.send_command_timing("y")
        debug_log(client, "send_command_timing response: %s", output)

    return candidates


def ensure_flash_space(
    client, result, operation_type: str, units: list[dict], *, dry_run: bool = False,
) -> None:
    """
    Compute required_space for the files `operation_type` needs, and if
    free flash space is insufficient, run cleanup_flash() and recheck.

    Records result.metadata["flash_required_bytes"], ["flash_free_bytes"],
    and ["flash_cleanup_performed"]/["deleted_files"] (both only set when
    cleanup actually ran — Faza 13).

    dry_run=True (Faza 14): if cleanup would be needed, records
    result.metadata["flash_cleanup_would_run"] = True instead of calling
    cleanup_flash() (which deletes files) — no RuntimeError is raised in
    this case, since dry-run only reports a plan, it doesn't attempt to
    prove the plan is feasible without actually deleting anything.

    Raises RuntimeError if space is still insufficient after cleanup (not
    in dry-run mode) — always before any upload.

    - no connect/disconnect
    """
    target_cc_size = target_cc_name = None
    if operation_type in (OPERATION_FIRMWARE_ONLY, OPERATION_FIRMWARE_AND_PATCH):
        firmware_path = Path(client.firmware_file)
        target_cc_size = firmware_path.stat().st_size
        target_cc_name = firmware_path.name

    target_pat_size = target_pat_name = None
    if operation_type in (OPERATION_PATCH_ONLY, OPERATION_FIRMWARE_AND_PATCH):
        patch_path = Path(client.patch_file)
        target_pat_size = patch_path.stat().st_size
        target_pat_name = patch_path.name

    flash_info = get_flash_info(client)
    required = calculate_required_space(
        target_cc_size or 0, target_pat_size or 0, flash_info["files"],
        target_cc_name=target_cc_name, target_pat_name=target_pat_name,
    )
    result.metadata["flash_required_bytes"] = required
    result.metadata["flash_free_bytes"] = flash_info["free_bytes"]

    if required <= flash_info["free_bytes"]:
        return

    master = units[0]
    protected_names = {
        name.removeprefix("flash:/") for name in (
            master.get("startup_image"),
            master.get("next_startup_image"),
            master.get("startup_patch"),
            master.get("next_startup_patch"),
        ) if name
    }
    backup_image = master.get("backup_image")
    backup_image_name = backup_image.removeprefix("flash:/") if backup_image else None
    startup_image_name = (master.get("startup_image") or "").removeprefix("flash:/")

    client.logger.info(
        "Insufficient flash space (%d bytes free, %d required) — running cleanup",
        flash_info["free_bytes"], required,
    )

    if dry_run:
        result.metadata["flash_cleanup_would_run"] = True
        return

    deleted = cleanup_flash(
        client,
        flash_files=flash_info["files"],
        protected_names=protected_names,
        startup_image_name=startup_image_name,
        backup_image_name=backup_image_name,
    )
    result.metadata["flash_cleanup_performed"] = True
    result.metadata["deleted_files"] = deleted

    flash_info = get_flash_info(client)
    result.metadata["flash_free_bytes"] = flash_info["free_bytes"]

    if required > flash_info["free_bytes"]:
        raise RuntimeError(
            f"Insufficient flash space after cleanup: need {required} bytes, "
            f"only {flash_info['free_bytes']} bytes free."
        )
