# network_automation/tests/huawei_vrp/test_client.py

from unittest.mock import MagicMock


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
