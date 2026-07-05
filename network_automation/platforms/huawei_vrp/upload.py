# network_automation/platforms/huawei_vrp/upload.py

import hashlib
import time
from pathlib import Path
from network_automation.results import OperationResult
from network_automation.platforms.huawei_vrp.debug_log import debug_log
from network_automation.platforms.huawei_vrp.info import get_flash_info

# Fixed pause between upload_with_retry() attempts. Not user-configurable —
# only the attempt count (upload_retries) and per-attempt transfer timeout
# (upload_timeout) are exposed on HuaweiVRP.
_RETRY_DELAY_SECONDS = 1


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
    # This device's SFTP server rejects an OPEN-for-write with an empty
    # SSH_FX_FAILURE if it's the first request on a freshly opened
    # channel; one prior read-only request makes every following write
    # succeed. OpenSSH's sftp client always sends a REALPATH on session
    # start for this reason — paramiko doesn't, so we do it explicitly.
    sftp.normalize(".")

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


def verify_remote_file(client, *, filename: str, expected_size: int) -> dict:
    """
    Verify that `filename` exists on flash and its reported size matches
    expected_size (dir listing) — run BEFORE MD5. MD5 verification is a
    separate, mandatory step (upgrade.verify_md5()) that runs after this
    one — this check does not compute or compare hashes.

    - no connect/disconnect
    - raises RuntimeError if the file is missing or its size mismatches
    """
    flash_info = get_flash_info(client)
    matches = [
        f for f in flash_info["files"]
        if not f["is_dir"] and f["name"] == filename
    ]

    if not matches:
        raise RuntimeError(
            f"Transfer verification failed: {filename!r} not found on "
            "flash after upload."
        )

    actual_size = matches[0]["size"]
    if actual_size != expected_size:
        raise RuntimeError(
            f"Transfer verification failed for {filename!r}: expected "
            f"size {expected_size} bytes, found {actual_size} bytes on "
            "flash."
        )

    return {
        "exists": True,
        "expected_size": expected_size,
        "actual_size": actual_size,
        "match": True,
    }


def upload_with_retry(
    client,
    *,
    files: list[Path],
    remote_dir: str,
    timeout: float,
    retries: int,
) -> dict:
    """
    Upload `files` and verify each landed intact (exists + expected size),
    retrying the whole upload+verify unit up to `retries` times before
    giving up. Transfer respects a configurable timeout and a configurable
    number of retry attempts before failing the operation.

    Deliberately does not delegate to upload_files() — that helper stays a
    single, unbounded-timeout SFTP put used elsewhere (client.upload()),
    while this one needs to bound each attempt's transfer with `timeout`
    (paramiko sftp channel timeout) and loop on failure. Retry uses a plain
    for-loop + time.sleep() between attempts, matching BaseClient.connect()'s
    established retry style — no tenacity/decorator.

    A missing local file (FileNotFoundError) is not retried — no number of
    attempts will make a nonexistent local file appear.

    - no connect/disconnect
    - raises RuntimeError after exhausting all retries, chained to the last
      underlying exception
    - returns {filename: {"exists", "expected_size", "actual_size", "match"}}
    """
    last_exc = None

    for attempt in range(1, retries + 1):
        try:
            sftp = client.conn.remote_conn_pre.open_sftp()
            try:
                sftp.get_channel().settimeout(timeout)
                # See upload_files()'s matching comment: this device's SFTP
                # server needs one prior read-only request before it will
                # accept an OPEN-for-write on a freshly opened channel.
                sftp.normalize(".")

                for path in files:
                    if not path.exists():
                        raise FileNotFoundError(path)

                    remote_path = f"{remote_dir.rstrip('/')}/{path.name}"
                    client.logger.info(
                        "Uploading %s → %s (attempt %d/%d)",
                        path, remote_path, attempt, retries,
                    )
                    debug_log(
                        client,
                        "upload attempt %d/%d starting: %s -> %s",
                        attempt, retries, path, remote_path,
                    )
                    sftp.put(str(path), remote_path)
            finally:
                sftp.close()

            results = {}
            for path in files:
                expected_size = path.stat().st_size
                results[path.name] = verify_remote_file(
                    client, filename=path.name, expected_size=expected_size,
                )
            return results

        except FileNotFoundError:
            raise

        except Exception as exc:
            last_exc = exc
            client.logger.warning(
                "Upload attempt %d/%d failed: %s", attempt, retries, exc,
            )
            if attempt < retries:
                time.sleep(_RETRY_DELAY_SECONDS)

    raise RuntimeError(
        f"Upload failed after {retries} attempt(s): {last_exc}"
    ) from last_exc


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
        debug_log(client, "run_upload() result.metadata: %s", result.metadata)
        client.disconnect()
