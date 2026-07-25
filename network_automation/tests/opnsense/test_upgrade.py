# network_automation/tests/opnsense/test_upgrade.py

import pytest
from unittest.mock import MagicMock

from network_automation.platforms.opnsense.exceptions import OPNsenseFirmwareError
from network_automation.platforms.opnsense.upgrade import (
    _has_reboot_marker,
    _has_done_marker,
    _looks_like_shell_error,
    _new_status_suffix,
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


def test_looks_like_shell_error_true():
    assert _looks_like_shell_error("-sh: /usr/local/sbin/configctl: not found")


def test_looks_like_shell_error_false_for_normal_states():
    assert not _looks_like_shell_error("ready")
    assert not _looks_like_shell_error("busy")


# -------------------------------------------------------
# _new_status_suffix: diff against last_len, no logging side effects
# -------------------------------------------------------

def test_new_status_suffix_returns_only_the_new_part():
    new_text, last_len = _new_status_suffix("A", 0)
    assert (new_text, last_len) == ("A", 1)

    new_text, last_len = _new_status_suffix("AB", last_len)
    assert (new_text, last_len) == ("B", 2)


def test_new_status_suffix_empty_when_nothing_new():
    new_text, last_len = _new_status_suffix("AB", 2)
    assert (new_text, last_len) == ("", 2)


def test_new_status_suffix_returns_whole_text_when_buffer_shrank():
    """A shorter buffer than last_len means the lockfile was reset (e.g.
    wiped by a reboot) - there's nothing sane to diff against."""
    new_text, last_len = _new_status_suffix("X", 10)
    assert (new_text, last_len) == ("X", 1)


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

def test_update_holds_back_partial_line_until_newline_arrives(monkeypatch, mocker, firmware_client):
    """
    status() can return output mid-line (e.g. progress dots with no
    trailing newline yet) - this must be held back and only fed to the
    progress parser once a newline completes the line, so a still-growing
    line can't trigger a premature/duplicate stage announcement.
    """
    _stub_lifecycle(monkeypatch, firmware_client)
    _stub_get_info(monkeypatch, ["26.1", "26.1.11_10"])

    mocker.patch("network_automation.platforms.opnsense.upgrade.time.sleep")
    mocker.patch(
        "network_automation.platforms.opnsense.upgrade.firmware.update",
        return_value="OK",
    )
    mocker.patch(
        "network_automation.platforms.opnsense.upgrade.firmware.running",
        side_effect=["ready", "busy", "busy", "ready"],
    )
    mocker.patch(
        "network_automation.platforms.opnsense.upgrade.firmware.status",
        side_effect=[
            "[1/1] Fetching foo.pkg: ..",
            "[1/1] Fetching foo.pkg: .... done\n",
            "[1/1] Fetching foo.pkg: .... done\n***GOT REQUEST***\n...\n***DONE***",
        ],
    )
    firmware_client.logger = MagicMock()

    update(firmware_client, return_result=True)

    info_messages = [c.args[0] % c.args[1:] for c in firmware_client.logger.info.call_args_list]
    assert not any("Fetching foo.pkg" in m for m in info_messages)
    assert info_messages.count("Downloading packages...") == 1


def test_update_logs_keepalive_only_after_60s_without_progress(monkeypatch, mocker, firmware_client):
    """
    While status() output isn't producing a new stage transition, no
    periodic progress message should be logged - only a keepalive, and
    only once per ~60s of silence, not on every poll.
    """
    _stub_lifecycle(monkeypatch, firmware_client)
    _stub_get_info(monkeypatch, ["26.1", "26.1.11_10"])
    firmware_client.firmware_poll_timeout = 100

    mocker.patch("network_automation.platforms.opnsense.upgrade.time.sleep")
    mocker.patch(
        "network_automation.platforms.opnsense.upgrade.time.monotonic",
        side_effect=[0, 10, 70, 71],
    )
    mocker.patch(
        "network_automation.platforms.opnsense.upgrade.firmware.update",
        return_value="OK",
    )
    mocker.patch(
        "network_automation.platforms.opnsense.upgrade.firmware.running",
        side_effect=["ready", "busy", "busy", "busy", "ready"],
    )
    mocker.patch(
        "network_automation.platforms.opnsense.upgrade.firmware.status",
        side_effect=["", "", "", "***GOT REQUEST***\n...\n***DONE***"],
    )
    mocker.patch.object(firmware_client, "wait_for_reconnect")
    firmware_client.logger = MagicMock()

    update(firmware_client, return_result=True)

    info_messages = [c.args[0] % c.args[1:] for c in firmware_client.logger.info.call_args_list]
    keepalives = [m for m in info_messages if m == "Still working..."]
    assert len(keepalives) == 1


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
    firmware_client.logger = MagicMock()

    result = update(firmware_client, return_result=True)

    assert result.metadata["rebooted"] is True
    wait_mock.assert_called_once()

    info_messages = [c.args[0] % c.args[1:] for c in firmware_client.logger.info.call_args_list]
    assert info_messages.count("Reboot detected.") == 1


def test_update_waits_out_grace_period_and_disconnects_stale_conn_before_reboot(
    monkeypatch, mocker, firmware_client
):
    """
    output_reboot() writes the ***REBOOT*** marker, then `sleep 5`, then
    actually reboots - reconnecting immediately risks landing on the
    still-alive, about-to-die session. _run_and_wait() must sleep
    reboot_grace_period and attempt to close the stale connection before
    nulling client.conn and calling wait_for_reconnect().
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
    mocker.patch(
        "network_automation.platforms.opnsense.upgrade.firmware.last_log",
        return_value="",
    )

    with pytest.raises(OPNsenseFirmwareError, match="ended without"):
        update(firmware_client, return_result=True)


def test_update_falls_back_to_last_log_when_lockfile_empty(monkeypatch, mocker, firmware_client):
    """
    Regression coverage for the fallback added alongside _poll_call():
    if the lockfile-based status() comes back empty/markerless (e.g. its
    /tmp tmpfs was reset by a reboot that happened while reconnecting),
    the persisted last_log() (which survives reboot) is used instead.
    """
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
        return_value="",
    )
    mocker.patch(
        "network_automation.platforms.opnsense.upgrade.firmware.last_log",
        return_value="***GOT REQUEST***\n...\n***DONE***",
    )
    wait_mock = mocker.patch.object(firmware_client, "wait_for_reconnect")

    result = update(firmware_client, return_result=True)

    assert "GOT REQUEST" in result.metadata["log"]
    assert result.metadata["rebooted"] is False
    wait_mock.assert_not_called()


def test_update_tolerates_transient_configctl_not_found(monkeypatch, mocker, firmware_client, tmp_path):
    """
    configctl (a symlink to configd_ctl.py) can transiently report "not
    found" for a poll or two while the opnsense package itself - what the
    update being polled is installing - is mid-replacing its own files.
    This must not be mistaken for "ready" and must not call
    firmware.status() during that iteration (skipped in favor of a
    friendlier log message) - it should just keep polling.

    This is expected, not noteworthy, so the unavailable/available-again
    transitions must never reach the user-facing INFO logger - only the
    detail log file, once per state transition (not once per poll): two
    consecutive "not found" polls must record "temporarily unavailable"
    only once, and "available again" only once when the state clears.
    """
    _stub_lifecycle(monkeypatch, firmware_client)
    _stub_get_info(monkeypatch, ["26.1", "26.1.11_10"])
    firmware_client.debug_log_dir = str(tmp_path)
    firmware_client.host = "10.0.0.1"

    mocker.patch(
        "network_automation.platforms.opnsense.upgrade.firmware.update",
        return_value="OK",
    )
    mocker.patch(
        "network_automation.platforms.opnsense.upgrade.firmware.running",
        side_effect=[
            "ready",
            "-sh: /usr/local/sbin/configctl: not found",
            "-sh: /usr/local/sbin/configctl: not found",
            "ready",
        ],
    )
    status_mock = mocker.patch(
        "network_automation.platforms.opnsense.upgrade.firmware.status",
        return_value="***GOT REQUEST***\n...\n***DONE***",
    )
    wait_mock = mocker.patch.object(firmware_client, "wait_for_reconnect")
    firmware_client.logger = MagicMock()

    result = update(firmware_client, return_result=True)

    assert result.success is True
    assert result.metadata["rebooted"] is False
    status_mock.assert_called_once()  # only the final post-loop read
    wait_mock.assert_not_called()

    info_messages = [c.args[0] % c.args[1:] for c in firmware_client.logger.info.call_args_list]
    assert not any("temporarily unavailable" in m for m in info_messages)
    assert not any("available again" in m for m in info_messages)

    detail_log = (tmp_path / "10.0.0.1_update.log").read_text()
    assert detail_log.count("temporarily unavailable") == 1
    assert detail_log.count("available again") == 1


def test_update_reconnects_when_connection_lost_mid_poll(monkeypatch, mocker, firmware_client):
    """
    Installing base/kernel packages can disrupt sshd and drop the
    polling connection well before any ***REBOOT*** marker appears, even
    though the backend job itself keeps running unaffected (it's
    detached from our session - see the module docstring). A dropped
    connection while polling must reconnect and resume, not fail the
    whole operation.
    """
    _stub_lifecycle(monkeypatch, firmware_client)
    _stub_get_info(monkeypatch, ["26.1", "26.1.11_10"])

    mocker.patch(
        "network_automation.platforms.opnsense.upgrade.firmware.update",
        return_value="OK",
    )
    mocker.patch(
        "network_automation.platforms.opnsense.upgrade.firmware.running",
        side_effect=["ready", Exception("Socket is closed"), "ready"],
    )
    mocker.patch(
        "network_automation.platforms.opnsense.upgrade.firmware.status",
        return_value="***GOT REQUEST***\n...\n***DONE***",
    )
    wait_mock = mocker.patch.object(firmware_client, "wait_for_reconnect")
    firmware_client.logger = MagicMock()

    result = update(firmware_client, return_result=True)

    assert result.success is True
    assert result.metadata["rebooted"] is False
    wait_mock.assert_called_once()

    # A dropped connection mid-poll doesn't necessarily mean a reboot
    # happened (see the module docstring above) - the final log here has
    # a ***DONE*** marker, so "Reboot detected." must NOT be reported even
    # though the connection did have to reconnect once.
    info_messages = [c.args[0] % c.args[1:] for c in firmware_client.logger.info.call_args_list]
    assert "Reboot detected." not in info_messages


def test_update_treats_ambiguous_log_as_reboot_when_reconnected_during_poll(
    monkeypatch, mocker, firmware_client
):
    """
    If polling reconnected at least once and the final log has no marker
    in either status() or last_log() (e.g. the lockfile was wiped by a
    reboot that happened while we were disconnected, and a reboot-
    required completion never got persisted to last_log() either), this
    must be treated as a probable reboot instead of a hard failure - the
    update almost certainly succeeded even though its log is
    unrecoverable. Without reconnected_during_poll being set, the same
    markerless log would raise (see test_update_raises_when_log_has_no_marker).
    """
    _stub_lifecycle(monkeypatch, firmware_client)
    _stub_get_info(monkeypatch, ["26.1", "26.1.11_10"])

    mocker.patch(
        "network_automation.platforms.opnsense.upgrade.firmware.update",
        return_value="OK",
    )
    mocker.patch(
        "network_automation.platforms.opnsense.upgrade.firmware.running",
        side_effect=["ready", Exception("Socket is closed"), "ready"],
    )
    mocker.patch(
        "network_automation.platforms.opnsense.upgrade.firmware.status",
        return_value="\n\n",
    )
    mocker.patch(
        "network_automation.platforms.opnsense.upgrade.firmware.last_log",
        return_value="",
    )
    wait_mock = mocker.patch.object(firmware_client, "wait_for_reconnect")
    firmware_client.logger = MagicMock()

    result = update(firmware_client, return_result=True)

    assert result.success is True
    assert result.metadata["rebooted"] is True
    assert result.metadata["reconnected_during_poll"] is True
    wait_mock.assert_called_once()

    info_messages = [c.args[0] % c.args[1:] for c in firmware_client.logger.info.call_args_list]
    assert info_messages.count("Reboot detected.") == 1


def test_update_logs_recovered_log_readably_when_reconnected_during_poll(
    monkeypatch, mocker, firmware_client
):
    """
    When reconnected_during_poll recovers real content from last_log()
    that just lacks a ***DONE***/***REBOOT*** marker, the message must
    render it with real newlines (%s), not an escaped single-line repr
    (%r) - a large recovered log shouldn't turn into one unreadable line.
    """
    _stub_lifecycle(monkeypatch, firmware_client)
    _stub_get_info(monkeypatch, ["26.1", "26.1.11_10"])

    mocker.patch(
        "network_automation.platforms.opnsense.upgrade.firmware.update",
        return_value="OK",
    )
    mocker.patch(
        "network_automation.platforms.opnsense.upgrade.firmware.running",
        side_effect=["ready", Exception("Socket is closed"), "ready"],
    )
    mocker.patch(
        "network_automation.platforms.opnsense.upgrade.firmware.status",
        return_value="",
    )
    mocker.patch(
        "network_automation.platforms.opnsense.upgrade.firmware.last_log",
        return_value="line one\nline two\n",
    )
    firmware_client.wait_for_reconnect = MagicMock()
    firmware_client.logger = MagicMock()

    result = update(firmware_client, return_result=True)

    assert result.metadata["rebooted"] is True
    assert result.metadata["log"] == "line one\nline two\n"

    matching = [
        c for c in firmware_client.logger.info.call_args_list
        if "connection was lost" in c.args[0]
    ]
    assert len(matching) == 1
    msg, *args = matching[0].args
    rendered = msg % tuple(args)
    assert "line one\nline two" in rendered
    assert "\\n" not in rendered


def test_update_failure_marks_result_and_reraises(monkeypatch, firmware_client):
    _stub_lifecycle(monkeypatch, firmware_client)
    monkeypatch.setattr(
        "network_automation.platforms.opnsense.upgrade.get_info",
        MagicMock(side_effect=RuntimeError("boom")),
    )

    with pytest.raises(RuntimeError, match="boom"):
        update(firmware_client, return_result=True)


def test_update_logs_verifying_installation_and_completion_bookends(
    monkeypatch, mocker, firmware_client
):
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
    firmware_client.logger = MagicMock()

    update(firmware_client, return_result=True)

    info_messages = [c.args[0] % c.args[1:] for c in firmware_client.logger.info.call_args_list]
    assert "Verifying installation..." in info_messages
    assert "Update completed: 26.1 -> 26.1.11_10" in info_messages
    assert (
        info_messages.index("Verifying installation...")
        < info_messages.index("Update completed: 26.1 -> 26.1.11_10")
    )


def test_update_reports_no_update_needed_when_version_unchanged(
    monkeypatch, mocker, firmware_client
):
    _stub_lifecycle(monkeypatch, firmware_client)
    _stub_get_info(monkeypatch, ["26.1.11_10", "26.1.11_10"])

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
    firmware_client.logger = MagicMock()

    result = update(firmware_client, return_result=True)

    assert result.metadata["version_changed"] is False
    assert result.message == "Already up to date: 26.1.11_10. No update was needed."

    info_messages = [c.args[0] % c.args[1:] for c in firmware_client.logger.info.call_args_list]
    assert "Already up to date: 26.1.11_10. No update was needed." in info_messages
    assert not any("Update completed:" in m for m in info_messages)


def test_update_writes_detail_log_with_raw_lines_and_stage_markers_and_overwrites(
    monkeypatch, mocker, firmware_client, tmp_path
):
    _stub_lifecycle(monkeypatch, firmware_client)
    _stub_get_info(monkeypatch, ["26.1", "26.1.11_10", "26.1", "26.1.11_10"])
    firmware_client.debug_log_dir = str(tmp_path)
    firmware_client.host = "10.0.0.1"

    mocker.patch(
        "network_automation.platforms.opnsense.upgrade.firmware.running",
        side_effect=["ready", "busy", "ready", "ready", "busy", "ready"],
    )
    mocker.patch(
        "network_automation.platforms.opnsense.upgrade.firmware.update",
        return_value="OK",
    )
    mocker.patch(
        "network_automation.platforms.opnsense.upgrade.time.sleep",
    )
    mocker.patch(
        "network_automation.platforms.opnsense.upgrade.firmware.status",
        side_effect=[
            "[1/1] Fetching foo.pkg: .... done\n***GOT REQUEST***\n...\n***DONE***",
            "[1/1] Fetching foo.pkg: .... done\n***GOT REQUEST***\n...\n***DONE***",
            "second run content\n***GOT REQUEST***\n...\n***DONE***",
            "second run content\n***GOT REQUEST***\n...\n***DONE***",
        ],
    )
    firmware_client.logger = MagicMock()

    update(firmware_client, return_result=True)
    log_path = tmp_path / "10.0.0.1_update.log"
    first_content = log_path.read_text()
    assert "[1/1] Fetching foo.pkg: .... done" in first_content
    assert "STAGE: Downloading packages..." in first_content

    info_messages = [c.args[0] % c.args[1:] for c in firmware_client.logger.info.call_args_list]
    assert info_messages[-1] == f"Detail log saved to: {log_path}"

    update(firmware_client, return_result=True)
    second_content = log_path.read_text()
    assert "[1/1] Fetching foo.pkg" not in second_content
    assert "second run content" in second_content


def test_update_does_not_log_detail_log_path_when_debug_log_dir_is_none(
    monkeypatch, mocker, firmware_client
):
    firmware_client.debug_log_dir = None
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
    firmware_client.logger = MagicMock()

    update(firmware_client, return_result=True)

    info_messages = [c.args[0] % c.args[1:] for c in firmware_client.logger.info.call_args_list]
    assert not any("Detail log saved to:" in m for m in info_messages)


# -------------------------------------------------------
# upgrade()
# -------------------------------------------------------

def test_upgrade_detects_branch_change(monkeypatch, mocker, firmware_client):
    """opnsense-version's real output is decorated ("OPNsense X.Y.Z_B
    (amd64)"), not a bare version string - use that shape here so this
    test actually exercises normalize_branch() against realistic input."""
    _stub_lifecycle(monkeypatch, firmware_client)
    _stub_get_info(
        monkeypatch,
        ["OPNsense 26.1.11_10 (amd64)", "OPNsense 26.7 (amd64)"],
    )

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
    firmware_client.logger = MagicMock()

    result = upgrade(firmware_client, return_result=True)

    assert result.metadata["current_branch"] == "26.1"
    assert result.metadata["final_branch"] == "26.7"
    assert result.metadata["branch_changed"] is True
    assert result.metadata["rebooted"] is True
    wait_mock.assert_called_once()

    info_messages = [c.args[0] % c.args[1:] for c in firmware_client.logger.info.call_args_list]
    assert info_messages.count("Reboot detected.") == 1


def test_upgrade_no_branch_change_reported(monkeypatch, mocker, firmware_client):
    _stub_lifecycle(monkeypatch, firmware_client)
    _stub_get_info(
        monkeypatch,
        ["OPNsense 26.1.11_10 (amd64)", "OPNsense 26.1.11_10 (amd64)"],
    )

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
    firmware_client.logger = MagicMock()

    result = upgrade(firmware_client, return_result=True)

    assert result.metadata["branch_changed"] is False
    assert result.metadata["rebooted"] is False
    wait_mock.assert_not_called()
    assert result.message == "Already on branch 26.1. No upgrade was needed."

    info_messages = [c.args[0] % c.args[1:] for c in firmware_client.logger.info.call_args_list]
    assert "Already on branch 26.1. No upgrade was needed." in info_messages


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
