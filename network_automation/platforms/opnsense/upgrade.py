# network_automation/platforms/opnsense/upgrade.py

"""
OPNsense firmware update/upgrade workflows.

OPNsense's GUI does not perform firmware operations itself - it only
triggers the native `configctl firmware ...` backend, which runs as a
detached daemon (configd -> daemon -f -> launcher.sh -> update.sh/
upgrade.sh -> opnsense-update) synchronized purely through a lockfile
(flock on /tmp/pkg_upgrade.progress). The SSH session used to start an
operation is not part of its ongoing execution, so these workflows poll
for completion (firmware.running()/status()) instead of watching live
command output.

Three distinct, independently callable operations, all built on the same
poll-then-detect-reboot-then-verify shape (_run_and_wait below):

- check_updates() - `configctl firmware check`, read-only, never reboots.
- update()        - `configctl firmware update`, updates within the
                     current release branch; reboots only if the backend
                     decided a base/kernel update required one.
- upgrade()        - `configctl firmware upgrade`, migrates to a new
                     release branch; reboots only if the backend decided
                     one was required.

update() and upgrade() are deliberately independent - upgrade() never
calls update() first. If the device isn't fully up to date on its current
branch, the backend may reject the upgrade; it's the caller's
responsibility to run update() first when that's needed (see
docs/architecture.md and the OPNsense platform notes in
engineering_handbook for the operational sequencing example).
"""

import time

from network_automation.results import OperationResult
from network_automation.platforms.opnsense import firmware
from network_automation.platforms.opnsense.debug_log import debug_log, debug_timed_step
from network_automation.platforms.opnsense.detail_log import open_detail_log
from network_automation.platforms.opnsense.exceptions import OPNsenseFirmwareError
from network_automation.platforms.opnsense.info import (
    get_info,
    normalize_branch,
    is_newer_branch,
)
from network_automation.platforms.opnsense.progress import ProgressParser


def _has_reboot_marker(text: str) -> bool:
    return "***REBOOT***" in text


def _has_done_marker(text: str) -> bool:
    return "***DONE***" in text


def _looks_like_shell_error(text: str) -> bool:
    """
    True if `text` looks like a shell error rather than real
    running()/status() output - e.g. configctl (a symlink into the
    opnsense package) can transiently report "not found" while that same
    package is mid-replacing its own files. Never equals "ready"/"busy",
    so the poll loop already tolerates it; this only picks a clearer log
    message instead of dumping the raw error text every poll.
    """
    return "not found" in text or "No such file or directory" in text


def _poll_call(client, fn, action_name: str, result: OperationResult, dlog):
    """
    Call a firmware.py primitive (running()/status()/last_log()) while
    polling, reconnecting once if the SSH session was lost.

    The configctl firmware backend runs detached from our polling session
    (see module docstring), so a dropped connection here means "reconnect
    and keep polling," not "the firmware operation failed" - only a
    reconnect failure (TimeoutError, propagated uncaught) or a second,
    immediate failure right after reconnecting is treated as fatal.

    Records result.metadata["reconnected_during_poll"] = True on
    reconnect - used by _run_and_wait() to tell a genuinely ambiguous
    final log apart from one that's ambiguous because a reboot happened
    while we were disconnected (see the "no marker" branch there), and to
    decide whether "Reboot detected." has already been reported.
    """
    try:
        return fn(client)
    except Exception as exc:
        client.logger.warning(
            "Lost connection while polling %s (%s) - reconnecting...",
            action_name, exc,
        )
        dlog.event(
            "Lost connection while polling %s (%s) - reconnecting...",
            action_name, exc,
        )
        result.metadata["reconnected_during_poll"] = True
        client.conn = None
        client.wait_for_reconnect()
        return fn(client)


_KEEPALIVE_INTERVAL = 60


def _new_status_suffix(current_text: str, last_len: int) -> tuple[str, int]:
    """
    Return (new_suffix, updated_len) for status(), which returns the
    entire accumulated lockfile content on every call, not just what's
    new. A current_text shorter than last_len means the lockfile was
    reset (e.g. by a reboot) - the whole text counts as new in that case,
    since there's nothing sane left to diff against.
    """
    new_text = current_text if len(current_text) < last_len else current_text[last_len:]
    return new_text, len(current_text)


