# network_automation/tests/cisco_xr/test_reboot.py

from unittest.mock import MagicMock

import pytest

from network_automation.platforms.cisco_xr.reboot import reboot, wait_for_reconnect


def test_reboot_confirms_immediately(cisco_xr_client):
    fake_conn = MagicMock()
    fake_conn.send_command_timing.return_value = "Proceed with reload? [confirm]"
    cisco_xr_client.conn = fake_conn

    reboot(cisco_xr_client)

    fake_conn.send_command_timing.assert_any_call("reload")
    fake_conn.send_command_timing.assert_any_call("\n")
    assert cisco_xr_client.conn is None


def test_reboot_confirms_on_delayed_prompt(cisco_xr_client):
    fake_conn = MagicMock()
    fake_conn.send_command_timing.side_effect = [
        "",
        "Proceed with reload? [confirm]",
        None,
    ]
    cisco_xr_client.conn = fake_conn

    reboot(cisco_xr_client)

    fake_conn.send_command_timing.assert_any_call("reload")
    fake_conn.send_command_timing.assert_any_call("")
    fake_conn.send_command_timing.assert_any_call("\n")
    assert cisco_xr_client.conn is None


def test_wait_for_reconnect_survives_logger_failure_during_heartbeat(mocker, cisco_xr_client):
    cisco_xr_client.reconnect_timeout = 300
    cisco_xr_client.reconnect_delay = 1

    time_values = iter([1000.0, 1000.0, 1065.0, 1065.0])
    mocker.patch(
        "network_automation.platforms.cisco_xr.reboot.time.time",
        side_effect=lambda: next(time_values),
    )
    mocker.patch("network_automation.platforms.cisco_xr.reboot.time.sleep")

    not_ready_conn = MagicMock()
    not_ready_conn.send_command.side_effect = Exception("device not ready yet")
    online_conn = MagicMock()
    online_conn.send_command.return_value = "Cisco IOS XR Software, Version 7.3.2"

    mocker.patch(
        "network_automation.platforms.cisco_xr.reboot.ConnectHandler",
        side_effect=[not_ready_conn, online_conn],
    )

    cisco_xr_client.logger = MagicMock()
    cisco_xr_client.logger.info.side_effect = [
        None,  # "Waiting for %s to reconnect..."
        RuntimeError("Lost connection to MySQL server during query"),  # heartbeat
        None,  # "Device fully online (SSH + CLI ready)."
    ]

    result = wait_for_reconnect(cisco_xr_client)  # must not raise

    assert result is online_conn
    assert cisco_xr_client.conn is online_conn
    assert cisco_xr_client.logger.info.call_count == 3


def test_wait_for_reconnect_times_out(mocker, cisco_xr_client):
    cisco_xr_client.reconnect_timeout = 1
    cisco_xr_client.reconnect_delay = 0

    time_values = iter([1000.0, 1000.0, 1002.0, 1002.0])
    mocker.patch(
        "network_automation.platforms.cisco_xr.reboot.time.time",
        side_effect=lambda: next(time_values),
    )
    mocker.patch("network_automation.platforms.cisco_xr.reboot.time.sleep")
    mocker.patch(
        "network_automation.platforms.cisco_xr.reboot.ConnectHandler",
        side_effect=Exception("connection refused"),
    )

    with pytest.raises(TimeoutError):
        wait_for_reconnect(cisco_xr_client)
