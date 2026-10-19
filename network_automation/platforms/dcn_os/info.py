# network_automation/platforms/dcn_os/info.py

import re

from network_automation.results import OperationResult

# First line of 'show version': "  S5750E-28X-SI Device, Compiled on ..."
_MODEL_RE = re.compile(r"^\s*(\S+)\s+Device,\s+Compiled", re.MULTILINE)
# Version line differs between firmware releases:
#   "  SoftWare Package Version V700R001C001B001"   (V700R, V706R)
#   "  SoftWare Version V702R001C001"               (V702R)
_VERSION_RE = re.compile(r"^\s*SoftWare(?: Package)? Version\s+(\S+)", re.MULTILINE)
# Serial line differs between firmware releases:
#   "  Serial No.:SW0000000000000001"           (V700R...)
#   "  Serial No        SW0000000000000002"     (V706R...)
_SERIAL_RE = re.compile(r"^\s*Serial No\.?:?[ \t]*([A-Za-z0-9]\S*)", re.MULTILINE)
# 'show vendor' row: "DevType(ID)     4            360"
_DEVTYPE_ID_RE = re.compile(r"^DevType\(ID\)\s+\d+\s+(\S+)", re.MULTILINE)


def _parse_show_version(output: str) -> dict:
    model = _MODEL_RE.search(output)
    if not model:
        raise ValueError("Model not found in 'show version' output")

    version = _VERSION_RE.search(output)
    if not version:
        raise ValueError("Version not found in 'show version' output")

    serial = _SERIAL_RE.search(output)
    if not serial:
        raise ValueError("Serial number not found in 'show version' output")

    return {
        "model": model.group(1),
        "version": version.group(1),
        "serial": serial.group(1),
    }


def _parse_show_vendor(output: str) -> str:
    devtype_id = _DEVTYPE_ID_RE.search(output)
    if not devtype_id:
        raise ValueError("DevType(ID) not found in 'show vendor' output")

    return devtype_id.group(1)


def get_info(client):
    client.logger.info("Reading system info...")

    version_output = client.conn.send_command("show version")
    parsed = _parse_show_version(version_output)

    vendor_output = client.conn.send_command("show vendor")
    devtype_id = _parse_show_vendor(vendor_output)

    client.current_version = parsed["version"]

    # 'show version' has no hostname; Netmiko's base prompt is the hostname.
    unit = {
        "id": 0,
        "role": "master",
        "version": parsed["version"],
        "name": client.conn.base_prompt,
        "serial": parsed["serial"],
        "model": parsed["model"],
        "devtype_id": devtype_id,
    }
    return {"units": [unit]}


def extract_discovery_facts(units):
    """
    Reduce get_info()'s unit list to the single-unit CMDB facts Device
    Discovery needs.

    software_version is the 'SoftWare Package Version' / 'SoftWare
    Version' string (e.g. "V700R001C001B001"), the format SoftwareVersion.version uses for this
    platform. model is the 'show version' model (e.g. "S5750E-28X-SI").
    devtype_id is the 'show vendor' DevType(ID) (e.g. "360"), the
    identifier DCN firmware images are built for; Device Discovery
    compares it with the device type's dcn_firmware_devtype_id.

    Returns dict: {"serial": str, "software_version": str, "model": str,
    "devtype_id": str}.
    """
    unit = units[0]
    return {
        "serial": unit["serial"],
        "software_version": unit["version"],
        "model": unit["model"],
        "devtype_id": unit["devtype_id"],
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