def _run_and_wait(client, action_fn, action_name: str, result: OperationResult) -> None:
    """
    Start a configctl firmware action and block until it completes.

    Raises OPNsenseFirmwareError if the backend is already busy, if the
    poll loop exceeds client.firmware_poll_timeout, or if the final log
    contains neither a ***DONE*** nor a ***REBOOT*** marker.

    On a ***REBOOT*** marker: marks client.conn as gone (the backend's own
    rc.reboot may have already dropped it) and calls client.wait_for_reconnect()
    directly - never client.reboot(), since the reboot here is a side effect
    of the already-running backend job, not something this call initiates.

    User-facing logging (client.logger, e.g. the Nautobot Job log) only
    ever sees stage transitions from a ProgressParser plus an occasional
    "Still working..." keepalive - never raw CLI output. Every raw line,
    reconnect attempt, and exception is additionally written to a detail
    log file (see detail_log.py), gated by client.debug_log_dir.

    Reboot detection/reporting ("Reboot detected.") is NOT handled by the
    parser: the only observed real-world signal is a dropped connection
    mid-poll with no textual marker at all (see _poll_call()), which isn't
    something a line-in/message-out parser can represent, and a dropped
    connection alone doesn't prove a reboot happened (e.g. sshd restarting
    while its own package is replaced can drop the session with the
    device never rebooting at all). So it's reported only once the final
    outcome is known - from the post-loop ***REBOOT***-marker branch, or
    the "reconnected but no marker recovered" ambiguous branch - never
    eagerly mid-loop. A mid-loop reconnect does eagerly reset the parser's
    epoch, though (see parser_reset_for_reconnect below), since if it does
    turn out to be a real reboot, later lines describe a legitimately new
    run. "Waiting for device..."/"Device is back online." remain owned by
    reboot.py's wait_for_reconnect(), reused unchanged.

    Sets result.metadata["log"] and result.metadata["rebooted"].
    """
    with open_detail_log(client, action_name) as dlog:
        try:
            _run_and_wait_inner(client, action_fn, action_name, result, dlog)
        except Exception as exc:
            dlog.exception(exc)
            raise


