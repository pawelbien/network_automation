# network_automation/tests/cisco_ios/test_reboot.py

from unittest.mock import MagicMock

import pytest

from network_automation.platforms.cisco_ios.reboot import reboot, wait_for_reconnect


def test_reboot_confirms_immediately(cisco_client):
    fake_conn = MagicMock()
    fake_conn.send_command_timing.return_value = "Proceed with reload? [confirm]"
    cisco_client.conn = fake_conn

    reboot(cisco_client)

    fake_conn.send_command_timing.assert_any_call("reload")
    fake_conn.send_command_timing.assert_any_call("\n")
    assert cisco_client.conn is None


def test_reboot_declines_save_prompt_first(cisco_client):
    fake_conn = MagicMock()
    fake_conn.send_command_timing.side_effect = [
        "System configuration has been modified. Save? [yes/no]:",
        "Proceed with reload? [confirm]",
        None,
    ]
    cisco_client.conn = fake_conn

    reboot(cisco_client)

    fake_conn.send_command_timing.assert_any_call("no")
    assert cisco_client.conn is None


def test_wait_for_reconnect_survives_logger_failure_during_heartbeat(mocker, cisco_client):
    cisco_client.reconnect_timeout = 300
    cisco_client.reconnect_delay = 1

    time_values = iter([1000.0, 1000.0, 1065.0, 1065.0])
    mocker.patch(
        "network_automation.platforms.cisco_ios.reboot.time.time",
        side_effect=lambda: next(time_values),
    )
    mocker.patch("network_automation.platforms.cisco_ios.reboot.time.sleep")

    not_ready_conn = MagicMock()
    not_ready_conn.send_command.side_effect = Exception("device not ready yet")
    online_conn = MagicMock()
    online_conn.send_command.return_value = "Cisco IOS Software, Version 17.9.4a"

    mocker.patch(
        "network_automation.platforms.cisco_ios.reboot.ConnectHandler",
        side_effect=[not_ready_conn, online_conn],
    )

    cisco_client.logger = MagicMock()
    cisco_client.logger.info.side_effect = [
        None,  # "Waiting for %s to reconnect..."
        RuntimeError("Lost connection to MySQL server during query"),  # heartbeat
        None,  # "Device fully online (SSH + CLI ready)."
    ]

    result = wait_for_reconnect(cisco_client)  # must not raise

    assert result is online_conn
    assert cisco_client.conn is online_conn
    assert cisco_client.logger.info.call_count == 3


def test_wait_for_reconnect_times_out(mocker, cisco_client):
    cisco_client.reconnect_timeout = 1
    cisco_client.reconnect_delay = 0

    time_values = iter([1000.0, 1000.0, 1002.0, 1002.0])
    mocker.patch(
        "network_automation.platforms.cisco_ios.reboot.time.time",
        side_effect=lambda: next(time_values),
    )
    mocker.patch("network_automation.platforms.cisco_ios.reboot.time.sleep")
    mocker.patch(
        "network_automation.platforms.cisco_ios.reboot.ConnectHandler",
        side_effect=Exception("connection refused"),
    )

    with pytest.raises(TimeoutError):
        wait_for_reconnect(cisco_client)
