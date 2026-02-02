# network_automation/tests/mikrotik_routeros/test_bootloader.py

import pytest
from unittest.mock import MagicMock

from network_automation.results import OperationResult
from network_automation.platforms.mikrotik_routeros.bootloader import (
    get_bootloader_info,
    bootloader_upgrade,
)


# -------------------------------------------------------
# Fixtures
# -------------------------------------------------------

@pytest.fixture
def fake_conn():
    return MagicMock()


@pytest.fixture
def bootloader_print_before():
    return """
       routerboard: yes
             model: CCR2004-16G-2S+
  current-firmware: 7.19.1
  upgrade-firmware: 7.20.7
    """


@pytest.fixture
def bootloader_print_after():
    return """
       ;;; Firmware upgraded successfully, please reboot for changes to take effect!
       routerboard: yes
             model: CCR2004-16G-2S+
  current-firmware: 7.19.1
  upgrade-firmware: 7.20.7
    """


@pytest.fixture
def bootloader_print_uptodate():
    return """
       routerboard: yes
             model: CCR2004-16G-2S+
  current-firmware: 7.20.7
  upgrade-firmware: 7.20.7
    """


# -------------------------------------------------------
# get_bootloader_info
# -------------------------------------------------------

def test_get_bootloader_info_parses_versions(
    mikrotik_client,
    fake_conn,
    bootloader_print_before,
):
    fake_conn.send_command.return_value = bootloader_print_before
    mikrotik_client.conn = fake_conn

    current, target, raw = get_bootloader_info(mikrotik_client)

    assert current == "7.19.1"
    assert target == "7.20.7"
    assert "routerboard" in raw


def test_get_bootloader_info_missing_fields_raises(
    mikrotik_client,
    fake_conn,
):
    fake_conn.send_command.return_value = "routerboard: yes"
    mikrotik_client.conn = fake_conn

    with pytest.raises(RuntimeError):
        get_bootloader_info(mikrotik_client)


# -------------------------------------------------------
# bootloader_upgrade workflow
# -------------------------------------------------------

def test_bootloader_upgrade_skipped_if_up_to_date(
    monkeypatch,
    mikrotik_client,
    fake_conn,
    bootloader_print_uptodate,
):
    # ---- lifecycle ----
    monkeypatch.setattr(mikrotik_client, "connect", lambda: None)
    monkeypatch.setattr(mikrotik_client, "disconnect", lambda: None)

    fake_conn.send_command.return_value = bootloader_print_uptodate
    mikrotik_client.conn = fake_conn

    result = bootloader_upgrade(
        mikrotik_client,
        return_result=True,
    )

    assert isinstance(result, OperationResult)
    assert result.success is True
    assert result.operation == "bootloader_upgrade"
    assert result.metadata["skipped"] is True
    assert "up-to-date" in result.message.lower()


def test_bootloader_upgrade_stages_and_reboots(
    monkeypatch,
    mikrotik_client,
    fake_conn,
    bootloader_print_before,
    bootloader_print_after,
):
    # ---- lifecycle ----
    monkeypatch.setattr(mikrotik_client, "connect", lambda: None)
    monkeypatch.setattr(mikrotik_client, "disconnect", lambda: None)

    # ---- avoid real sleep ----
    monkeypatch.setattr(
        "network_automation.platforms.mikrotik_routeros.bootloader.time.sleep",
        lambda _: None,
    )

    # ---- connection behavior ----
    fake_conn.send_command.side_effect = [
        bootloader_print_before,  # initial read
        bootloader_print_after,   # re-read after upgrade
    ]

    fake_conn.send_command_timing.return_value = "Do you really want to upgrade firmware? [y/n]"

    mikrotik_client.conn = fake_conn

    # ---- reboot & reconnect ----
    reboot_called = False

    def fake_reboot():
        nonlocal reboot_called
        reboot_called = True

    monkeypatch.setattr(mikrotik_client, "reboot", fake_reboot)
    monkeypatch.setattr(
        mikrotik_client,
        "wait_for_reconnect",
        lambda: fake_conn,
    )

    result = bootloader_upgrade(
        mikrotik_client,
        return_result=True,
    )

    # ---- assertions ----
    assert result.success is True
    assert result.metadata["current_bootloader"] == "7.19.1"
    assert result.metadata["target_bootloader"] == "7.20.7"
    assert result.metadata["upgrade_staged"] is True
    assert result.metadata.get("confirmation_message_seen") is True
    assert reboot_called is True


def test_bootloader_upgrade_unclear_state_still_reboots(
    monkeypatch,
    mikrotik_client,
    fake_conn,
    bootloader_print_before,
):
    """
    If state after upgrade is unclear, workflow must still reboot
    and not fail.
    """

    monkeypatch.setattr(mikrotik_client, "connect", lambda: None)
    monkeypatch.setattr(mikrotik_client, "disconnect", lambda: None)

    monkeypatch.setattr(
        "network_automation.platforms.mikrotik_routeros.bootloader.time.sleep",
        lambda _: None,
    )

    # same output before and after (edge case)
    fake_conn.send_command.side_effect = [
        bootloader_print_before,
        bootloader_print_before,
    ]

    fake_conn.send_command_timing.return_value = "y"

    mikrotik_client.conn = fake_conn

    monkeypatch.setattr(mikrotik_client, "reboot", lambda: None)
    monkeypatch.setattr(
        mikrotik_client,
        "wait_for_reconnect",
        lambda: fake_conn,
    )

    result = bootloader_upgrade(
        mikrotik_client,
        return_result=True,
    )

    assert result.success is True
    assert result.operation == "bootloader_upgrade"
