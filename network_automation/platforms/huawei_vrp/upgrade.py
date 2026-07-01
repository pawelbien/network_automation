# network_automation/platforms/huawei_vrp/upgrade.py

"""
Huawei VRP firmware upgrade workflow (firmware-only, single-unit).

Scope of this implementation — see engineering_handbook/tmp/huawei_vrp_update.txt
for the full target algorithm: version comparison, firmware upload, startup
configuration, reboot, and post-reboot verification.

Deliberately out of scope for this pass (tracked as follow-up work):
patch handling, MD5 verification, idempotency checks beyond the version
comparison, pre/post health checks, flash cleanup, automatic rollback,
concurrency locking, forced downgrade, and multi-unit/stack upgrades.
"""

from pathlib import Path

from network_automation.results import OperationResult
from network_automation.platforms.huawei_vrp.info import get_info, _parse_startup
from network_automation.platforms.huawei_vrp.upload import upload_files
from network_automation.platforms.huawei_vrp.version import is_firmware_newer


def configure_next_startup(client, filename: str):
    """
    Point the device's next-boot startup image at `filename` and verify it stuck.

    - no connect/disconnect
    - raises RuntimeError if `display startup` doesn't reflect the change
    """
    client.conn.send_command(f"startup system-software flash:/{filename}")

    startup = _parse_startup(client.conn.send_command("display startup"))
    master = startup.get("master", {})
    next_image = master.get("next_startup_image") or ""

    if not next_image.endswith(filename):
        raise RuntimeError(
            "Startup configuration verification failed: expected next "
            f"startup image to end with '{filename}', got {next_image!r}"
        )


def upgrade(client, *, return_result: bool = False):
    """
    Run the firmware-only upgrade workflow for a single-unit device.

    Steps: connect, compare firmware version, upload firmware, configure
    next startup image, reboot, wait for reconnect, verify final version.

    Raises RuntimeError if the device reports more than one unit (stacks are
    not yet supported by this workflow) or if post-reboot verification fails.
    """
    if not client.firmware_version:
        raise ValueError("firmware_version is required for upgrade operation")
    if not client.firmware_file:
        raise ValueError("firmware_file is required for upgrade operation")

    result = OperationResult(
        success=True,
        operation="upgrade",
        metadata={"target_firmware": client.firmware_version},
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

        if not is_firmware_newer(current_version, client.firmware_version):
            msg = (
                f"Skipping upgrade: current firmware {current_version} is "
                f">= target {client.firmware_version}"
            )
            client.logger.info(msg)

            result.message = msg
            result.metadata["skipped"] = True

            return result if return_result else None

        firmware_path = Path(client.firmware_file)
        upload_files(client, files=[firmware_path], remote_dir="flash:/")
        result.metadata["uploaded_file"] = firmware_path.name

        configure_next_startup(client, firmware_path.name)

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
