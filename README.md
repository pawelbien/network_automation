# network_automation

`network_automation` is a **platform-centric** Python library for automating
network device operations such as **info**, **backup**, **command execution**,
and **firmware upgrades**.

The library is designed to work consistently:

- with **Nautobot Jobs**
- from **CLI tools**
- in **pytest-based test suites**

Currently supported platforms:

- **Cisco IOS/IOS-XE** — device information (`get_info`), configuration backup (`backup`, `show running-config` captured over the existing SSH session, no SFTP), `reboot`/`wait_for_reconnect`; firmware upgrade (`upgrade`) is not implemented yet (raises `NotImplementedError`); use `device_type="cisco_ios"` (same string as Netmiko's Cisco IOS driver)
- **Cisco IOS-XR** — device information (`get_info`, `show version` + `show inventory`), configuration backup (`backup`, `show running-config` captured over the existing SSH session, no SFTP), `reboot`/`wait_for_reconnect`; firmware upgrade (`upgrade`) is not implemented yet (raises `NotImplementedError`); use `device_type="cisco_xr"` (same string as Netmiko's Cisco IOS-XR driver)
- **Huawei VRP** — device information (`get_info`), remote command execution (`run`), file download (`download`), file upload (`upload`) via Netmiko/SFTP, named configuration backup and download (`backup`), and an upgrade (`upgrade`, single-unit devices) covering firmware, patch, or both; use `device_type="huawei"` (same string as Netmiko’s Huawei driver)
- **MikroTik RouterOS** — device information (`get_info`), command execution (`run`), backup creation and download (`backup`), firmware upgrade (`upgrade`, online download or offline SSH/SFTP upload), and bootloader firmware upgrade (`bootloader_upgrade`, RouterOS only, not supported on CHR); use `device_type="mikrotik_routeros"` (same string as Netmiko's MikroTik RouterOS driver)
- **OPNsense** — device information (`get_info`), update/upgrade checking (`check_updates`, `update`, `upgrade`) via the native `configctl firmware` backend, `reboot`/`wait_for_reconnect`, and configuration backup (`backup`, SFTP GET of `/conf/config.xml`) — over SSH/CLI (Netmiko, no native driver — see below); use `device_type="opnsense"`

---

## Design Principles

- Platform-centric design (not vendor-agnostic by accident)
- Single factory for client creation
- Thin clients, explicit workflows
- Explicit connection lifecycle
- Fail-fast configuration
- Exceptions control flow, results describe outcomes

---

## Supported Operations

Not every operation is available on every platform.

### Cisco IOS/IOS-XE

- Device information (`get_info`) — hostname, version, model, serial via `show version`
- Reboot (`reboot`) and reconnect waiting (`wait_for_reconnect`)
- Configuration backup (`backup`) — `show running-config` captured over the existing SSH session and written to a local file; no SFTP, no on-device artifact
- Firmware upgrade (`upgrade`) — not implemented yet, raises `NotImplementedError`

### Cisco IOS-XR

- Device information (`get_info`) — hostname, version, model via `show version`; serial via `show inventory`
- Configuration backup (`backup`) — `show running-config` captured over the existing SSH session and written to a local file; no SFTP, no on-device artifact
- Reboot (`reboot`) and reconnect waiting (`wait_for_reconnect`)
- Firmware upgrade (`upgrade`) — not implemented yet, raises `NotImplementedError`

### Huawei VRP

- Device information (`get_info`) — unified member model, supports single devices and stacks
- Command execution (`run`)
- File download (`download`) — retrieve files from device via SFTP
- File upload (`upload`) — push local files to the device via SFTP
- Configuration backup and download (`backup`) — named on-device config snapshot (`save <filename>`) + SFTP download, with cleanup of old `nauto_`-prefixed snapshots
- Firmware upgrade (`upgrade`) — firmware, patch, or both, single-unit devices (see below)

### MikroTik RouterOS

- Device information (`get_info`) — unified unit model, hardware fields `None` on CHR
- Backup creation and download (`backup`)
- Command execution (`run`)
- Firmware upgrade (`upgrade`)
  - online (device downloads firmware)
  - offline (firmware uploaded via SSH/SFTP)
- Bootloader firmware upgrade (`bootloader_upgrade`, RouterOS only)
  - optional
  - platform-dependent (not supported on CHR)
  - requires reboot to take effect

### OPNsense

- Device information (`get_info`) — hostname, OPNsense version, FreeBSD version, uptime
- Update checking (`check_updates`) — read-only, never modifies the device
- Update within the current release branch (`update`) and migration to a new branch (`upgrade`) — both drive the native `configctl firmware` backend; neither calls the other automatically
- Reboot (`reboot`) and reconnect waiting (`wait_for_reconnect`)
- Configuration backup (`backup`) — SFTP GET of the live `/conf/config.xml`; no on-device snapshot step (see below)

---


## Device Information

### Cisco IOS/IOS-XE

`get_info` runs a single `show version` and returns a unified **unit
structure**. Cisco IOS is always a single-unit device on this platform (no
stack support yet).

```python
info = client.get_info()
unit = info["units"][0]

print(f"{unit['name']}: {unit['version']} ({unit['model']}, {unit['serial']})")
```

Each unit dict contains:

| Field | Description |
|---|---|
| `id` | Always `0` (single-unit device) |
| `role` | Always `"master"` |
| `version` | IOS/IOS-XE version string |
| `name` | Hostname |
| `serial` | Processor board ID |
| `model` | Device model |

All fields are mandatory — a missing field raises `ValueError`.

### Cisco IOS-XR

`get_info` runs `show version` and `show inventory` and returns a unified
**unit structure**. Cisco IOS-XR is always a single-unit device on this
platform (no stack support yet). Unlike Cisco IOS/IOS-XE, the serial number
is not present in `show version` output, hence the extra command.

```python
info = client.get_info()
unit = info["units"][0]

print(f"{unit['name']}: {unit['version']} ({unit['model']}, {unit['serial']})")
```

Each unit dict contains:

| Field | Description |
|---|---|
| `id` | Always `0` (single-unit device) |
| `role` | Always `"master"` |
| `version` | IOS-XR version string |
| `name` | Hostname |
| `serial` | Chassis serial number (`show inventory`) |
| `model` | Device model |

All fields are mandatory — a missing field raises `ValueError`.

### Huawei VRP

`get_info` collects data from `display version`, `display esn`, and `display startup`,
and correlates them into a unified **unit list**. Each unit represents one physical
device — either a standalone router or a slot in a stack.

```python
result = client.get_info()

for unit in result["units"]:
    print(f"[{unit['id']}] {unit['role']}: {unit['model']} "
          f"ESN={unit['esn']} SW={unit['software_version']}")
```

Each member dict contains:

| Field | Description |
|---|---|
| `id` | Slot number (`0` for standalone MPU, `1`/`2`/… for stack members) |
| `role` | `"master"` or `"standby"` |
| `model` | Device model (e.g. `AR651`, `S6730-H24X6C`) |
| `esn` | Electronic Serial Number |
| `vrp_version` | VRP software version (e.g. `5.170`) |
| `software_version` | Full version string (e.g. `V300R024C00SPC100`) |
| `startup_image` | Currently active startup image path |
| `next_startup_image` | Image loaded on next boot |
| `startup_patch` | Active patch package path, or `None` |
| `next_startup_patch` | Patch loaded on next boot, or `None` |

Example output for a 2-member stack:

```python
{
    "units": [
        {
            "id": 1,
            "role": "master",
            "model": "S6730-H24X6C",
            "esn": "6R23C0039583",
            "vrp_version": "5.170",
            "software_version": "V200R024C00SPC500",
            "startup_image": "flash:/s6730_v200r024c00spc500.cc",
            "next_startup_image": "flash:/s6730_v200r024c00spc500.cc",
            "startup_patch": "flash:/s6730-h_v200r024sph121.pat",
            "next_startup_patch": "flash:/s6730-h_v200r024sph121.pat",
        },
        {
            "id": 2,
            "role": "standby",
            "model": "S6730-H24X6C",
            "esn": "6R23C0039593",
            ...
        },
    ]
}
```

### MikroTik RouterOS

`read_info` collects software, identity, and hardware information and returns
a unified **unit structure**. MikroTik is always a single-unit device, so the
list always contains exactly one entry.

Hardware fields are `None` on CHR (Cloud Hosted Router), which does not expose
RouterBOARD hardware.

```python
info = client.get_info()
unit = info["units"][0]

print(f"Arch: {unit['arch']}, Version: {unit['version']}, Name: {unit['name']}")
if unit["serial"]:
    print(f"Serial: {unit['serial']}, Model: {unit['model']}")
    print(f"Bootloader: {unit['bootloader_current_firmware']}")
```

Each unit dict contains:

| Field | Description |
|---|---|
| `id` | Always `0` (single-unit device) |
| `role` | Always `"master"` |
| `arch` | Architecture (e.g. `arm64`, `x86_64`) |
| `version` | RouterOS version string |
| `name` | System identity (hostname) |
| `serial` | RouterBOARD serial number, or `None` on CHR |
| `model` | Device model, or `None` on CHR |
| `bootloader_current_firmware` | Current RouterBOARD firmware, or `None` on CHR |
| `bootloader_upgrade_firmware` | Available RouterBOARD firmware upgrade, or `None` on CHR |

Example output (RouterBOARD device):

```python
{
    "units": [
        {
            "id": 0,
            "role": "master",
            "arch": "arm64",
            "version": "7.13.5 (stable)",
            "name": "core-router",
            "serial": "HG6099981S2",
            "model": "CCR2004-16G-2S+",
            "bootloader_current_firmware": "7.19.1",
            "bootloader_upgrade_firmware": "7.20.7",
        }
    ]
}
```

### OPNsense

`get_info` reads `hostname`, `opnsense-version`, `uname -r`, and `uptime`
over an SSH shell and returns a unified **unit structure**. OPNsense is
always a single-unit device.

```python
info = client.get_info()
unit = info["units"][0]

print(f"{unit['hostname']}: {unit['opnsense_version']} (FreeBSD {unit['freebsd_version']})")
```

Each unit dict contains:

| Field | Description |
|---|---|
| `id` | Always `0` (single-unit device) |
| `role` | Always `"master"` |
| `hostname` | Device hostname |
| `opnsense_version` | OPNsense version string |
| `freebsd_version` | Underlying FreeBSD version, or `None` if unavailable (best-effort) |
| `uptime` | Raw BSD `uptime` output, or `None` if unavailable (best-effort) |

OPNsense's SSH console normally shows a numbered menu (`0) Logout` … `8)
Shell`) instead of a shell prompt directly. The client assumes
(`skip_menu=True`, the default) that the SSH account already lands in a
shell; pass `skip_menu=False` for accounts that still see the console menu
— the client then selects `shell_menu_option` (default `"8"`) before
running any command. See `docs/architecture.md` for details.

---

## Basic Usage

### Cisco IOS/IOS-XE

```python
from network_automation.factory import get_client

client = get_client(
    device_type="cisco_ios",
    host="10.0.0.1",
    username="admin",
    password="secret",
)

info = client.get_info()
unit = info["units"][0]
print(f"{unit['name']}: {unit['version']} ({unit['model']}, {unit['serial']})")

# Configuration backup: captures 'show running-config' over the existing
# SSH session and writes it to daily.cfg — no SFTP, no on-device snapshot
client.backup("daily", download_dir="/tmp/backups")
```

`examples/cisco_ios/read_info.py` shows `get_info`, printed as a formatted
summary.

`client.upgrade()` is not implemented yet and raises `NotImplementedError`.

### Cisco IOS-XR

```python
from network_automation.factory import get_client

client = get_client(
    device_type="cisco_xr",
    host="10.0.0.1",
    username="admin",
    password="secret",
)

info = client.get_info()
unit = info["units"][0]
print(f"{unit['name']}: {unit['version']} ({unit['model']}, {unit['serial']})")

# Configuration backup: captures 'show running-config' over the existing
# SSH session and writes it to daily.cfg — no SFTP, no on-device snapshot
client.backup("daily", download_dir="/tmp/backups")
```

`examples/cisco_xr/read_info.py` shows `get_info`, printed as a formatted
summary.

`client.upgrade()` is not implemented yet and raises `NotImplementedError`.

### Huawei VRP

```python
from network_automation.factory import get_client

client = get_client(
    device_type="huawei",
    host="10.0.0.1",
    username="admin",
    password="secret",
)

# Device information
info = client.get_info()
for unit in info["units"]:
    print(f"[{unit['id']}] {unit['role']}: {unit['model']} ESN={unit['esn']}")

# Command execution
result = client.run(
    ["display version", "display ip interface brief"],
    return_result=True,
)
for entry in result.metadata["output"]:
    print(entry["command"], entry["output"])

# File download
client.download(
    files=["flash:/config.zip"],
    local_dir="/tmp/backups",
)

# File upload
client.upload(
    files=["/tmp/firmware.cc", "/tmp/patch.pat"],
    remote_dir="flash:/",
)

# Configuration backup: saves a named snapshot on-device (flash:/nauto_daily.zip)
# and downloads it locally as daily.zip; also removes old nauto_-prefixed
# snapshots before creating the new one.
client.backup("daily", download_dir="/tmp/backups")
```

CLI-style scripts live in `examples/huawei_vrp/`:

- `run_command.py` — SSH key auth, multiple commands, formatted output
- `read_info.py` — collect and print device information (version, ESN, startup image) per unit
- `upgrade.py` — firmware and/or patch upgrade for single-unit devices (target versions + local `.cc`/`.pat` files)

### MikroTik RouterOS

```python
from network_automation.factory import get_client

client = get_client(
    device_type="mikrotik_routeros",
    host="10.0.0.1",
    username="admin",
    password="secret",
)

info = client.get_info()
client.backup("daily")
```

### OPNsense

```python
from network_automation.factory import get_client

client = get_client(
    device_type="opnsense",
    host="10.0.0.1",
    username="admin",
    password="secret",
)

info = client.get_info()
unit = info["units"][0]
print(f"{unit['hostname']}: {unit['opnsense_version']}")

# Check for available updates (read-only)
client.check_updates()

# Update within the current release branch; reboots only if the backend
# decides a base/kernel update requires one
client.update()

# Migrate to a new release branch; does NOT call update() first
client.upgrade()

# Configuration backup: downloads the live /conf/config.xml via SFTP as
# daily.xml — no on-device snapshot is created (see docs/architecture.md)
client.backup("daily", download_dir="/tmp/backups")
```

`examples/opnsense/read_info.py` shows `get_info`, printed as a formatted
summary.

---

## Firmware Upgrade

Firmware upgrade is implemented for **Huawei VRP** (firmware and/or
patch, single-unit devices — see below), for **MikroTik RouterOS**, and
for **OPNsense** via its native `configctl firmware` backend (see
below). Not yet implemented for **Cisco IOS/IOS-XE** or **Cisco
IOS-XR** — `client.upgrade()` raises `NotImplementedError`.

### Huawei VRP

Huawei VRP upgrade is **single-unit only** (stacks are explicitly rejected,
not silently mis-handled) and covers firmware, patch (`.pat`), or both,
depending on the current vs. target versions. Unlike MikroTik, Huawei `.cc`/
`.pat` filenames are vendor-arbitrary, so the local files must be passed
explicitly via `firmware_file`/`patch_file` — there is no `firmware_delivery`
choice, upload is always via SFTP.

```python
client = get_client(
    device_type="huawei",
    host="10.0.0.1",
    username="admin",
    password="secret",
    firmware_version="V300R024C00SPC100",
    firmware_file="/opt/firmware/huawei/AR650A_V300R024C00SPC100.cc",
    patch_version="SPH1b0",                                       # optional
    patch_file="/opt/firmware/huawei/AR650A_V300R024SPH1b0.pat",   # optional
)

client.upgrade()
```

Additional constructor parameters (all optional, sensible defaults):
connection retry/reconnect timing (`connect_retries`, `connect_delay`,
`reconnect_timeout`, `reconnect_delay`), the per-device concurrency lock
(`lock_timeout`, `lock_dir`), forced downgrade (`force_downgrade`,
`i_understand_downgrade_risk`), firmware/patch upload retry and timeout
(`upload_timeout`, `upload_retries`), pre-upgrade health checks
(`health_check_mode`, `health_check_cpu_threshold`,
`health_check_memory_threshold`, `health_check_max_down_interfaces`), and
execution diagnostics via `get_client()` (`dry_run`, `debug_log`) — see
`examples/huawei_vrp/upgrade.py` for a fully annotated example showing
every parameter.

`firmware_version`/`firmware_file` are always required; `patch_version`/
`patch_file` are optional but must be provided together. A patch-only
maintenance run passes `firmware_version` equal to the device's current
version (i.e. "stay on this firmware, only add this patch").

Behavior — `determine_operation_type()` compares current vs. target firmware
and patch versions and picks one of four operations:

- **NONE** — nothing newer: skip (`result.metadata["skipped"] = True`)
- **FIRMWARE_ONLY** — uploads `firmware_file`, verifies its MD5, configures
  it as the next startup image (`display startup` verification), reboots,
  waits for reconnect (bounded by `reconnect_timeout`/`reconnect_delay`),
  verifies the post-reboot firmware version
- **PATCH_ONLY** — uploads `patch_file`, verifies its MD5, hot-applies it
  (`patch load flash:/<file>.pat all run`, no reboot), verifies it's active
  via `display patch-information`, then saves the configuration (`save`)
- **FIRMWARE_AND_PATCH** — uploads both files, verifies both MD5s, configures
  next startup firmware **and** patch, reboots, waits for reconnect, verifies
  both the firmware version and the active patch, then saves the
  configuration

MD5 verification is mandatory for every uploaded file: the local MD5 is
computed before upload (`hashlib.md5`, see `compute_local_md5` in
`upload.py`) and compared against the device-reported MD5 from
`display system file-md5 flash:/<file>` (parsed in `info.py`'s
`get_file_md5`). A mismatch aborts the operation with a `RuntimeError`
before any configuration/apply step runs. Results are recorded in
`result.metadata["md5_results"]` (per-file `expected_md5`/`actual_md5`/
`match`) and `result.metadata["md5_verified"]`. This check only applies to
`upgrade()`'s own uploads — the generic `client.upload()` is unaffected.

Not yet implemented (see `docs/architecture.md` for details): automatic
rollback after a failed post-reboot validation, and multi-unit/stack
upgrades.

### MikroTik RouterOS

Firmware upgrade requires **explicit configuration** of the delivery method.

#### Online upgrade (download)

```python
client = get_client(
    device_type="mikrotik_routeros",
    host="10.0.0.1",
    username="admin",
    password="secret",
    firmware_version="7.18.2",
    firmware_delivery="download",
    repo_url="https://download.mikrotik.com/routeros",
)

client.upgrade()
```

#### Bootloader Firmware Upgrade (RouterOS)

MikroTik RouterOS devices support a separate **bootloader
(RouterBOARD firmware)** upgrade.

Characteristics:

- Bootloader upgrade is a **separate operation** from RouterOS upgrade
- It is **never implicit**
- It always requires an **additional reboot**
- It must be explicitly enabled by the caller
- It is **not supported on all platforms** (e.g. CHR)

Example:

```python
client.bootloader_upgrade(return_result=True)
```

#### Offline upgrade (upload)

```python
client = get_client(
    device_type="mikrotik_routeros",
    host="10.0.0.1",
    username="admin",
    password="secret",
    firmware_version="7.18.2",
    firmware_delivery="upload",
    repo_path="/opt/firmware/routeros",
)

client.upgrade()
```

Rules:

- `firmware_delivery` **must be explicitly set**
- supported values: `download`, `upload`
- `download` requires `repo_url`
- `upload` requires `repo_path`

### OPNsense

OPNsense's native firmware backend (`configctl firmware ...`) runs
detached from the SSH/GUI session, synchronized via a lockfile — the
client polls it to completion rather than tracking a live command
stream. Three independent operations, none auto-chained:

```python
client.check_updates()   # configctl firmware check — read-only
client.update()          # configctl firmware update — current branch
client.upgrade()         # configctl firmware upgrade — new branch
```

`upgrade()` does not call `update()` first — if the device isn't up to
date on its current branch, the backend may reject the migration; the
caller decides the order. Both `update()` and `upgrade()` reboot only if
the backend decides one is required; a reboot mid-operation (including a
connection drop during it) is tolerated and reconnected automatically.

Additional constructor parameters (all optional): `firmware_poll_interval`
(15s), `firmware_poll_timeout` (3600s), `reboot_grace_period` (15s),
`reconnect_timeout` (600s), `reconnect_delay` (10s).

Configuration backup (`backup(name, download_dir=".")`) is a direct SFTP
GET of `/conf/config.xml` — OPNsense keeps this file live and current at
all times, so there is no separate on-device "save a snapshot" step (nor
`nauto_`-prefixed on-device artifacts to clean up, unlike MikroTik/Huawei).

---

## Structured Results

All workflows may optionally return an `OperationResult` object.

```python
result = client.upgrade(return_result=True)

if result.success:
    print(result.message)
else:
    print(result.errors)
```

`OperationResult` provides:

- operation name
- success flag
- message
- warnings and errors
- metadata
- timestamps and duration

---

## Nautobot Job Integration (Example)

```python
from nautobot.apps.jobs import Job
from network_automation.factory import get_client

class UpgradeRouterOS(Job):
    class Meta:
        name = "Upgrade MikroTik RouterOS"

    def run(self, device, firmware_version):
        client = get_client(
            device_type=device.platform.network_driver,
            host=device.primary_ip.address.ip,
            username="admin",
            password="secret",
            firmware_version=firmware_version,
            firmware_delivery="download",
            logger=self.logger,
        )

        result = client.upgrade(return_result=True)

        if result.success:
            self.logger.info(result.message)
        else:
            for error in result.errors:
                self.logger.error(error)
```

The Job:

- injects the Nautobot logger
- does not manage connection lifecycle
- does not perform platform mapping
- orchestrates workflows only
- consumes structured results

---

## Logging

The library does **not** configure logging.

- Nautobot Jobs inject `self.logger`
- CLI tools configure logging explicitly (e.g. `logging.basicConfig`)

---

## Tests

```bash
python -m pytest
```

Tests are designed to run without real network devices.

---

## Documentation

- `docs/architecture.md` — architectural invariants and patterns
- `examples/cisco_ios/` — Cisco IOS/IOS-XE usage examples (`read_info.py`)
- `examples/cisco_xr/` — Cisco IOS-XR usage examples (`read_info.py`)
- `examples/huawei_vrp/` — Huawei VRP usage examples (device info, remote command execution, firmware upgrade)
- `examples/mikrotik_routeros/` — MikroTik RouterOS usage examples (`read_info.py`, `run_command.py`, `update.py`)
- `examples/opnsense/` — OPNsense usage examples (`read_info.py`)

---

## License

MIT License
