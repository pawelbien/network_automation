# network_automation/platforms/huawei_vrp/backup.py

"""
Huawei VRP configuration backup: save a named device-side configuration
snapshot and download it via SFTP.

Mirrors mikrotik_routeros/backup.py's approach (named on-device snapshot +
SFTP GET), not a plain-text `display current-configuration` dump, so the
downloaded artifact matches VRP's own binary/compressed startup-config
format (`vrpcfg.zip` at `flash:/`). Hence the '.zip' extension and
`flash:/` prefix, consistent with flash.py, info.py, and
docs/architecture.md's worked example.

Follows the network_automation `nauto_` prefix convention on the *device
side only*; OperationResult metadata always exposes the caller-supplied
logical name (docs/architecture.md's platform-naming-isolation rule),
exactly like mikrotik_routeros/backup.py.

Download uses a dedicated, non-interactive-shell SFTP connection (see
upload.py's _dedicated_sftp()), not client.conn.remote_conn_pre — sharing
the SFTP channel with client.conn's interactive Netmiko shell session
hangs indefinitely (docs/problems/huawei-vrp-sftp-open-failure.md's
shared-transport-hang pitfall applies to GET, not just PUT).

UNVERIFIED ON REAL HARDWARE — validate before production use:
  1. `save <filename>` semantics: whether VRP accepts the `flash:/`-
     prefixed form used here, and whether saving under an explicit
     filename repoints "next startup saved-configuration file"
     (`display startup`) as a side effect. Known failure mode: `save`
     silently fails to create the file if the `flash:/<path>` string
     exceeds MAX_FLASH_PATH_LENGTH (64) — VRP rejects the whole command
     as "Unrecognized command". _flash_safe_filename() falls back to a
     short hash when the full name would exceed the limit, and
     run_backup() calls _verify_backup_file_exists() right after
     save_configuration() as a backstop for any other rejection reason.
  2. Cleanup delete command: cleanup_old_backups() reuses flash.py's
     _delete_file(), whose `delete flash:/<filename>` + [Y/N] handling is
     already exercised by the existing upgrade() flash-cleanup path, but
     has not specifically been exercised against nauto_-prefixed backup
     files on real hardware.
"""

import time

from netmiko.exceptions import ReadTimeout

from network_automation.results import OperationResult
from network_automation.device_paths import safe_device_name
from network_automation.platforms.huawei_vrp.debug_log import debug_log
from network_automation.platforms.huawei_vrp.info import get_flash_info
from network_automation.platforms.huawei_vrp.flash import _delete_file
from network_automation.platforms.huawei_vrp.upgrade import save_configuration
from network_automation.platforms.huawei_vrp.upload import _dedicated_sftp, _make_progress_callback

BACKUP_PREFIX = "nauto_"
BACKUP_EXTENSION = ".zip"

# VRP's CLI parser hard-rejects the whole `save <path>` command
# ("Unrecognized command found at '^' position.") once the "flash:/<file>"
# path exceeds this length (confirmed on AR650/AR651: 64 chars accepted,
# 65 rejected). Named constant so the limit is easy to revisit per model.
MAX_FLASH_PATH_LENGTH = 64

# Retries for the flash directory read inside _verify_backup_file_exists()
# (right after `save`), on a Netmiko ReadTimeout only. The device can still
# be finishing `save`'s asynchronous "please wait" tail and briefly not
# respond, tripping netmiko's ~10s command-echo sub-timeout before it's
# actually ready.
_FLASH_INFO_RETRIES = 3
_FLASH_INFO_RETRY_DELAY_SECONDS = 2


# -------------------------------------------------------
# Helper (pure logic)
# -------------------------------------------------------

def cleanup_old_backups(client):
    """
    Delete old network_automation-created backup snapshots from flash.

    Runs: dir (via get_flash_info), then flash.py's _delete_file() for
    each flash file matching the 'nauto_*.zip' naming convention.

    - no connect/disconnect
    - raises RuntimeError if any delete is rejected (propagated from
      flash.py::_delete_file)
    """
    flash_info = get_flash_info(client)
    candidates = [
        f["name"] for f in flash_info["files"]
        if not f["is_dir"]
        and f["name"].startswith(BACKUP_PREFIX)
        and f["name"].endswith(BACKUP_EXTENSION)
    ]

    for filename in candidates:
        client.logger.info("Removing old backup file: %s", filename)
        _delete_file(client, filename)


