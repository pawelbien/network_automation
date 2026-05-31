# network_automation/tests/mikrotik_routeros/test_bootloader.py

import pytest
from unittest.mock import MagicMock

from network_automation.results import OperationResult
from network_automation.platforms.mikrotik_routeros.bootloader import (
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
          revision: r2
     serial-number: HG6099981S2
  current-firmware: 7.19.1
  upgrade-firmware: 7.20.7
    """


@pytest.fixture
def bootloader_print_after():
    return """
       ;;; Firmware upgraded successfully, please reboot for changes to take effect!
       routerboard: yes
             model: CCR2004-16G-2S+
          revision: r2
     serial-number: HG6099981S2
  current-firmware: 7.19.1
  upgrade-firmware: 7.20.7
    """


@pytest.fixture
def bootloader_print_uptodate():
    return """
       routerboard: yes
             model: CCR2004-16G-2S+
          revision: r2
     serial-number: HG6099981S2
  current-firmware: 7.20.7
  upgrade-firmware: 7.20.7
    """


@pytest.fixture
def chr_routerboard_output():
    return "bad command name routerboard (line 1 column 9)"


# -------------------------------------------------------
# bootloader_upgrade workflow
# -------------------------------------------------------

def test_bootloader_upgrade_skipped_if_up_to_date(
    monkeypatch,
    mikrotik_client,
    fake_conn,
    bootloader_print_uptodate,
):
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
    assert result.metadata["skipped"] is True
    assert "up-to-date" in result.message.lower()


def test_bootloader_upgrade_chr_is_skipped(
    monkeypatch,
    mikrotik_client,
    fake_conn,
    chr_routerboard_output,
):
    """
    CHR platforms do not support RouterBOARD / bootloader.
    Operation must be skipped, not failed.
    """

    monkeypatch.setattr(mikrotik_client, "connect", lambda: None)
    monkeypatch.setattr(mikrotik_client, "disconnect", lambda: None)

    fake_conn.send_command.return_value = chr_routerboard_output
    mikrotik_client.conn = fake_conn

    result = bootloader_upgrade(
        mikrotik_client,
        return_result=True,
    )

    assert result.success is True
    assert result.metadata["skipped"] is True
    assert result.metadata["reason"] == "bootloader not supported"
    assert "not supported" in result.message.lower()


def test_bootloader_upgrade_stages_and_reboots(
    monkeypatch,
    mikrotik_client,
    fake_conn,
    bootloader_print_before,
    bootloader_print_after,
):
    monkeypatch.setattr(mikrotik_client, "connect", lambda: None)
    monkeypatch.setattr(mikrotik_client, "disconnect", lambda: None)

    monkeypatch.setattr(
        "network_automation.platforms.mikrotik_routeros.bootloader.time.sleep",
        lambda _: None,
    )

    fake_conn.send_command.side_effect = [
        bootloader_print_before,  # get_info before upgrade
        bootloader_print_after,   # get_info after upgrade
        bootloader_print_after,   # raw_output check for confirmation message
    ]

    fake_conn.send_command_timing.return_value = "y"
    mikrotik_client.conn = fake_conn

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

    assert result.success is True
    assert result.metadata["upgrade_staged"] is True
    assert reboot_called is True


def test_bootloader_upgrade_unclear_state_still_reboots(
    monkeypatch,
    mikrotik_client,
    fake_conn,
    bootloader_print_before,
):
    monkeypatch.setattr(mikrotik_client, "connect", lambda: None)
    monkeypatch.setattr(mikrotik_client, "disconnect", lambda: None)

    monkeypatch.setattr(
        "network_automation.platforms.mikrotik_routeros.bootloader.time.sleep",
        lambda _: None,
    )

    fake_conn.send_command.side_effect = [
        bootloader_print_before,  # get_info before upgrade
        bootloader_print_before,  # get_info after upgrade
        bootloader_print_before,  # raw_output check (optional)
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
