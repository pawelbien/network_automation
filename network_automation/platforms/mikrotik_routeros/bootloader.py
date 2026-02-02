# network_automation/platforms/mikrotik_routeros/bootloader.py

"""
Bootloader (RouterBOARD firmware) upgrade support for Mikrotik RouterOS.
"""

import time
from network_automation.results import OperationResult
from network_automation.platforms.mikrotik_routeros.info import normalize_version


# -------------------------------------------------------
# Helpers (pure logic, no lifecycle)
# -------------------------------------------------------

def get_bootloader_info(client):
    """
    Read bootloader (RouterBOARD) firmware information.

    Returns:
    - current_firmware (str)
    - upgrade_firmware (str)
    - raw_output (str)
    """

    output = client.conn.send_command(
        "/system routerboard print"
    )

    current = None
    upgrade = None

    for line in output.splitlines():
        line = line.strip()

        if line.startswith("current-firmware:"):
            current = line.split(":", 1)[1].strip()

        elif line.startswith("upgrade-firmware:"):
            upgrade = line.split(":", 1)[1].strip()

    if not current or not upgrade:
        raise RuntimeError(
            "Unable to read bootloader firmware information "
            "from /system routerboard print"
        )

    return current, upgrade, output


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

        current, target, raw_before = get_bootloader_info(client)

        result.metadata["current_bootloader"] = current
        result.metadata["target_bootloader"] = target

        if normalize_version(current) == normalize_version(target):
            msg = (
                f"Bootloader already up-to-date ({current})"
            )
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

        current_after, target_after, raw_after = get_bootloader_info(client)

        result.metadata["current_bootloader_after"] = current_after
        result.metadata["target_bootloader_after"] = target_after

        if normalize_version(current_after) != normalize_version(target_after):
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

        # Optional diagnostic: inline message presence
        if "Firmware upgraded successfully" in raw_after:
            result.metadata["confirmation_message_seen"] = True

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
