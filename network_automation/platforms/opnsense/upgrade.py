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
from network_automation.platforms.opnsense.exceptions import OPNsenseFirmwareError
from network_automation.platforms.opnsense.info import (
    get_info,
    normalize_branch,
    is_newer_branch,
)


def _has_reboot_marker(text: str) -> bool:
    return "***REBOOT***" in text


def _has_done_marker(text: str) -> bool:
    return "***DONE***" in text


def _poll_call(client, fn, action_name: str):
    """
    Call a firmware.py primitive (running()/status()/last_log()) while
    polling, reconnecting once if the SSH session was lost.

    The configctl firmware backend runs detached from our polling session
    (see module docstring) - observed live (2026-07-23) that installing
    base/kernel packages can disrupt sshd and drop our connection well
    before any ***REBOOT*** marker appears, even though the backend job
    keeps running unaffected. A dropped connection here means "reconnect
    and keep polling," not "the firmware operation failed" - only a
    reconnect failure (TimeoutError, propagated uncaught) or a second,
    immediate failure right after reconnecting is treated as fatal.
    """
    try:
        return fn(client)
    except Exception as exc:
        client.logger.warning(
            "Lost connection while polling %s (%s) - reconnecting...",
            action_name, exc,
        )
        client.conn = None
        client.wait_for_reconnect()
        return fn(client)


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

    Sets result.metadata["log"] and result.metadata["rebooted"].
    """
    if firmware.running(client) == "busy":
        raise OPNsenseFirmwareError(
            f"Cannot start {action_name}: firmware backend is already busy"
        )

    ack = action_fn(client)
    client.logger.info("%s started: %s", action_name, ack)

    start = time.monotonic()
    while True:
        if _poll_call(client, firmware.running, action_name) == "ready":
            break

        if time.monotonic() - start > client.firmware_poll_timeout:
            raise OPNsenseFirmwareError(
                f"{action_name} did not complete within "
                f"{client.firmware_poll_timeout}s"
            )

        client._safe_log_info(
            "%s in progress:\n%s",
            action_name,
            _poll_call(client, firmware.status, action_name),
        )
        time.sleep(client.firmware_poll_interval)

    log_text = _poll_call(client, firmware.status, action_name)

    if not log_text.strip() or (
        not _has_reboot_marker(log_text) and not _has_done_marker(log_text)
    ):
        # LOCKFILE lives under /tmp, which OPNsense resets on reboot - if
        # our connection dropped and a reboot happened while we were
        # reconnecting, the lockfile may already be gone/empty by the
        # time we're back. The persisted log at LOGFILE (under
        # /var/cache) survives a reboot, so fall back to it before
        # giving up.
        fallback_log = _poll_call(client, firmware.last_log, action_name)
        if fallback_log.strip():
            log_text = fallback_log

    result.metadata["log"] = log_text

    if _has_reboot_marker(log_text):
        result.metadata["rebooted"] = True

        # output_reboot() writes the ***REBOOT*** marker, then `sleep 5`,
        # then rc.reboot - observed live (2026-07-23) to mean the device
        # is still fully up for a few seconds after the marker appears.
        # Without this grace period, wait_for_reconnect()'s first attempt
        # can land on that still-alive, about-to-die session: the
        # readiness probe succeeds, we call it reconnected, and the real
        # reboot then kills that same connection moments later, surfacing
        # as "Socket is closed" on the very next command (get_info() right
        # after this function returns).
        client.logger.info(
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

        info_after = get_info(client)
        final_version = info_after["units"][0]["opnsense_version"]
        result.metadata["final_version"] = final_version

        result.message = f"Update completed: {current_version} -> {final_version}"
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

        info_after = get_info(client)
        final_version = info_after["units"][0]["opnsense_version"]
        result.metadata["final_branch"] = "%d.%d" % normalize_branch(final_version)
        result.metadata["branch_changed"] = is_newer_branch(current_version, final_version)

        result.message = (
            f"Upgrade completed: {result.metadata['current_branch']} -> "
            f"{result.metadata['final_branch']}"
        )
        return result if return_result else None

    except Exception as exc:
        result.success = False
        result.errors.append(str(exc))
        raise

    finally:
        result.mark_finished()
        debug_log(client, "upgrade() result.metadata: %s", result.metadata)
        client.disconnect()
