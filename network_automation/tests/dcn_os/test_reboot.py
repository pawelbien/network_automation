# network_automation/tests/dcn_os/test_reboot.py

from unittest.mock import MagicMock, call

import pytest

from network_automation.platforms.dcn_os.reboot import reboot, wait_for_reconnect

_CONFIRM = "Process with reboot? [Y/N] "
_SAVE = "Current configuration has been changed, save it? [Y/N] "


def test_reboot_confirms_immediately(dcn_os_client):
    fake_conn = MagicMock()
    fake_conn.send_command_timing.return_value = _CONFIRM
    dcn_os_client.conn = fake_conn

    reboot(dcn_os_client)

    assert fake_conn.send_command_timing.call_args_list == [
        call("reload"),
        call("Y"),
    ]
    assert dcn_os_client.conn is None


def test_reboot_declines_save_then_confirms(dcn_os_client):
    fake_conn = MagicMock()
    fake_conn.send_command_timing.side_effect = [_SAVE, _CONFIRM, ""]
    dcn_os_client.conn = fake_conn

    reboot(dcn_os_client)

    assert fake_conn.send_command_timing.call_args_list == [
        call("reload"),
        call("N"),
        call("Y"),
    ]
    assert dcn_os_client.conn is None


def test_reboot_confirms_on_delayed_prompt(mocker, dcn_os_client):
    mocker.patch("network_automation.platforms.dcn_os.reboot.time.sleep")
    fake_conn = MagicMock()
    fake_conn.send_command_timing.side_effect = ["", _CONFIRM, ""]
    dcn_os_client.conn = fake_conn

    reboot(dcn_os_client)

    assert fake_conn.send_command_timing.call_args_list == [
        call("reload"),
        call(""),
        call("Y"),
    ]
    assert dcn_os_client.conn is None


def test_reboot_without_prompt_warns_and_sends_y(mocker, dcn_os_client):
    mocker.patch("network_automation.platforms.dcn_os.reboot.time.sleep")
    fake_conn = MagicMock()
    fake_conn.send_command_timing.return_value = ""
    dcn_os_client.conn = fake_conn
    dcn_os_client.logger = MagicMock()

    reboot(dcn_os_client)

    fake_conn.send_command_timing.assert_called_with("Y")
    assert call("N") not in fake_conn.send_command_timing.call_args_list
    dcn_os_client.logger.warning.assert_called_once()
    assert dcn_os_client.conn is None


def test_wait_for_reconnect_survives_logger_failure_during_heartbeat(mocker, dcn_os_client):
    dcn_os_client.reconnect_timeout = 300
    dcn_os_client.reconnect_delay = 1

    time_values = iter([1000.0, 1000.0, 1065.0, 1065.0])
    mocker.patch(
        "network_automation.platforms.dcn_os.reboot.time.time",
        side_effect=lambda: next(time_values),
    )
    mocker.patch("network_automation.platforms.dcn_os.reboot.time.sleep")

    not_ready_conn = MagicMock()
    not_ready_conn.send_command.side_effect = Exception("device not ready yet")
    online_conn = MagicMock()
    online_conn.send_command.return_value = (
        "  S5750E-28X-SI Device, Compiled on Jan 01 00:00:00 2024\n"
        "  SoftWare Package Version V700R001C001B001\n"
    )

    mocker.patch.object(
        dcn_os_client,
        "_open_connection",
        side_effect=[not_ready_conn, online_conn],
    )

    dcn_os_client.logger = MagicMock()
    dcn_os_client.logger.info.side_effect = [
        None,  # "Waiting for %s to reconnect..."
        RuntimeError("Lost connection to MySQL server during query"),  # heartbeat
        None,  # "Device fully online (SSH + CLI ready)."
    ]

    result = wait_for_reconnect(dcn_os_client)  # must not raise

    assert result is online_conn
    assert dcn_os_client.conn is online_conn
    assert dcn_os_client.logger.info.call_count == 3


def test_wait_for_reconnect_times_out(mocker, dcn_os_client):
    dcn_os_client.reconnect_timeout = 1
    dcn_os_client.reconnect_delay = 0

    time_values = iter([1000.0, 1000.0, 1002.0, 1002.0])
    mocker.patch(
        "network_automation.platforms.dcn_os.reboot.time.time",
        side_effect=lambda: next(time_values),
    )
    mocker.patch("network_automation.platforms.dcn_os.reboot.time.sleep")
    mocker.patch.object(
        dcn_os_client,
        "_open_connection",
        side_effect=Exception("connection refused"),
    )

    with pytest.raises(TimeoutError):
        wait_for_reconnect(dcn_os_client)
