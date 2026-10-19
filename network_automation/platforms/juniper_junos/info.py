# network_automation/platforms/juniper_junos/info.py

import re

from network_automation.results import OperationResult

_HOSTNAME_RE = re.compile(r"^Hostname:\s*(\S+)", re.MULTILINE)
_MODEL_RE = re.compile(r"^Model:\s*(\S+)", re.MULTILINE)
# Junos 15.1+ prints "Junos: 21.4R3-S5.4"; older releases only list
# packages, e.g. "JUNOS Base OS boot [12.3R12.4]".
_VERSION_RE = re.compile(r"^Junos:\s*(\S+)", re.MULTILINE)
_LEGACY_VERSION_RE = re.compile(r"^JUNOS .*?\[(\S+)\]", re.MULTILINE)
_CHASSIS_SERIAL_RE = re.compile(r"^Chassis\s+(\S+)", re.MULTILINE)


def _parse_show_version(output: str) -> dict:
    """
    Parse 'show version'. On multi-RE / Virtual Chassis / cluster systems
    the output repeats per member (re0:, fpc0:, node0: ...); the first
    block is used.
    """
    hostname = _HOSTNAME_RE.search(output)
    if not hostname:
        raise ValueError("Hostname not found in 'show version' output")

    model = _MODEL_RE.search(output)
    if not model:
        raise ValueError("Model not found in 'show version' output")

    version = _VERSION_RE.search(output) or _LEGACY_VERSION_RE.search(output)
    if not version:
        raise ValueError("Version not found in 'show version' output")

    return {
        "name": hostname.group(1),
        "version": version.group(1),
        "model": model.group(1),
    }


def _parse_chassis_hardware(output: str) -> str:
    serial = _CHASSIS_SERIAL_RE.search(output)
    if not serial:
        raise ValueError("Chassis serial number not found in 'show chassis hardware' output")

    return serial.group(1)


def get_info(client):
    client.logger.info("Reading system info...")

    version_output = client.conn.send_command("show version")
    parsed = _parse_show_version(version_output)

    hardware_output = client.conn.send_command("show chassis hardware")
    serial = _parse_chassis_hardware(hardware_output)

    client.current_version = parsed["version"]

    unit = {
        "id": 0,
        "role": "master",
        "version": parsed["version"],
        "name": parsed["name"],
        "serial": serial,
        "model": parsed["model"],
    }
    return {"units": [unit]}


def extract_discovery_facts(units):
    """
    Reduce get_info()'s unit list to the single-unit CMDB facts Device
    Discovery needs: serial number, software version and model.

    Virtual Chassis members are not split into units in this library, so
    units[0] always holds the chassis serial. software_version is the full
    release string including the build number (e.g. "21.4R3-S5.4"), which
    is the format SoftwareVersion.version uses for this platform. model is
    the 'show version' model (e.g. "mx204"); Device Discovery compares it
    case-insensitively with the device type.

    Returns dict: {"serial": str, "software_version": str, "model": str}.
    """
    unit = units[0]
    return {
        "serial": unit["serial"],
        "software_version": unit["version"],
        "model": unit["model"],
    }


def read_info(client, *, return_result: bool = False):
    result = OperationResult(success=True, operation="info")
    result.mark_started()

    client.connect()
    try:
        info = get_info(client)
        result.metadata.update(info)
        result.message = "Info retrieved successfully."
    except Exception as exc:
        result.success = False
        result.errors.append(str(exc))
        raise
    finally:
        result.mark_finished()
        client.disconnect()

    return result if return_result else info
