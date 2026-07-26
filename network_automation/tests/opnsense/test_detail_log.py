# network_automation/tests/opnsense/test_detail_log.py

import os
from types import SimpleNamespace

from network_automation.platforms.opnsense.detail_log import open_detail_log


def _client(*, debug_log_file=None):
    return SimpleNamespace(debug_log_file=debug_log_file)


# -------------------------------------------------------
# Disabled / unusable cases never raise
# -------------------------------------------------------

def test_no_file_created_when_debug_log_file_is_none():
    client = _client(debug_log_file=None)

    with open_detail_log(client) as dlog:
        dlog.raw("some line")
        dlog.event("some event")
        dlog.exception(RuntimeError("boom"))
        assert dlog.path is None


def test_no_file_created_when_debug_log_file_is_empty_string():
    client = _client(debug_log_file="")

    with open_detail_log(client) as dlog:
        dlog.raw("some line")
        assert dlog.path is None


def test_unwritable_path_never_raises(tmp_path, monkeypatch):
    client = _client(debug_log_file=str(tmp_path / "sub" / "detail.log"))

    monkeypatch.setattr(
        "network_automation.platforms.opnsense.detail_log.open",
        lambda *a, **k: (_ for _ in ()).throw(OSError("permission denied")),
        raising=False,
    )

    with open_detail_log(client) as dlog:
        dlog.raw("some line")
        dlog.event("some event")
        dlog.exception(RuntimeError("boom"))
        assert dlog.path is None
    # no exception propagated - test passing is the assertion


# -------------------------------------------------------
# Normal writing
# -------------------------------------------------------

def test_path_is_exposed_as_given(tmp_path):
    log_file = str(tmp_path / "detail.log")
    client = _client(debug_log_file=log_file)

    with open_detail_log(client) as dlog:
        assert dlog.path == log_file


def test_missing_parent_directory_is_created(tmp_path):
    log_file = str(tmp_path / "nested" / "dir" / "detail.log")
    client = _client(debug_log_file=log_file)

    with open_detail_log(client) as dlog:
        dlog.raw("line")

    assert os.path.exists(log_file)


def test_relative_path_with_no_directory_component_works(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = _client(debug_log_file="detail.log")

    with open_detail_log(client) as dlog:
        dlog.raw("line")

    assert (tmp_path / "detail.log").exists()


def test_raw_and_event_and_exception_are_written(tmp_path):
    log_file = str(tmp_path / "detail.log")
    client = _client(debug_log_file=log_file)

    with open_detail_log(client) as dlog:
        dlog.raw("[1/1] Fetching foo.pkg: .... done")
        dlog.event("Lost connection while polling %s (%s)", "update", "Socket is closed")
        try:
            raise RuntimeError("boom")
        except RuntimeError as exc:
            dlog.exception(exc)

    content = open(log_file).read()
    assert "[1/1] Fetching foo.pkg: .... done" in content
    assert "[EVENT] Lost connection while polling update (Socket is closed)" in content
    assert "[EXCEPTION]" in content
    assert "RuntimeError: boom" in content
    assert "Traceback" in content


# -------------------------------------------------------
# Overwrite semantics
# -------------------------------------------------------

def test_second_operation_overwrites_rather_than_appends(tmp_path):
    log_file = str(tmp_path / "detail.log")
    client = _client(debug_log_file=log_file)

    with open_detail_log(client) as dlog:
        dlog.raw("first run - line one")
        dlog.raw("first run - line two")

    with open_detail_log(client) as dlog:
        dlog.raw("second run - only line")

    content = open(log_file).read()
    assert "first run" not in content
    assert "second run - only line" in content
