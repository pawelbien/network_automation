# network_automation/platforms/mikrotik_routeros/upgrade.py

"""
Mikrotik firmware upgrade helpers.
"""

import re
import time

from network_automation.results import OperationResult
from network_automation.platforms.mikrotik_routeros.info import get_info
from network_automation.platforms.mikrotik_routeros.info import (
    get_info,
    normalize_version,
    is_newer_version,
)

def download_firmware(client):
    """Download firmware and validate .npk size."""

    if client.arch == "x86_64":
        filename = f"routeros-{client.version}.npk"
    else:
        filename = f"routeros-{client.version}-{client.arch}.npk"

    client.firmware_file = filename
    url = f"{client.repo_url}/{client.version}/{filename}"

    client.logger.info(f"Firmware file: {filename}")
    client.logger.info(f"Download URL: {url}")

    # Check if file exists
    initial_info = client.conn.send_command(
        f'/file print detail where name~"{filename}"'
    )

    exists = bool(
        re.search(rf'\bname=[^\s]*{re.escape(filename)}\b', initial_info)
    )

    if exists:
        client.logger.info(f"File '{filename}' already exists. Skipping fetch.")
    else:
        client.logger.info("File not found — downloading firmware...")

        cmd = f'/tool fetch url="{url}"'
        client.logger.info(f"Executing: {cmd}")

        output = client.conn.send_command_timing(cmd)
        output_l = output.lower()

        if "failure" in output_l or "error" in output_l:
            raise RuntimeError(f"Firmware download failed: {output}")

        if "finished" not in output_l:
            client.logger.warning("Fetch did not explicitly report 'finished'.")

    # Refresh file list
    time.sleep(0.5)
    file_info = client.conn.send_command(
        f'/file print detail where name~"{filename}"'
    )

    # Find our .npk line
    line_match = re.search(
        rf'^.*\bname=[^\s]*{re.escape(filename)}\b.*$',
        file_info,
        re.MULTILINE,
    )

    if not line_match:
        raise RuntimeError(f"Firmware '{filename}' not found after download.")

    line = line_match.group(0)

    # Validate file size (MiB only)
    match = re.search(r'size=(\d+(?:\.\d+)?)MiB', line)
    if not match:
        raise RuntimeError(f"Firmware '{filename}' size missing or invalid.")

    size = float(match.group(1))
    if size < 10:
        raise RuntimeError(
            f"Firmware '{filename}' too small ({size}MiB) — invalid or corrupted."
        )

    client.logger.info(f"Firmware '{filename}' size OK: {size}MiB")


def upgrade(client, *, return_result: bool = False):
    """Run full firmware upgrade workflow."""

    if not client.version:
        raise ValueError(
            "firmware_version is required for upgrade operation"
        )

    result = OperationResult(
        success=True,
        operation="upgrade",
        metadata={
            "target_version": client.version,
        },
    )

    result.mark_started()

    client.connect()
    try:
        arch, current_version = get_info(client)
        client.arch = arch
        client.current_version = current_version

        result.metadata["current_version"] = current_version
        result.metadata["arch"] = arch

        if not is_newer_version(client.current_version, client.version):
            msg = (
                f"Skipping upgrade: current version {client.current_version} "
                f"is >= target {client.version}"
            )
            client.logger.info(msg)

            result.message = msg
            result.metadata["skipped"] = True

            return result if return_result else None

        download_firmware(client)

        client.reboot()
        client.conn = client.wait_for_reconnect()

        arch, final_version = get_info(client)
        client.current_version = final_version

        result.metadata["final_version"] = final_version

        if normalize_version(final_version) != normalize_version(client.version):
            raise RuntimeError(
                f"Upgrade version mismatch: expected {client.version}, got {final_version}"
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

