# network_automation/platforms/huawei_vrp/upgrade.py

"""
Huawei VRP upgrade workflow (single-unit): firmware, patch, or both.

Covers version comparison, firmware/patch upload, MD5 verification,
startup configuration, hot patch apply, reboot, and post-reboot
verification.

Deliberately out of scope for this pass (tracked as follow-up work):
automatic rollback and multi-unit/stack upgrades.
"""

import time
from pathlib import Path

from network_automation.results import OperationResult
from network_automation.platforms.huawei_vrp.cli_errors import _check_cli_output
from network_automation.platforms.huawei_vrp.debug_log import debug_log, debug_timed_step
from network_automation.platforms.huawei_vrp.flash import ensure_flash_space
from network_automation.platforms.huawei_vrp.health_check import (
    run_pre_upgrade_health_check,
    get_ip_routing_table,
    collect_health_snapshot,
    compare_interfaces_to_baseline,
    compare_health_to_baseline,
    validate_routing_restored,
)
from network_automation.platforms.huawei_vrp.idempotency import (
    already_running_target,
    file_already_on_flash,
    patch_already_active,
)
from network_automation.platforms.huawei_vrp.lock import device_lock
from network_automation.platforms.huawei_vrp.info import get_info, get_patch_info, get_file_md5, _parse_startup
from network_automation.platforms.huawei_vrp.upload import upload_with_retry, compute_local_md5
from network_automation.platforms.huawei_vrp.validation import validate_upgrade_inputs, warn_if_downgrade
from network_automation.platforms.huawei_vrp.version import (
    determine_operation_type,
    parse_patch_version,
    OPERATION_NONE,
    OPERATION_PATCH_ONLY,
    OPERATION_FIRMWARE_AND_PATCH,
)


def configure_next_startup(client, filename: str):
    """
    Point the device's next-boot startup image at `filename` and verify it stuck.

    VRP itself warns this is slow ("Info: Start processing. The check may
    take a long time. Please wait...") — it re-verifies the whole firmware
    package. Observed to exceed Netmiko's ~10s default read_timeout for a
    162MB image (same failure mode as get_file_md5): the command actually
    succeeds on-device, but send_command() raises a false ReadTimeout
    first — read_timeout=300 matches the other known-slow VRP commands.

    - no connect/disconnect
    - raises RuntimeError if `display startup` doesn't reflect the change
    """
    client.logger.info(
        "Configuring next-boot startup image: flash:/%s (device "
        "re-verifies the whole package, can take a while)...",
        filename,
    )
    command = f"startup system-software flash:/{filename}"
    debug_log(client, "send_command: %s", command)
    ack = client.conn.send_command(command, read_timeout=300)
    debug_log(client, "send_command response: %s", ack)
    _check_cli_output(command, ack, expect_content=False)

    debug_log(client, "send_command: %s", "display startup")
    startup_output = client.conn.send_command("display startup")
    debug_log(client, "send_command response: %s", startup_output)
    _check_cli_output("display startup", startup_output)
    startup = _parse_startup(startup_output)
    master = startup.get("master", {})
    next_image = master.get("next_startup_image") or ""

    if not next_image.endswith(filename):
        raise RuntimeError(
            "Startup configuration verification failed: expected next "
            f"startup image to end with '{filename}', got {next_image!r}"
        )

    client.logger.info("Next-boot startup image set to flash:/%s", filename)


