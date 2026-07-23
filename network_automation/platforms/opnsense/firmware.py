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


def check(client) -> str:
    """Kick off an asynchronous check for available updates."""
    return client.conn.send_command("configctl firmware check").strip()


def update(client) -> str:
    """Kick off an update within the device's current release branch."""
    return client.conn.send_command("configctl firmware update").strip()


def upgrade(client) -> str:
    """Kick off a migration to a new OPNsense release branch."""
    return client.conn.send_command("configctl firmware upgrade").strip()


def running(client) -> str:
    """
    Return "busy" or "ready" depending on whether the firmware backend
    currently holds its lockfile (`flock` on /tmp/pkg_upgrade.progress) -
    the only thing this check reflects, not PID/daemon/rc state.
    """
    return client.conn.send_command("configctl firmware running").strip()


def status(client) -> str:
    """
    Return the full transcript of the currently running (or just
    finished) firmware operation - a raw `cat` of the lockfile, not a
    short status line.
    """
    return client.conn.send_command("configctl firmware status")


def last_log(client) -> str:
    """
    Return the persisted log of the last completed firmware operation
    (copied from the lockfile on completion), or an empty string if no
    operation has run yet.
    """
    return client.conn.send_command("configctl firmware log show")
