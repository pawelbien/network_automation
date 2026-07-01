# network_automation/tests/huawei_vrp/test_upgrade.py

import pytest
from unittest.mock import MagicMock

from network_automation.platforms.huawei_vrp.upgrade import (
    configure_next_startup,
    upgrade,
)
from network_automation.results import OperationResult


# ---------- Shared device output helpers ----------

_ESN = " ESN of device: 2S5001048324A0014851\n"

TARGET_FILENAME = "AR650A_V300R024C00SPC200.cc"


def _display_version(spc: str) -> str:
    return f"""\
Huawei Versatile Routing Platform Software
VRP (R) software, Version 5.170 (AR650 V300R024C00SPC{spc})
Copyright (C) 2011-2024 HUAWEI TECH CO., LTD
Huawei AR651 Router uptime is 2 weeks, 1 day, 12 hours, 21 minutes

MPU 0(Master) : uptime is 2 weeks, 1 day, 12 hours, 21 minutes
"""


def _display_startup(current_filename: str, next_filename: str) -> str:
    return f"""\
MainBoard:
  Startup system software:                   flash:/{current_filename}
  Next startup system software:              flash:/{next_filename}
  Startup patch package:                     null
  Next startup patch package:                null
"""


# ---------- Fixtures ----------

@pytest.fixture
def fake_conn():
    return MagicMock()


# ---------- configure_next_startup ----------

def test_configure_next_startup_success(huawei_client, fake_conn):
    huawei_client.conn = fake_conn

    fake_conn.send_command.side_effect = [
        "",  # ack for "startup system-software ..."
        _display_startup("old.cc", TARGET_FILENAME),
    ]

    configure_next_startup(huawei_client, TARGET_FILENAME)

    assert fake_conn.send_command.call_count == 2


def test_configure_next_startup_mismatch_raises(huawei_client, fake_conn):
    huawei_client.conn = fake_conn

    fake_conn.send_command.side_effect = [
        "",
        _display_startup("old.cc", "unexpected.cc"),
    ]

    with pytest.raises(RuntimeError):
        configure_next_startup(huawei_client, TARGET_FILENAME)


# ---------- upgrade workflow ----------

def test_upgrade_skipped_if_not_newer(mocker, huawei_client, fake_conn):
    huawei_client.firmware_version = "V300R024C00SPC100"
    huawei_client.firmware_file = "/tmp/AR650A_V300R024C00SPC100.cc"

    mocker.patch(
        "network_automation.base_client.ConnectHandler",
        return_value=fake_conn,
    )

    fake_conn.send_command.side_effect = [
        _display_version("100"), _ESN, _display_startup("old.cc", "old.cc"),
    ]

    mock_upload = mocker.patch(
        "network_automation.platforms.huawei_vrp.upgrade.upload_files"
    )

    huawei_client.upgrade()

    mock_upload.assert_not_called()


def test_upgrade_success(mocker, huawei_client, fake_conn):
    huawei_client.firmware_version = "V300R024C00SPC200"
    huawei_client.firmware_file = f"/tmp/{TARGET_FILENAME}"

    mocker.patch(
        "network_automation.base_client.ConnectHandler",
        return_value=fake_conn,
    )

    fake_conn.send_command.side_effect = [
        # get_info() before upgrade (current=100)
        _display_version("100"), _ESN, _display_startup("old.cc", "old.cc"),
        # configure_next_startup
        "", _display_startup("old.cc", TARGET_FILENAME),
        # get_info() after reboot (final=200)
        _display_version("200"), _ESN,
        _display_startup(TARGET_FILENAME, TARGET_FILENAME),
    ]

    mocker.patch(
        "network_automation.platforms.huawei_vrp.upgrade.upload_files"
    )

    mocker.patch.object(huawei_client, "reboot")
    mocker.patch.object(
        huawei_client,
        "wait_for_reconnect",
        return_value=fake_conn,
    )

    huawei_client.upgrade()

    huawei_client.reboot.assert_called_once()


def test_upgrade_raises_on_multiple_units(mocker, huawei_client):
    huawei_client.firmware_version = "V300R024C00SPC200"
    huawei_client.firmware_file = f"/tmp/{TARGET_FILENAME}"

    mocker.patch.object(huawei_client, "connect")
    mocker.patch.object(huawei_client, "disconnect")

    mocker.patch(
        "network_automation.platforms.huawei_vrp.upgrade.get_info",
        return_value={
            "units": [
                {"software_version": "V300R024C00SPC100"},
                {"software_version": "V300R024C00SPC100"},
            ]
        },
    )

    with pytest.raises(RuntimeError):
        upgrade(huawei_client)


def test_upgrade_version_mismatch_raises(mocker, huawei_client, fake_conn):
    huawei_client.firmware_version = "V300R024C00SPC200"
    huawei_client.firmware_file = f"/tmp/{TARGET_FILENAME}"

    mocker.patch(
        "network_automation.base_client.ConnectHandler",
        return_value=fake_conn,
    )

    fake_conn.send_command.side_effect = [
        # get_info() before upgrade
        _display_version("100"), _ESN, _display_startup("old.cc", "old.cc"),
        # configure_next_startup
        "", _display_startup("old.cc", TARGET_FILENAME),
        # get_info() after reboot (mismatch: still 100 instead of 200)
        _display_version("100"), _ESN,
        _display_startup(TARGET_FILENAME, TARGET_FILENAME),
    ]

    mocker.patch(
        "network_automation.platforms.huawei_vrp.upgrade.upload_files"
    )

    mocker.patch.object(huawei_client, "reboot")
    mocker.patch.object(
        huawei_client,
        "wait_for_reconnect",
        return_value=fake_conn,
    )

    with pytest.raises(RuntimeError):
        huawei_client.upgrade()


def test_upgrade_returns_result(monkeypatch, huawei_client):
    huawei_client.firmware_version = "V300R024C00SPC200"
    huawei_client.firmware_file = f"/tmp/{TARGET_FILENAME}"

    monkeypatch.setattr(huawei_client, "connect", lambda: None)
    monkeypatch.setattr(huawei_client, "disconnect", lambda: None)

    monkeypatch.setattr(
        "network_automation.platforms.huawei_vrp.upgrade.get_info",
        lambda client: {
            "units": [{"software_version": client.firmware_version}]
        },
    )
    monkeypatch.setattr(
        "network_automation.platforms.huawei_vrp.upgrade.upload_files",
        lambda client, **kwargs: None,
    )
    monkeypatch.setattr(
        "network_automation.platforms.huawei_vrp.upgrade.configure_next_startup",
        lambda client, filename: None,
    )
    monkeypatch.setattr(huawei_client, "reboot", lambda: None)
    monkeypatch.setattr(
        huawei_client,
        "wait_for_reconnect",
        lambda: huawei_client.conn,
    )

    result = huawei_client.upgrade(return_result=True)

    assert isinstance(result, OperationResult)
    assert result.success is True
    assert result.operation == "upgrade"