def _run_and_wait_inner(client, action_fn, action_name, result, dlog) -> None:
    if firmware.running(client) == "busy":
        raise OPNsenseFirmwareError(
            f"Cannot start {action_name}: firmware backend is already busy"
        )

    ack = action_fn(client)
    client.logger.info("%s started: %s", action_name, ack)
    dlog.event("%s started: %s", action_name, ack)

    parser = ProgressParser()
    parser_reset_for_reconnect = False

    def _announce_reboot_detected():
        """
        User-facing "Reboot detected." - only called once the final
        outcome is known (see the post-loop marker handling below), never
        eagerly on every mid-poll reconnect: a dropped connection during
        polling does not always mean the device rebooted (e.g. sshd
        itself restarting while its own package is being replaced can
        drop the session with the backend job - and the device - both
        still very much up; see test_update_reconnects_when_connection_lost_mid_poll).
        """
        client._safe_log_info("Reboot detected.")
        dlog.event("STAGE: Reboot detected.")

    def _emit(line):
        dlog.raw(line)
        message = parser.feed_line(line)
        if message:
            client._safe_log_info(message)
            dlog.event("STAGE: %s", message)
        return message is not None

    start = time.monotonic()
    last_status_len = 0
    last_progress_at = start
    pending = ""  # trailing line not yet terminated by "\n" - held back until it is
    shell_error_active = False

    while True:
        running_state = _poll_call(client, firmware.running, action_name, result, dlog)

        if result.metadata.get("reconnected_during_poll") and not parser_reset_for_reconnect:
            # A reboot is only *possible* here, not confirmed (see
            # _announce_reboot_detected()'s docstring) - but if the device
            # did reboot, any further output describes a new run (e.g.
            # the repository catalogue update can legitimately happen
            # again), so the parser's epoch is reset regardless. Harmless
            # in the rare false-alarm case (a sshd restart with no actual
            # reboot): worst case, one already-seen stage gets announced
            # a second time - a minor cosmetic duplicate, not raw-output
            # spam, and far cheaper than missing a real post-reboot stage.
            parser.reset()
            dlog.event(
                "%s: connection was reconnected mid-poll; progress parser "
                "epoch reset in case a reboot occurred",
                action_name,
            )
            parser_reset_for_reconnect = True
            last_progress_at = time.monotonic()

        if running_state == "ready":
            if shell_error_active:
                client._safe_log_info("%s: configctl available again", action_name)
                dlog.event("%s: configctl available again", action_name)
            if pending.strip():
                _emit(pending)
            break

        now = time.monotonic()
        if now - start > client.firmware_poll_timeout:
            raise OPNsenseFirmwareError(
                f"{action_name} did not complete within "
                f"{client.firmware_poll_timeout}s"
            )

        if _looks_like_shell_error(running_state):
            if not shell_error_active:
                client._safe_log_info(
                    "%s: configctl temporarily unavailable (expected "
                    "while replacing the opnsense package)",
                    action_name,
                )
                dlog.event(
                    "%s: configctl temporarily unavailable (expected "
                    "while replacing the opnsense package)",
                    action_name,
                )
                shell_error_active = True
        else:
            if shell_error_active:
                client._safe_log_info("%s: configctl available again", action_name)
                dlog.event("%s: configctl available again", action_name)
                shell_error_active = False

            status_text = _poll_call(client, firmware.status, action_name, result, dlog)
            new_text, last_status_len = _new_status_suffix(status_text, last_status_len)
            pending += new_text

            if "\n" in pending:
                *complete_lines, pending = pending.split("\n")
                progressed = False
                for line in complete_lines:
                    if not line.strip():
                        continue
                    if _emit(line):
                        progressed = True
                if progressed:
                    last_progress_at = now

        if now - last_progress_at > _KEEPALIVE_INTERVAL:
            client._safe_log_info("Still working...")
            dlog.event("KEEPALIVE")
            last_progress_at = now

        time.sleep(client.firmware_poll_interval)

    log_text = _poll_call(client, firmware.status, action_name, result, dlog)

    if not log_text.strip() or (
        not _has_reboot_marker(log_text) and not _has_done_marker(log_text)
    ):
        # LOCKFILE lives under /tmp, which OPNsense resets on reboot - if
        # our connection dropped and a reboot happened while we were
        # reconnecting, the lockfile may already be gone/empty by the
        # time we're back. The persisted log at LOGFILE (under
        # /var/cache) survives a reboot, so fall back to it before
        # giving up.
        fallback_log = _poll_call(client, firmware.last_log, action_name, result, dlog)
        if fallback_log.strip():
            log_text = fallback_log

    result.metadata["log"] = log_text

    if _has_reboot_marker(log_text):
        result.metadata["rebooted"] = True
        _announce_reboot_detected()

        # output_reboot() writes the marker, then `sleep 5`, then
        # rc.reboot - the device is still up for a few seconds after the
        # marker appears. Without this grace period, wait_for_reconnect()
        # can reconnect to that still-alive, about-to-die session and
        # declare success right before the real reboot severs it.
        client.logger.info(
            "Reboot required; waiting %ds for the backend's internal "
            "delay before rc.reboot actually runs...",
            client.reboot_grace_period,
        )
        dlog.event(
            "Reboot required; waiting %ds for the backend's internal "
            "delay before rc.reboot actually runs...",
            client.reboot_grace_period,
        )
        time.sleep(client.reboot_grace_period)

        try:
            client.conn.disconnect()
        except Exception:
            pass
        client.conn = None
        client.wait_for_reconnect()
    elif _has_done_marker(log_text):
        result.metadata["rebooted"] = False
    elif result.metadata.get("reconnected_during_poll"):
        # No marker in either log, but we know the connection was lost
        # and reconnected while polling - most likely the device
        # rebooted before we could observe the marker being written
        # (LOCKFILE lives under /tmp, wiped by reboot; a reboot-required
        # completion may not persist to LOGFILE either - see the
        # ***REBOOT*** branch above vs. output_done()'s copy step).
        # Treating this as a hard failure would be wrong when the update
        # most likely succeeded; the caller's own post-call get_info()
        # is the real verification of the outcome.
        if log_text.strip():
            client.logger.warning(
                "%s: connection was lost and reconnected while polling; "
                "assuming a reboot occurred (recovered log has no "
                "***DONE***/***REBOOT*** marker):\n%s",
                action_name, log_text,
            )
        else:
            client.logger.warning(
                "%s: connection was lost and reconnected while polling; "
                "assuming a reboot occurred (no log recovered)",
                action_name,
            )
        result.metadata["rebooted"] = True
        _announce_reboot_detected()
    else:
        raise OPNsenseFirmwareError(
            f"{action_name} log ended without ***DONE*** or ***REBOOT***: "
            f"{log_text!r}"
        )


