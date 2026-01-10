# network_automation

`network_automation` is a **platform-centric** Python library for automating
network device operations such as **info**, **backup**, **command execution**,
and **firmware upgrades**.

The library is designed to work consistently:

- with **Nautobot Jobs**
- from **CLI tools**
- in **pytest-based test suites**

Currently supported platform:

- MikroTik RouterOS

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

- Device information (`info`)
- Backup creation and download (`backup`)
- Command execution (`run`)
- Firmware upgrade (`upgrade`)
  - online (device downloads firmware)
  - offline (firmware uploaded via SSH/SFTP)

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

client.info()
client.backup("daily")
```

---

## Firmware Upgrade

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
- `docs/examples/` — usage examples

---

## License

MIT License
