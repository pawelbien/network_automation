# network_automation/platforms/huawei_vrp/download.py

from pathlib import Path
from network_automation.results import OperationResult
from network_automation.platforms.huawei_vrp.debug_log import debug_log
from network_automation.platforms.huawei_vrp.upload import _dedicated_sftp, _keep_cli_alive_during


# -------------------------------------------------------
# Helper (pure logic)
# -------------------------------------------------------

def download_files(
    client,
    *,
    files: list[str],
    local_dir: str,
):
    """
    Download files from device via SFTP.

    Uses a dedicated, non-interactive-shell SFTP connection (see
    upload.py's _dedicated_sftp()/_keep_cli_alive_during()), not
    client.conn.remote_conn_pre — sharing the SFTP channel with
    client.conn's interactive Netmiko shell session hangs indefinitely on
    this hardware (docs/problems/huawei-vrp-sftp-open-failure.md's
    shared-transport-hang pitfall; confirmed live 2026-07-08 for GET via
    backup.py, same fix applied here).

    - no connect/disconnect (of client.conn — this opens and closes its
      own separate SFTP connection internally, every call)
    - raises exceptions on failure
    """

    local_dir = Path(local_dir)
    local_dir.mkdir(parents=True, exist_ok=True)

    with _keep_cli_alive_during(client), _dedicated_sftp(client) as sftp:
        for filename in files:
            local_path = local_dir / filename

            client.logger.info(
                "Downloading %s → %s",
                filename,
                local_path,
            )
            debug_log(client, "sftp.get starting: %s -> %s", filename, local_path)

            sftp.get(
                filename,
                str(local_path),
            )

            debug_log(client, "sftp.get finished: %s -> %s", filename, local_path)


# -------------------------------------------------------
# Operation / workflow
# -------------------------------------------------------

def run_download(
    client,
    *,
    files: list[str],
    local_dir: str,
    return_result: bool = False,
):
    result = OperationResult(
        success=True,
        operation="download",
        metadata={
            "files": files,
            "local_dir": local_dir,
        },
    )

    result.mark_started()

    client.connect()
    try:
        download_files(
            client,
            files=files,
            local_dir=local_dir,
        )

        result.message = "Files downloaded successfully"
        return result if return_result else None

    except Exception as exc:
        result.success = False
        result.errors.append(str(exc))
        raise

    finally:
        result.mark_finished()
        debug_log(client, "run_download() result.metadata: %s", result.metadata)
        client.disconnect()
