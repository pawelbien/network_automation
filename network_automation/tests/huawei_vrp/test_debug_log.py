# network_automation/tests/huawei_vrp/test_debug_log.py

"""
Tests for opt-in DEBUG-level diagnostics (client.context.debug_log).

Covers: off by default (zero DEBUG records, no change to existing INFO/
WARNING behavior), on when enabled (raw command/response, result.metadata
dump, upload retry attempt logs), and that credentials never leak into any
log record regardless of debug_log.

No real network I/O — client.conn / SFTP are mocked, matching the style of
test_run.py / test_upload.py / test_info.py.
"""

import logging

import pytest
from unittest.mock import MagicMock

from network_automation.context import ExecutionContext
from network_automation.platforms.huawei_vrp.client import HuaweiVRP
from network_automation.platforms.huawei_vrp.upload import upload_with_retry


_DISPLAY_VERSION = """\
Huawei Versatile Routing Platform Software
VRP (R) software, Version 5.170 (AR650 V300R024C00SPC100)
Copyright (C) 2011-2024 HUAWEI TECH CO., LTD
Huawei AR651 Router uptime is 2 weeks, 1 day, 12 hours, 21 minutes

MPU 0(Master) : uptime is 2 weeks, 1 day, 12 hours, 21 minutes
"""

_DISPLAY_ESN = " ESN of device: 2S5001048324A0014851\n"

_DISPLAY_STARTUP = """\
MainBoard:
  Startup system software:                   flash:/fw.cc
  Next startup system software:              flash:/fw.cc
  Startup patch package:                     null
  Next startup patch package:                null
"""

_SECRET_PASSWORD = "supersecret123"
_SECRET_PASSPHRASE = "supersecretpassphrase456"


@pytest.fixture
def debug_client():
    """HuaweiVRP client with debug_log enabled, carrying a fake secret."""
    return HuaweiVRP(
        host="1.1.1.1",
        username="admin",
        password=_SECRET_PASSWORD,
        passphrase=_SECRET_PASSPHRASE,
        connect_retries=1,
        connect_delay=0,
        context=ExecutionContext(debug_log=True),
    )


# -------------------------------------------------------
# Off by default: zero DEBUG records, existing behavior unchanged
# -------------------------------------------------------

def test_debug_log_off_by_default_run(caplog, monkeypatch, huawei_client):
    caplog.set_level(logging.DEBUG)

    monkeypatch.setattr(huawei_client, "connect", lambda: None)
    monkeypatch.setattr(huawei_client, "disconnect", lambda: None)

    fake_conn = MagicMock()
    fake_conn.send_command.return_value = "OK response text"
    huawei_client.conn = fake_conn

    huawei_client.run("display version")

    assert not any(r.levelname == "DEBUG" for r in caplog.records)
    assert any(r.levelname == "INFO" for r in caplog.records)


def test_debug_log_off_by_default_get_info(caplog, monkeypatch, huawei_client):
    caplog.set_level(logging.DEBUG)

    monkeypatch.setattr(huawei_client, "connect", lambda: None)
    monkeypatch.setattr(huawei_client, "disconnect", lambda: None)

    fake_conn = MagicMock()
    fake_conn.send_command.side_effect = [_DISPLAY_VERSION, _DISPLAY_ESN, _DISPLAY_STARTUP]
    huawei_client.conn = fake_conn

    huawei_client.get_info()

    assert not any(r.levelname == "DEBUG" for r in caplog.records)


# -------------------------------------------------------
# Enabled: raw command/response + result.metadata dump
# -------------------------------------------------------

def test_debug_log_enabled_logs_raw_command_and_response(caplog, monkeypatch, debug_client):
    caplog.set_level(logging.DEBUG)

    monkeypatch.setattr(debug_client, "connect", lambda: None)
    monkeypatch.setattr(debug_client, "disconnect", lambda: None)

    fake_conn = MagicMock()
    fake_conn.send_command.return_value = "OK response text"
    debug_client.conn = fake_conn

    debug_client.run("display version")

    debug_messages = [r.getMessage() for r in caplog.records if r.levelname == "DEBUG"]
    assert any("display version" in m for m in debug_messages)
    assert any("OK response text" in m for m in debug_messages)


def test_debug_log_enabled_get_info_logs_result_metadata(caplog, monkeypatch, debug_client):
    caplog.set_level(logging.DEBUG)

    monkeypatch.setattr(debug_client, "connect", lambda: None)
    monkeypatch.setattr(debug_client, "disconnect", lambda: None)

    fake_conn = MagicMock()
    fake_conn.send_command.side_effect = [_DISPLAY_VERSION, _DISPLAY_ESN, _DISPLAY_STARTUP]
    debug_client.conn = fake_conn

    debug_client.get_info(return_result=True)

    debug_messages = [r.getMessage() for r in caplog.records if r.levelname == "DEBUG"]
    assert any(
        m.startswith("read_info() result.metadata:") and "units" in m
        for m in debug_messages
    )


