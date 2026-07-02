# network_automation/tests/huawei_vrp/test_client.py

from unittest.mock import MagicMock

from network_automation.platforms.huawei_vrp.client import HuaweiVRP


def test_upload_timeout_and_retries_defaults(huawei_client):
    assert huawei_client.upload_timeout == 120
    assert huawei_client.upload_retries == 3


def test_upload_timeout_and_retries_overridable():
    client = HuaweiVRP(
        host="1.1.1.1", username="admin", password="secret",
        upload_timeout=60, upload_retries=5,
    )
    assert client.upload_timeout == 60
    assert client.upload_retries == 5


def test_health_check_defaults(huawei_client):
    assert huawei_client.health_check_mode == "abort"
    assert huawei_client.health_check_cpu_threshold == 80.0
    assert huawei_client.health_check_memory_threshold == 80.0
    assert huawei_client.health_check_max_down_interfaces == 0


def test_health_check_overridable():
    client = HuaweiVRP(
        host="1.1.1.1", username="admin", password="secret",
        health_check_mode="warn", health_check_cpu_threshold=90.0,
        health_check_memory_threshold=95.0, health_check_max_down_interfaces=2,
    )
    assert client.health_check_mode == "warn"
    assert client.health_check_cpu_threshold == 90.0
    assert client.health_check_memory_threshold == 95.0
    assert client.health_check_max_down_interfaces == 2


def test_reboot_does_not_raise_on_normal_yn_prompt(huawei_client):
    # Proves reboot() does NOT falsely trigger the CLI-error check on
    # ordinary [Y/N] prompt text (no check is applied at all here).
    fake_conn = MagicMock()
    fake_conn.send_command_timing.side_effect = [
        "Warning: continue? [Y/N]:",
        "System will reboot now.",
    ]
    huawei_client.conn = fake_conn

    huawei_client.reboot()  # must not raise

    assert fake_conn.send_command_timing.call_count == 2
