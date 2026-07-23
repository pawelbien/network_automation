# network_automation/tests/opnsense/test_upgrade.py

import pytest
from unittest.mock import MagicMock

from network_automation.platforms.opnsense.exceptions import OPNsenseFirmwareError
from network_automation.platforms.opnsense.upgrade import (
    _has_reboot_marker,
    _has_done_marker,
    check_updates,
    update,
    upgrade,
)
from network_automation.results import OperationResult


# -------------------------------------------------------
# Marker detection
# -------------------------------------------------------

def test_has_reboot_marker_true():
    assert _has_reboot_marker("***GOT REQUEST***\n...\n***REBOOT***\n")


def test_has_reboot_marker_false():
    assert not _has_reboot_marker("***GOT REQUEST***\n...\n***DONE***\n")


def test_has_done_marker_true():
    assert _has_done_marker("***GOT REQUEST***\n...\n***DONE***\n")


def test_has_done_marker_false():
    assert not _has_done_marker("***GOT REQUEST***\n...\n***REBOOT***\n")


# -------------------------------------------------------
# Shared test helpers
# -------------------------------------------------------

def _stub_lifecycle(monkeypatch, client):
    monkeypatch.setattr(client, "connect", lambda: None)
    monkeypatch.setattr(client, "disconnect", lambda: None)
    monkeypatch.setattr(client, "_ensure_shell", lambda: None)


def _stub_get_info(monkeypatch, versions):
    """
    versions - opnsense_version strings returned by successive get_info()
    calls (update()/upgrade() call it once before and once after
    _run_and_wait(); check_updates() doesn't call it at all).
    """
    it = iter(versions)
    monkeypatch.setattr(
        "network_automation.platforms.opnsense.upgrade.get_info",
        lambda client: {"units": [{"opnsense_version": next(it)}]},
    )


@pytest.fixture
def firmware_client(opnsense_client):
    opnsense_client.firmware_poll_interval = 0
    opnsense_client.firmware_poll_timeout = 5
    opnsense_client.reboot_grace_period = 0
    return opnsense_client


# -------------------------------------------------------
# update()
# -------------------------------------------------------

def test_update_completes_without_reboot(monkeypatch, mocker, firmware_client):
    _stub_lifecycle(monkeypatch, firmware_client)
    _stub_get_info(monkeypatch, ["26.1", "26.1.11_10"])

    mocker.patch(
        "network_automation.platforms.opnsense.upgrade.firmware.running",
        side_effect=["ready", "ready"],
    )
    mocker.patch(
        "network_automation.platforms.opnsense.upgrade.firmware.update",
        return_value="OK",
    )
    mocker.patch(
        "network_automation.platforms.opnsense.upgrade.firmware.status",
        return_value="***GOT REQUEST***\n...\n***DONE***",
    )
    wait_mock = mocker.patch.object(firmware_client, "wait_for_reconnect")

    result = update(firmware_client, return_result=True)

    assert isinstance(result, OperationResult)
    assert result.success is True
    assert result.operation == "update"
    assert result.metadata["current_version"] == "26.1"
    assert result.metadata["final_version"] == "26.1.11_10"
    assert result.metadata["rebooted"] is False
    wait_mock.assert_not_called()


def test_update_completes_with_reboot(monkeypatch, mocker, firmware_client):
    _stub_lifecycle(monkeypatch, firmware_client)
    _stub_get_info(monkeypatch, ["26.1", "26.1.11_10"])

    mocker.patch(
        "network_automation.platforms.opnsense.upgrade.firmware.running",
        side_effect=["ready", "ready"],
    )
    mocker.patch(
        "network_automation.platforms.opnsense.upgrade.firmware.update",
        return_value="OK",
    )
    mocker.patch(
        "network_automation.platforms.opnsense.upgrade.firmware.status",
        return_value="...\n***REBOOT***",
    )
    wait_mock = mocker.patch.object(firmware_client, "wait_for_reconnect")

    result = update(firmware_client, return_result=True)

    assert result.metadata["rebooted"] is True
    wait_mock.assert_called_once()


def test_update_waits_out_grace_period_and_disconnects_stale_conn_before_reboot(
    monkeypatch, mocker, firmware_client
):
    """
    Regression test (found live 2026-07-23): output_reboot() writes the
    ***REBOOT*** marker, then `sleep 5`, then actually reboots - reconnecting
    immediately risks landing on the still-alive, about-to-die session and
    getting "Socket is closed" on the next command. _run_and_wait() must
    sleep reboot_grace_period and attempt to close the stale connection
    before nulling client.conn and calling wait_for_reconnect().
    """
    _stub_lifecycle(monkeypatch, firmware_client)
    _stub_get_info(monkeypatch, ["26.1", "26.1.11_10"])
    firmware_client.reboot_grace_period = 12

    stale_conn = MagicMock()
    firmware_client.conn = stale_conn

    mocker.patch(
        "network_automation.platforms.opnsense.upgrade.firmware.running",
        side_effect=["ready", "ready"],
    )
    mocker.patch(
        "network_automation.platforms.opnsense.upgrade.firmware.update",
        return_value="OK",
    )
    mocker.patch(
        "network_automation.platforms.opnsense.upgrade.firmware.status",
        return_value="...\n***REBOOT***",
    )
    sleep_mock = mocker.patch("network_automation.platforms.opnsense.upgrade.time.sleep")

    def _reconnect():
        firmware_client.conn = MagicMock()

    mocker.patch.object(firmware_client, "wait_for_reconnect", side_effect=_reconnect)

    update(firmware_client, return_result=True)

    sleep_mock.assert_any_call(12)
    stale_conn.disconnect.assert_called_once()


