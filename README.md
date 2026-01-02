# network_automation

`network_automation` is a platform-centric Python library for automating
network device operations such as **info**, **backup**, and **upgrade**.

The library is designed to work:
- with Nautobot Jobs,
- from CLI tools,
- in pytest-based test suites.

Currently supported platform:
- Mikrotik RouterOS

---

## Key Concepts

- Platform-centric design (not vendor-centric)
- Single factory for client creation
- Thin clients, explicit workflows
- Explicit connection lifecycle
- Optional structured results

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
client.upgrade()
```

To obtain structured results:

```python
result = client.upgrade(return_result=True)
```

---

## Nautobot Job Integration (Example)

```python
from nautobot.extras.jobs import Job
from network_automation.factory import get_client

class UpgradeRouterOS(Job):
    class Meta:
        name = "Upgrade Mikrotik RouterOS"

    def run(self, device, firmware_version):
        client = get_client(
            device_type=device.platform.network_driver,
            host=device.primary_ip.address.ip,
            username="admin",
            password="secret",
            firmware_version=firmware_version,
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
- injects Nautobot logger,
- does not manage connection lifecycle,
- does not perform platform mapping,
- consumes structured results.

---

## Logging

The library does not configure logging.

- Nautobot Jobs inject `self.logger`
- CLI tools configure logging via `logging.basicConfig`

---

## Tests

```bash
python -m pytest
```

---

## License

MIT License
