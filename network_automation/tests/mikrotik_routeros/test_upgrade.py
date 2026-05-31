# network_automation/tests/mikrotik_routeros/test_upgrade.py

import pytest
from unittest.mock import MagicMock
from network_automation.platforms.mikrotik_routeros.upgrade import download_firmware
from network_automation.results import OperationResult


# ---------- Shared device output helpers ----------

_IDENTITY = "name: RouterOS-Device"


def _software_info(version: str) -> str:
    return f"""
        version: {version}
        architecture-name: arm64
        """


def _routerboard_info(current: str, upgrade: str) -> str:
    return f"""
           routerboard: yes
                 model: CCR2004-16G-2S+
         serial-number: HG6099981S2
      current-firmware: {current}
      upgrade-firmware: {upgrade}
        """


# ---------- Fixtures ----------

@pytest.fixture
def fake_conn():
    return MagicMock()


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

    fake_conn.send_command.side_effect = [
        _software_info("7.14"),
        _IDENTITY,
        _routerboard_info("7.14.0", "7.14.0"),
    ]

    mikrotik_client.upgrade()

    fake_conn.send_command_timing.assert_not_called()


def test_upgrade_success(mocker, mikrotik_client, fake_conn):
    mikrotik_client.firmware_delivery = "download"

    mocker.patch(
        "network_automation.base_client.ConnectHandler",
        return_value=fake_conn,
    )

    fake_conn.send_command.side_effect = [
        # get_info() before upgrade (current=7.13)
        _software_info("7.13"), _IDENTITY, _routerboard_info("7.13.0", "7.14.0"),
        # get_info() after reboot (final=7.14)
        _software_info("7.14"), _IDENTITY, _routerboard_info("7.14.0", "7.14.0"),
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
        # get_info() before upgrade
        _software_info("7.13"), _IDENTITY, _routerboard_info("7.13.0", "7.14.0"),
        # get_info() after reboot (version mismatch: 7.12 instead of 7.14)
        _software_info("7.12"), _IDENTITY, _routerboard_info("7.12.0", "7.14.0"),
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


def test_upgrade_returns_result(monkeypatch, mikrotik_client):
    monkeypatch.setattr(mikrotik_client, "connect", lambda: None)
    monkeypatch.setattr(mikrotik_client, "disconnect", lambda: None)

    monkeypatch.setattr(
        "network_automation.platforms.mikrotik_routeros.upgrade.download_firmware",
        lambda client: None,
    )

    monkeypatch.setattr(
        "network_automation.platforms.mikrotik_routeros.upgrade.get_info",
        lambda client: {"units": [{"arch": "x86_64", "version": client.version}]},
    )

    monkeypatch.setattr(mikrotik_client, "reboot", lambda: None)

    monkeypatch.setattr(
        mikrotik_client,
        "wait_for_reconnect",
        lambda: mikrotik_client.conn,
    )

    result = mikrotik_client.upgrade(return_result=True)

    assert isinstance(result, OperationResult)
    assert result.success is True
    assert result.operation == "upgrade"
