# network_automation/platforms/opnsense/info.py

"""
OPNsense device information helpers.
"""

import re

from network_automation.results import OperationResult


def _get_hostname(client):
    """Read the device hostname. Mandatory field."""
    output = client.conn.send_command("hostname")

    hostname = output.strip()
    if not hostname:
        raise ValueError("Hostname not found in 'hostname' output.")

    return hostname


def _get_opnsense_version(client):
    """Read the OPNsense version. Mandatory field."""
    output = client.conn.send_command("opnsense-version")

    version = output.strip()
    if not version:
        raise ValueError(
            "OPNsense version not found in 'opnsense-version' output."
        )

    return version


def _get_freebsd_version(client):
    """
    Read the underlying FreeBSD version. Best-effort: returns None if the
    command fails or the output is empty, instead of raising.
    """
    try:
        output = client.conn.send_command("uname -r")
    except Exception:
        return None

    return output.strip() or None


_UPTIME_DURATION_RE = re.compile(
    r"^(?P<duration>.*?),\s*\d+\s+users?,\s*load averages:\s*(?P<loads>.*)$"
)


def _get_uptime(client):
    """
    Read device uptime and load averages from BSD `uptime`. Best-effort:
    returns (None, None) if the command fails or the output is empty,
    instead of raising.

    Full raw output looks like "11:13AM  up 54 mins, 1 user, load
    averages: 0.58, 0.56, 0.54" (or "... up 10 days, 4:32, 1 user, ..."
    for longer uptimes). The leading wall-clock time and the user count
    are dropped; only the duration and the three load averages are kept.

    The duration is returned exactly as BSD formats it - "N mins" (< 1h),
    "H:MM" (1h-1 day), or "D days, H:MM" (>= 1 day) - rather than
    converted to a single unit. BSD already scales the granularity to the
    magnitude (so a multi-year uptime reads as "1125 days, 3:12", not an
    unwieldy hour count), and reimplementing that conversion would just
    add parsing surface for no benefit.

    Returns (duration, load_averages) where load_averages is a
    (1min, 5min, 15min) tuple of floats. Falls back to
    (<trimmed output>, None) if the output doesn't match the expected
    "..., N user(s), load averages: a, b, c" shape.
    """
    try:
        output = client.conn.send_command("uptime")
    except Exception:
        return None, None

    raw = output.strip()
    if not raw:
        return None, None

    up_match = re.search(r"\bup\s+(.*)$", raw)
    after_up = up_match.group(1).strip() if up_match else raw

    match = _UPTIME_DURATION_RE.match(after_up)
    if not match:
        return after_up, None

    duration = match.group("duration").strip()
    load_averages = tuple(
        float(value) for value in match.group("loads").split(",")
    )

    return duration, load_averages


def get_info(client):
    """
    Collect system information and return a unified unit structure.

    Returns dict:
    {
        "units": [
            {
                "id":                int,                  # always 0
                "role":              str,                  # always "master"
                "hostname":          str,
                "opnsense_version":  str,
                "freebsd_version":   str | None,            # best-effort
                "uptime":            str | None,            # best-effort, e.g. "10 days, 4:32"
                "load_averages":     tuple[float, float, float] | None,  # best-effort
            }
        ]
    }
    """
    client.logger.info("Reading system info...")

    hostname = _get_hostname(client)
    opnsense_version = _get_opnsense_version(client)

    client.hostname = hostname
    client.opnsense_version = opnsense_version

    freebsd_version = _get_freebsd_version(client)
    uptime, load_averages = _get_uptime(client)

    unit = {
        "id": 0,
        "role": "master",
        "hostname": hostname,
        "opnsense_version": opnsense_version,
        "freebsd_version": freebsd_version,
        "uptime": uptime,
        "load_averages": load_averages,
    }

    return {"units": [unit]}


def read_info(client, *, return_result: bool = False):
    """
    Read system information as a full workflow operation (connect → enter
    shell → collect → disconnect).

    Returns:
        return_result=False: dict {"units": [...]}
        return_result=True:  OperationResult with metadata["units"]
    """
    result = OperationResult(
        success=True,
        operation="info",
    )

    result.mark_started()

    client.connect()
    try:
        client._ensure_shell()

        info = get_info(client)
        result.metadata.update(info)
        result.message = "System information read successfully"

        return result if return_result else info

    except Exception as exc:
        result.success = False
        result.errors.append(str(exc))
        raise

    finally:
        result.mark_finished()
        client.disconnect()
