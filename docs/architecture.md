# Architecture Overview

This document describes the internal architecture of the
`network_automation` library and its intended usage patterns.

The architecture is intentionally explicit and conservative.
Hidden behavior is avoided in favor of predictable control flow,
clear ownership boundaries, and testability.

---

## Core Design Goals

- No hard dependency on Nautobot
- Platform-centric, not vendor-agnostic by accident
- Predictable and explicit behavior
- Exceptions control flow, results describe outcomes
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

There is a **1:1 mapping** between:

```
platform ↔ client ↔ Netmiko device_type
```

This eliminates conditional logic in jobs and avoids cross-platform branching.

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
- normalize caller inputs

Jobs, CLI tools, and tests **never instantiate clients directly**.

The factory is the **only decision point** for platform selection.

---

## ExecutionContext

`ExecutionContext` carries execution-scoped data and dependencies.

Typical fields:

- logger
- device name / identifier
- job identifier
- dry-run flag
- arbitrary metadata

Characteristics:

- framework-agnostic
- immutable by convention
- injected from the outside
- never created implicitly by helpers

It allows the same codebase to run in:

- Nautobot Jobs
- CLI tools
- tests

without modification.

---

## BaseClient

`BaseClient` provides shared infrastructure:

- connection lifecycle (`connect` / `disconnect`)
- retry logic
- logging integration
- execution context handling

Platform clients inherit from `BaseClient` and implement only:

- platform-specific connection parameters
- platform-specific workflows

`BaseClient` does **not**:

- know job semantics
- know Nautobot
- know platform logic

---

## Unified Operation Pattern

All non-trivial behavior follows a strict three-layer pattern.

This pattern is the core architectural invariant of the library.

---

### 1. Helper (internal)

Responsibilities:

- pure logic
- platform-specific details
- no connection handling
- no result objects
- raises exceptions on failure

Helpers assume:

- an active connection exists
- lifecycle is handled elsewhere

Examples:

- `get_info`
- `download_firmware`
- `upload_firmware`
- `cleanup_old_backups`
- `run_commands`

Helpers are easy to unit test in isolation.

---

### 2. Operation / Workflow

Responsibilities:

- manage connection lifecycle
- orchestrate helpers
- create and populate `OperationResult`
- record timing and metadata
- re-raise exceptions

Characteristics:

- explicit start / finish
- no hidden retries
- no swallowed errors

Examples:

- `upgrade`
- `run_backup`
- `read_info`
- `run`

Workflows describe *what happened*, not *how errors propagate*.

---

### 3. Client API

Responsibilities:

- thin public facade
- delegates to workflows
- exposes a stable API

Characteristics:

- no business logic
- no platform branching
- optional structured results

Examples:

```python
client.run("/system resource print")
client.run(cmds, return_result=True)

client.backup("daily", return_result=True)
client.upgrade(return_result=True)
```

Clients may be stateful (e.g. cached device info),
but do not own lifecycle decisions.

---

## Firmware Delivery Model

Firmware upgrades require an explicit **delivery strategy**.

The delivery mechanism is selected via the client attribute:

```
firmware_delivery
```

Supported values:

- `download` — device fetches firmware from a remote repository
- `upload` — firmware is uploaded to the device via SSH/SFTP

Rules:

- `firmware_delivery` **must be explicitly set**
- there is **no default**
- `upload` requires `repo_path`
- `download` requires `repo_url`

This fail-fast model avoids hidden behavior and ensures
that upgrade semantics are always explicit.

---

## OperationResult

A single generic result object is used for all operations.

Semantics are expressed via **fields**, not inheritance.

Key properties:

- `success`
- `operation`
- `message`
- `warnings`
- `errors`
- `metadata`
- timestamps and duration

Important rules:

- exceptions control flow
- results describe outcomes
- results do not suppress failures

This allows:

- rich job reporting
- CLI-friendly output
- future API serialization

without complicating control flow.

---

## Logical vs Platform Artifacts

Some operations create artifacts that exist both:

- on the device (platform-specific)
- locally (job-level / user-facing)

Example: backups

Rules:

- platform-specific identifiers (e.g. `nauto_` prefix) **never leak**
- local artifacts use logical, human-readable names
- `OperationResult` exposes only logical artifacts

This separation protects jobs and tooling from platform internals.

---

## Nautobot Integration Pattern

When used from Nautobot Jobs:

- the Job provides the logger
- device platform maps directly to `device_type`
- Jobs remain thin and declarative
- Jobs orchestrate workflows, not logic

Typical flow:

1. Job collects parameters
2. Job creates client via factory
3. Job executes workflow(s)
4. Job logs using `OperationResult`
5. Job manages job-level artifacts

The library never depends on Nautobot internals.

---

## CLI Integration Pattern

When used from CLI tools:

- standard Python logging is used
- no execution context is required
- workflows behave identically to Jobs

CLI and Job behavior is intentionally symmetric.

---

## Testing Strategy

Testing is a first-class design concern.

Principles:

- no real network connections
- lifecycle methods mocked
- helpers tested in isolation
- workflows tested with fake clients
- platform details validated explicitly

Tests describe contracts, not implementations.

---

## Extending the Library

### Adding a new operation

1. Create a helper
2. Create a workflow using the helper
3. Expose it via the client API
4. Add focused unit tests

### Adding a new platform

1. Create a platform module
2. Implement a client inheriting from `BaseClient`
3. Implement platform helpers and workflows
4. Register the platform in the factory

No changes to jobs or existing platforms are required.

---

## Architectural Invariants

The following rules must not be violated:

- clients are created only via the factory
- helpers never manage lifecycle
- workflows always manage lifecycle
- jobs never call helpers directly
- platform details never leak into jobs
- delivery strategies must be explicit
- exceptions control flow

These invariants are intentionally strict.
