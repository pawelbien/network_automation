# network_automation/platforms/opnsense/backup.py

"""
OPNsense configuration backup: SFTP GET of /conf/config.xml.

Unlike mikrotik_routeros/backup.py and huawei_vrp/backup.py, there is no
on-device "save a named snapshot" step: /conf/config.xml is always the live,
current configuration (configd rewrites it on every change), so downloading
it at call time already gives the same point-in-time guarantee a separate
snapshot would. No on-device housekeeping (cleanup_old_backups, nauto_
prefix) either - nothing is written to the device.

This is deliberate, not an oversight: b2bauto (the automation account) can
read /conf/config.xml via its 'wheel' group membership, but /conf/backup/
is 750 owned by wwwonly and not group-writable, and OPNsense has no
installed backup provider to delegate a privileged write through (Local.php
extends Base.php but neither implements IBackupProvider - confirmed live,
2026-07-24).
"""

import os

from network_automation.results import OperationResult
from network_automation.platforms.opnsense.debug_log import debug_log

_CONFIG_PATH = "/conf/config.xml"


def _looks_like_valid_config_xml(path: str):
    """
    Sanity check the downloaded file: non-empty and starts with an XML
    declaration. Raises RuntimeError otherwise - backstop against silently
    saving a truncated/empty transfer as if it were a real backup.
    """
    size = os.path.getsize(path)
    if size == 0:
        raise RuntimeError(f"Downloaded backup file '{path}' is empty.")

    with open(path, "rb") as f:
        head = f.read(64)

    if not head.lstrip().startswith(b"<?xml"):
        raise RuntimeError(
            f"Downloaded backup file '{path}' does not look like valid XML "
            f"(expected to start with '<?xml', got: {head!r})."
        )


def run_backup(client, name: str, *, return_result: bool = False, download_dir: str = "."):
    """
    Download the device's live configuration (/conf/config.xml) via SFTP.

    Workflow: connect -> SFTP GET -> sanity-check -> disconnect.
    """
    result = OperationResult(
        success=True,
        operation="backup",
        metadata={"backup_name": name},
    )

    result.mark_started()

    try:
        client.connect()
        client._ensure_shell()

        result.metadata["remote_file"] = _CONFIG_PATH

        local_path = f"{download_dir.rstrip('/')}/{name}.xml"
        client.logger.info("Downloading %s to %s", _CONFIG_PATH, local_path)

        sftp = client.conn.remote_conn_pre.open_sftp()
        try:
            sftp.get(_CONFIG_PATH, local_path)
        finally:
            sftp.close()

        _looks_like_valid_config_xml(local_path)

        result.metadata["local_path"] = local_path
        result.message = f"Backup downloaded to '{local_path}'"

        return result if return_result else None

    except Exception as exc:
        result.success = False
        result.errors.append(str(exc))
        raise

    finally:
        result.mark_finished()
        debug_log(client, "run_backup() result.metadata: %s", result.metadata)
        client.disconnect()
