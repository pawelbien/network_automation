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
    fake_conn.send_command.return_value = "Warning: continue? [Y/N]:"
    fake_conn.send_command_timing.return_value = "System will reboot now."
    huawei_client.conn = fake_conn

    huawei_client.reboot()  # must not raise

    fake_conn.send_command.assert_called_once_with(
        "reboot", expect_string=r"(?i)y/n|[\]>]", read_timeout=300,
        strip_prompt=False, strip_command=False,
    )
    fake_conn.send_command_timing.assert_called_once_with("y", read_timeout=15)


def test_reboot_confirms_yn_prompt_delayed_by_please_wait_message(huawei_client):
    # VRP can print an "Info: ... please wait" message before the real [y/n] prompt
    # shows up. The old send_command_timing()-based loop returned as soon as
    # the channel went idle during that pause, saw no "y/n" yet, and silently
    # skipped confirming — so the reboot never happened. Pattern-based
    # send_command() must instead wait for the actual prompt text, however
    # delayed, and still send "y".
    fake_conn = MagicMock()
    fake_conn.send_command.return_value = (
        "Info: The system is comparing the configuration, please wait.\n"
        "System will reboot! Continue? [y/n]:"
    )
    fake_conn.send_command_timing.return_value = "Info: system is rebooting, please wait..."
    huawei_client.conn = fake_conn

    huawei_client.reboot()  # must not raise

    fake_conn.send_command_timing.assert_called_once_with("y", read_timeout=15)


def test_reboot_confirmation_uses_idle_based_timing_not_pattern_matching(huawei_client):
    # Root cause #8 follow-up: confirming "y" is followed by "Info: system
    # is rebooting, please wait..." and then nothing else for a long time,
    # without the connection actually closing — observed live to make
    # pattern-based send_command(read_timeout=300) poll read_channel() for
    # minutes, flooding the log. The confirmation step must use
    # send_command_timing() (idle-time based, short read_timeout ceiling),
    # never send_command()/expect_string, which is only appropriate for the
    # initial "reboot" send (see the test above).
    fake_conn = MagicMock()
    fake_conn.send_command.return_value = "System will reboot! Continue? [y/n]:"
    fake_conn.send_command_timing.return_value = "Info: system is rebooting, please wait..."
    huawei_client.conn = fake_conn

    huawei_client.reboot()  # must not raise

    assert fake_conn.send_command.call_count == 1
    fake_conn.send_command_timing.assert_called_once_with("y", read_timeout=15)


def test_reboot_tolerates_connection_dying_after_confirmation(huawei_client):
    # The device actually rebooting and dropping the connection right after
    # "y" is the expected success case, not an error to propagate.
    fake_conn = MagicMock()
    fake_conn.send_command.return_value = "System will reboot! Continue? [y/n]:"
    fake_conn.send_command_timing.side_effect = ConnectionError("connection closed")
    huawei_client.conn = fake_conn

    huawei_client.reboot()  # must not raise
