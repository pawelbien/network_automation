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

Examples (`device_type` matches Netmiko’s `device_type` string):

```
mikrotik_routeros
huawei
```

There is a **1:1 mapping** between:

```
platform ↔ client ↔ Netmiko device_type
```

This eliminates conditional logic in jobs and avoids cross-platform branching.

**Exception:** `opnsense`. Netmiko has no native OPNsense driver, so the
registry key (`opnsense`) and the internal Netmiko `device_type`
(`"generic_termserver_ssh"`, chosen because it doesn't assert a prompt
pattern during session setup) differ. This is a documentation-only
deviation from the 1:1 mapping above — the factory/registry mechanism
itself is unchanged, callers still only ever see `device_type="opnsense"`.

OPNsense also has an SSH-specific quirk handled entirely inside its
platform package (`platforms/opnsense/client.py`), analogous to Huawei
VRP's `disabled_algorithms` handling: its console shows a numbered menu
(`0) Logout` … `8) Shell`) instead of a shell prompt by default. The
`skip_menu` constructor parameter (default `True`) controls whether the
client selects "Shell" from that menu before running commands.

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

- `get_info` — mandatory, always available
- `download_firmware`
- `upload_firmware`
- `cleanup_old_backups`
- `run_commands`

Helpers are easy to unit test in isolation.

**Information Collection Model:**

The model is platform-specific. Platforms choose the model that fits their
data structure and correlation requirements.

**MikroTik RouterOS — unified unit model (with split internal helpers)**

The public `read_info` workflow calls `get_info`, which assembles all collected
data into a unified `{"units": [...]}` structure — the same shape as Huawei.
MikroTik is always a single-unit device, so `units` always contains exactly one entry.

Hardware fields (`serial`, `model`, `bootloader_current_firmware`,
`bootloader_upgrade_firmware`) are `None` when RouterBOARD is unavailable (e.g., CHR).

```python
info = read_info(client)
# {"units": [{"id": 0, "role": "master", "arch": "...", "version": "...", ...}]}
```

Internally, `get_info` delegates to three private helpers:

- **`_get_software_info`** — mandatory; architecture and RouterOS version
- **`_get_system_identity`** — mandatory; system hostname
- **`_get_hardware_info`** — optional; serial, model, bootloader firmware; raises `RuntimeError` on CHR

**Huawei VRP — unified member model**

Information is collected via a single `get_info` helper that runs three commands
(`display version`, `display esn`, `display startup`) and correlates the results
by slot ID and role. The output is a `units` list — one entry per physical device
(standalone router or stack slot).

This model is used because:
- Slot IDs must be correlated across all three commands
- Stacked devices are a first-class concept (master + standby slots)
- Splitting into independent helpers would require callers to perform the correlation

```python
info = client.get_info()
# {"units": [{"id": 1, "role": "master", "model": "...", "esn": "...", ...}]}
```

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

- `upgrade` (RouterOS, Huawei VRP)
- `bootloader_upgrade` (RouterBOARD firmware)
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

Huawei VRP:

```python
client.get_info()                                    # unified member model
client.run(["display version"], return_result=True)  # command execution
client.download(files=["flash:/config.zip"], local_dir="/tmp/backups")  # SFTP download
client.upload(files=["/tmp/fw.cc"], remote_dir="flash:/")               # SFTP upload
client.backup("daily", download_dir="/tmp/backups")                     # named config snapshot + SFTP download
```

`client.upgrade()` uploads firmware/patch files through the same SFTP path as
`client.upload()`, but additionally verifies each uploaded file's MD5
(`display system file-md5 flash:/<file>` vs. a local `hashlib.md5` pass)
before proceeding to configuration — see `huawei_vrp/upgrade.py`'s
`verify_md5`. This MD5 check is specific to the `upgrade()` workflow;
`client.upload()` itself remains a plain SFTP transfer, unchanged.

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

## Progress Reporting for Long-Running Backend Operations

