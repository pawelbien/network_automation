# network_automation/platforms/opnsense/firmware.py

"""
Low-level primitives for OPNsense's native firmware backend
(`configctl firmware ...`), run over the existing SSH shell session.

Each function maps 1:1 onto a single shell command and returns its raw
output - no polling, no marker parsing, no connect/disconnect. The
process-level logic (start an operation, poll until done, detect a
required reboot, verify the result) lives in upgrade.py, the only caller
of these functions.
"""

from network_automation.platforms.opnsense.debug_log import debug_log

# Absolute path, not just "configctl" - observed live (2026-07-23) that a
# session re-established mid-upgrade (e.g. right after openssh-portable
# itself gets replaced) can land with a PATH that doesn't include
# /usr/local/sbin, making a bare "configctl" fail with "not found" instead
# of running - silently breaking every subsequent poll instead of raising.
_CONFIGCTL = "/usr/local/sbin/configctl"


def _send(client, command: str) -> str:
    """Run a `configctl firmware ...` command, logging it at DEBUG level
    when client.context.debug_log is enabled (see debug_log.py)."""
    debug_log(client, "send_command: %s", command)
    output = client.conn.send_command(command)
    debug_log(client, "send_command response: %s", output)
    return output


def check(client) -> str:
    """Kick off an asynchronous check for available updates."""
    return _send(client, f"{_CONFIGCTL} firmware check").strip()


def update(client) -> str:
    """Kick off an update within the device's current release branch."""
    return _send(client, f"{_CONFIGCTL} firmware update").strip()


def upgrade(client) -> str:
    """Kick off a migration to a new OPNsense release branch."""
    return _send(client, f"{_CONFIGCTL} firmware upgrade").strip()


def running(client) -> str:
    """
    Return "busy" or "ready" depending on whether the firmware backend
    currently holds its lockfile (`flock` on /tmp/pkg_upgrade.progress) -
    the only thing this check reflects, not PID/daemon/rc state.
    """
    return _send(client, f"{_CONFIGCTL} firmware running").strip()


def status(client) -> str:
    """
    Return the full transcript of the currently running (or just
    finished) firmware operation - a raw `cat` of the lockfile, not a
    short status line.
    """
    return _send(client, f"{_CONFIGCTL} firmware status")


def last_log(client) -> str:
    """
    Return the persisted log of the last completed firmware operation
    (copied from the lockfile on completion), or an empty string if no
    operation has run yet.
    """
    return _send(client, f"{_CONFIGCTL} firmware log show")
