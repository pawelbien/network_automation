# network_automation/platforms/mikrotik_routeros/upgrade.py

"""
Mikrotik firmware upgrade helpers.
"""

import re
import time
from pathlib import Path

from network_automation.results import OperationResult
from network_automation.platforms.mikrotik_routeros.info import (
    get_info,
    normalize_version,
    is_newer_version,
)
from network_automation.platforms.mikrotik_routeros.upload import upload_files


# -------------------------------------------------------
# Firmware helpers
# -------------------------------------------------------

def firmware_filename(version: str, arch: str) -> str:
    if arch == "x86_64":
        return f"routeros-{version}.npk"
    return f"routeros-{version}-{arch}.npk"


def download_firmware(client):
    """
    Download firmware directly on device from repo_url.
    """

    filename = firmware_filename(client.version, client.arch)
    client.firmware_file = filename

    url = f"{client.repo_url}/{client.version}/{filename}"

    client.logger.info("Firmware file: %s", filename)
    client.logger.info("Download URL: %s", url)

    # Check if file already exists
    initial_info = client.conn.send_command(
        f'/file print detail where name~"{filename}"'
    )

    exists = bool(
        re.search(rf'\bname=[^\s]*{re.escape(filename)}\b', initial_info)
    )

    if not exists:
        client.logger.info("File not found — downloading firmware...")

        cmd = f'/tool fetch url="{url}"'
        client.logger.info("Executing: %s", cmd)

        output = client.conn.send_command_timing(cmd)
        output_l = output.lower()

        if "failure" in output_l or "error" in output_l:
            raise RuntimeError(f"Firmware download failed: {output}")

        if "finished" not in output_l:
            client.logger.warning(
                "Firmware fetch did not explicitly report 'finished'."
            )
    else:
        client.logger.info(
            "Firmware file '%s' already exists. Skipping download.",
            filename,
        )

    # Validate file presence and size
    time.sleep(0.5)

    file_info = client.conn.send_command(
        f'/file print detail where name~"{filename}"'
    )

    line_match = re.search(
        rf'^.*\bname=[^\s]*{re.escape(filename)}\b.*$',
        file_info,
        re.MULTILINE,
    )

    if not line_match:
        raise RuntimeError(
            f"Firmware '{filename}' not found after download."
        )

    line = line_match.group(0)

    match = re.search(r'size=(\d+(?:\.\d+)?)MiB', line)
    if not match:
        raise RuntimeError(
            f"Firmware '{filename}' size missing or invalid."
        )

    size = float(match.group(1))
    if size < 10:
        raise RuntimeError(
            f"Firmware '{filename}' too small ({size}MiB)."
        )

    client.logger.info(
        "Firmware '%s' size OK: %.1f MiB",
        filename,
        size,
    )


def upload_firmware(client):
    """
    Upload firmware to device from local repo_path.
    """

    if not client.repo_path:
        raise RuntimeError(
            "repo_path is required when firmware_method='upload'"
        )

    filename = firmware_filename(client.version, client.arch)
    client.firmware_file = filename

    local_file = (
        Path(client.repo_path) / client.version / filename
    )

    if not local_file.exists():
        raise FileNotFoundError(local_file)

    client.logger.info(
        "Uploading firmware from local repository: %s",
        local_file,
    )

    upload_files(
        client,
        files=[local_file],
        remote_dir="/",
    )


def provide_firmware(client):
    """
    Provide firmware to device using selected method.

    firmware_method is REQUIRED.
    """

    method = getattr(client, "firmware_method", None)

    if not method:
        raise RuntimeError(
            "firmware_method must be explicitly set "
            "('upload' or 'download')"
        )

    client.logger.info(
        "Providing firmware using method: %s",
        method,
    )

    if method == "upload":
        if not client.repo_path:
            raise RuntimeError(
                "firmware_method='upload' requires repo_path"
            )
        upload_firmware(client)

    elif method == "download":
        download_firmware(client)

    else:
        raise ValueError(
            f"Unsupported firmware_method: {method}"
        )



# -------------------------------------------------------
# Upgrade workflow
# -------------------------------------------------------

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

        if not is_newer_version(
            client.current_version,
            client.version,
        ):
            msg = (
                f"Skipping upgrade: current version "
                f"{client.current_version} is >= target {client.version}"
            )
            client.logger.info(msg)

            result.message = msg
            result.metadata["skipped"] = True

            return result if return_result else None

        # ---- provide firmware (upload or download) ----
        provide_firmware(client)

        # ---- reboot & reconnect ----
        client.reboot()
        client.conn = client.wait_for_reconnect()

        # ---- verify version ----
        arch, final_version = get_info(client)
        client.current_version = final_version

        result.metadata["final_version"] = final_version

        if normalize_version(final_version) != normalize_version(
            client.version
        ):
            raise RuntimeError(
                f"Upgrade version mismatch: expected "
                f"{client.version}, got {final_version}"
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
