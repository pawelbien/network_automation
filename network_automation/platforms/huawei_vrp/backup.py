# network_automation/platforms/huawei_vrp/backup.py

"""
Huawei VRP configuration backup: save a named device-side configuration
snapshot and download it via SFTP.

Mirrors mikrotik_routeros/backup.py's approach (named on-device snapshot +
SFTP GET), not a plain-text `display current-configuration` dump, so the
downloaded artifact matches VRP's own binary/compressed startup-config
format — observed on real hardware as `vrpcfg.zip` at `flash:/` (see
tests/huawei_vrp/test_info.py's `display startup` / `dir` fixtures). Hence
the '.zip' extension and `flash:/` prefix used here, consistent with the
same prefix already used by flash.py's `delete flash:/<file>`, info.py's
`display system file-md5 flash:/<file>`, and docs/architecture.md's own
worked example (`client.download(files=["flash:/config.zip"], ...)`).

Follows the network_automation `nauto_` prefix convention on the *device
side only*; OperationResult metadata always exposes the caller-supplied
logical name (docs/architecture.md's platform-naming-isolation rule),
exactly like mikrotik_routeros/backup.py.

Download uses a dedicated, non-interactive-shell SFTP connection (see
upload.py's _dedicated_sftp()), not client.conn.remote_conn_pre —
confirmed live (2026-07-08, AR650) that sharing the SFTP channel with
client.conn's interactive Netmiko shell session hangs indefinitely
(docs/problems/huawei-vrp-sftp-open-failure.md's shared-transport-hang
pitfall applies to GET, not just PUT).

UNVERIFIED ON REAL HARDWARE — validate before production use:
  1. `save <filename>` semantics: whether VRP accepts the `flash:/`-
     prefixed form used here (inferred from adjacent evidence, not from a
     live test of `save` itself), whether it silently repoints "next
     startup saved-configuration file" (`display startup`) as a side
     effect, and whether any interactive prompt beyond the [Y/N]
     confirmation already handled by save_configuration() can appear.
     CONFIRMED LIVE (2026-07-12, third/production device, different unit
     than the two lab AR650s this had been exercised against): `save`
     returned in ~2.5s instead of the usual ~9-11s and never actually
     created the file — the follow-up SFTP GET failed with a content-free
     'OSError: [Errno 2] '. run_backup() now calls
     _verify_backup_file_exists() right after save_configuration() to
     turn that into a clear error instead of a cryptic SFTP failure, but
     the underlying prompt-handling gap on this device/VRP build is not
     otherwise fixed here.
  2. Cleanup delete command: cleanup_old_backups() reuses flash.py's
     _delete_file(), whose `delete flash:/<filename>` + [Y/N] handling is
     already exercised by the existing upgrade() flash-cleanup path, but
     has not specifically been exercised against nauto_-prefixed backup
     files on real hardware.
"""

from network_automation.results import OperationResult
from network_automation.platforms.huawei_vrp.debug_log import debug_log
from network_automation.platforms.huawei_vrp.info import get_flash_info
from network_automation.platforms.huawei_vrp.flash import _delete_file
from network_automation.platforms.huawei_vrp.upgrade import save_configuration
from network_automation.platforms.huawei_vrp.upload import _dedicated_sftp, _make_progress_callback

BACKUP_PREFIX = "nauto_"
BACKUP_EXTENSION = ".zip"


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


def _verify_backup_file_exists(client, *, filename: str):
    """
    Confirm `filename` (bare name, no 'flash:/' prefix) exists on flash
    right after save_configuration() — before attempting the SFTP GET.

    save_configuration(client, filename) (the `save <filename>` form, as
    opposed to bare `save`) is flagged in this module's docstring as
    unverified on real hardware: its confirmation-prompt handling was only
    ever exercised against two lab units. Observed live on a third,
    different device: `save` returned in ~2.5s (vs. ~9-11s on the lab
    units) and the file was never actually created, so the next step
    (SFTP GET) failed with a bare 'OSError: [Errno 2] ' — this device's
    SFTP server returns SSH_FX_NO_SUCH_FILE with an empty text field, so
    paramiko's exception carries no useful detail on its own (same empty-
    text-field pattern as docs/problems/huawei-vrp-sftp-open-failure.md).
    Failing here instead turns that into a clear, actionable error at the
    point it actually happened.

    - no connect/disconnect
    - raises RuntimeError if the file is missing
    """
    flash_info = get_flash_info(client)
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

        remote_path = f"flash:/{BACKUP_PREFIX}{name}{BACKUP_EXTENSION}"
        logical_file = f"{name}{BACKUP_EXTENSION}"

        client.logger.info("Creating backup '%s'", remote_path)
        save_configuration(client, remote_path)

        _verify_backup_file_exists(client, filename=f"{BACKUP_PREFIX}{name}{BACKUP_EXTENSION}")

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