def check_updates(client, *, return_result: bool = False):
    """
    Check for available updates (`configctl firmware check`). Read-only -
    never reboots, never modifies the device.
    """
    result = OperationResult(success=True, operation="check_updates")
    result.mark_started()

    client.connect()
    try:
        client._ensure_shell()

        with debug_timed_step(client, "check_updates"):
            _run_and_wait(client, firmware.check, "check", result)

        result.message = "Update check completed"
        client.logger.info("Update check completed.")
        return result if return_result else None

    except Exception as exc:
        result.success = False
        result.errors.append(str(exc))
        raise

    finally:
        result.mark_finished()
        debug_log(client, "check_updates() result.metadata: %s", result.metadata)
        client.disconnect()


def update(client, *, return_result: bool = False):
    """
    Update within the device's current release branch
    (`configctl firmware update`): package update, optional base/kernel
    update, reboot only if the backend decided one is required.
    """
    result = OperationResult(success=True, operation="update")
    result.mark_started()

    client.connect()
    try:
        client._ensure_shell()

        info = get_info(client)
        current_version = info["units"][0]["opnsense_version"]
        result.metadata["current_version"] = current_version

        with debug_timed_step(client, "update"):
            _run_and_wait(client, firmware.update, "update", result)

        client.logger.info("Verifying installation...")
        info_after = get_info(client)
        final_version = info_after["units"][0]["opnsense_version"]
        result.metadata["final_version"] = final_version

        result.message = f"Update completed: {current_version} -> {final_version}"
        client.logger.info("Update completed successfully.")
        return result if return_result else None

    except Exception as exc:
        result.success = False
        result.errors.append(str(exc))
        raise

    finally:
        result.mark_finished()
        debug_log(client, "update() result.metadata: %s", result.metadata)
        client.disconnect()


def upgrade(client, *, return_result: bool = False):
    """
    Migrate the device to a new OPNsense release branch
    (`configctl firmware upgrade`): reboot only if the backend decided one
    is required.

    Does NOT run update() first. If the device isn't up to date on its
    current branch, the backend may reject the upgrade - the caller is
    responsible for calling update() first when that's needed.
    """
    result = OperationResult(success=True, operation="upgrade")
    result.mark_started()

    client.connect()
    try:
        client._ensure_shell()

        info = get_info(client)
        current_version = info["units"][0]["opnsense_version"]
        current_branch = normalize_branch(current_version)
        result.metadata["current_branch"] = "%d.%d" % current_branch

        with debug_timed_step(client, "upgrade"):
            _run_and_wait(client, firmware.upgrade, "upgrade", result)

        client.logger.info("Verifying installation...")
        info_after = get_info(client)
        final_version = info_after["units"][0]["opnsense_version"]
        result.metadata["final_branch"] = "%d.%d" % normalize_branch(final_version)
        result.metadata["branch_changed"] = is_newer_branch(current_version, final_version)

        result.message = (
            f"Upgrade completed: {result.metadata['current_branch']} -> "
            f"{result.metadata['final_branch']}"
        )
        client.logger.info("Upgrade completed successfully.")
        return result if return_result else None

    except Exception as exc:
        result.success = False
        result.errors.append(str(exc))
        raise

    finally:
        result.mark_finished()
        debug_log(client, "upgrade() result.metadata: %s", result.metadata)
        client.disconnect()
