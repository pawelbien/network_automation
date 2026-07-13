# network_automation/platforms/huawei_vrp/upload.py

import hashlib
import os
import time
from contextlib import contextmanager
from pathlib import Path
import paramiko
from network_automation.results import OperationResult
from network_automation.platforms.huawei_vrp.debug_log import debug_log
from network_automation.platforms.huawei_vrp.info import get_flash_info

# Fixed pause between upload_with_retry() attempts. Not user-configurable —
# only the attempt count (upload_retries) and per-attempt transfer timeout
# (upload_timeout) are exposed on HuaweiVRP.
_RETRY_DELAY_SECONDS = 1

# How often, at most, the sftp.put() progress callback (see
# _make_progress_callback()) is allowed to log/ping while a long transfer
# runs. Well under this device's console idle-timeout (observed to fire
# during a real ~15-minute firmware transfer) — an SSH-transport-level
# keepalive (client.device's keepalive=30) does NOT reset it, since it
# never touches the CLI application layer.
_CLI_KEEPALIVE_INTERVAL_SECONDS = 60


# -------------------------------------------------------
# Helper (pure logic)
# -------------------------------------------------------

def _connect_dedicated(client) -> paramiko.SSHClient:
    """
    Connect a plain paramiko SSHClient using the same credentials as
    client.device — deliberately NOT Netmiko's ConnectHandler, which
    always opens an interactive shell channel as part of connecting.
    That's exactly the condition (an interactive shell channel sharing a
    transport with an SFTP channel) that makes this device's SFTP
    subsystem hang for minutes before resetting the connection — using
    ConnectHandler again for a "separate" connection just recreates the
    same problem with a second shell session. Plain paramiko opens only
    the channels we explicitly ask for. See
    docs/problems/huawei-vrp-sftp-open-failure.md.
    """
    device = client.device
    key_file = device.get("key_file")

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(
        hostname=device["host"],
        port=device.get("port") or 22,
        username=device["username"],
        password=device.get("password"),
        key_filename=os.path.abspath(os.path.expanduser(key_file)) if key_file else None,
        passphrase=device.get("passphrase"),
        look_for_keys=bool(device.get("use_keys")),
        allow_agent=False,
        disabled_algorithms=device.get("disabled_algorithms"),
    )
    return ssh


@contextmanager
def _dedicated_sftp(client, *, timeout: float | None = None):
    """
    Open SFTP on a brand-new, dedicated SSH connection with no
    interactive shell channel — never client.conn's interactive CLI
    session, and not a second Netmiko session either (see
    _connect_dedicated()).

    Also issues one warm-up sftp.normalize(".") before yielding: this
    device's SFTP server rejects an OPEN-for-write that's the very first
    request on a freshly opened channel with an empty SSH_FX_FAILURE —
    one prior read-only request on the same channel is enough to make
    every following write succeed. See
    docs/problems/huawei-vrp-sftp-open-failure.md for how both this and
    the shared-transport-hang issue were found.

    Closes the SFTP client and the dedicated connection on exit, even on
    exception.
    """
    debug_log(client, "opening dedicated SFTP connection (plain paramiko, no interactive shell channel)")
    ssh = _connect_dedicated(client)
    try:
        sftp = ssh.open_sftp()
        try:
            if timeout is not None:
                sftp.get_channel().settimeout(timeout)
            debug_log(client, "dedicated SFTP connection open, sending warm-up normalize('.')")
            cwd = sftp.normalize(".")
            debug_log(client, "warm-up normalize('.') ok, server cwd: %s", cwd)
            yield sftp
        finally:
            sftp.close()
    finally:
        ssh.close()
        debug_log(client, "dedicated SFTP connection closed")