def test_update_raises_when_backend_busy(monkeypatch, mocker, firmware_client):
    _stub_lifecycle(monkeypatch, firmware_client)
    _stub_get_info(monkeypatch, ["26.1"])

    mocker.patch(
        "network_automation.platforms.opnsense.upgrade.firmware.running",
        return_value="busy",
    )

    with pytest.raises(OPNsenseFirmwareError, match="already busy"):
        update(firmware_client, return_result=True)


def test_update_raises_on_poll_timeout(monkeypatch, mocker, firmware_client):
    _stub_lifecycle(monkeypatch, firmware_client)
    _stub_get_info(monkeypatch, ["26.1"])
    firmware_client.firmware_poll_timeout = 0.05
    firmware_client.firmware_poll_interval = 0.01

    mocker.patch(
        "network_automation.platforms.opnsense.upgrade.firmware.running",
        side_effect=["ready"] + ["busy"] * 50,
    )
    mocker.patch(
        "network_automation.platforms.opnsense.upgrade.firmware.update",
        return_value="OK",
    )
    mocker.patch(
        "network_automation.platforms.opnsense.upgrade.firmware.status",
        return_value="still going",
    )

    with pytest.raises(OPNsenseFirmwareError, match="did not complete within"):
        update(firmware_client, return_result=True)


def test_update_raises_when_log_has_no_marker(monkeypatch, mocker, firmware_client):
    _stub_lifecycle(monkeypatch, firmware_client)
    _stub_get_info(monkeypatch, ["26.1"])

    mocker.patch(
        "network_automation.platforms.opnsense.upgrade.firmware.running",
        side_effect=["ready", "ready"],
    )
    mocker.patch(
        "network_automation.platforms.opnsense.upgrade.firmware.update",
        return_value="OK",
    )
    mocker.patch(
        "network_automation.platforms.opnsense.upgrade.firmware.status",
        return_value="garbage log, no marker",
    )

    with pytest.raises(OPNsenseFirmwareError, match="ended without"):
        update(firmware_client, return_result=True)


def test_update_failure_marks_result_and_reraises(monkeypatch, firmware_client):
    _stub_lifecycle(monkeypatch, firmware_client)
    monkeypatch.setattr(
        "network_automation.platforms.opnsense.upgrade.get_info",
        MagicMock(side_effect=RuntimeError("boom")),
    )

    with pytest.raises(RuntimeError, match="boom"):
        update(firmware_client, return_result=True)


# -------------------------------------------------------
# upgrade()
# -------------------------------------------------------

def test_upgrade_detects_branch_change(monkeypatch, mocker, firmware_client):
    _stub_lifecycle(monkeypatch, firmware_client)
    _stub_get_info(monkeypatch, ["26.1.11_10", "26.7"])

    mocker.patch(
        "network_automation.platforms.opnsense.upgrade.firmware.running",
        side_effect=["ready", "ready"],
    )
    mocker.patch(
        "network_automation.platforms.opnsense.upgrade.firmware.upgrade",
        return_value="OK",
    )
    mocker.patch(
        "network_automation.platforms.opnsense.upgrade.firmware.status",
        return_value="...\n***REBOOT***",
    )
    wait_mock = mocker.patch.object(firmware_client, "wait_for_reconnect")

    result = upgrade(firmware_client, return_result=True)

    assert result.metadata["current_branch"] == "26.1"
    assert result.metadata["final_branch"] == "26.7"
    assert result.metadata["branch_changed"] is True
    assert result.metadata["rebooted"] is True
    wait_mock.assert_called_once()


def test_upgrade_no_branch_change_reported(monkeypatch, mocker, firmware_client):
    _stub_lifecycle(monkeypatch, firmware_client)
    _stub_get_info(monkeypatch, ["26.1.11_10", "26.1.11_10"])

    mocker.patch(
        "network_automation.platforms.opnsense.upgrade.firmware.running",
        side_effect=["ready", "ready"],
    )
    mocker.patch(
        "network_automation.platforms.opnsense.upgrade.firmware.upgrade",
        return_value="OK",
    )
    mocker.patch(
        "network_automation.platforms.opnsense.upgrade.firmware.status",
        return_value="...\n***DONE***",
    )
    wait_mock = mocker.patch.object(firmware_client, "wait_for_reconnect")

    result = upgrade(firmware_client, return_result=True)

    assert result.metadata["branch_changed"] is False
    assert result.metadata["rebooted"] is False
    wait_mock.assert_not_called()


# -------------------------------------------------------
# check_updates()
# -------------------------------------------------------

def test_check_updates_returns_log_without_rebooting(monkeypatch, mocker, firmware_client):
    _stub_lifecycle(monkeypatch, firmware_client)

    mocker.patch(
        "network_automation.platforms.opnsense.upgrade.firmware.running",
        side_effect=["ready", "ready"],
    )
    mocker.patch(
        "network_automation.platforms.opnsense.upgrade.firmware.check",
        return_value="OK",
    )
    mocker.patch(
        "network_automation.platforms.opnsense.upgrade.firmware.status",
        return_value="***GOT REQUEST***\n...\n***DONE***",
    )
    wait_mock = mocker.patch.object(firmware_client, "wait_for_reconnect")

    result = check_updates(firmware_client, return_result=True)

    assert result.success is True
    assert result.operation == "check_updates"
    assert "GOT REQUEST" in result.metadata["log"]
    assert result.metadata["rebooted"] is False
    wait_mock.assert_not_called()
