# network_automation

`network_automation` is a **platform-centric** Python library for automating
network device operations such as **info**, **backup**, **command execution**,
and **firmware upgrades**.

The library is designed to work consistently:

- with **Nautobot Jobs**
- from **CLI tools**
- in **pytest-based test suites**

Currently supported platforms:

- **MikroTik RouterOS** — info, backup, command execution, firmware upgrade, bootloader upgrade (where applicable)
- **Huawei VRP** — device information (`get_info`), remote command execution (`run`), file download (`download`), file upload (`upload`) via Netmiko/SFTP, and an upgrade (`upgrade`, single-unit devices) covering firmware, patch, or both; use `device_type="huawei"` (same string as Netmiko’s Huawei driver)

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

### Huawei VRP

- Device information (`get_info`) — unified member model, supports single devices and stacks
- Command execution (`run`)
- File download (`download`) — retrieve files from device via SFTP
- File upload (`upload`) — push local files to the device via SFTP
- Firmware upgrade (`upgrade`) — firmware, patch, or both, single-unit devices (see below)

---


## Device Information

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

---

## Basic Usage

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
```

CLI-style scripts live in `examples/huawei_vrp/`:

- `run_command.py` — SSH key auth, multiple commands, formatted output
- `read_info.py` — collect and print device information (version, ESN, startup image) per unit
- `upgrade.py` — firmware and/or patch upgrade for single-unit devices (target versions + local `.cc`/`.pat` files)

---

## Firmware Upgrade

Firmware upgrade is implemented for **MikroTik RouterOS** and, in a reduced
form, **Huawei VRP** (firmware and/or patch, single-unit devices — see below).

Firmware upgrade requires **explicit configuration** of the delivery method.

### Online upgrade (download)

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

### Bootloader Firmware Upgrade (RouterOS)

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

### Offline upgrade (upload)

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
- `examples/mikrotik_routeros/` — MikroTik RouterOS usage examples (`read_info.py`, `run_command.py`, `update.py`)
- `examples/huawei_vrp/` — Huawei VRP usage examples (device info, remote command execution, firmware upgrade)

---

## License

MIT License
