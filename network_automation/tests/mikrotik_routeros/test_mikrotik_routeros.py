# network_automation/tests/mikrotik_routeros/test_mikrotik_routeros.py

import pytest
from unittest.mock import MagicMock
from network_automation.platforms.mikrotik_routeros.client import MikrotikRouterOS
from network_automation.platforms.mikrotik_routeros.info import (
    normalize_version,
    is_newer_version,
    get_software_info,
    get_hardware_info,
    read_info,
)
from network_automation.platforms.mikrotik_routeros.upgrade import download_firmware


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


# ---------- get_software_info helper ----------

def test_get_software_info_parsing(mikrotik_client, fake_conn):
    fake_conn.send_command.return_value = """
        uptime: 1d
        version: 7.13.5 (stable)
        architecture-name: arm64
    """
    mikrotik_client.conn = fake_conn

    info = get_software_info(mikrotik_client)

    assert info["arch"] == "arm64"
    assert info["version"] == "7.13.5 (stable)"


def test_get_software_info_missing_version(mikrotik_client, fake_conn):
    fake_conn.send_command.return_value = "architecture-name: arm64"
    mikrotik_client.conn = fake_conn

    with pytest.raises(ValueError, match="Version not found"):
        get_software_info(mikrotik_client)


def test_get_software_info_missing_arch(mikrotik_client, fake_conn):
    fake_conn.send_command.return_value = "version: 7.13.5"
    mikrotik_client.conn = fake_conn

    with pytest.raises(ValueError, match="Architecture not found"):
        get_software_info(mikrotik_client)


# ---------- get_hardware_info helper ----------

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

    info = get_hardware_info(mikrotik_client)

    assert info["serial"] == "HG6099981S2"
    assert info["model"] == "CCR2004-16G-2S+"
    assert info["bootloader_current_firmware"] == "7.19.1"
    assert info["bootloader_upgrade_firmware"] == "7.20.7"


def test_get_hardware_info_chr_raises(mikrotik_client, fake_conn):
    fake_conn.send_command.return_value = "bad command name routerboard (line 1 column 9)"
    mikrotik_client.conn = fake_conn

    with pytest.raises(RuntimeError, match="Hardware info not supported"):
        get_hardware_info(mikrotik_client)


def test_get_hardware_info_missing_serial(mikrotik_client, fake_conn):
    fake_conn.send_command.return_value = """
       routerboard: yes
             model: CCR2004-16G-2S+
  current-firmware: 7.19.1
  upgrade-firmware: 7.20.7
    """
    mikrotik_client.conn = fake_conn

    with pytest.raises(ValueError, match="Serial number not found"):
        get_hardware_info(mikrotik_client)


def test_get_hardware_info_missing_model(mikrotik_client, fake_conn):
    fake_conn.send_command.return_value = """
       routerboard: yes
     serial-number: HG6099981S2
  current-firmware: 7.19.1
  upgrade-firmware: 7.20.7
    """
    mikrotik_client.conn = fake_conn

    with pytest.raises(ValueError, match="Model not found"):
        get_hardware_info(mikrotik_client)


def test_get_hardware_info_missing_current_firmware(mikrotik_client, fake_conn):
    fake_conn.send_command.return_value = """
       routerboard: yes
             model: CCR2004-16G-2S+
     serial-number: HG6099981S2
  upgrade-firmware: 7.20.7
    """
    mikrotik_client.conn = fake_conn

    with pytest.raises(ValueError, match="Current firmware not found"):
        get_hardware_info(mikrotik_client)


def test_get_hardware_info_missing_upgrade_firmware(mikrotik_client, fake_conn):
    fake_conn.send_command.return_value = """
       routerboard: yes
             model: CCR2004-16G-2S+
     serial-number: HG6099981S2
  current-firmware: 7.19.1
    """
    mikrotik_client.conn = fake_conn

    with pytest.raises(ValueError, match="Upgrade firmware not found"):
        get_hardware_info(mikrotik_client)