def configure_backup_startup(client, filename: str):
    """
    Point the device's backup startup image at `filename` and verify it stuck.

    Called during a firmware upgrade to preserve the firmware that was
    running *before* this upgrade as a fallback, in case the new image
    fails to boot. VRP has no equivalent "backup patch" slot — only the
    startup image can be backed up this way, so this is never called for
    patch-only operations and never touches the patch startup fields.

    Same slow on-device verification as configure_next_startup() — see
    that function's docstring for the read_timeout rationale.

    - no connect/disconnect
    - raises RuntimeError if `display startup` doesn't reflect the change
    """
    client.logger.info(
        "Configuring backup startup image: flash:/%s (device "
        "re-verifies the whole package, can take a while)...",
        filename,
    )
    command = f"startup system-software flash:/{filename} backup"
    debug_log(client, "send_command: %s", command)
    ack = client.conn.send_command(command, read_timeout=300)
    debug_log(client, "send_command response: %s", ack)
    _check_cli_output(command, ack, expect_content=False)

    debug_log(client, "send_command: %s", "display startup")
    startup_output = client.conn.send_command("display startup")
    debug_log(client, "send_command response: %s", startup_output)
    _check_cli_output("display startup", startup_output)
    startup = _parse_startup(startup_output)
    master = startup.get("master", {})
    backup_image = master.get("backup_image") or ""

    if not backup_image.endswith(filename):
        raise RuntimeError(
            "Backup startup configuration verification failed: expected "
            f"backup image to end with '{filename}', got {backup_image!r}"
        )

    client.logger.info("Backup startup image set to flash:/%s", filename)


def configure_next_startup_patch(client, filename: str):
    """
    Point the device's next-boot startup patch at `filename` and verify it stuck.

    Same slow on-device verification as configure_next_startup() — see the
    read_timeout note there.

    - no connect/disconnect
    - raises RuntimeError if `display startup` doesn't reflect the change
    """
    client.logger.info(
        "Configuring next-boot startup patch: flash:/%s (device "
        "re-verifies the package, can take a while)...",
        filename,
    )
    command = f"startup patch flash:/{filename}"
    debug_log(client, "send_command: %s", command)
    ack = client.conn.send_command(command, read_timeout=300)
    debug_log(client, "send_command response: %s", ack)
    _check_cli_output(command, ack, expect_content=False)

    debug_log(client, "send_command: %s", "display startup")
    startup_output = client.conn.send_command("display startup")
    debug_log(client, "send_command response: %s", startup_output)
    _check_cli_output("display startup", startup_output)
    startup = _parse_startup(startup_output)
    master = startup.get("master", {})
    next_patch = master.get("next_startup_patch") or ""

    if not next_patch.endswith(filename):
        raise RuntimeError(
            "Startup configuration verification failed: expected next "
            f"startup patch to end with '{filename}', got {next_patch!r}"
        )

    client.logger.info("Next-boot startup patch set to flash:/%s", filename)


def verify_md5(client, path: Path):
    """
    Verify that a file just uploaded to flash matches its local MD5.

    Computes the local file's MD5 (hashlib) and compares it against the
    device-reported MD5 (`display system file-md5 flash:/<file>`).

    - no connect/disconnect
    - raises RuntimeError on mismatch — MD5 verification is mandatory for
      every uploaded file
    """
    client.logger.info(
        "Verifying MD5 checksum for %s on-device (can take a while for "
        "large firmware files)...",
        path.name,
    )
    expected_md5 = compute_local_md5(path)
    actual_md5 = get_file_md5(client, path.name)

    if actual_md5 != expected_md5:
        raise RuntimeError(
            f"MD5 verification failed for {path.name}: expected "
            f"{expected_md5}, got {actual_md5}"
        )

    client.logger.info("MD5 verified for %s", path.name)
    return {"expected_md5": expected_md5, "actual_md5": actual_md5, "match": True}


def _verify_patch_active(client, expected_patch_version: str):
    """
    Read display patch-information and raise RuntimeError unless the patch
    is running and its version matches expected_patch_version.
    """
    patch_info = get_patch_info(client)
    state = (patch_info["state"] or "").lower()

    if state != "running":
        raise RuntimeError(
            "Patch verification failed: expected state 'Running', got "
            f"{patch_info['state']!r}"
        )

    current = patch_info["patch_version"]
    if current is None or parse_patch_version(current) != parse_patch_version(expected_patch_version):
        raise RuntimeError(
            "Patch verification failed: expected patch version matching "
            f"{expected_patch_version!r}, got {current!r}"
        )

    return patch_info


