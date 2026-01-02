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

- **Platform-centric** design (not vendor-centric)
- **Single factory** for client creation
- **Thin clients**, rich helpers
- **Explicit connection lifecycle**
- **Optional structured results**

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

## Logging

The library does not configure logging.

- In Nautobot Jobs, pass `self.logger`
- In CLI tools, configure logging via `logging.basicConfig`

---

## Tests

Run tests with:

```bash
python -m pytest
```

---

## License

MIT License
