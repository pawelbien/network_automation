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


def _send(client, command: str) -> str:
    """Run a `configctl firmware ...` command, logging it at DEBUG level
    when client.context.debug_log is enabled (see debug_log.py)."""
    debug_log(client, "send_command: %s", command)
    output = client.conn.send_command(command)
    debug_log(client, "send_command response: %s", output)
    return output


def check(client) -> str:
    """Kick off an asynchronous check for available updates."""
    return _send(client, "configctl firmware check").strip()


def update(client) -> str:
    """Kick off an update within the device's current release branch."""
    return _send(client, "configctl firmware update").strip()


def upgrade(client) -> str:
    """Kick off a migration to a new OPNsense release branch."""
    return _send(client, "configctl firmware upgrade").strip()


def running(client) -> str:
    """
    Return "busy" or "ready" depending on whether the firmware backend
    currently holds its lockfile (`flock` on /tmp/pkg_upgrade.progress) -
    the only thing this check reflects, not PID/daemon/rc state.
    """
    return _send(client, "configctl firmware running").strip()


def status(client) -> str:
    """
    Return the full transcript of the currently running (or just
    finished) firmware operation - a raw `cat` of the lockfile, not a
    short status line.
    """
    return _send(client, "configctl firmware status")


def last_log(client) -> str:
    """
    Return the persisted log of the last completed firmware operation
    (copied from the lockfile on completion), or an empty string if no
    operation has run yet.
    """
    return _send(client, "configctl firmware log show")
