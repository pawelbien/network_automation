# network_automation/platforms/mikrotik_routeros/bootloader.py

"""
Bootloader (RouterBOARD firmware) upgrade support for Mikrotik RouterOS.
"""

import time
from network_automation.results import OperationResult
from network_automation.platforms.mikrotik_routeros.info import (
    normalize_version,
    get_info,
)


def upgrade_bootloader_helper(client):
    """
    Trigger bootloader firmware upgrade.

    This only stages the upgrade; reboot is required.
    """

    out = client.conn.send_command_timing(
        "/system routerboard upgrade"
    )

    if "[y/n" in out.lower():
        client.conn.send_command_timing("y")


# -------------------------------------------------------
# Workflow / Operation
# -------------------------------------------------------

def bootloader_upgrade(client, *, return_result: bool = False):
    """
    Upgrade device bootloader firmware if needed.

    Behavior:
    - Reads current and upgrade bootloader firmware
    - Skips if already up-to-date
    - Skips explicitly if bootloader is not supported (e.g. CHR)
    - Triggers bootloader upgrade
    - Re-reads routerboard state (best-effort confirmation)
    - Reboots device
    - Waits for reconnect
    """

    result = OperationResult(
        success=True,
        operation="bootloader_upgrade",
    )
    result.mark_started()

    client.connect()
    try:
        # -------------------------------------------------
        # Initial state
        # -------------------------------------------------

        info = get_info(client)
        unit = info["units"][0]
        current = unit["bootloader_current_firmware"]
        target = unit["bootloader_upgrade_firmware"]

        if current is None:
            skip_msg = "Bootloader upgrade not supported on this platform"
            client.logger.info(skip_msg)
            result.message = skip_msg
            result.metadata["skipped"] = True
            result.metadata["reason"] = "bootloader not supported"
            return result if return_result else None

        result.metadata["current_bootloader"] = current
        result.metadata["target_bootloader"] = target

        if normalize_version(current) == normalize_version(target):
            msg = f"Bootloader already up-to-date ({current})"
            client.logger.info(msg)
            result.message = msg
            result.metadata["skipped"] = True
            return result if return_result else None

        client.logger.info(
            "Upgrading bootloader firmware: %s → %s",
            current,
            target,
        )

        # -------------------------------------------------
        # Trigger upgrade
        # -------------------------------------------------

        upgrade_bootloader_helper(client)

        # Give RouterOS a moment to update internal state
        time.sleep(1.0)

        # -------------------------------------------------
        # Re-read state (confirmation by observation)
        # -------------------------------------------------

        try:
            info_after = get_info(client)
            unit_after = info_after["units"][0]
            current_after = unit_after["bootloader_current_firmware"]
            target_after = unit_after["bootloader_upgrade_firmware"]

            result.metadata["current_bootloader_after"] = current_after
            result.metadata["target_bootloader_after"] = target_after

            if normalize_version(current_after) != normalize_version(
                target_after
            ):
                # Expected before reboot: upgrade staged
                result.metadata["upgrade_staged"] = True
                client.logger.info(
                    "Bootloader upgrade staged successfully "
                    "(reboot required)"
                )
            else:
                client.logger.warning(
                    "Bootloader upgrade state unclear after staging; "
                    "continuing with reboot"
                )

            # Optional diagnostic: check for confirmation message in raw output
            try:
                raw_output = client.conn.send_command("/system routerboard print")
                if "firmware upgraded successfully" in raw_output.lower():
                    result.metadata["confirmation_message_seen"] = True
            except Exception:
                # Best-effort only; ignore if check fails
                pass

        except Exception:
            # Best-effort only; do not fail the workflow here
            client.logger.warning(
                "Unable to re-read bootloader state after staging; "
                "continuing with reboot"
            )

        # -------------------------------------------------
        # Reboot & reconnect
        # -------------------------------------------------

        client.reboot()
        client.conn = client.wait_for_reconnect()

        result.message = (
            f"Bootloader upgrade completed (target {target})"
        )

        return result if return_result else None

    except Exception as exc:
        result.success = False
        result.errors.append(str(exc))
        raise

    finally:
        result.mark_finished()
        client.disconnect()
