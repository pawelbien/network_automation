# network_automation/platforms/huawei_vrp/lock.py

"""
Huawei VRP concurrency lock.

Before any state-changing operation (currently: upgrade()), the library
must acquire an exclusive lock scoped to the device, so two such
operations can never run concurrently against the same device.

This is a file-based lock, keyed by host, stored under a configurable
directory (HuaweiVRP.lock_dir). It only protects against concurrent
operations launched from the same machine, not a distributed lock.
"""

import contextlib
import json
import os
import re
import time


class DeviceBusyError(RuntimeError):
    """
    Raised when a device's lock is already held by another (live, non-
    stale) operation. Subclasses RuntimeError for consistency with
    CLIError; kept distinct so callers can special-case "busy, try again
    later" without string-matching.
    """


def _lock_path(client) -> str:
    os.makedirs(client.lock_dir, exist_ok=True)
    safe_host = re.sub(r'[^A-Za-z0-9._-]', '_', str(client.host))
    return os.path.join(client.lock_dir, f"{safe_host}.lock")


def _process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # process exists but is owned by someone else — treat as alive
        return True
    return True


def _try_create(path: str) -> bool:
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False

    with os.fdopen(fd, "w") as f:
        json.dump({"pid": os.getpid(), "acquired_at": time.time()}, f)
    return True


def _is_stale(path: str, lock_timeout: float) -> bool:
    try:
        with open(path) as f:
            info = json.load(f)
        pid = info["pid"]
        acquired_at = info["acquired_at"]
    except (OSError, ValueError, KeyError):
        # unreadable/corrupt lock file — treat as reclaimable
        return True

    return not _process_alive(pid) and (time.time() - acquired_at) >= lock_timeout


@contextlib.contextmanager
def device_lock(client):
    """
    Acquire an exclusive, host-scoped lock for `client` for the duration
    of the `with` block, releasing it on success, failure, or exception.

    Raises DeviceBusyError immediately (no waiting/retrying) if the lock
    is already held by another live operation, or by a dead one whose
    lock hasn't yet aged past client.lock_timeout — never touches the
    device in that case.
    """
    path = _lock_path(client)

    if not _try_create(path):
        if not _is_stale(path, client.lock_timeout):
            raise DeviceBusyError(
                f"Device {client.host!r} is busy: lock held by another operation."
            )

        # Stale — reclaim. Another process could win this race; if so,
        # our create fails too and we report busy rather than looping.
        try:
            os.remove(path)
        except FileNotFoundError:
            pass

        if not _try_create(path):
            raise DeviceBusyError(
                f"Device {client.host!r} is busy: lock held by another operation."
            )

    try:
        yield
    finally:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
