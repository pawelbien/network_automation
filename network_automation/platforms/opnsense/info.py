# network_automation/platforms/opnsense/info.py

"""
OPNsense device information helpers.
"""

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


def _get_uptime(client):
    """
    Read device uptime (raw BSD `uptime` output). Best-effort: returns None
    if the command fails or the output is empty, instead of raising.
    """
    try:
        output = client.conn.send_command("uptime")
    except Exception:
        return None

    return output.strip() or None


def get_info(client):
    """
    Collect system information and return a unified unit structure.

    Returns dict:
    {
        "units": [
            {
                "id":                int,        # always 0
                "role":              str,        # always "master"
                "hostname":          str,
                "opnsense_version":  str,
                "freebsd_version":   str | None,  # best-effort
                "uptime":            str | None,  # best-effort
            }
        ]
    }
    """
    client.logger.info("Reading system info...")

    hostname = _get_hostname(client)
    opnsense_version = _get_opnsense_version(client)

    client.hostname = hostname
    client.opnsense_version = opnsense_version

    unit = {
        "id": 0,
        "role": "master",
        "hostname": hostname,
        "opnsense_version": opnsense_version,
        "freebsd_version": _get_freebsd_version(client),
        "uptime": _get_uptime(client),
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
