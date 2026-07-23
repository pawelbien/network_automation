# network_automation/tests/opnsense/test_debug_log.py

"""
Tests for opt-in DEBUG-level diagnostics (client.context.debug_log) on
the OPNsense platform - mirrors huawei_vrp/tests/test_debug_log.py.

Covers: off by default (zero DEBUG records), on when enabled (raw
command/response, result.metadata dumps), and that credentials never
leak into any log record regardless of debug_log.

No real network I/O - client.conn is mocked, matching test_client.py/
test_info.py.
"""

import logging

import pytest
from unittest.mock import MagicMock

from network_automation.context import ExecutionContext
from network_automation.platforms.opnsense.client import OPNsense

_SECRET_PASSWORD = "supersecret123"
_SECRET_PASSPHRASE = "supersecretpassphrase456"

_INFO_RESPONSES = [
    "fw1",
    "26.1.11_10",
    "13.2-RELEASE",
    "11:13AM  up 54 mins, 1 user, load averages: 0.58, 0.56, 0.54",
]


@pytest.fixture
def debug_client():
    """OPNsense client with debug_log enabled, carrying a fake secret."""
    return OPNsense(
        host="1.1.1.1",
        username="admin",
        password=_SECRET_PASSWORD,
        passphrase=_SECRET_PASSPHRASE,
        connect_retries=1,
        connect_delay=0,
        context=ExecutionContext(debug_log=True),
    )


def _fake_conn(responses):
    conn = MagicMock()
    conn.send_command.side_effect = list(responses)
    return conn


# -------------------------------------------------------
# Off by default: zero DEBUG records
# -------------------------------------------------------

def test_debug_log_off_by_default_get_info(caplog, monkeypatch, opnsense_client):
    caplog.set_level(logging.DEBUG)

    monkeypatch.setattr(opnsense_client, "connect", lambda: None)
    monkeypatch.setattr(opnsense_client, "disconnect", lambda: None)
    opnsense_client.conn = _fake_conn(_INFO_RESPONSES)

    opnsense_client.get_info()

    assert not any(r.levelname == "DEBUG" for r in caplog.records)


# -------------------------------------------------------
# Enabled: raw command/response + result.metadata dump
# -------------------------------------------------------

def test_debug_log_enabled_logs_raw_command_and_response(caplog, monkeypatch, debug_client):
    caplog.set_level(logging.DEBUG)

    monkeypatch.setattr(debug_client, "connect", lambda: None)
    monkeypatch.setattr(debug_client, "disconnect", lambda: None)
    debug_client.conn = _fake_conn(_INFO_RESPONSES)

    debug_client.get_info(return_result=True)

    debug_messages = [r.getMessage() for r in caplog.records if r.levelname == "DEBUG"]
    assert any("hostname" in m for m in debug_messages)
    assert any("fw1" in m for m in debug_messages)
    assert any(
        m.startswith("read_info() result.metadata:") and "units" in m
        for m in debug_messages
    )


def test_debug_log_enabled_firmware_check_logs_command(caplog, monkeypatch, debug_client):
    caplog.set_level(logging.DEBUG)

    monkeypatch.setattr(debug_client, "connect", lambda: None)
    monkeypatch.setattr(debug_client, "disconnect", lambda: None)
    monkeypatch.setattr(debug_client, "_ensure_shell", lambda: None)

    debug_client.conn = _fake_conn(
        ["ready", "OK", "ready", "***GOT REQUEST***\n...\n***DONE***"]
    )

    debug_client.check_updates(return_result=True)

    debug_messages = [r.getMessage() for r in caplog.records if r.levelname == "DEBUG"]
    assert any("configctl firmware check" in m for m in debug_messages)
    assert any(m.startswith("check_updates() result.metadata:") for m in debug_messages)


# -------------------------------------------------------
# Security: password/passphrase never appear in any log record
# -------------------------------------------------------

def test_debug_log_never_leaks_password_or_passphrase(caplog, monkeypatch, debug_client):
    caplog.set_level(logging.DEBUG)

    monkeypatch.setattr(debug_client, "connect", lambda: None)
    monkeypatch.setattr(debug_client, "disconnect", lambda: None)
    debug_client.conn = _fake_conn(_INFO_RESPONSES)

    debug_client.get_info()

    for record in caplog.records:
        message = record.getMessage()
        assert _SECRET_PASSWORD not in message
        assert _SECRET_PASSPHRASE not in message
