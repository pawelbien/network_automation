# network_automation/tests/mikrotik_routeros/test_client.py

from unittest.mock import MagicMock


def test_wait_for_reconnect_survives_logger_failure_during_heartbeat(mocker, mikrotik_client):
    """
    A logger.info() failure on the 60s heartbeat (e.g. a transient DB
    hiccup in Nautobot's Job logger) must not abort wait_for_reconnect()
    — the device reconnecting is what matters, not whether the heartbeat
    got logged. Same risk as huawei_vrp's wait_for_reconnect() (which hit
    this live, 2026-07-12); mikrotik_routeros shares the identical
    start/heartbeat/success logging shape via BaseClient._safe_log_info().
    """
    mikrotik_client.reconnect_timeout = 300
    mikrotik_client.reconnect_delay = 1

    time_values = iter([1000.0, 1000.0, 1065.0, 1065.0])
    mocker.patch(
        "network_automation.platforms.mikrotik_routeros.client.time.time",
        side_effect=lambda: next(time_values),
    )
    mocker.patch("network_automation.platforms.mikrotik_routeros.client.time.sleep")

    not_ready_conn = MagicMock()
    not_ready_conn.send_command.side_effect = Exception("device not ready yet")
    online_conn = MagicMock()
    online_conn.send_command.return_value = "RouterOS version: 7.14"

    mocker.patch(
        "network_automation.platforms.mikrotik_routeros.client.ConnectHandler",
        side_effect=[not_ready_conn, online_conn],
    )

    mikrotik_client.logger = MagicMock()
    mikrotik_client.logger.info.side_effect = [
        None,  # "Waiting for %s to reconnect..."
        RuntimeError("Lost connection to MySQL server during query"),  # heartbeat
        None,  # "Device fully online (SSH + CLI ready)."
    ]

    result = mikrotik_client.wait_for_reconnect()  # must not raise

    assert result is online_conn
    assert mikrotik_client.conn is online_conn
    assert mikrotik_client.logger.info.call_count == 3
