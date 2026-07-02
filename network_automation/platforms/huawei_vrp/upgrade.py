# network_automation/platforms/huawei_vrp/upgrade.py

"""
Huawei VRP upgrade workflow (single-unit): firmware, patch, or both.

Scope of this implementation — see engineering_handbook/tmp/huawei_vrp_update.txt
for the full target algorithm: version comparison, firmware/patch upload,
MD5 verification, startup configuration, hot patch apply, reboot, and
post-reboot verification.

Deliberately out of scope for this pass (tracked as follow-up work):
idempotency checks beyond the version comparison, pre/post health checks,
flash cleanup, automatic rollback, and multi-unit/stack upgrades.
"""

from pathlib import Path

from network_automation.results import OperationResult
from network_automation.platforms.huawei_vrp.cli_errors import _check_cli_output
from network_automation.platforms.huawei_vrp.lock import device_lock
from network_automation.platforms.huawei_vrp.info import get_info, get_patch_info, get_file_md5, _parse_startup
from network_automation.platforms.huawei_vrp.upload import upload_files, compute_local_md5
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

    - no connect/disconnect
    - raises RuntimeError if `display startup` doesn't reflect the change
    """
    command = f"startup system-software flash:/{filename}"
    ack = client.conn.send_command(command)
    _check_cli_output(command, ack, expect_content=False)

    startup_output = client.conn.send_command("display startup")
    _check_cli_output("display startup", startup_output)
    startup = _parse_startup(startup_output)
    master = startup.get("master", {})
    next_image = master.get("next_startup_image") or ""

    if not next_image.endswith(filename):
        raise RuntimeError(
            "Startup configuration verification failed: expected next "
            f"startup image to end with '{filename}', got {next_image!r}"
        )


def configure_next_startup_patch(client, filename: str):
    """
    Point the device's next-boot startup patch at `filename` and verify it stuck.

    - no connect/disconnect
    - raises RuntimeError if `display startup` doesn't reflect the change
    """
    command = f"startup patch flash:/{filename}"
    ack = client.conn.send_command(command)
    _check_cli_output(command, ack, expect_content=False)

    startup_output = client.conn.send_command("display startup")
    _check_cli_output("display startup", startup_output)
    startup = _parse_startup(startup_output)
    master = startup.get("master", {})
    next_patch = master.get("next_startup_patch") or ""

    if not next_patch.endswith(filename):
        raise RuntimeError(
            "Startup configuration verification failed: expected next "
            f"startup patch to end with '{filename}', got {next_patch!r}"
        )


def verify_md5(client, path: Path):
    """
    Verify that a file just uploaded to flash matches its local MD5.

    Computes the local file's MD5 (hashlib) and compares it against the
    device-reported MD5 (`display system file-md5 flash:/<file>`).

    - no connect/disconnect
    - raises RuntimeError on mismatch — MD5 verification is mandatory for
      every uploaded file, per engineering_handbook/tmp/huawei_vrp_update.txt
    """
    expected_md5 = compute_local_md5(path)
    actual_md5 = get_file_md5(client, path.name)

    if actual_md5 != expected_md5:
        raise RuntimeError(
            f"MD5 verification failed for {path.name}: expected "
            f"{expected_md5}, got {actual_md5}"
        )

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

    - no connect/disconnect
    - raises RuntimeError if the patch isn't running or the version mismatches
    """
    command = f"patch load flash:/{filename} all run"
    ack = client.conn.send_command(command)
    _check_cli_output(command, ack, expect_content=False)
    return _verify_patch_active(client, expected_patch_version)


def save_configuration(client):
    """
    Save the running configuration, confirming any interactive [Y/N] prompt.

    - no connect/disconnect
    """
    # send_command_timing output here is an interactive [Y/N] confirmation
    # prompt, not command output to validate — the CLI-error check does not
    # apply to prompt-handling loops.
    output = client.conn.send_command_timing("save")

    for _ in range(3):
        if "y/n" not in output.lower():
            break
        output = client.conn.send_command_timing("y")


def upgrade(client, *, return_result: bool = False):
    """
    Run the upgrade workflow for a single-unit device: firmware, patch, or
    both, depending on determine_operation_type().

    Steps: connect, compare firmware/patch versions, then depending on the
    operation type:
    - NONE: skip.
    - PATCH_ONLY: upload patch, verify its MD5, hot-apply, verify, save
      configuration.
    - FIRMWARE_ONLY: upload firmware, verify its MD5, configure next startup
      image, reboot, wait for reconnect, verify final firmware version.
    - FIRMWARE_AND_PATCH: upload firmware + patch, verify both MD5s,
      configure next startup image and patch, reboot, wait for reconnect,
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

            validate_upgrade_inputs(
                client, unit_model=units[0]["model"], operation_type=operation_type
            )

            if operation_type == OPERATION_PATCH_ONLY:
                patch_path = Path(client.patch_file)
                upload_files(client, files=[patch_path], remote_dir="flash:/")
                result.metadata["uploaded_patch_file"] = patch_path.name

                result.metadata["md5_results"] = {
                    patch_path.name: verify_md5(client, patch_path)
                }
                result.metadata["md5_verified"] = True

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

            upload_files(client, files=files_to_upload, remote_dir="flash:/")
            result.metadata["uploaded_file"] = firmware_path.name

            md5_results = {firmware_path.name: verify_md5(client, firmware_path)}

            if operation_type == OPERATION_FIRMWARE_AND_PATCH:
                result.metadata["uploaded_patch_file"] = patch_path.name
                md5_results[patch_path.name] = verify_md5(client, patch_path)

            result.metadata["md5_results"] = md5_results
            result.metadata["md5_verified"] = True

            configure_next_startup(client, firmware_path.name)

            if operation_type == OPERATION_FIRMWARE_AND_PATCH:
                configure_next_startup_patch(client, patch_path.name)

            client.logger.info(
                "Upgrade: %s -> %s — reboot required",
                current_version,
                client.firmware_version,
            )

            client.reboot()
            client.conn = client.wait_for_reconnect()
            result.metadata["rebooted"] = True

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
            client.disconnect()
