# network_automation/tests/mikrotik_routeros/test_info.py

import pytest
from unittest.mock import MagicMock
from network_automation.platforms.mikrotik_routeros.info import (
    normalize_version,
    is_newer_version,
    _get_software_info,
    _get_hardware_info,
    _get_system_identity,
    get_info,
    read_info,
)


# ---------- Fixtures ----------

@pytest.fixture
def fake_conn():
    return MagicMock()


# ---------- Version helpers ----------

def test_normalize_version_basic():
    assert normalize_version("7.14") == (7, 14, 0)
    assert normalize_version("7.14.1") == (7, 14, 1)
    assert normalize_version("7.14.1 (stable)") == (7, 14, 1)


def test_is_newer_version():
    assert is_newer_version("7.13.5", "7.14") is True
    assert is_newer_version("7.14", "7.14") is False
    assert is_newer_version("7.15", "7.14") is False


# ---------- get_info ----------

def test_get_info_parsing(mikrotik_client, fake_conn):
    fake_conn.send_command.return_value = """
        uptime: 1d
        version: 7.13.5 (stable)
        architecture-name: arm64
    """
    mikrotik_client.conn = fake_conn

    mikrotik_client.get_info()

    assert mikrotik_client.arch == "arm64"
    assert mikrotik_client.current_version == "7.13.5 (stable)"


def test_get_info_missing_arch(mikrotik_client, fake_conn):
    fake_conn.send_command.return_value = "version: 7.13.5"
    mikrotik_client.conn = fake_conn

    with pytest.raises(ValueError):
        mikrotik_client.get_info()


# ---------- _get_software_info helper ----------

def test_get_software_info_parsing(mikrotik_client, fake_conn):
    fake_conn.send_command.return_value = """
        uptime: 1d
        version: 7.13.5 (stable)
        architecture-name: arm64
    """
    mikrotik_client.conn = fake_conn

    info = _get_software_info(mikrotik_client)

    assert info["arch"] == "arm64"
    assert info["version"] == "7.13.5 (stable)"


def test_get_software_info_missing_version(mikrotik_client, fake_conn):
    fake_conn.send_command.return_value = "architecture-name: arm64"
    mikrotik_client.conn = fake_conn

    with pytest.raises(ValueError, match="Version not found"):
        _get_software_info(mikrotik_client)


def test_get_software_info_missing_arch(mikrotik_client, fake_conn):
    fake_conn.send_command.return_value = "version: 7.13.5"
    mikrotik_client.conn = fake_conn

    with pytest.raises(ValueError, match="Architecture not found"):
        _get_software_info(mikrotik_client)


# ---------- _get_hardware_info helper ----------

def test_get_hardware_info_parsing(mikrotik_client, fake_conn):
    fake_conn.send_command.return_value = """
       routerboard: yes
             model: CCR2004-16G-2S+
          revision: r2
     serial-number: HG6099981S2
  current-firmware: 7.19.1
  upgrade-firmware: 7.20.7
    """
    mikrotik_client.conn = fake_conn

    info = _get_hardware_info(mikrotik_client)

    assert info["serial"] == "HG6099981S2"
    assert info["model"] == "CCR2004-16G-2S+"
    assert info["bootloader_current_firmware"] == "7.19.1"
    assert info["bootloader_upgrade_firmware"] == "7.20.7"


def test_get_hardware_info_chr_raises(mikrotik_client, fake_conn):
    fake_conn.send_command.return_value = "bad command name routerboard (line 1 column 9)"
    mikrotik_client.conn = fake_conn

    with pytest.raises(RuntimeError, match="Hardware info not supported"):
        _get_hardware_info(mikrotik_client)


def test_get_hardware_info_missing_serial(mikrotik_client, fake_conn):
    fake_conn.send_command.return_value = """
       routerboard: yes
             model: CCR2004-16G-2S+
  current-firmware: 7.19.1
  upgrade-firmware: 7.20.7
    """
    mikrotik_client.conn = fake_conn

    with pytest.raises(ValueError, match="Serial number not found"):
        _get_hardware_info(mikrotik_client)


def test_get_hardware_info_missing_model(mikrotik_client, fake_conn):
    fake_conn.send_command.return_value = """
       routerboard: yes
     serial-number: HG6099981S2
  current-firmware: 7.19.1
  upgrade-firmware: 7.20.7
    """
    mikrotik_client.conn = fake_conn

    with pytest.raises(ValueError, match="Model not found"):
        _get_hardware_info(mikrotik_client)


def test_get_hardware_info_missing_current_firmware(mikrotik_client, fake_conn):
    fake_conn.send_command.return_value = """
       routerboard: yes
             model: CCR2004-16G-2S+
     serial-number: HG6099981S2
  upgrade-firmware: 7.20.7
    """
    mikrotik_client.conn = fake_conn

    with pytest.raises(ValueError, match="Current firmware not found"):
        _get_hardware_info(mikrotik_client)