def _make_progress_callback(client):
    """
    Build a paramiko sftp.put() progress callback: paramiko invokes it
    synchronously, on the same thread that called put(), on every chunk
    (tens of times per second for a large file) — throttled here to at
    most once every _CLI_KEEPALIVE_INTERVAL_SECONDS.

    Deliberately NOT a background thread (previous implementation): a
    prior version ran this on a separate threading.Thread, and its
    client.logger.info() calls never showed up in the Nautobot job log —
    Nautobot's Job.logger appears to be scoped to whichever thread
    actually runs Job.run() (Celery's task thread), so log calls from an
    independently spawned thread are silently lost. Running on put()'s
    own calling thread (the same one running Job.run()) avoids that
    entirely, as a side effect of using paramiko's own progress hook
    instead of polling from the side.

    Each call also nudges client.conn's interactive CLI session so its
    console idle-timeout doesn't fire while sftp.put() blocks this thread
    for minutes at a time — best-effort: if client.conn is already dead,
    logged at DEBUG only and swallowed, since the real error surfaces
    wherever client.conn is next actually used for something that matters
    (e.g. verify_remote_file's 'dir').

    The progress log itself goes through client._safe_log_info()
    (BaseClient) rather than client.logger.info() directly — same
    identical risk as wait_for_reconnect()'s heartbeat: an upload that's
    actually succeeding must never be aborted by a transient failure in
    the logger call itself.
    """
    state = {"last": time.monotonic(), "start": time.monotonic()}

    def _callback(bytes_transferred, total_bytes):
        now = time.monotonic()
        if now - state["last"] < _CLI_KEEPALIVE_INTERVAL_SECONDS:
            return
        state["last"] = now

        elapsed = int(now - state["start"])
        pct = (bytes_transferred / total_bytes * 100) if total_bytes else 0.0
        client._safe_log_info(
            "Upload progress: %.0f%% (%d/%d bytes, %ds elapsed)",
            pct, bytes_transferred, total_bytes, elapsed,
        )

        try:
            client.conn.send_command_timing("\n", read_timeout=5)
        except Exception as exc:
            debug_log(client, "CLI keepalive: client.conn unusable (%s)", exc)

    return _callback


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

    Opens its own dedicated SSH connection for SFTP (see
    _dedicated_sftp()) rather than reusing client.conn's interactive CLI
    session — that connection/channel is untouched by this function,
    apart from a periodic no-op keepalive+progress-log driven by
    sftp.put()'s own progress callback while the transfer runs (see
    _make_progress_callback()).

    - no connect/disconnect (of client.conn — this opens and closes its
      own separate SFTP connection internally, every call)
    - raises exceptions on failure
    """

    with _dedicated_sftp(client) as sftp:
        for path in files:
            if not path.exists():
                raise FileNotFoundError(path)

            remote_path = f"{remote_dir.rstrip('/')}/{path.name}"

            client.logger.info(
                "Uploading %s → %s",
                path,
                remote_path,
            )
            debug_log(client, "sftp.put starting: %s -> %s", path, remote_path)

            sftp.put(
                str(path),
                remote_path,
                callback=_make_progress_callback(client),
            )

            client.logger.info("Upload completed: %s → %s", path, remote_path)
            debug_log(client, "sftp.put finished: %s -> %s", path, remote_path)


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

    client.conn (the interactive CLI session used by the post-transfer
    verify_remote_file() call below) gets a periodic no-op keepalive for
    the duration of the transfer — driven by sftp.put()'s own progress
    callback, see _make_progress_callback() — since this device's console
    idle-timeout can otherwise kill it during a long transfer, which
    would fail verification (and trigger a wasted retry-from-scratch)
    even though the transfer itself succeeded.

    - no connect/disconnect
    - raises RuntimeError after exhausting all retries, chained to the last
      underlying exception
    - returns {filename: {"exists", "expected_size", "actual_size", "match"}}
    """
    last_exc = None

    for attempt in range(1, retries + 1):
        try:
            with _dedicated_sftp(client, timeout=timeout) as sftp:
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
                    sftp.put(
                        str(path),
                        remote_path,
                        callback=_make_progress_callback(client),
                    )
                    client.logger.info(
                        "Upload completed: %s → %s (attempt %d/%d)",
                        path, remote_path, attempt, retries,
                    )
                    debug_log(
                        client,
                        "upload attempt %d/%d finished: %s -> %s",
                        attempt, retries, path, remote_path,
                    )

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
