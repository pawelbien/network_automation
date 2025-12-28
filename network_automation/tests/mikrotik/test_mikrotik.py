import pytest
from unittest.mock import MagicMock
from network_automation.vendors.mikrotik.client import Mikrotik
from network_automation.vendors.mikrotik.info import (
    normalize_version,
    is_newer_version,
)
from network_automation.vendors.mikrotik.upgrade import download_firmware


# ---------- Fixtures ----------

@pytest.fixture
def updater():
    return Mikrotik(
        host="1.1.1.1",
        username="admin",
        key_file="key",
        passphrase="pass",
        firmware_version="7.14",
        connect_retries=1,
        connect_delay=0,
        reconnect_timeout=1,
        reconnect_delay=0,
        log_file="/tmp/test.log",
    )


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

def test_get_info_parsing(updater, fake_conn):
    fake_conn.send_command.return_value = """
        uptime: 1d
        version: 7.13.5 (stable)
        architecture-name: arm64
    """
    updater.conn = fake_conn

    updater.get_info()

    assert updater.arch == "arm64"
    assert updater.current_version == "7.13.5 (stable)"


def test_get_info_missing_arch(updater, fake_conn):
    fake_conn.send_command.return_value = "version: 7.13.5"
    updater.conn = fake_conn

    with pytest.raises(ValueError):
        updater.get_info()


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


def test_download_firmware_skips_if_exists_flash(updater, fake_conn):
    updater.conn = fake_conn
    updater.arch = "arm64"
    updater.version = "7.14"

    fake_conn.send_command.side_effect = [
        FILE_OUT_FLASH,   # initial -> exists
        FILE_OUT_FLASH,   # refresh
    ]

    download_firmware(updater)

    fake_conn.send_command_timing.assert_not_called()


def test_download_firmware_skips_if_exists_noflash(updater, fake_conn):
    updater.conn = fake_conn
    updater.arch = "arm64"
    updater.version = "7.14"

    fake_conn.send_command.side_effect = [
        FILE_OUT_NOFLASH,  # initial -> exists
        FILE_OUT_NOFLASH,  # refresh
    ]

    download_firmware(updater)

    fake_conn.send_command_timing.assert_not_called()


def test_download_firmware_fetch_and_validate(updater, fake_conn):
    updater.conn = fake_conn
    updater.arch = "arm64"
    updater.version = "7.14"

    fake_conn.send_command.side_effect = [
        "",               # not exists
        FILE_OUT_FLASH,   # after fetch
    ]
    fake_conn.send_command_timing.return_value = "finished"

    download_firmware(updater)


    fake_conn.send_command_timing.assert_called_once()


def test_download_firmware_too_small(updater, fake_conn):
    updater.conn = fake_conn
    updater.arch = "arm64"
    updater.version = "7.14"

    small_out = FILE_OUT_NOFLASH.replace("12.5MiB", "5.0MiB")

    fake_conn.send_command.side_effect = [
        "",         # not exists
        small_out,  # too small
    ]

    with pytest.raises(RuntimeError):
        download_firmware(updater)

# ---------- upgrade workflow ----------

def test_upgrade_skipped_if_not_newer(mocker, updater, fake_conn):
    mocker.patch("network_automation.vendors.mikrotik.client.ConnectHandler", return_value=fake_conn)

    fake_conn.send_command.return_value = """
        version: 7.14
        architecture-name: arm64
    """

    updater.upgrade()

    fake_conn.send_command_timing.assert_not_called()


def test_upgrade_success(mocker, updater, fake_conn):
    mocker.patch(
        "network_automation.vendors.mikrotik.client.ConnectHandler",
        return_value=fake_conn
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

    mocker.patch.object(updater, "wait_for_reconnect", return_value=fake_conn)
    mock_download = mocker.patch(
        "network_automation.vendors.mikrotik.upgrade.download_firmware"
    )
    mocker.patch.object(updater, "reboot")

    updater.upgrade()

    mock_download.assert_called_once_with(updater)
    updater.reboot.assert_called_once()


def test_upgrade_version_mismatch(mocker, updater, fake_conn):
    mocker.patch("network_automation.vendors.mikrotik.client.ConnectHandler", return_value=fake_conn)

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

    mocker.patch.object(updater, "wait_for_reconnect", return_value=fake_conn)
    mocker.patch("network_automation.vendors.mikrotik.upgrade.download_firmware")
    mocker.patch.object(updater, "reboot")

    with pytest.raises(RuntimeError):
        updater.upgrade()