def apply_patch(client, filename: str, expected_patch_version: str):
    """
    Load and run a hot patch, then verify it's actually active.

    Same slow-verification risk as configure_next_startup() — read_timeout=300
    as a precaution, even though patches are typically much smaller than
    firmware images.

    - no connect/disconnect
    - raises RuntimeError if the patch isn't running or the version mismatches
    """
    client.logger.info(
        "Applying patch flash:/%s (device loads and activates the patch, "
        "can take a while)...",
        filename,
    )
    command = f"patch load flash:/{filename} all run"
    debug_log(client, "send_command: %s", command)
    ack = client.conn.send_command(command, read_timeout=300)
    debug_log(client, "send_command response: %s", ack)
    _check_cli_output(command, ack, expect_content=False)
    return _verify_patch_active(client, expected_patch_version)


def save_configuration(client, filename: str | None = None):
    """
    Save the running configuration, confirming any interactive [Y/N] prompt.

    filename — when given, saves to this device-side path instead of the
        existing startup configuration file (`save <filename>` instead of
        bare `save`). UNVERIFIED ON REAL HARDWARE: whether VRP accepts a
        `flash:/`-prefixed path here, and whether saving under an explicit
        filename repoints "next startup saved-configuration file"
        (`display startup`) as a side effect the way the no-filename form
        does not. Used by backup.py::run_backup() for named on-device
        snapshots; the existing no-filename call sites below are
        unaffected and their tested behavior is unchanged.

    VRP's "y" confirmation is followed by an asynchronous "It will take
    several minutes to save configuration file, please wait..." notice
    that can land *after* send_command_timing()'s idle-time heuristic has
    already decided the command is done (observed live: the notice arrived
    ~0.9s after the 2.0s idle window closed, well before the save itself
    was actually finished). The leftover text then sits unread until the
    *next* command's send_command() call, whose default auto_find_prompt()
    probe reads it and mistakes it for the current prompt — producing a
    search pattern that never matches again and hanging that next command
    for its full read_timeout.

    Confirming with an explicit expect_string instead waits for the real
    prompt to reappear (bounded by read_timeout, matching VRP's own
    "several minutes" warning) and — because auto_find_prompt() is only
    invoked when expect_string is None — never sends that risky probe in
    the first place, so nothing is left dangling for the next command to
    misread.

    The *initial* `save`/`save <filename>` send used send_command_timing()
    (the same blind idle-time heuristic) until a live failure (2026-07-12,
    a fourth device): the response came back completely empty — the
    device's "(y/n)" prompt hadn't arrived before send_command_timing()'s
    idle window closed, so this function saw no "y/n" in the (empty)
    output, assumed no confirmation was needed, and returned immediately
    — leaving the device sitting at an unanswered confirmation prompt.
    Every subsequent command then landed on that stuck prompt instead of a
    real command line, failing repeatedly with no way to self-resolve
    (confirmed live: 3 retries of the next command over ~35s, all
    identical failures) since nothing had actually gone wrong that a
    retry could wait out. Now uses the same send_command()+expect_string
    approach as reboot() for this same reason — see that method's
    docstring — for the initial send too, not just the "y" confirmation.

    - no connect/disconnect
    """
    command = f"save {filename}" if filename else "save"

    # This output is an interactive [Y/N] confirmation prompt (or, if none
    # is asked, the command prompt reappearing) — not command output to
    # validate, so the CLI-error check does not apply to this or the
    # confirmation loop below.
    debug_log(client, "send_command: %s", command)
    output = client.conn.send_command(
        command,
        expect_string=r"(?i)y/n|[\]>]",
        read_timeout=300,
        strip_prompt=False,
        strip_command=False,
    )
    debug_log(client, "send_command response: %s", output)

    for _ in range(3):
        if "y/n" not in output.lower():
            break
        debug_log(client, "send_command: %s", "y")
        output = client.conn.send_command(
            "y",
            expect_string=r"[\]>]",
            read_timeout=300,
            strip_prompt=False,
            strip_command=False,
        )
        debug_log(client, "send_command response: %s", output)