# ---------- read_info workflow ----------

def test_read_info_with_hardware(monkeypatch, mikrotik_client, fake_conn):
    """Test read_info returns dict with software and hardware info."""
    monkeypatch.setattr(mikrotik_client, "connect", lambda: None)
    monkeypatch.setattr(mikrotik_client, "disconnect", lambda: None)
    
    mikrotik_client.conn = fake_conn
    
    fake_conn.send_command.side_effect = [
        """
        uptime: 1d
        version: 7.13.5 (stable)
        architecture-name: arm64
        """,
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
    assert info["arch"] == "arm64"
    assert info["version"] == "7.13.5 (stable)"
    assert info["serial"] == "HG6099981S2"
    assert info["model"] == "CCR2004-16G-2S+"
    assert info["bootloader_current_firmware"] == "7.19.1"
    assert info["bootloader_upgrade_firmware"] == "7.20.7"
    
    # Check client state
    assert mikrotik_client.arch == "arm64"
    assert mikrotik_client.current_version == "7.13.5 (stable)"


def test_read_info_chr_no_hardware(monkeypatch, mikrotik_client, fake_conn):
    """Test read_info returns dict with only software info on CHR."""
    monkeypatch.setattr(mikrotik_client, "connect", lambda: None)
    monkeypatch.setattr(mikrotik_client, "disconnect", lambda: None)
    
    mikrotik_client.conn = fake_conn
    
    fake_conn.send_command.side_effect = [
        """
        uptime: 1d
        version: 7.13.5 (stable)
        architecture-name: arm64
        """,
        "bad command name routerboard (line 1 column 9)",
    ]
    
    info = read_info(mikrotik_client)
    
    assert isinstance(info, dict)
    assert info["arch"] == "arm64"
    assert info["version"] == "7.13.5 (stable)"
    assert "serial" not in info
    assert "model" not in info
    assert "bootloader_current_firmware" not in info
    assert "bootloader_upgrade_firmware" not in info


def test_read_info_returns_result(monkeypatch, mikrotik_client, fake_conn):
    """Test read_info returns OperationResult when return_result=True."""
    monkeypatch.setattr(mikrotik_client, "connect", lambda: None)
    monkeypatch.setattr(mikrotik_client, "disconnect", lambda: None)
    
    mikrotik_client.conn = fake_conn
    
    fake_conn.send_command.side_effect = [
        """
        uptime: 1d
        version: 7.13.5 (stable)
        architecture-name: arm64
        """,
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
    assert result.metadata["arch"] == "arm64"
    assert result.metadata["version"] == "7.13.5 (stable)"
    assert result.metadata["serial"] == "HG6099981S2"
    assert result.metadata["model"] == "CCR2004-16G-2S+"


# ---------- download_firmware ----------

FILE_OUT_FLASH = (
    " 0 name=flash type=disk last-modified=2025-01-25 12:40:02\n"
    " 1 name=flash/skins type=directory last-modified=1970-01-01 01:00:18\n"
    " 2 name=flash/routeros-7.14-arm64.npk type=package size=12.3MiB "
    "last-modified=2025-12-26 20:00:00\n"
)

FILE_OUT_NOFLASH = (
    " 0 name=mt3-r1-20251216-1307.backup type=backup size=40.2KiB\n"
    " 1 name=mt3-r1-20251216-1153.backup type=backup size=40.0KiB\n"
    " 2 name=pub type=directory last-modified=2021-08-19 14:38:58\n"
    " 3 name=skins type=directory last-modified=1970-01-01 01:00:08\n"
    " 4 name=routeros-7.14-arm64.npk type=package size=12.5MiB "
    "last-modified=2025-12-26 20:00:00\n"
)


def test_download_firmware_skips_if_exists_flash(mikrotik_client, fake_conn):
    mikrotik_client.conn = fake_conn
    mikrotik_client.arch = "arm64"
    mikrotik_client.version = "7.14"

    fake_conn.send_command.side_effect = [
        FILE_OUT_FLASH,
        FILE_OUT_FLASH,
    ]

    download_firmware(mikrotik_client)

    fake_conn.send_command_timing.assert_not_called()


def test_download_firmware_skips_if_exists_noflash(mikrotik_client, fake_conn):
    mikrotik_client.conn = fake_conn
    mikrotik_client.arch = "arm64"
    mikrotik_client.version = "7.14"

    fake_conn.send_command.side_effect = [
        FILE_OUT_NOFLASH,
        FILE_OUT_NOFLASH,
    ]

    download_firmware(mikrotik_client)

    fake_conn.send_command_timing.assert_not_called()


def test_download_firmware_fetch_and_validate(mikrotik_client, fake_conn):
    mikrotik_client.conn = fake_conn
    mikrotik_client.arch = "arm64"
    mikrotik_client.version = "7.14"

    fake_conn.send_command.side_effect = [
        "",
        FILE_OUT_FLASH,
    ]
    fake_conn.send_command_timing.return_value = "finished"

    download_firmware(mikrotik_client)

    fake_conn.send_command_timing.assert_called_once()


def test_download_firmware_too_small(mikrotik_client, fake_conn):
    mikrotik_client.conn = fake_conn
    mikrotik_client.arch = "arm64"
    mikrotik_client.version = "7.14"

    small_out = FILE_OUT_NOFLASH.replace("12.5MiB", "5.0MiB")

    fake_conn.send_command.side_effect = [
        "",
        small_out,
    ]

    with pytest.raises(RuntimeError):
        download_firmware(mikrotik_client)


# ---------- upgrade workflow ----------

def test_upgrade_skipped_if_not_newer(mocker, mikrotik_client, fake_conn):
    mikrotik_client.firmware_delivery = "download"

    mocker.patch(
        "network_automation.base_client.ConnectHandler",
        return_value=fake_conn,
    )

    fake_conn.send_command.return_value = """
        version: 7.14
        architecture-name: arm64
    """

    mikrotik_client.upgrade()

    fake_conn.send_command_timing.assert_not_called()


def test_upgrade_success(mocker, mikrotik_client, fake_conn):
    mikrotik_client.firmware_delivery = "download"

    mocker.patch(
        "network_automation.base_client.ConnectHandler",
        return_value=fake_conn,
    )

    fake_conn.send_command.side_effect = [
        """
        version: 7.13
        architecture-name: arm64
        """,
        """
        version: 7.14
        architecture-name: arm64
        """,
    ]

    fake_conn.send_command_timing.return_value = "rebooting"

    mocker.patch.object(
        mikrotik_client,
        "wait_for_reconnect",
        return_value=fake_conn,
    )

    mock_download = mocker.patch(
        "network_automation.platforms.mikrotik_routeros.upgrade.download_firmware"
    )

    mocker.patch.object(mikrotik_client, "reboot")

    mikrotik_client.upgrade()

    mock_download.assert_called_once_with(mikrotik_client)
    mikrotik_client.reboot.assert_called_once()


def test_upgrade_version_mismatch(mocker, mikrotik_client, fake_conn):
    mikrotik_client.firmware_delivery = "download"

    mocker.patch(
        "network_automation.base_client.ConnectHandler",
        return_value=fake_conn,
    )

    fake_conn.send_command.side_effect = [
        """
        version: 7.13
        architecture-name: arm64
        """,
        """
        version: 7.12
        architecture-name: arm64
        """,
    ]

    mocker.patch.object(
        mikrotik_client,
        "wait_for_reconnect",
        return_value=fake_conn,
    )

    mocker.patch(
        "network_automation.platforms.mikrotik_routeros.upgrade.download_firmware"
    )

    mocker.patch.object(mikrotik_client, "reboot")

    with pytest.raises(RuntimeError):
        mikrotik_client.upgrade()
