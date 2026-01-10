# network_automation/platforms/mikrotik_routeros/download.py

from pathlib import Path
from network_automation.results import OperationResult


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

    - no connect/disconnect
    - raises exceptions on failure
    """

    local_dir = Path(local_dir)
    local_dir.mkdir(parents=True, exist_ok=True)

    sftp = client.conn.remote_conn_pre.open_sftp()

    try:
        for filename in files:
            local_path = local_dir / filename

            client.logger.info(
                "Downloading %s → %s",
                filename,
                local_path,
            )

            sftp.get(
                filename,
                str(local_path),
            )

    finally:
        sftp.close()


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
        client.disconnect()
