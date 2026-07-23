# network_automation/tests/opnsense/test_reboot.py

import pytest
from unittest.mock import MagicMock

from network_automation.platforms.opnsense import reboot as reboot_mod


# -------------------------------------------------------
# reboot()
# -------------------------------------------------------

def test_reboot_sends_shutdown_command_and_clears_conn(opnsense_client):
    fake_conn = MagicMock()
    opnsense_client.conn = fake_conn

    reboot_mod.reboot(opnsense_client)

    fake_conn.send_command_timing.assert_called_once_with("/sbin/shutdown -r now")
    fake_conn.disconnect.assert_called_once()
    assert opnsense_client.conn is None


def test_reboot_tolerates_connection_drop_mid_command(opnsense_client):
    """A connection dropping mid-reboot is the expected success case, not an error."""
    fake_conn = MagicMock()
    fake_conn.send_command_timing.side_effect = OSError("connection reset")
    fake_conn.disconnect.side_effect = OSError("already closed")
    opnsense_client.conn = fake_conn

    reboot_mod.reboot(opnsense_client)  # must not raise

    assert opnsense_client.conn is None


# -------------------------------------------------------
# wait_for_reconnect()
# -------------------------------------------------------

def test_wait_for_reconnect_success(mocker, opnsense_client):
    opnsense_client.reconnect_timeout = 300
    opnsense_client.reconnect_delay = 0

    time_values = iter([1000.0, 1000.0, 1001.0])
    mocker.patch(
        "network_automation.platforms.opnsense.reboot.time.time",
        side_effect=lambda: next(time_values),
    )
    mocker.patch("network_automation.platforms.opnsense.reboot.time.sleep")

    online_conn = MagicMock()
    online_conn.send_command.return_value = "OPNsense 26.1.11_10"
    mocker.patch(
        "network_automation.platforms.opnsense.reboot.ConnectHandler",
        return_value=online_conn,
    )
    mocker.patch.object(opnsense_client, "_ensure_shell")

    result = reboot_mod.wait_for_reconnect(opnsense_client)

    assert result is online_conn
    assert opnsense_client.conn is online_conn


def test_wait_for_reconnect_retries_until_ready(mocker, opnsense_client):
    opnsense_client.reconnect_timeout = 300
    opnsense_client.reconnect_delay = 0

    time_values = iter([1000.0, 1000.0, 1005.0, 1005.0])
    mocker.patch(
        "network_automation.platforms.opnsense.reboot.time.time",
        side_effect=lambda: next(time_values),
    )
    mocker.patch("network_automation.platforms.opnsense.reboot.time.sleep")

    not_ready_conn = MagicMock()
    not_ready_conn.send_command.side_effect = Exception("device not ready yet")
    online_conn = MagicMock()
    online_conn.send_command.return_value = "OPNsense 26.1.11_10"

    mocker.patch(
        "network_automation.platforms.opnsense.reboot.ConnectHandler",
        side_effect=[not_ready_conn, online_conn],
    )
    mocker.patch.object(opnsense_client, "_ensure_shell")

    result = reboot_mod.wait_for_reconnect(opnsense_client)

    assert result is online_conn
    assert opnsense_client.conn is online_conn


def test_wait_for_reconnect_raises_timeout_error(mocker, opnsense_client):
    opnsense_client.reconnect_timeout = 10
    opnsense_client.reconnect_delay = 0

    time_values = iter([1000.0] + [1000.0 + i for i in range(1, 30)])
    mocker.patch(
        "network_automation.platforms.opnsense.reboot.time.time",
        side_effect=lambda: next(time_values),
    )
    mocker.patch("network_automation.platforms.opnsense.reboot.time.sleep")
    mocker.patch(
        "network_automation.platforms.opnsense.reboot.ConnectHandler",
        side_effect=Exception("connection refused"),
    )

    with pytest.raises(TimeoutError):
        reboot_mod.wait_for_reconnect(opnsense_client)


def test_wait_for_reconnect_survives_logger_failure_during_heartbeat(mocker, opnsense_client):
    """
    A logger.info() failure on the 60s heartbeat must not abort
    wait_for_reconnect() - same risk as MikroTik/Huawei's equivalent,
    handled here via the same BaseClient._safe_log_info() mechanism.
    """
    opnsense_client.reconnect_timeout = 300
    opnsense_client.reconnect_delay = 0

    time_values = iter([1000.0, 1000.0, 1065.0, 1065.0])
    mocker.patch(
        "network_automation.platforms.opnsense.reboot.time.time",
        side_effect=lambda: next(time_values),
    )
    mocker.patch("network_automation.platforms.opnsense.reboot.time.sleep")

    not_ready_conn = MagicMock()
    not_ready_conn.send_command.side_effect = Exception("device not ready yet")
    online_conn = MagicMock()
    online_conn.send_command.return_value = "OPNsense 26.1.11_10"

    mocker.patch(
        "network_automation.platforms.opnsense.reboot.ConnectHandler",
        side_effect=[not_ready_conn, online_conn],
    )
    mocker.patch.object(opnsense_client, "_ensure_shell")

    opnsense_client.logger = MagicMock()
    opnsense_client.logger.info.side_effect = [
        None,  # "Waiting for %s to reconnect..."
        RuntimeError("Lost connection to MySQL server during query"),  # heartbeat
        None,  # "Device fully online (SSH + CLI ready)."
    ]

    result = reboot_mod.wait_for_reconnect(opnsense_client)  # must not raise

    assert result is online_conn
