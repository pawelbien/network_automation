# network_automation/tests/juniper_junos/test_connection.py

import re
from unittest.mock import MagicMock

import pytest

from network_automation.platforms.juniper_junos.connection import JunosSSH

# Reply of a login class that is not allowed to run the command.
_RESTRICTED_REPLY = """admin@sw1> set cli complete-on-space
                        ^
syntax error, expecting <command>.
"""


@pytest.fixture
def prepared_conn():
    conn = object.__new__(JunosSSH)
    for name in (
        "_test_channel_read",
        "enter_cli_mode",
        "set_terminal_width",
        "write_channel",
        "read_until_pattern",
        "disable_paging",
        "set_base_prompt",
    ):
        setattr(conn, name, MagicMock())
    conn.normalize_cmd = lambda cmd: cmd + "\n"
    return conn


def test_session_preparation_complete_on_space_is_best_effort(prepared_conn):
    prepared_conn.session_preparation()

    prepared_conn.write_channel.assert_called_once_with("set cli complete-on-space off\n")
    pattern = prepared_conn.read_until_pattern.call_args.kwargs["pattern"]
    assert re.search(pattern, _RESTRICTED_REPLY)
    assert re.search(pattern, "Disabling complete-on-space")

    # complete-on-space no longer goes through disable_paging's echo check.
    prepared_conn.disable_paging.assert_called_once_with(
        command="set cli screen-length 0", pattern=r"Screen length set to"
    )
    prepared_conn.set_terminal_width.assert_called_once()
    prepared_conn.set_base_prompt.assert_called_once()


def test_client_opens_connection_with_junos_ssh(mocker, juniper_junos_client):
    junos_ssh = mocker.patch("network_automation.platforms.juniper_junos.client.JunosSSH")

    conn = juniper_junos_client._open_connection()

    assert conn is junos_ssh.return_value
    junos_ssh.assert_called_once_with(**juniper_junos_client.device)