def test_debug_log_enabled_upload_logs_result_metadata(caplog, monkeypatch, debug_client, tmp_path):
    caplog.set_level(logging.DEBUG)

    local_file = tmp_path / "config.cfg"
    local_file.write_text("version 5.170")

    monkeypatch.setattr(debug_client, "connect", lambda: None)
    monkeypatch.setattr(debug_client, "disconnect", lambda: None)

    fake_sftp = MagicMock()
    fake_conn = MagicMock()
    fake_conn.remote_conn_pre.open_sftp.return_value = fake_sftp
    debug_client.conn = fake_conn

    debug_client.upload(files=[str(local_file)], remote_dir="/flash/")

    debug_messages = [r.getMessage() for r in caplog.records if r.levelname == "DEBUG"]
    assert any(m.startswith("run_upload() result.metadata:") for m in debug_messages)


# -------------------------------------------------------
# upload_with_retry: attempt-start DEBUG log, WARNING failure log unaffected
# -------------------------------------------------------

class _FakeChannel:
    def settimeout(self, timeout):
        pass


class _FakeSFTP:
    def __init__(self, fail_first_n=0):
        self._fail_first_n = fail_first_n
        self._put_calls = 0
        self.channel = _FakeChannel()

    def get_channel(self):
        return self.channel

    def put(self, local, remote):
        self._put_calls += 1
        if self._put_calls <= self._fail_first_n:
            raise OSError("simulated transfer failure")

    def close(self):
        pass


class _FakeRemoteConnPre:
    def __init__(self, sftp):
        self._sftp = sftp

    def open_sftp(self):
        return self._sftp


class _FakeConn:
    def __init__(self, sftp):
        self.remote_conn_pre = _FakeRemoteConnPre(sftp)


def _mock_flash_info_for(mocker, files):
    mocker.patch(
        "network_automation.platforms.huawei_vrp.upload.get_flash_info",
        return_value={
            "files": [
                {"name": p.name, "size": p.stat().st_size, "is_dir": False}
                for p in files
            ],
            "free_bytes": 10_000_000,
        },
    )


def test_upload_with_retry_debug_log_on_attempt_when_enabled(caplog, mocker, debug_client, tmp_path):
    caplog.set_level(logging.DEBUG)

    local_file = tmp_path / "fw.cc"
    local_file.write_bytes(b"firmware contents")

    fake_sftp = _FakeSFTP()
    debug_client.conn = _FakeConn(fake_sftp)
    _mock_flash_info_for(mocker, [local_file])

    upload_with_retry(debug_client, files=[local_file], remote_dir="flash:/", timeout=30, retries=3)

    debug_messages = [r.getMessage() for r in caplog.records if r.levelname == "DEBUG"]
    assert any("attempt 1/3 starting" in m for m in debug_messages)


def test_upload_with_retry_warning_on_failure_unaffected_by_debug_flag(caplog, mocker, huawei_client, tmp_path):
    """
    WARNING with the failure reason is existing, always-on behavior — it
    must fire regardless of debug_log, and debug_log defaulting to off must
    not add any DEBUG "attempt ... starting" records.
    """
    caplog.set_level(logging.DEBUG)

    local_file = tmp_path / "fw.cc"
    local_file.write_bytes(b"firmware contents")

    fake_sftp = _FakeSFTP(fail_first_n=1)
    huawei_client.conn = _FakeConn(fake_sftp)
    _mock_flash_info_for(mocker, [local_file])
    mocker.patch("network_automation.platforms.huawei_vrp.upload.time.sleep")

    upload_with_retry(huawei_client, files=[local_file], remote_dir="flash:/", timeout=30, retries=3)

    warning_messages = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert any("Upload attempt 1/3 failed" in m for m in warning_messages)

    debug_messages = [r.getMessage() for r in caplog.records if r.levelname == "DEBUG"]
    assert not any("starting" in m for m in debug_messages)


# -------------------------------------------------------
# Security: password/passphrase never appear in any log record
# -------------------------------------------------------

def test_debug_log_never_leaks_password_or_passphrase(caplog, monkeypatch, debug_client):
    caplog.set_level(logging.DEBUG)

    monkeypatch.setattr(debug_client, "connect", lambda: None)
    monkeypatch.setattr(debug_client, "disconnect", lambda: None)

    fake_conn = MagicMock()
    fake_conn.send_command.side_effect = [_DISPLAY_VERSION, _DISPLAY_ESN, _DISPLAY_STARTUP]
    debug_client.conn = fake_conn

    debug_client.get_info()

    for record in caplog.records:
        message = record.getMessage()
        assert _SECRET_PASSWORD not in message
        assert _SECRET_PASSPHRASE not in message