def _upload_pending(client, result, paths: list[Path]) -> dict:
    """
    Upload only the files in `paths` that aren't already on flash with a
    matching MD5 (idempotent resume after an interruption) — one batched
    upload_with_retry() call for whatever's still pending, matching prior
    behavior when nothing is skipped. Records each skip in
    result.metadata["skipped_steps"]. Returns {filename: md5_result}.
    """
    md5_results = {}
    pending = []

    for path in paths:
        already_present, md5_result = file_already_on_flash(client, path)
        if already_present:
            msg = f"{path.name} already on flash with matching MD5"
            client.logger.info("Skipping upload: %s", msg)
            result.metadata.setdefault("skipped_steps", {})[f"upload_{path.name}"] = msg
            md5_results[path.name] = md5_result
        else:
            pending.append(path)

    if pending:
        transfer_verification = upload_with_retry(
            client,
            files=pending,
            remote_dir="flash:/",
            timeout=client.upload_timeout,
            retries=client.upload_retries,
        )
        result.metadata.setdefault("transfer_verification", {}).update(transfer_verification)
        for path in pending:
            md5_results[path.name] = verify_md5(client, path)

    return md5_results


def upgrade(client, *, return_result: bool = False):
    """
    Run the upgrade workflow for a single-unit device: firmware, patch, or
    both, depending on determine_operation_type().

    Steps: connect, compare firmware/patch versions, then depending on the
    operation type:
    - NONE: skip.
    - PATCH_ONLY: upload patch, verify its MD5, hot-apply, verify, save
      configuration. Never touches the backup startup image — VRP has no
      "backup patch" concept.
    - FIRMWARE_ONLY: upload firmware, verify its MD5, configure next startup
      image, point the backup startup image at the firmware that was
      running before this upgrade, reboot, wait for reconnect, verify
      final firmware version.
    - FIRMWARE_AND_PATCH: upload firmware + patch, verify both MD5s,
      configure next startup image and patch, point the backup startup
      image at the pre-upgrade firmware, reboot, wait for reconnect,
      verify final firmware and patch, save configuration.

    Raises RuntimeError if the device reports more than one unit (stacks are
    not yet supported by this workflow), if an uploaded file's MD5 doesn't
    match the device-reported MD5, or if any other verification fails.
    Raises DowngradeRejectedError (a RuntimeError) if the target firmware or
    patch is older than what's currently running, unless client.force_downgrade
    is set — see version.py. Raises ValueError on malformed firmware/patch
    filenames or a hardware/release-train mismatch — see validation.py; this
    check runs after determine_operation_type() but before any upload.

    Acquires an exclusive, host-scoped lock (see lock.py) before doing
    anything else — including before validating arguments — so a second
    concurrent upgrade() against the same device aborts immediately with
    DeviceBusyError instead of racing this one.

    Idempotent: before each state-changing step (upload, apply_patch,
    configure_next_startup[_patch], configure_backup_startup, reboot)
    checks whether it's already done — see idempotency.py — so re-running
    after an interruption is safe. Every skipped step is logged and
    recorded in result.metadata["skipped_steps"].

    Before any upload: computes required flash space for the target files
    (see flash.py) and, if free space is insufficient, deletes candidate
    files (orphaned .cc/.pat, backup image — never protected or currently
    running files) and rechecks; raises RuntimeError if still insufficient.
    """
    with device_lock(client):
        if not client.firmware_version:
            raise ValueError("firmware_version is required for upgrade operation")
        if not client.firmware_file:
            raise ValueError("firmware_file is required for upgrade operation")
        if bool(client.patch_version) != bool(client.patch_file):
            raise ValueError(
                "patch_version and patch_file must be provided together"
            )
        if client.force_downgrade and not client.i_understand_downgrade_risk:
            raise ValueError(
                "force_downgrade=True requires i_understand_downgrade_risk=True "
                "as an explicit second confirmation."
            )
        if client.health_check_mode not in ("abort", "warn"):
            raise ValueError(
                "health_check_mode must be 'abort' or 'warn', got "
                f"{client.health_check_mode!r}"
            )

        result = OperationResult(
            success=True,
            operation="upgrade",
            metadata={
                "target_firmware": client.firmware_version,
                "target_patch": client.patch_version,
                "lock_acquired": True,
            },
        )

        result.mark_started()

        client.connect()
        try:
            info = get_info(client)
            units = info["units"]

            if len(units) != 1:
                raise RuntimeError(
                    "upgrade() only supports single-unit devices; found "
                    f"{len(units)} units. Stack/multi-unit upgrade is not yet "
                    "implemented."
                )

            current_version = units[0]["software_version"]
            result.metadata["current_firmware"] = current_version

            # Only read patch-information when a patch operation was requested,
            # so upgrade() issues no extra send_command() call otherwise.
            current_patch = None
            if client.patch_version:
                current_patch = get_patch_info(client)["patch_version"]
            result.metadata["current_patch"] = current_patch

            operation_type = determine_operation_type(
                current_version, client.firmware_version, current_patch, client.patch_version,
                force_downgrade=client.force_downgrade,
            )
            result.metadata["operation_type"] = operation_type

            if operation_type == OPERATION_NONE:
                msg = (
                    f"Skipping upgrade: current firmware {current_version} / "
                    f"patch {current_patch} already >= target"
                )
                client.logger.info(msg)

                result.message = msg
                result.metadata["skipped"] = True

                return result if return_result else None

            if warn_if_downgrade(
                client, current_version, client.firmware_version, current_patch, client.patch_version
            ):
                result.metadata["downgrade_forced"] = True

            with debug_timed_step(client, "run_pre_upgrade_health_check"):
                run_pre_upgrade_health_check(client, result, mode=client.health_check_mode)

            dry_run = client.context.dry_run

            # Explicit pre-upgrade backup, in addition to the existing
            # post-upgrade save — before any state-changing step below.
            # Skipped in dry-run (Faza 14): it's itself a state-changing
            # device command, not a read/validation/comparison step.
            if not dry_run:
                with debug_timed_step(client, "pre_upgrade_save_configuration"):
                    save_configuration(client)
                result.metadata["pre_upgrade_backup_performed"] = True

            validate_upgrade_inputs(
                client, unit_model=units[0]["model"], operation_type=operation_type
            )

            with debug_timed_step(client, "ensure_flash_space"):
                ensure_flash_space(client, result, operation_type, units, dry_run=dry_run)

            if dry_run:
                # All read/validation/comparison phases above already ran
                # normally (health check, version comparison, flash space
                # calculation, input validation) — only the plan for the
                # remaining destructive steps (upload, delete, configure
                # next startup, apply patch, reboot, save) is computed here,
                # reusing the same read-only idempotency checks the real
                # run would use, without calling any of them for real.
                execution_plan = {"operation_type": operation_type}

                if operation_type == OPERATION_PATCH_ONLY:
                    patch_path = Path(client.patch_file)
                    already_present, _ = file_already_on_flash(client, patch_path)
                    execution_plan["would_upload"] = [] if already_present else [patch_path.name]
                    execution_plan["would_apply_patch"] = not patch_already_active(
                        client, client.patch_version
                    )
                else:
                    firmware_path = Path(client.firmware_file)
                    would_upload = []
                    already_present, _ = file_already_on_flash(client, firmware_path)
                    if not already_present:
                        would_upload.append(firmware_path.name)

                    if operation_type == OPERATION_FIRMWARE_AND_PATCH:
                        patch_path = Path(client.patch_file)
                        already_present, _ = file_already_on_flash(client, patch_path)
                        if not already_present:
                            would_upload.append(patch_path.name)

                    execution_plan["would_upload"] = would_upload

                    next_startup = units[0].get("next_startup_image") or ""
                    execution_plan["would_configure_next_startup"] = (
                        not next_startup.endswith(firmware_path.name)
                    )

                    previous_firmware_filename = (units[0].get("startup_image") or "").removeprefix("flash:/")
                    backup_image = units[0].get("backup_image") or ""
                    execution_plan["would_configure_backup_startup"] = (
                        not backup_image.endswith(previous_firmware_filename)
                    )

                    if operation_type == OPERATION_FIRMWARE_AND_PATCH:
                        next_startup_patch = units[0].get("next_startup_patch") or ""
                        execution_plan["would_configure_next_startup_patch"] = (
                            not next_startup_patch.endswith(patch_path.name)
                        )

                    execution_plan["would_reboot"] = not already_running_target(
                        client, client.firmware_version, client.patch_version
                    )

                execution_plan["flash_cleanup_would_run"] = result.metadata.get(
                    "flash_cleanup_would_run", False
                )

                result.metadata["dry_run"] = True
                result.metadata["execution_plan"] = execution_plan
                result.message = "Dry run: execution plan generated, no changes made."

                return result if return_result else None

            if operation_type == OPERATION_PATCH_ONLY:
                patch_path = Path(client.patch_file)
                with debug_timed_step(client, "_upload_pending"):
                    result.metadata["md5_results"] = _upload_pending(client, result, [patch_path])
                result.metadata["uploaded_patch_file"] = patch_path.name
                result.metadata["md5_verified"] = True

                if patch_already_active(client, client.patch_version):
                    msg = f"patch {client.patch_version} already active"
                    client.logger.info("Skipping apply_patch: %s", msg)
                    result.metadata.setdefault("skipped_steps", {})["apply_patch"] = msg
                else:
                    with debug_timed_step(client, "apply_patch"):
                        apply_patch(client, patch_path.name, client.patch_version)

                save_configuration(client)

                msg = f"Patch applied successfully: {client.patch_version}"
                client.logger.info(msg)
                result.message = msg
                result.metadata["new_patch"] = client.patch_version

                return result if return_result else None

            # FIRMWARE_ONLY or FIRMWARE_AND_PATCH: upload, configure, reboot.
            firmware_path = Path(client.firmware_file)
            files_to_upload = [firmware_path]

            if operation_type == OPERATION_FIRMWARE_AND_PATCH:
                patch_path = Path(client.patch_file)
                files_to_upload.append(patch_path)

            with debug_timed_step(client, "_upload_pending"):
                md5_results = _upload_pending(client, result, files_to_upload)
            result.metadata["uploaded_file"] = firmware_path.name

            if operation_type == OPERATION_FIRMWARE_AND_PATCH:
                result.metadata["uploaded_patch_file"] = patch_path.name

            result.metadata["md5_results"] = md5_results
            result.metadata["md5_verified"] = True

            next_startup = units[0].get("next_startup_image") or ""
            if next_startup.endswith(firmware_path.name):
                msg = f"next_startup_image already points to {firmware_path.name}"
                client.logger.info("Skipping configure_next_startup: %s", msg)
                result.metadata.setdefault("skipped_steps", {})["configure_next_startup"] = msg
            else:
                with debug_timed_step(client, "configure_next_startup"):
                    configure_next_startup(client, firmware_path.name)

            if operation_type == OPERATION_FIRMWARE_AND_PATCH:
                next_startup_patch = units[0].get("next_startup_patch") or ""
                if next_startup_patch.endswith(patch_path.name):
                    msg = f"next_startup_patch already points to {patch_path.name}"
                    client.logger.info("Skipping configure_next_startup_patch: %s", msg)
                    result.metadata.setdefault("skipped_steps", {})["configure_next_startup_patch"] = msg
                else:
                    with debug_timed_step(client, "configure_next_startup_patch"):
                        configure_next_startup_patch(client, patch_path.name)

            previous_firmware_filename = (units[0].get("startup_image") or "").removeprefix("flash:/")
            backup_image = units[0].get("backup_image") or ""
            if backup_image.endswith(previous_firmware_filename):
                msg = f"backup_image already points to {previous_firmware_filename}"
                client.logger.info("Skipping configure_backup_startup: %s", msg)
                result.metadata.setdefault("skipped_steps", {})["configure_backup_startup"] = msg
            else:
                with debug_timed_step(client, "configure_backup_startup"):
                    configure_backup_startup(client, previous_firmware_filename)

            if already_running_target(client, client.firmware_version, client.patch_version):
                msg = "device already running target firmware/patch"
                client.logger.info("Skipping reboot: %s", msg)
                result.metadata.setdefault("skipped_steps", {})["reboot"] = msg
                info_after = get_info(client)
            else:
                client.logger.info(
                    "Upgrade: %s -> %s — reboot required",
                    current_version,
                    client.firmware_version,
                )

                with debug_timed_step(client, "reboot_and_reconnect"):
                    reboot_started = time.monotonic()
                    client.reboot()
                    client.conn = client.wait_for_reconnect()
                    result.metadata["rebooted"] = True
                    result.metadata["reboot_duration_seconds"] = time.monotonic() - reboot_started

                info_after = get_info(client)

            final_version = info_after["units"][0]["software_version"]
            result.metadata["new_firmware"] = final_version

            if final_version != client.firmware_version:
                raise RuntimeError(
                    f"Upgrade version mismatch: expected "
                    f"{client.firmware_version}, got {final_version}"
                )

            if operation_type == OPERATION_FIRMWARE_AND_PATCH:
                _verify_patch_active(client, client.patch_version)
                result.metadata["new_patch"] = client.patch_version
                save_configuration(client)

            # Extended post-reboot validation (Faza 11): uptime (informational),
            # routing restored, and interface/alarm comparison against the
            # Faza 10 pre-upgrade baseline. Firmware/patch version mismatches
            # are handled above as immediate hard failures — they do not feed
            # into post_reboot_validation_passed.
            result.metadata["post_upgrade_uptime"] = info_after["units"][0].get("uptime_raw")

            with debug_timed_step(client, "post_reboot_validation"):
                routing_info = get_ip_routing_table(client)
                routing_result = validate_routing_restored(routing_info)

                post_health_snapshot = collect_health_snapshot(client)
                interface_comparison = compare_interfaces_to_baseline(
                    result.metadata["pre_upgrade_baseline_health"], post_health_snapshot,
                )
                alarm_comparison = compare_health_to_baseline(
                    result.metadata["pre_upgrade_baseline_health"], post_health_snapshot,
                )

            result.metadata["routing_validation"] = routing_result
            result.metadata["post_upgrade_health"] = post_health_snapshot
            result.metadata["interface_validation"] = interface_comparison
            result.metadata["alarm_validation"] = alarm_comparison

            result.metadata["post_reboot_validation_passed"] = (
                routing_result["passed"]
                and interface_comparison["passed"]
                and alarm_comparison["passed"]
            )

            msg = f"Upgrade completed successfully: {final_version}"
            client.logger.info(msg)
            result.message = msg

            return result if return_result else None

        except Exception as exc:
            result.success = False
            result.errors.append(str(exc))
            raise

        finally:
            result.mark_finished()
            debug_log(client, "upgrade() result.metadata: %s", result.metadata)
            client.disconnect()
