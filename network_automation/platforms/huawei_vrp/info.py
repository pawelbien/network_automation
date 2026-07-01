# network_automation/platforms/huawei_vrp/info.py

"""
Huawei VRP device information helpers.
"""

import re

from network_automation.results import OperationResult


def _parse_version(output):
    """
    Parse 'display version' output.

    Returns list of partial unit dicts with keys:
    id, role, model, vrp_version, software_version.
    """
    vrp_version = None
    software_version = None
    model = None
    units = []

    for line in output.splitlines():
        line = line.strip()

        # VRP (R) software, Version 5.170 (AR650 V300R024C00SPC100)
        # Requires two tokens inside parens (platform name + version) to avoid
        # matching per-slot lines like "Software Version : VRP (..., Version 5.170 (V200R024C00SPC500))"
        m = re.search(r'Version\s+([\d.]+)\s+\(\S+\s+(V\w+)\)', line)
        if m:
            vrp_version = m.group(1)
            software_version = m.group(2)
            continue

        # Huawei AR651 Router uptime is ...
        # HUAWEI S6730-H24X6C Routing Switch uptime is ...
        m = re.search(
            r'(?:Huawei|HUAWEI)\s+(\S+)\s+(?:Routing Switch|Router|Switch)\s+uptime',
            line,
        )
        if m:
            model = m.group(1)
            continue

        # MPU 0(Master) : uptime is ...
        # ES6D2S30S003 1(Master)  : uptime is ...
        # ES6D2S30S003 2(Standby)  : uptime is ...
        m = re.search(r'\S+\s+(\d+)\s*\((Master|Standby)\)\s*:', line)
        if m:
            units.append({
                "id": int(m.group(1)),
                "role": m.group(2).lower(),
            })

    if not vrp_version:
        raise ValueError("VRP version not found in 'display version' output.")
    if not software_version:
        raise ValueError("Software version not found in 'display version' output.")
    if not model:
        raise ValueError("Device model not found in 'display version' output.")
    if not units:
        raise ValueError("No units (Master/Standby slots) found in 'display version' output.")

    for unit in units:
        unit["model"] = model
        unit["vrp_version"] = vrp_version
        unit["software_version"] = software_version

    return units


def _parse_esn(output):
    """
    Parse 'display esn' output.

    Returns dict mapping slot identifier to ESN string:
    - {"device": "ESN"} for single devices
    - {1: "ESN1", 2: "ESN2"} for stacked devices
    """
    esn_map = {}

    for line in output.splitlines():
        line = line.strip()

        # ESN of slot 1: 6R23C0039583
        m = re.match(r'ESN of slot\s+(\d+):\s*(\S+)', line)
        if m:
            esn_map[int(m.group(1))] = m.group(2)
            continue

        # ESN of device: 2S5001048324A0014851
        m = re.match(r'ESN of (\w+):\s*(\S+)', line)
        if m:
            esn_map[m.group(1)] = m.group(2)

    if not esn_map:
        raise ValueError("No ESN entries found in 'display esn' output.")

    return esn_map


def _parse_startup(output):
    """
    Parse 'display startup' output.

    Returns dict mapping role to startup fields:
    {
        "master":  {startup_image, next_startup_image, startup_patch, next_startup_patch},
        "standby": {...},   # only present for stacked devices
    }

    startup_patch / next_startup_patch are None when the device reports "null" or "default".
    """
    SECTION_ROLES = {
        "MainBoard": "master",
        "SlaveBoard": "standby",
    }

    result = {}
    current_role = None

    for line in output.splitlines():
        m = re.match(r'^(MainBoard|SlaveBoard):', line)
        if m:
            current_role = SECTION_ROLES[m.group(1)]
            result[current_role] = {
                "startup_image": None,
                "next_startup_image": None,
                "startup_patch": None,
                "next_startup_patch": None,
            }
            continue

        if current_role is None:
            continue

        # Key:    value   (alignment whitespace — require 2+ spaces before value)
        m = re.match(r'\s+(.+?):\s{2,}(\S.*)', line)
        if not m:
            continue

        key = m.group(1).strip()
        value = m.group(2).strip()
        optional = value if value not in ("null", "default") else None

        if key == "Startup system software":
            result[current_role]["startup_image"] = value
        elif key == "Next startup system software":
            result[current_role]["next_startup_image"] = value
        elif key == "Startup patch package":
            result[current_role]["startup_patch"] = optional
        elif key == "Next startup patch package":
            result[current_role]["next_startup_patch"] = optional

    if not result:
        raise ValueError("No startup sections (MainBoard/SlaveBoard) found in 'display startup' output.")

    return result


def _parse_patch_information(output):
    """
    Parse 'display patch-information' output.

    Returns dict:
    {
        "patch_version":      str | None,  # e.g. "ARV300R023SPH1b0"
        "patch_package_name": str | None,  # e.g. "flash:/AR650A_V300R023SPH1b0.pat"
        "state":              str | None,  # e.g. "Running"
    }

    All fields are None when no patch is currently installed — that's a
    valid device state, not a parse error (unlike _parse_version's required
    fields).
    """
    m_version = re.search(r'Patch version\s*:\s*(\S+)', output)
    m_package = re.search(r'Patch package name\s*:\s*(\S+)', output)
    m_state = re.search(r'The current state is\s*:\s*(\S+)', output)

    return {
        "patch_version": m_version.group(1) if m_version else None,
        "patch_package_name": m_package.group(1) if m_package else None,
        "state": m_state.group(1) if m_state else None,
    }


def get_patch_info(client):
    """
    Read the currently active patch version and state.

    Runs: display patch-information.

    - no connect/disconnect
    - not part of get_info()/read_info() — only called from upgrade.py when
      a patch operation is requested, so it never affects the get_info()
      command sequence.
    """
    output = client.conn.send_command("display patch-information")
    return _parse_patch_information(output)


def get_info(client):
    """
    Collect device information from three VRP commands and return a unified unit list.

    Runs: display version, display esn, display startup.

    Returns dict:
    {
        "units": [
            {
                "id":               int,   # slot number (0 for single-device MPU)
                "role":             str,   # "master" or "standby"
                "model":            str,
                "esn":              str,
                "vrp_version":      str,
                "software_version": str,
                "startup_image":    str,
                "next_startup_image": str,
                "startup_patch":    str | None,
                "next_startup_patch": str | None,
            },
            ...
        ]
    }
    """
    client.logger.info("Reading device info...")

    version_output = client.conn.send_command("display version")
    esn_output = client.conn.send_command("display esn")
    startup_output = client.conn.send_command("display startup")

    units = _parse_version(version_output)
    esn_map = _parse_esn(esn_output)
    startup_map = _parse_startup(startup_output)

    single_device = "device" in esn_map

    _empty_startup = {
        "startup_image": None,
        "next_startup_image": None,
        "startup_patch": None,
        "next_startup_patch": None,
    }

    for unit in units:
        unit["esn"] = esn_map.get("device" if single_device else unit["id"])
        unit.update(startup_map.get(unit["role"], _empty_startup))

    return {"units": units}


def read_info(client, *, return_result: bool = False):
    """
    Read device information as a full workflow operation (connect → collect → disconnect).

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
        info = get_info(client)
        result.metadata.update(info)
        result.message = "Device information read successfully"

        return result if return_result else info

    except Exception as exc:
        result.success = False
        result.errors.append(str(exc))
        raise

    finally:
        result.mark_finished()
        client.disconnect()
