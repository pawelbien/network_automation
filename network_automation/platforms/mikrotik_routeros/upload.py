# network_automation/platforms/mikrotik_routeros/upload.py

from pathlib import Path
from network_automation.results import OperationResult


# -------------------------------------------------------
# Upload helper
# -------------------------------------------------------

def upload_files(
    client,
    *,
    files: list[Path],
    remote_dir: str = "/",
):
    """
    Upload local files to MikroTik via SFTP.

    - no connect/disconnect
    - raises exceptions on failure
    """

    sftp = client.conn.remote_conn_pre.open_sftp()

    try:
        for path in files:
            if not path.exists():
                raise FileNotFoundError(path)

            remote_path = f"{remote_dir.rstrip('/')}/{path.name}"

            client.logger.info(
                "Uploading %s → %s",
                path,
                remote_path,
            )

            sftp.put(
                str(path),
                remote_path,
            )

    finally:
        sftp.close()


# -------------------------------------------------------
# Operation / workflow
# -------------------------------------------------------

def run_upload(
    client,
    *,
    files: list[str | Path],
    remote_dir: str = "/",
    return_result: bool = False,
):
    result = OperationResult(
        success=True,
        operation="upload",
        metadata={
            "files": [],
            "remote_dir": remote_dir,
        },
    )

    result.mark_started()

    client.connect()
    try:
        paths = [Path(f) for f in files]

        upload_files(
            client,
            files=paths,
            remote_dir=remote_dir,
        )

        result.metadata["files"] = [p.name for p in paths]
        result.message = "Files uploaded successfully"

        return result if return_result else None

    except Exception as exc:
        result.success = False
        result.errors.append(str(exc))
        raise

    finally:
        result.mark_finished()
        client.disconnect()