def _flash_safe_filename(name: str) -> str:
    """
    Build the on-device backup filename ('nauto_<name>.zip'), falling back
    to a short, deterministic hash of `name` if the full
    'flash:/nauto_<name>.zip' path would exceed MAX_FLASH_PATH_LENGTH (see
    that constant for how the limit was found — long Nautobot device
    names are what push the generated name over it).

    This name is purely an internal, device-side implementation detail —
    per this module's platform-naming-isolation note, callers only ever
    see the caller-supplied logical name via OperationResult.metadata,
    never this one, so trading readability for a guaranteed-short,
    collision-resistant name here (only when actually needed) is safe.
    """
    return safe_device_name(
        name,
        prefix=BACKUP_PREFIX,
        suffix=BACKUP_EXTENSION,
        max_length=MAX_FLASH_PATH_LENGTH,
        path_prefix="flash:/",
    )


def _verify_backup_file_exists(client, *, filename: str):
    """
    Confirm `filename` (bare name, no 'flash:/' prefix) exists on flash
    right after save_configuration() — before attempting the SFTP GET.

    Backstop for `save` silently failing to create the file (e.g. the
    MAX_FLASH_PATH_LENGTH limit): without this check, the failure only
    surfaces as a cryptic 'OSError: [Errno 2] ' from the SFTP GET, since
    this device's SFTP server returns SSH_FX_NO_SUCH_FILE with no text.

    Retries the flash directory read (see _FLASH_INFO_RETRIES) on a
    Netmiko ReadTimeout only: the device can still be settling from
    `save`'s asynchronous tail, briefly failing netmiko's command-echo
    check with "Pattern not detected: 'dir' in output" — a transient
    condition, not the file genuinely missing.

    - no connect/disconnect
    - raises RuntimeError if the file is missing, or if the flash
      directory listing keeps timing out after all retries
    """
    last_exc = None
    flash_info = None

    for attempt in range(1, _FLASH_INFO_RETRIES + 1):
        try:
            flash_info = get_flash_info(client)
            break
        except ReadTimeout as exc:
            last_exc = exc
            debug_log(
                client,
                "get_flash_info() attempt %d/%d timed out (device likely "
                "still settling from 'save'): %s",
                attempt, _FLASH_INFO_RETRIES, exc,
            )
            if attempt < _FLASH_INFO_RETRIES:
                time.sleep(_FLASH_INFO_RETRY_DELAY_SECONDS)
    else:
        raise RuntimeError(
            f"Could not read the flash directory listing after 'save' "
            f"({_FLASH_INFO_RETRIES} attempts, device may still be busy "
            f"saving): {last_exc}"
        ) from last_exc

    exists = any(
        not f["is_dir"] and f["name"] == filename
        for f in flash_info["files"]
    )

    if not exists:
        raise RuntimeError(
            f"Backup file 'flash:/{filename}' was not found on the device "
            "after 'save' — the save may have failed or used unexpected "
            "prompt behavior on this device/VRP build."
        )


# -------------------------------------------------------
# Operation / workflow
# -------------------------------------------------------

def run_backup(client, name: str, *, return_result: bool = False, download_dir: str = "."):
    """
    Save a named configuration snapshot on-device and download it via SFTP.

    Workflow: connect -> cleanup_old_backups -> save <nauto_name>.zip ->
    SFTP GET -> disconnect.

    On-device file is named f"nauto_{name}.zip" (network_automation's own
    housekeeping prefix); OperationResult only ever reports the logical
    f"{name}.zip" name — the nauto_ prefix and flash:/ path never appear
    in result.metadata, per docs/architecture.md's platform-naming-
    isolation rule.

    See module docstring for unverified hardware behaviors that must be
    validated before production use.
    """
    result = OperationResult(
        success=True,
        operation="backup",
        metadata={"backup_name": name},
    )

    result.mark_started()

    try:
        client.connect()

        cleanup_old_backups(client)

        backup_filename = _flash_safe_filename(name)
        remote_path = f"flash:/{backup_filename}"
        logical_file = f"{name}{BACKUP_EXTENSION}"

        client.logger.info("Creating backup '%s'", remote_path)
        save_configuration(client, remote_path)

        _verify_backup_file_exists(client, filename=backup_filename)

        result.metadata["remote_file"] = logical_file

        local_path = f"{download_dir.rstrip('/')}/{logical_file}"
        client.logger.info("Downloading backup to %s", local_path)

        with _dedicated_sftp(client) as sftp:
            sftp.get(remote_path, local_path, callback=_make_progress_callback(client))

        result.metadata["local_path"] = local_path
        result.message = f"Backup '{remote_path}' created and downloaded"

        return result if return_result else None

    except Exception as exc:
        result.success = False
        result.errors.append(str(exc))
        raise

    finally:
        result.mark_finished()
        debug_log(client, "run_backup() result.metadata: %s", result.metadata)
        client.disconnect()
