# network_automation/tests/juniper_junos/test_reboot.py

from unittest.mock import MagicMock, call

import pytest

from network_automation.platforms.juniper_junos.reboot import reboot, wait_for_reconnect

_PROMPT = "Reboot the system ? [yes,no] (no)"


def test_reboot_confirms_immediately(juniper_junos_client):
    fake_conn = MagicMock()
    fake_conn.send_command_timing.return_value = _PROMPT
    juniper_junos_client.conn = fake_conn

    reboot(juniper_junos_client)

    assert fake_conn.send_command_timing.call_args_list == [
        call("request system reboot"),
        call("yes"),
    ]
    assert juniper_junos_client.conn is None


def test_reboot_confirms_on_delayed_prompt(mocker, juniper_junos_client):
    mocker.patch("network_automation.platforms.juniper_junos.reboot.time.sleep")
    fake_conn = MagicMock()
    fake_conn.send_command_timing.side_effect = ["", _PROMPT, "Shutdown NOW!"]
    juniper_junos_client.conn = fake_conn

    reboot(juniper_junos_client)

    assert fake_conn.send_command_timing.call_args_list == [
        call("request system reboot"),
        call(""),
        call("yes"),
    ]
    assert juniper_junos_client.conn is None


def test_reboot_without_prompt_warns_and_sends_yes(mocker, juniper_junos_client):
    mocker.patch("network_automation.platforms.juniper_junos.reboot.time.sleep")
    fake_conn = MagicMock()
    fake_conn.send_command_timing.side_effect = ["", "", ""]
    juniper_junos_client.conn = fake_conn
    juniper_junos_client.logger = MagicMock()

    reboot(juniper_junos_client)

    fake_conn.send_command_timing.assert_called_with("yes")
    juniper_junos_client.logger.warning.assert_called_once()
    assert juniper_junos_client.conn is None


def test_wait_for_reconnect_survives_logger_failure_during_heartbeat(mocker, juniper_junos_client):
    juniper_junos_client.reconnect_timeout = 300
    juniper_junos_client.reconnect_delay = 1

    time_values = iter([1000.0, 1000.0, 1065.0, 1065.0])
    mocker.patch(
        "network_automation.platforms.juniper_junos.reboot.time.time",
        side_effect=lambda: next(time_values),
    )
    mocker.patch("network_automation.platforms.juniper_junos.reboot.time.sleep")

    not_ready_conn = MagicMock()
    not_ready_conn.send_command.side_effect = Exception("device not ready yet")
    online_conn = MagicMock()
    online_conn.send_command.return_value = "Hostname: r1\nModel: mx204\nJunos: 21.4R3-S5.4"

    mocker.patch.object(
        juniper_junos_client,
        "_open_connection",
        side_effect=[not_ready_conn, online_conn],
    )

    juniper_junos_client.logger = MagicMock()
    juniper_junos_client.logger.info.side_effect = [
        None,  # "Waiting for %s to reconnect..."
        RuntimeError("Lost connection to MySQL server during query"),  # heartbeat
        None,  # "Device fully online (SSH + CLI ready)."
    ]

    result = wait_for_reconnect(juniper_junos_client)  # must not raise

    assert result is online_conn
    assert juniper_junos_client.conn is online_conn
    assert juniper_junos_client.logger.info.call_count == 3


def test_wait_for_reconnect_times_out(mocker, juniper_junos_client):
    juniper_junos_client.reconnect_timeout = 1
    juniper_junos_client.reconnect_delay = 0

    time_values = iter([1000.0, 1000.0, 1002.0, 1002.0])
    mocker.patch(
        "network_automation.platforms.juniper_junos.reboot.time.time",
        side_effect=lambda: next(time_values),
    )
    mocker.patch("network_automation.platforms.juniper_junos.reboot.time.sleep")
    mocker.patch.object(
        juniper_junos_client,
        "_open_connection",
        side_effect=Exception("connection refused"),
    )

    with pytest.raises(TimeoutError):
        wait_for_reconnect(juniper_junos_client)
