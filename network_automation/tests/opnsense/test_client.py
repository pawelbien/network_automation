# network_automation/tests/opnsense/test_client.py

import pytest
from unittest.mock import MagicMock
from network_automation.platforms.opnsense.exceptions import OPNsenseShellError


# ---------- _ensure_shell ----------

def test_ensure_shell_noop_when_skip_menu(opnsense_client):
    fake_conn = MagicMock()
    opnsense_client.conn = fake_conn

    opnsense_client._ensure_shell()

    fake_conn.send_command_timing.assert_not_called()


def test_ensure_shell_selects_menu_option(opnsense_client):
    opnsense_client.skip_menu = False

    fake_conn = MagicMock()
    fake_conn.send_command_timing.return_value = "root@firewall:~ # "
    opnsense_client.conn = fake_conn

    opnsense_client._ensure_shell()

    fake_conn.send_command_timing.assert_called_once_with("8")


def test_ensure_shell_custom_menu_option(opnsense_client):
    opnsense_client.skip_menu = False
    opnsense_client.shell_menu_option = "shell"

    fake_conn = MagicMock()
    fake_conn.send_command_timing.return_value = "$ "
    opnsense_client.conn = fake_conn

    opnsense_client._ensure_shell()

    fake_conn.send_command_timing.assert_called_once_with("shell")


def test_ensure_shell_raises_when_prompt_not_observed(opnsense_client):
    opnsense_client.skip_menu = False

    fake_conn = MagicMock()
    fake_conn.send_command_timing.return_value = (
        "0) Logout\n1) Assign Interfaces\n...\n8) Shell\nEnter an option:"
    )
    opnsense_client.conn = fake_conn

    with pytest.raises(OPNsenseShellError, match="shell prompt"):
        opnsense_client._ensure_shell()


# ---------- not-yet-implemented operations (skeleton) ----------

def test_upgrade_not_implemented(opnsense_client):
    with pytest.raises(NotImplementedError):
        opnsense_client.upgrade()


def test_reboot_not_implemented(opnsense_client):
    with pytest.raises(NotImplementedError):
        opnsense_client.reboot()


def test_wait_for_reconnect_not_implemented(opnsense_client):
    with pytest.raises(NotImplementedError):
        opnsense_client.wait_for_reconnect()


def test_backup_not_implemented(opnsense_client):
    with pytest.raises(NotImplementedError):
        opnsense_client.backup("daily")
