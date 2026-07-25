# network_automation/tests/opnsense/test_detail_log.py

import os
from types import SimpleNamespace

from network_automation.platforms.opnsense.detail_log import open_detail_log


_USE_TMP_PATH = object()


def _client(tmp_path, *, debug_log_dir=_USE_TMP_PATH, host="10.0.0.1", device_name=None):
    return SimpleNamespace(
        host=host,
        debug_log_dir=str(tmp_path) if debug_log_dir is _USE_TMP_PATH else debug_log_dir,
        context=SimpleNamespace(device_name=device_name),
    )


def _log_path(tmp_path, device_label, action_name="update"):
    return os.path.join(tmp_path, f"{device_label}_{action_name}.log")


# -------------------------------------------------------
# Disabled / unusable cases never raise
# -------------------------------------------------------

def test_no_file_created_when_debug_log_dir_is_none(tmp_path):
    client = _client(tmp_path, debug_log_dir=None, host="10.0.0.1")

    with open_detail_log(client, "update") as dlog:
        dlog.raw("some line")
        dlog.event("some event")
        dlog.exception(RuntimeError("boom"))
        assert dlog.path is None

    assert list(tmp_path.iterdir()) == []


def test_no_file_created_when_debug_log_dir_is_empty_string(tmp_path):
    client = _client(tmp_path, debug_log_dir="", host="10.0.0.1")

    with open_detail_log(client, "update") as dlog:
        dlog.raw("some line")

    assert list(tmp_path.iterdir()) == []


def test_unwritable_directory_never_raises(tmp_path, monkeypatch):
    client = _client(tmp_path, host="10.0.0.1")

    monkeypatch.setattr(
        "network_automation.platforms.opnsense.detail_log.open",
        lambda *a, **k: (_ for _ in ()).throw(OSError("permission denied")),
        raising=False,
    )

    with open_detail_log(client, "update") as dlog:
        dlog.raw("some line")
        dlog.event("some event")
        dlog.exception(RuntimeError("boom"))
        assert dlog.path is None
    # no exception propagated - test passing is the assertion


# -------------------------------------------------------
# Normal writing
# -------------------------------------------------------

def test_path_is_exposed_when_a_file_is_actually_written(tmp_path):
    client = _client(tmp_path, host="10.0.0.1")

    with open_detail_log(client, "update") as dlog:
        assert dlog.path == _log_path(tmp_path, "10.0.0.1", "update")


def test_raw_and_event_and_exception_are_written(tmp_path):
    client = _client(tmp_path, host="10.0.0.1")

    with open_detail_log(client, "update") as dlog:
        dlog.raw("[1/1] Fetching foo.pkg: .... done")
        dlog.event("Lost connection while polling %s (%s)", "update", "Socket is closed")
        try:
            raise RuntimeError("boom")
        except RuntimeError as exc:
            dlog.exception(exc)

    content = open(_log_path(tmp_path, "10.0.0.1")).read()
    assert "[1/1] Fetching foo.pkg: .... done" in content
    assert "[EVENT] Lost connection while polling update (Socket is closed)" in content
    assert "[EXCEPTION]" in content
    assert "RuntimeError: boom" in content
    assert "Traceback" in content


def test_filename_prefers_context_device_name_over_host(tmp_path):
    client = _client(tmp_path, host="10.0.0.1", device_name="fw-branch-01")

    with open_detail_log(client, "upgrade") as dlog:
        dlog.raw("line")

    assert os.path.exists(_log_path(tmp_path, "fw-branch-01", "upgrade"))
    assert not os.path.exists(_log_path(tmp_path, "10.0.0.1", "upgrade"))


def test_filename_falls_back_to_host_without_device_name(tmp_path):
    client = _client(tmp_path, host="10.0.0.1", device_name=None)

    with open_detail_log(client, "update") as dlog:
        dlog.raw("line")

    assert os.path.exists(_log_path(tmp_path, "10.0.0.1", "update"))


def test_device_label_with_unsafe_characters_is_slugified_for_the_filesystem(tmp_path):
    client = _client(tmp_path, host="10.0.0.1", device_name="fw/branch 01")

    with open_detail_log(client, "update") as dlog:
        dlog.raw("line")

    assert os.path.exists(_log_path(tmp_path, "fw_branch_01", "update"))


# -------------------------------------------------------
# Overwrite semantics
# -------------------------------------------------------

def test_second_operation_overwrites_rather_than_appends(tmp_path):
    client = _client(tmp_path, host="10.0.0.1")

    with open_detail_log(client, "update") as dlog:
        dlog.raw("first run - line one")
        dlog.raw("first run - line two")

    with open_detail_log(client, "update") as dlog:
        dlog.raw("second run - only line")

    content = open(_log_path(tmp_path, "10.0.0.1")).read()
    assert "first run" not in content
    assert "second run - only line" in content


def test_different_actions_get_separate_files(tmp_path):
    client = _client(tmp_path, host="10.0.0.1")

    with open_detail_log(client, "update") as dlog:
        dlog.raw("update run")
    with open_detail_log(client, "upgrade") as dlog:
        dlog.raw("upgrade run")

    assert "update run" in open(_log_path(tmp_path, "10.0.0.1", "update")).read()
    assert "upgrade run" in open(_log_path(tmp_path, "10.0.0.1", "upgrade")).read()
