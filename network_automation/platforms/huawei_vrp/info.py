# network_automation/platforms/huawei_vrp/info.py

"""
Huawei VRP device information helpers.
"""

import re

from network_automation.results import OperationResult
from network_automation.platforms.huawei_vrp.cli_errors import _check_cli_output
from network_automation.platforms.huawei_vrp.debug_log import debug_log


def _parse_version(output):
    """
    Parse 'display version' output.

    Returns list of partial unit dicts with keys:
    id, role, model, vrp_version, software_version, software_family, uptime_raw.

    software_family (e.g. "AR650") is the platform-family token that
    prefixes the version inside the parens, e.g. "(AR650 V300R024C00SPC100)"
    — distinct from `model`, which is the exact chassis SKU reported in the
    uptime banner (e.g. "AR651"). Nautobot's SoftwareVersion.version for
    Huawei VRP is stored as "<software_family> <software_version>" (e.g.
    "AR650 V300R024C00SPC100", confirmed via nbshell 2026-07-14) — CMDB
    matching needs both tokens combined, not software_version alone.

    uptime_raw (Faza 11) is parsed from the same per-unit line that already
    supplies id/role, avoiding a second 'display version' call just for
    uptime; it is None when the line doesn't include the "uptime is ..."
    text (not all devices/firmware report it inline).
    """
    vrp_version = None
    software_version = None
    software_family = None
    model = None
    units = []

    for line in output.splitlines():
        line = line.strip()

        # VRP (R) software, Version 5.170 (AR650 V300R024C00SPC100)
        # Requires two tokens inside parens (platform family + version) to avoid
        # matching per-slot lines like "Software Version : VRP (..., Version 5.170 (V200R024C00SPC500))"
        m = re.search(r'Version\s+([\d.]+)\s+\((\S+)\s+(V\w+)\)', line)
        if m:
            vrp_version = m.group(1)
            software_family = m.group(2)
            software_version = m.group(3)
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

        # MPU 0(Master) : uptime is 2 weeks, 1 day, 12 hours, 21 minutes
        # ES6D2S30S003 1(Master)  : uptime is ...
        # ES6D2S30S003 2(Standby)  : uptime is ...
        m = re.search(r'\S+\s+(\d+)\s*\((Master|Standby)\)\s*:\s*uptime is\s*(.+)', line)
        if m:
            units.append({
                "id": int(m.group(1)),
                "role": m.group(2).lower(),
                "uptime_raw": m.group(3).strip(),
            })
            continue

        # Same line without inline uptime text (not all devices report it).
        m = re.search(r'\S+\s+(\d+)\s*\((Master|Standby)\)\s*:', line)
        if m:
            units.append({
                "id": int(m.group(1)),
                "role": m.group(2).lower(),
                "uptime_raw": None,
            })

    if not vrp_version:
        raise ValueError("VRP version not found in 'display version' output.")
    if not software_version:
        raise ValueError("Software version not found in 'display version' output.")
    if not software_family:
        raise ValueError("Software family not found in 'display version' output.")
    if not model:
        raise ValueError("Device model not found in 'display version' output.")
    if not units:
        raise ValueError("No units (Master/Standby slots) found in 'display version' output.")

    for unit in units:
        unit["model"] = model
        unit["vrp_version"] = vrp_version
        unit["software_version"] = software_version
        unit["software_family"] = software_family

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
        "master":  {startup_image, next_startup_image, backup_image, startup_patch, next_startup_patch},
        "standby": {...},   # only present for stacked devices
    }

    startup_patch / next_startup_patch / backup_image are None when the
    device reports "null" or "default", or when the line is absent (not
    every device/firmware reports "Backup system software for next
    startup").
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
                "backup_image": None,
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
        elif key == "Backup system software for next startup":
            result[current_role]["backup_image"] = optional
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


_MD5_HEX_RE = re.compile(r'(?<![0-9a-fA-F])([0-9a-fA-F]{32})(?![0-9a-fA-F])')


def _parse_file_md5(output: str) -> str:
    """
    Parse 'display system file-md5 flash:/<file>' output.

    The exact vendor wording around the hash varies, so this looks for a
    bare 32-character hex token rather than anchoring on surrounding text.

    Returns the MD5 hex digest, lowercased.
    """
    m = _MD5_HEX_RE.search(output)
    if not m:
        raise ValueError(
            "Could not parse MD5 value from 'display system file-md5' "
            f"output: {output!r}"
        )

    return m.group(1).lower()


# Matches a 'dir' file/directory listing line, e.g.:
#   0  drw-              -  Nov 30 2023 14:17:02   shelldir
#  31  -rw-    161,819,648  Mar 16 2025 13:38:03   AR650A_V300R023C00SPC100.cc
# Attr's first char is 'd' (directory) or '-' (file); Size(Byte) is either
# a comma-grouped number or '-' for directories.
_DIR_LINE_RE = re.compile(
    r'^\s*\d+\s+(?P<attr>[d-][rwo-]{3})\s+(?P<size>[\d,]+|-)\s+'
    r'\w+\s+\d+\s+\d+\s+[\d:]+\s+(?P<name>\S+)\s*$'
)

# 631,960 KB total available (237,728 KB free)
_DIR_FREE_SPACE_RE = re.compile(r'([\d,]+)\s*KB\s+free', re.IGNORECASE)


def _parse_dir(output: str) -> dict:
    """
    Parse 'dir' (flash root listing) output.

    Returns dict:
    {
        "files": [{"name": str, "size": int, "is_dir": bool}, ...],
        "free_bytes": int,
    }

    File sizes and free space are both normalized to bytes (the device
    reports free space in KB, individual file sizes in bytes) so callers
    can compare them directly. Directory entries have size 0.

    Raises ValueError if the free-space summary line isn't found.
    """
    files = []
    for line in output.splitlines():
        m = _DIR_LINE_RE.match(line)
        if not m:
            continue

        size_str = m.group("size")
        size = 0 if size_str == "-" else int(size_str.replace(",", ""))

        files.append({
            "name": m.group("name"),
            "size": size,
            "is_dir": m.group("attr").startswith("d"),
        })

    m = _DIR_FREE_SPACE_RE.search(output)
    if not m:
        raise ValueError(
            f"Could not parse free space from 'dir' output: {output!r}"
        )

    free_kb = int(m.group(1).replace(",", ""))

    return {"files": files, "free_bytes": free_kb * 1024}


def get_flash_info(client) -> dict:
    """
    Read the flash root directory listing and free space.

    Runs: dir.

    - no connect/disconnect
    - not part of get_info()/read_info() — only called from upgrade.py's
      flash-space/cleanup step, so it never affects the get_info() command
      sequence.
    """
    command = "dir"
    debug_log(client, "send_command: %s", command)
    output = client.conn.send_command(command)
    debug_log(client, "send_command response: %s", output)
    _check_cli_output(command, output)
    return _parse_dir(output)


def get_file_md5(client, filename: str) -> str:
    """
    Read the device-computed MD5 of a file already present on flash.

    Runs: display system file-md5 flash:/<filename>.

    Device-side hashing time scales with file size (observed: ~13s for a
    162MB firmware image against Netmiko's ~10s default read_timeout,
    tripping a false ReadTimeout mid-computation and leaving unread output
    in the buffer for the next command) — read_timeout=300 matches the
    other known-slow VRP command in flash.py's ensure_flash_space().

    - no connect/disconnect
    - only called from upgrade.py's MD5 verification step, so it never
      affects the get_info() command sequence.
    """
    command = f"display system file-md5 flash:/{filename}"
    debug_log(client, "send_command: %s", command)
    output = client.conn.send_command(command, read_timeout=300)
    debug_log(client, "send_command response: %s", output)
    _check_cli_output(command, output)
    return _parse_file_md5(output)


def get_patch_info(client):
    """
    Read the currently active patch version and state.

    Runs: display patch-information.

    - no connect/disconnect
    - not part of get_info()/read_info() — only called from upgrade.py when
      a patch operation is requested, so it never affects the get_info()
      command sequence.
    """
    command = "display patch-information"
    debug_log(client, "send_command: %s", command)
    output = client.conn.send_command(command)
    debug_log(client, "send_command response: %s", output)
    _check_cli_output(command, output)
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
                "backup_image":     str | None,
                "startup_patch":    str | None,
                "next_startup_patch": str | None,
            },
            ...
        ]
    }
    """
    client.logger.info("Reading device info...")

    debug_log(client, "send_command: %s", "display version")
    version_output = client.conn.send_command("display version")
    debug_log(client, "send_command response: %s", version_output)
    _check_cli_output("display version", version_output)

    debug_log(client, "send_command: %s", "display esn")
    esn_output = client.conn.send_command("display esn")
    debug_log(client, "send_command response: %s", esn_output)
    _check_cli_output("display esn", esn_output)

    debug_log(client, "send_command: %s", "display startup")
    startup_output = client.conn.send_command("display startup")
    debug_log(client, "send_command response: %s", startup_output)
    _check_cli_output("display startup", startup_output)

    units = _parse_version(version_output)
    esn_map = _parse_esn(esn_output)
    startup_map = _parse_startup(startup_output)

    single_device = "device" in esn_map

    _empty_startup = {
        "startup_image": None,
        "next_startup_image": None,
        "backup_image": None,
        "startup_patch": None,
        "next_startup_patch": None,
    }

    for unit in units:
        unit["esn"] = esn_map.get("device" if single_device else unit["id"])
        unit.update(startup_map.get(unit["role"], _empty_startup))

    return {"units": units}


def extract_discovery_facts(units):
    """
    Reduce get_info()'s unit list to the single-unit CMDB facts Device
    Discovery needs: serial number and base firmware version.

    Picks the 'master' unit (falls back to the first unit if no unit is
    marked master) — v1 has no multi-chassis support, so any standby/slave
    units in a stack are ignored.

    software_version is built as "<software_family> <software_version>"
    (e.g. "AR650 V300R024C00SPC100") to match how Nautobot stores
    SoftwareVersion.version for Huawei VRP (confirmed via nbshell
    2026-07-14: entries look like "AR650 V300R023C00SPC100", not a bare
    VRP version string) — software_family is the platform-family token
    ("AR650"), distinct from the exact chassis model ("AR651") reported
    elsewhere. Patch-free by construction: get_info() never runs 'display
    patch-information', and the catalog only holds base firmware versions
    (patches are a separate SoftwareImageFile layer, not their own
    SoftwareVersion row).

    Returns dict: {"serial": str, "software_version": str}.
    """
    unit = next((u for u in units if u.get("role") == "master"), units[0])
    return {
        "serial": unit["esn"],
        "software_version": f"{unit['software_family']} {unit['software_version']}",
    }


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
        debug_log(client, "read_info() result.metadata: %s", result.metadata)
        client.disconnect()
