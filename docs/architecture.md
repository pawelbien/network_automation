# Architecture Overview

This document describes the internal architecture of the
`network_automation` library.

---

## Core Design Goals

- No hard dependency on Nautobot
- Predictable and explicit behavior
- Easy testing without real devices
- Long-term maintainability

---

## Platform-centric Model

The primary abstraction is **platform**, identified by `device_type`.

The value of `device_type` must match:
- Nautobot: `device.platform.network_driver`
- Netmiko: `device_type`

Example:
```
mikrotik_routeros
```

---

## Factory

All clients are created through a single factory:

```python
get_client(**params)
```

Responsibilities:
- validate `device_type`
- select platform implementation
- inject execution context
- hide platform-specific classes

Jobs, CLI tools, and tests never instantiate clients directly.

---

## ExecutionContext

`ExecutionContext` carries execution-scoped data:

- logger
- device metadata
- job metadata
- dry-run flag
- arbitrary metadata

It is injected from the outside and remains framework-agnostic.

---

## BaseClient

`BaseClient` provides shared infrastructure:

- connection lifecycle
- retry logic
- logging integration
- execution context handling

Platform clients inherit from `BaseClient` and only implement
platform-specific behavior.

---

## Unified Operation Pattern

Each operation is split into three layers.

### 1. Helper (internal)

- pure logic
- no connection handling
- no result objects
- raises exceptions

Examples:
- `get_info`
- `download_firmware`

---

### 2. Operation / Workflow

- manages connect / disconnect
- produces `OperationResult`
- records metadata and timing
- re-raises exceptions

Examples:
- `upgrade`
- `run_backup`
- `read_info`

---

### 3. Client API

- thin public facade
- selects helper or operation
- optional structured result

Examples:
```python
client.info()
client.info(return_result=True)
client.backup("daily", return_result=True)
client.upgrade(return_result=True)
```

---

## OperationResult

A single generic result object is used for all operations.

Semantics are expressed via fields, not inheritance.

Characteristics:
- framework-agnostic
- suitable for CLI, Jobs, and APIs
- does not replace exceptions

Exceptions control flow.
Results describe outcomes.

---

## Testing Strategy

- no real network connections
- connection lifecycle mocked
- helpers tested in isolation
- workflows tested with fake clients

---

## Extending the Library

To add a new operation:

1. create a helper
2. create an operation/workflow
3. expose it via the client API

To add a new platform:

1. create a platform module
2. implement a client inheriting from `BaseClient`
3. register it in the factory
