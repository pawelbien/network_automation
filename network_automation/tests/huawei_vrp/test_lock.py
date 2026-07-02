# network_automation/tests/huawei_vrp/test_lock.py

import json
import os
import time
from types import SimpleNamespace

import pytest

from network_automation.platforms.huawei_vrp.lock import (
    DeviceBusyError,
    _lock_path,
    device_lock,
)


def _client(tmp_path, *, host="1.1.1.1", lock_timeout=3600):
    return SimpleNamespace(host=host, lock_dir=str(tmp_path), lock_timeout=lock_timeout)


def test_device_lock_acquires_and_releases_on_success(tmp_path):
    client = _client(tmp_path)
    path = _lock_path(client)

    with device_lock(client):
        assert os.path.exists(path)

    assert not os.path.exists(path)


def test_device_lock_releases_on_exception(tmp_path):
    client = _client(tmp_path)
    path = _lock_path(client)

    with pytest.raises(RuntimeError, match="boom"):
        with device_lock(client):
            assert os.path.exists(path)
            raise RuntimeError("boom")

    assert not os.path.exists(path)


def test_device_lock_raises_busy_when_held_by_live_process(tmp_path):
    client = _client(tmp_path)
    path = _lock_path(client)
    os.makedirs(os.path.dirname(path), exist_ok=True)

    # Simulate a lock held by this same (very much alive) test process.
    with open(path, "w") as f:
        json.dump({"pid": os.getpid(), "acquired_at": time.time()}, f)

    with pytest.raises(DeviceBusyError, match="busy"):
        with device_lock(client):
            pass  # pragma: no cover — must not be reached


def test_device_lock_reclaims_stale_lock_from_dead_process(tmp_path):
    client = _client(tmp_path, lock_timeout=1)
    path = _lock_path(client)
    os.makedirs(os.path.dirname(path), exist_ok=True)

    # A pid that (almost certainly) doesn't exist, aged well past lock_timeout.
    dead_pid = 2**31 - 1
    with open(path, "w") as f:
        json.dump({"pid": dead_pid, "acquired_at": time.time() - 10}, f)

    with device_lock(client):
        assert os.path.exists(path)

    assert not os.path.exists(path)


def test_device_lock_does_not_reclaim_dead_pid_before_timeout_elapses(tmp_path):
    client = _client(tmp_path, lock_timeout=3600)
    path = _lock_path(client)
    os.makedirs(os.path.dirname(path), exist_ok=True)

    dead_pid = 2**31 - 1
    with open(path, "w") as f:
        json.dump({"pid": dead_pid, "acquired_at": time.time()}, f)

    with pytest.raises(DeviceBusyError):
        with device_lock(client):
            pass  # pragma: no cover — must not be reached


def test_device_lock_reclaims_corrupt_lock_file(tmp_path):
    client = _client(tmp_path)
    path = _lock_path(client)
    os.makedirs(os.path.dirname(path), exist_ok=True)

    with open(path, "w") as f:
        f.write("not json")

    with device_lock(client):
        assert os.path.exists(path)

    assert not os.path.exists(path)


def test_device_lock_never_touches_device_when_busy(tmp_path):
    # DeviceBusyError must be raised without any device interaction — the
    # caller (upgrade()) relies on this to abort before client.connect().
    client = _client(tmp_path)
    path = _lock_path(client)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump({"pid": os.getpid(), "acquired_at": time.time()}, f)

    touched = []
    with pytest.raises(DeviceBusyError):
        with device_lock(client):
            touched.append(True)  # pragma: no cover

    assert touched == []


def test_lock_path_is_keyed_by_host(tmp_path):
    client_a = _client(tmp_path, host="10.0.0.1")
    client_b = _client(tmp_path, host="10.0.0.2")

    assert _lock_path(client_a) != _lock_path(client_b)
