# network_automation/tests/opnsense/test_info.py

import pytest
from unittest.mock import MagicMock
from network_automation.results import OperationResult
from network_automation.platforms.opnsense.info import (
    _get_hostname,
    _get_opnsense_version,
    _get_freebsd_version,
    _get_uptime,
    get_info,
    read_info,
)


_HOSTNAME = "fw01.example.com"
_OPNSENSE_VERSION = "OPNsense 24.7.2_1"
_FREEBSD_VERSION = "14.1-RELEASE-p6"
_UPTIME = "3:45PM up 10 days, 4:32, 1 user, load averages: 0.10, 0.08, 0.05"


# ---------- Fixtures ----------

@pytest.fixture
def fake_conn():
    return MagicMock()


# ---------- _get_hostname ----------

def test_get_hostname_parsing(opnsense_client, fake_conn):
    fake_conn.send_command.return_value = _HOSTNAME
    opnsense_client.conn = fake_conn

    assert _get_hostname(opnsense_client) == _HOSTNAME


def test_get_hostname_empty_raises(opnsense_client, fake_conn):
    fake_conn.send_command.return_value = ""
    opnsense_client.conn = fake_conn

    with pytest.raises(ValueError, match="Hostname not found"):
        _get_hostname(opnsense_client)


# ---------- _get_opnsense_version ----------

def test_get_opnsense_version_parsing(opnsense_client, fake_conn):
    fake_conn.send_command.return_value = _OPNSENSE_VERSION
    opnsense_client.conn = fake_conn

    assert _get_opnsense_version(opnsense_client) == _OPNSENSE_VERSION


def test_get_opnsense_version_empty_raises(opnsense_client, fake_conn):
    fake_conn.send_command.return_value = "   "
    opnsense_client.conn = fake_conn

    with pytest.raises(ValueError, match="OPNsense version not found"):
        _get_opnsense_version(opnsense_client)


# ---------- _get_freebsd_version / _get_uptime (best-effort) ----------

def test_get_freebsd_version_parsing(opnsense_client, fake_conn):
    fake_conn.send_command.return_value = _FREEBSD_VERSION
    opnsense_client.conn = fake_conn

    assert _get_freebsd_version(opnsense_client) == _FREEBSD_VERSION


def test_get_freebsd_version_command_error_returns_none(opnsense_client, fake_conn):
    fake_conn.send_command.side_effect = Exception("unknown command")
    opnsense_client.conn = fake_conn

    assert _get_freebsd_version(opnsense_client) is None


def test_get_uptime_parsing(opnsense_client, fake_conn):
    fake_conn.send_command.return_value = _UPTIME
    opnsense_client.conn = fake_conn

    assert _get_uptime(opnsense_client) == _UPTIME


def test_get_uptime_empty_returns_none(opnsense_client, fake_conn):
    fake_conn.send_command.return_value = ""
    opnsense_client.conn = fake_conn

    assert _get_uptime(opnsense_client) is None


# ---------- get_info ----------

def test_get_info_parsing(opnsense_client, fake_conn):
    fake_conn.send_command.side_effect = [
        _HOSTNAME,
        _OPNSENSE_VERSION,
        _FREEBSD_VERSION,
        _UPTIME,
    ]
    opnsense_client.conn = fake_conn

    info = get_info(opnsense_client)

    assert info == {
        "units": [
            {
                "id": 0,
                "role": "master",
                "hostname": _HOSTNAME,
                "opnsense_version": _OPNSENSE_VERSION,
                "freebsd_version": _FREEBSD_VERSION,
                "uptime": _UPTIME,
            }
        ]
    }
    assert opnsense_client.hostname == _HOSTNAME
    assert opnsense_client.opnsense_version == _OPNSENSE_VERSION


def test_get_info_missing_version_raises(opnsense_client, fake_conn):
    fake_conn.send_command.side_effect = [_HOSTNAME, ""]
    opnsense_client.conn = fake_conn

    with pytest.raises(ValueError, match="OPNsense version not found"):
        get_info(opnsense_client)


# ---------- read_info workflow ----------

def test_read_info_returns_units(monkeypatch, opnsense_client, fake_conn):
    monkeypatch.setattr(opnsense_client, "connect", lambda: None)
    monkeypatch.setattr(opnsense_client, "disconnect", lambda: None)
    monkeypatch.setattr(opnsense_client, "_ensure_shell", lambda: None)

    opnsense_client.conn = fake_conn
    fake_conn.send_command.side_effect = [
        _HOSTNAME,
        _OPNSENSE_VERSION,
        _FREEBSD_VERSION,
        _UPTIME,
    ]

    info = read_info(opnsense_client)

    assert isinstance(info, dict)
    assert "units" in info
    unit = info["units"][0]
    assert unit["hostname"] == _HOSTNAME
    assert unit["opnsense_version"] == _OPNSENSE_VERSION


def test_read_info_returns_result(monkeypatch, opnsense_client, fake_conn):
    monkeypatch.setattr(opnsense_client, "connect", lambda: None)
    monkeypatch.setattr(opnsense_client, "disconnect", lambda: None)
    monkeypatch.setattr(opnsense_client, "_ensure_shell", lambda: None)

    opnsense_client.conn = fake_conn
    fake_conn.send_command.side_effect = [
        _HOSTNAME,
        _OPNSENSE_VERSION,
        _FREEBSD_VERSION,
        _UPTIME,
    ]

    result = read_info(opnsense_client, return_result=True)

    assert isinstance(result, OperationResult)
    assert result.success is True
    assert result.operation == "info"
    assert result.metadata["units"][0]["hostname"] == _HOSTNAME


def test_read_info_calls_ensure_shell(monkeypatch, opnsense_client, fake_conn):
    monkeypatch.setattr(opnsense_client, "connect", lambda: None)
    monkeypatch.setattr(opnsense_client, "disconnect", lambda: None)

    ensure_shell_mock = MagicMock()
    monkeypatch.setattr(opnsense_client, "_ensure_shell", ensure_shell_mock)

    opnsense_client.conn = fake_conn
    fake_conn.send_command.side_effect = [
        _HOSTNAME,
        _OPNSENSE_VERSION,
        _FREEBSD_VERSION,
        _UPTIME,
    ]

    read_info(opnsense_client)

    ensure_shell_mock.assert_called_once()


def test_read_info_propagates_and_marks_failure(monkeypatch, opnsense_client, fake_conn):
    monkeypatch.setattr(opnsense_client, "connect", lambda: None)
    monkeypatch.setattr(opnsense_client, "disconnect", lambda: None)
    monkeypatch.setattr(opnsense_client, "_ensure_shell", lambda: None)

    opnsense_client.conn = fake_conn
    fake_conn.send_command.side_effect = ["", _OPNSENSE_VERSION]

    with pytest.raises(ValueError):
        read_info(opnsense_client)