Some firmware operations run as a **detached backend job** polled over an
existing session rather than a command whose output streams back inline
(OPNsense's `configctl firmware update`/`upgrade` is the reference case -
see `platforms/opnsense/upgrade.py`'s module docstring). Forwarding every
polled line straight to the operation's logger doesn't scale: a real
transcript runs to 1000+ lines (dependency resolution, per-package
download/install progress, migration scripts), which is fine for a local
CLI's stdout but unusable as a Nautobot Job log.

The pattern splits into four decoupled components:

- **SSH output reader** — the poll loop itself (e.g. `_run_and_wait()`),
  responsible only for talking to the transport (polling, reconnecting,
  diffing accumulated output into new lines) and handing each complete
  line to the next two components. Knows nothing about what the lines mean.
- **Progress parser / state machine** — a pure, I/O-free component (e.g.
  `platforms/opnsense/progress.py`'s `ProgressParser`) that takes one line
  of text and returns at most one stage-transition message. Detects phases
  from stable, structural anchors (regex on command-output shape, e.g.
  `^\[\d+/\d+\]`) rather than exact package names/counts, so it keeps
  working across future firmware releases without changes. Monotonic by
  design: stages only move forward, so out-of-order or repeated anchor
  matches can't make an already-announced stage disappear or repeat. A
  `reset()` starts a fresh epoch - used when the underlying device
  restarts mid-operation, so a legitimately new run (e.g. repositories
  being re-resolved after a reboot) isn't mistaken for a regression.
- **User-facing progress logger** — the operation's normal logger (e.g.
  Nautobot's Job logger). Only ever sees stage-transition messages plus an
  occasional keepalive (e.g. "Still working...", emitted when nothing new
  has happened for ~60s) - never raw output. This is what keeps Job logs
  small regardless of how verbose the underlying transcript is.
- **Detailed debug logger** — a separate, opt-in, per-device diagnostic
  file (e.g. `platforms/opnsense/detail_log.py`'s `DetailLog`) that
  captures every raw line, reconnect attempt, and exception (with full
  traceback), overwritten at the start of each new operation for that
  device. Never forwarded to the user-facing logger; exists purely for
  local troubleshooting. Best-effort by construction - a failure to open
  or write the file degrades to a silent no-op rather than aborting an
  operation that is otherwise succeeding.

A signal that isn't observable as a line of text (e.g. a dropped SSH
session with no textual marker at all) cannot be represented by the
parser's line-in/message-out contract, and shouldn't be forced into it -
report it directly from the poll loop instead, once the actual outcome is
known. OPNsense's reboot detection is the concrete example: a mid-poll
reconnect only *might* indicate a reboot (the same disruption can come
from something as mundane as sshd restarting while its own package is
replaced), so the parser's epoch is reset eagerly on any reconnect
(cheap and safe even if it turns out to be a false alarm), but the
user-facing "Reboot detected." message is only logged once the poll loop
concludes - from whichever confirms it actually happened.

A future platform with a similarly detached/polled backend operation
should reuse this shape rather than inventing a new one.

---

## Bootloader (RouterBOARD) Upgrade Model

Some platforms (e.g. MikroTik RouterOS) support a separate
**bootloader (RouterBOARD firmware)** upgrade.

Characteristics:

- Bootloader upgrade is a **separate operation** from OS upgrade
- It uses platform-specific commands
- It requires an **additional reboot**
- It is **never implicit**
- It may not be supported on all platforms (e.g. CHR)

For MikroTik RouterOS:

- RouterOS upgrade **must complete and reboot first**
- Bootloader upgrade can be performed **only after the OS reboot**
- A second reboot is always required to apply bootloader changes

Bootloader upgrade is exposed as an explicit workflow:

```python
client.bootloader_upgrade(return_result=True)
```

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

### Test File Layout

Each test file maps **1:1 to a platform module**:

```
tests/
├── test_results.py              # OperationResult
├── test_execution_context.py    # ExecutionContext + logger injection
├── test_logging_injected.py     # injected logger via get_client()
├── test_logging_cli.py          # default Python logger
├── mikrotik_routeros/
│   ├── conftest.py              # mikrotik_client fixture
│   ├── test_backup.py           # ← backup.py
│   ├── test_bootloader.py       # ← bootloader.py
│   ├── test_download.py         # ← download.py
│   ├── test_info.py             # ← info.py
│   ├── test_run.py              # ← run.py
│   ├── test_upgrade.py          # ← upgrade.py
│   └── test_upload.py           # ← upload.py
├── huawei_vrp/
│   ├── conftest.py              # huawei_client fixture
│   ├── test_backup.py           # ← backup.py
│   ├── test_download.py         # ← download.py
│   ├── test_info.py             # ← info.py
│   ├── test_run.py              # ← run.py
│   ├── test_upload.py           # ← upload.py
│   ├── test_version.py          # ← version.py
│   └── test_upgrade.py          # ← upgrade.py
└── opnsense/
    ├── conftest.py              # opnsense_client fixture
    ├── test_backup.py           # ← backup.py
    ├── test_client.py           # ← client.py
    ├── test_debug_log.py        # ← debug_log.py
    ├── test_detail_log.py       # ← detail_log.py
    ├── test_firmware.py         # ← firmware.py
    ├── test_info.py             # ← info.py
    ├── test_progress.py         # ← progress.py
    ├── test_reboot.py           # ← reboot.py
    └── test_upgrade.py          # ← upgrade.py
```

When adding a new module `foo.py`, the corresponding test file is `test_foo.py`.

---

### Testing Patterns

**Lifecycle mocking** — every workflow test patches `connect` and `disconnect`:

```python
monkeypatch.setattr(client, "connect", lambda: None)
monkeypatch.setattr(client, "disconnect", lambda: None)
```

**SFTP testing** — upload and download tests use a minimal fake SFTP stack
instead of real SSH connections:

```python
class FakeSFTP:
    def __init__(self): self.transfers = []
    def get(self, remote, local): self.transfers.append((remote, local))
    def put(self, local, remote): self.transfers.append((local, remote))
    def close(self): pass

class FakeRemoteConnPre:
    def open_sftp(self): return FakeSFTP()

class FakeConn:
    remote_conn_pre = FakeRemoteConnPre()
```

**Helper isolation** — helpers (`_get_software_info`, `_parse_version`, …) are
tested directly with a client whose `conn` attribute is a `MagicMock`,
without going through `connect` / `disconnect`.

**OperationResult tests** — each workflow module's test file includes a test
for the `return_result=True` path alongside the unit tests for internal logic.

---

## Extending the Library

### Adding a new operation

1. Create a helper
2. Create a workflow using the helper
3. Expose it via the client API
4. Add focused unit tests
5. Document any lifecycle or reboot implications

### Adding a new information category

To add a new information category (e.g., license info):

1. Create a helper function (e.g., `get_license_info`)
2. Follow the capability model:
   - If mandatory: always raise exceptions on failure
   - If optional: raise `RuntimeError` with descriptive message when not supported
3. Return a dict with consistent field names
4. Add unit tests covering:
   - Successful parsing
   - Missing required fields (ValueError)
   - Unsupported platform (RuntimeError)
5. Update workflows that need this information to handle exceptions appropriately

Example:

```python
def get_license_info(client):
    """Read license information (optional capability)."""
    output = client.conn.send_command("/system license print")
    
    if "bad command name" in output.lower():
        raise RuntimeError("License info not supported on this platform")
    
    # Parse and validate...
    return {"level": level, "expiration": expiration}
```

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
- reboot-causing operations must be explicit
- exceptions control flow
- operations may explicitly skip unsupported platforms (reported via OperationResult)
- **information model is platform-specific** — both MikroTik and Huawei expose a unified unit model via `read_info` / `get_info`; MikroTik uses private split helpers (`_get_software_info`, `_get_system_identity`, `_get_hardware_info`) internally
- **workflows decide what to collect** — workflows choose which helpers to call and how to handle missing capabilities

These invariants are intentionally strict.
