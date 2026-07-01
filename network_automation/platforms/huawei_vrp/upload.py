# network_automation/platforms/huawei_vrp/upload.py

import hashlib
from pathlib import Path
from network_automation.results import OperationResult


# -------------------------------------------------------
# Helper (pure logic)
# -------------------------------------------------------

def compute_local_md5(path: Path) -> str:
    """
    Compute the MD5 hex digest of a local file.

    Read in fixed-size chunks so large firmware images don't need to be
    loaded into memory whole.
    """
    digest = hashlib.md5()

    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


def upload_files(
    client,
    *,
    files: list[Path],
    remote_dir: str = "/",
):
    """
    Upload local files to Huawei VRP via SFTP.

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

    except FileNotFoundError as exc:
        missing = Path(exc.args[0])

        msg = (
            "Local file not found for upload. "
            f"Expected file: {missing}"
        )

        result.success = False
        result.errors.append(msg)

        raise RuntimeError(msg) from exc

    except Exception as exc:
        result.success = False
        result.errors.append(str(exc))
        raise

    finally:
        result.mark_finished()
        client.disconnect()