def test_get_hardware_info_missing_upgrade_firmware(mikrotik_client, fake_conn):
    fake_conn.send_command.return_value = """
       routerboard: yes
             model: CCR2004-16G-2S+
     serial-number: HG6099981S2
  current-firmware: 7.19.1
    """
    mikrotik_client.conn = fake_conn

    with pytest.raises(ValueError, match="Upgrade firmware not found"):
        _get_hardware_info(mikrotik_client)


# ---------- _get_system_identity helper ----------

def test_get_system_identity_parsing(mikrotik_client, fake_conn):
    fake_conn.send_command.return_value = "name: RouterOS-Device"
    mikrotik_client.conn = fake_conn

    info = _get_system_identity(mikrotik_client)

    assert info["name"] == "RouterOS-Device"


def test_get_system_identity_missing_name(mikrotik_client, fake_conn):
    fake_conn.send_command.return_value = "some other output"
    mikrotik_client.conn = fake_conn

    with pytest.raises(ValueError, match="System identity name not found"):
        _get_system_identity(mikrotik_client)


# ---------- read_info workflow ----------

def test_read_info_with_hardware(monkeypatch, mikrotik_client, fake_conn):
    monkeypatch.setattr(mikrotik_client, "connect", lambda: None)
    monkeypatch.setattr(mikrotik_client, "disconnect", lambda: None)

    mikrotik_client.conn = fake_conn

    fake_conn.send_command.side_effect = [
        """
        uptime: 1d
        version: 7.13.5 (stable)
        architecture-name: arm64
        """,
        "name: RouterOS-Device",
        """
       routerboard: yes
             model: CCR2004-16G-2S+
          revision: r2
     serial-number: HG6099981S2
  current-firmware: 7.19.1
  upgrade-firmware: 7.20.7
        """,
    ]

    info = read_info(mikrotik_client)

    assert isinstance(info, dict)
    assert "units" in info
    assert len(info["units"]) == 1

    unit = info["units"][0]
    assert unit["id"] == 0
    assert unit["role"] == "master"
    assert unit["arch"] == "arm64"
    assert unit["version"] == "7.13.5 (stable)"
    assert unit["name"] == "RouterOS-Device"
    assert unit["serial"] == "HG6099981S2"
    assert unit["model"] == "CCR2004-16G-2S+"
    assert unit["bootloader_current_firmware"] == "7.19.1"
    assert unit["bootloader_upgrade_firmware"] == "7.20.7"

    assert mikrotik_client.arch == "arm64"
    assert mikrotik_client.current_version == "7.13.5 (stable)"


def test_read_info_chr_no_hardware(monkeypatch, mikrotik_client, fake_conn):
    monkeypatch.setattr(mikrotik_client, "connect", lambda: None)
    monkeypatch.setattr(mikrotik_client, "disconnect", lambda: None)

    mikrotik_client.conn = fake_conn

    fake_conn.send_command.side_effect = [
        """
        uptime: 1d
        version: 7.13.5 (stable)
        architecture-name: arm64
        """,
        "name: RouterOS-Device",
        "bad command name routerboard (line 1 column 9)",
    ]

    info = read_info(mikrotik_client)

    assert isinstance(info, dict)
    assert "units" in info

    unit = info["units"][0]
    assert unit["arch"] == "arm64"
    assert unit["version"] == "7.13.5 (stable)"
    assert unit["name"] == "RouterOS-Device"
    assert unit["serial"] is None
    assert unit["model"] is None
    assert unit["bootloader_current_firmware"] is None
    assert unit["bootloader_upgrade_firmware"] is None


def test_read_info_returns_result(monkeypatch, mikrotik_client, fake_conn):
    monkeypatch.setattr(mikrotik_client, "connect", lambda: None)
    monkeypatch.setattr(mikrotik_client, "disconnect", lambda: None)

    mikrotik_client.conn = fake_conn

    fake_conn.send_command.side_effect = [
        """
        uptime: 1d
        version: 7.13.5 (stable)
        architecture-name: arm64
        """,
        "name: RouterOS-Device",
        """
       routerboard: yes
             model: CCR2004-16G-2S+
     serial-number: HG6099981S2
  current-firmware: 7.19.1
  upgrade-firmware: 7.20.7
        """,
    ]

    from network_automation.results import OperationResult

    result = read_info(mikrotik_client, return_result=True)

    assert isinstance(result, OperationResult)
    assert result.success is True
    assert result.operation == "info"
    assert "units" in result.metadata

    unit = result.metadata["units"][0]
    assert unit["arch"] == "arm64"
    assert unit["version"] == "7.13.5 (stable)"
    assert unit["name"] == "RouterOS-Device"
    assert unit["serial"] == "HG6099981S2"
    assert unit["model"] == "CCR2004-16G-2S+"
