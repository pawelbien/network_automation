# network_automation/platforms/opnsense/info.py

"""
OPNsense device information helpers.
"""

import re

from network_automation.results import OperationResult
from network_automation.platforms.opnsense.debug_log import debug_log


def _send(client, command: str) -> str:
    """Run a shell command, logging it at DEBUG level when
    client.context.debug_log is enabled (see debug_log.py)."""
    debug_log(client, "send_command: %s", command)
    output = client.conn.send_command(command)
    debug_log(client, "send_command response: %s", output)
    return output


def _get_hostname(client):
    """Read the device hostname. Mandatory field."""
    output = _send(client, "hostname")

    hostname = output.strip()
    if not hostname:
        raise ValueError("Hostname not found in 'hostname' output.")

    return hostname


def _get_opnsense_version(client):
    """
    Read the OPNsense version. Mandatory field.

    Absolute path, not just "opnsense-version" - same PATH robustness
    reasoning as firmware.py's _CONFIGCTL: this is an OPNsense-local
    /usr/local/sbin script, not a base-system utility, so it can't be
    assumed present on every possible session's PATH.
    """
    output = _send(client, "/usr/local/sbin/opnsense-version")

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
        output = _send(client, "uname -r")
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
        output = _send(client, "uptime")
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


# -------------------------------------------------------
# Version comparison
# -------------------------------------------------------
#
# OPNsense version strings ("26.1", "26.1.11_10", "26.7") don't fit a
# clean dotted-semver tuple: the "_10" suffix is a package/build counter,
# not a patch level, and isn't always present. Two distinct comparisons
# are needed, matching update() vs upgrade():
#
# - normalize_branch()/is_newer_branch() only look at MAJOR.MINOR - used
#   by upgrade() to decide whether the release branch itself changed.
# - normalize_version()/is_newer_version() look at the full string - used
#   by update() to decide whether the version moved forward within the
#   same branch.
#
# Neither is used to compare against a caller-supplied exact target
# version (unlike MikroTik's is_newer_version()) - OPNsense doesn't let a
# caller pick an exact target build the way MikroTik's /tool fetch does,
# so verification only checks that the branch/version moved forward.

# Unanchored - opnsense-version's actual output is decorated
# ("OPNsense 26.1.11_10 (amd64)"), not a bare version string, so the
# version substring must be found rather than matched from position 0.
_BRANCH_RE = re.compile(r"(\d+)\.(\d+)")
_VERSION_RE = re.compile(r"(\d+)\.(\d+)(?:\.(\d+))?(?:_(\d+))?")


def normalize_branch(version: str) -> tuple[int, int]:
    """Extract (major, minor) from an OPNsense version, e.g. "OPNsense 26.1.11_10 (amd64)" -> (26, 1)."""
    match = _BRANCH_RE.search(version.strip())
    if not match:
        raise ValueError(f"Cannot extract branch from OPNsense version: {version!r}")
    return (int(match.group(1)), int(match.group(2)))


def is_newer_branch(current_version: str, target_version: str) -> bool:
    """Return True if target_version is on a newer release branch than current_version."""
    return normalize_branch(target_version) > normalize_branch(current_version)


def normalize_version(version: str) -> tuple[int, int, int, int]:
    """
    Extract (major, minor, patch, build) from an OPNsense version, e.g.
    "OPNsense 26.1.11_10 (amd64)" -> (26, 1, 11, 10). patch/build default
    to 0 when absent (e.g. "26.1" -> (26, 1, 0, 0)).
    """
    match = _VERSION_RE.search(version.strip())
    if not match:
        raise ValueError(f"Cannot parse OPNsense version: {version!r}")
    major, minor, patch, build = match.groups()
    return (int(major), int(minor), int(patch or 0), int(build or 0))


def is_newer_version(current_version: str, target_version: str) -> bool:
    """Return True if target_version is newer than current_version within the same branch."""
    return normalize_version(target_version) > normalize_version(current_version)


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
    hostname = _get_hostname(client)
    client.logger.info("Hostname: %s", hostname)
    client.logger.info("Reading system info...")
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
        debug_log(client, "read_info() result.metadata: %s", result.metadata)
        client.disconnect()
