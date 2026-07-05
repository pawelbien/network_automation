# Huawei VRP: SFTP upload fails with immediate, empty SSH_FX_FAILURE

Status: both root causes below (missing warm-up request, and the
shared-transport hang) are fixed in `upload.py`
(`_connect_dedicated()` / `_dedicated_sftp()`), pending a real
end-to-end `upgrade()` run against a live device to confirm.

## Symptom

`HuaweiVRP.upload()` / `upgrade()` (via `upload.py`'s `upload_files()` and
`upload_with_retry()`) fails uploading the firmware `.cc` file to
`flash:/`, in well under 0.1s, with a raw SFTP status:

```
code=4 (SSH_FX_FAILURE)
text=''
```

The device closes the SFTP session immediately afterward. This happened
regardless of:

- remote filename length or content
- OPEN flags (`CREATE|TRUNC`, `CREATE|APPEND`, `CREATE|EXCL`, explicit
  `0644` permission attributes, etc.)
- using a dedicated fresh SSH connection instead of one shared with an
  interactive Netmiko shell session (sharing a transport with an
  interactive shell produces a *different* failure mode — see root
  cause #3 below — so always use a dedicated, plain-paramiko connection
  for SFTP, never one obtained via Netmiko)

The OpenSSH `sftp` command-line client, against the same host/user/key,
uploads the same file without issue.

## Root cause #1: no warm-up request before the first SFTP write

**This device's SFTP server rejects an `OPEN` for write if it is the
first request sent on a freshly opened SFTP channel** — regardless of
path, flags, attributes, free flash space, or paramiko version. Issuing
any read-only SFTP request first (e.g. `normalize(".")`) on the same
channel makes every subsequent write on that channel succeed.

- OpenSSH's `sftp` binary always issues a `REALPATH(".")` immediately
  after opening an SFTP session (to establish its remote working
  directory) before it does anything else — so it never hits this.
- `paramiko.SFTPClient` does **not** do this automatically (its internal
  `_cwd` stays `None` until something explicitly touches it — see
  `_adjust_cwd()` in `paramiko/sftp_client.py`). `upload_files()` and
  `upload_with_retry()` in `upload.py` call `sftp.put()` as the very
  first operation on a freshly opened channel (`client.conn.remote_conn_pre.open_sftp()`
  immediately followed by `sftp.put(...)`), which hits this exactly
  every time.

Confirmed live: with a plain paramiko connection, `sftp.open(path, "wb")`
as the first request → immediate empty `SSH_FX_FAILURE`. Same connection,
same path, but calling `sftp.normalize(".")` first → the write succeeds.
Reproduced repeatedly, before and after a full device reboot.

**Fix**: in `upload.py`, call `sftp.normalize(".")` (or any other
harmless read-only SFTP request) immediately after `open_sftp()`, before
the first `put()`/`open()` call, in both `upload_files()` and
`upload_with_retry()`.

## Root cause #2 (independent): paramiko >=5.0.0 cannot authenticate to this device at all

This device only supports the legacy `ssh-rsa` (SHA-1) public-key
signature algorithm; `disabled_algorithms={"pubkeys": ["rsa-sha2-512",
"rsa-sha2-256"]}` is required to avoid an outright `Authentication
failed` with the modern SHA-2 RSA variants.

paramiko 5.0.0's changelog states it "Removed RSA SHA-1 signature
verification support". Confirmed live: with `disabled_algorithms` as
above, paramiko 5.0.0 fails *every* connection attempt against this
device with:

```
paramiko.ssh_exception.SSHException: An RSA key was specified, but no
RSA pubkey algorithms are configured!
```

paramiko 4.0.0, with the identical connection code, authenticates
successfully every time. This is unrelated to root cause #1 above (it
blocks the connection before any SFTP request is even sent), but was
initially confounding because the project's `pyproject.toml` does not
pin an upper bound on paramiko (`netmiko>=4.3.0` pulls in whatever is
newest), so a freshly provisioned `.venv` can silently resolve to an
incompatible paramiko version.

**Fix**: pin `paramiko<5.0.0` as a project dependency.

## Root cause #3: SFTP sharing a transport with an interactive shell channel hangs

Initially assumed not to affect production code and deprioritized —
turned out to be very much live in `upgrade()`'s actual code path, and
only surfaced once root cause #1 was fixed and a real `upgrade()` run
got far enough to reach the upload step.

Symptom: no immediate error. `sftp.put()` (even with a
`callback=...` progress callback) makes zero progress for ~5 minutes,
during which only transport-level `keepalive@lag.net` global requests
are visible in the debug log — nothing SFTP-specific — then the
connection dies with `Connection reset by peer` / `SSH session not
active`.

`upload_files()`/`upload_with_retry()` open SFTP via
`client.conn.remote_conn_pre.open_sftp()` — `client.conn` **is** the
live, active interactive Netmiko CLI shell session (the same one
`send_command()` etc. use throughout `upgrade()`), so this was always
opening the SFTP channel on a transport that already had an
interactive shell channel on it. That combination is what hangs on
this device.

**First fix attempt that did *not* work**: opening a second, separate
Netmiko session via `ConnectHandler(**client.device)` for SFTP,
believing that a distinct connection object would avoid sharing state
with `client.conn`. It doesn't help: `ConnectHandler()` always spins up
its own interactive shell channel as part of connecting (that's what
`session_preparation()` does — find the prompt, run
`screen-length 0 temporary`, etc.), so the "dedicated" Netmiko
connection reproduces the exact same condition (an interactive shell
channel plus an SFTP channel on one transport) with a brand new shell
session instead of the old one. Confirmed live: `[chan 0]` was the new
session's own shell, `[chan 1]` the SFTP channel, and the same 5-minute
hang followed.

**Actual fix**: `_connect_dedicated()` in `upload.py` builds a plain
`paramiko.SSHClient` directly (same host/port/username/password-or-key/
disabled_algorithms as `client.device`) and never calls Netmiko at all
for this connection, so no interactive shell channel is ever created on
it — only the SFTP channel `_dedicated_sftp()` explicitly opens. This
matches how the diagnostic scripts in `diagnostics/huawei_vrp/` always
connected, which is also why they never hit this failure mode.

## Ruled out during investigation

These all looked plausible at some point and were each disproved with a
live test against the reference device — kept here so they aren't
re-investigated from scratch next time:

- **Remote path spelling** (`flash:/name` vs `flash:name` vs `/name` vs
  bare `name`): real, independent, stable rule — a leading `/` is
  required somewhere (`flash:/name` and `/name` both work; `flash:name`
  and bare `name` both fail) — but `upload.py` already uses `flash:/`,
  so this was never the cause of the production failures. Confirmed
  paramiko's SFTP attribute block sent on `OPEN` is empty by default
  (`SFTPAttributes()`, no flags at all) regardless of mode, so attribute
  flags/permissions are not a factor either.
- **Insufficient flash space**: real and worth fixing independently
  (see `flash.py`'s `ensure_flash_space()` / `calculate_required_space()`,
  which already exists in this codebase for exactly this reason), but
  not the cause of the specific failures reproduced here — the failure
  reproduced identically with ~427 MiB free (comfortably more than
  `calculate_required_space()` would require for the target file).
- **VRP-side SFTP server/session state** (tried: restarting just the
  SFTP service via `undo sftp server enable` / `sftp server enable`;
  tried: a full device reboot): no effect, ruling out a wedged
  server-side session/resource as the cause.
- **VRP attack-defense / rate limiting** (`display anti-attack
  statistics`, `display cpu-defend statistics`): zero drops on any
  protocol, including SSH — not a packet-level throttling/blacklist
  issue.
- **VRP-side logging**: the device logs almost nothing useful for this
  failure. `display logbuffer` / `display trapbuffer` show only
  login/logout and an unrelated `SUPPRESS_LOG ModuleName=FTPS
  InfoAlias=SFTPS_REQUEST` entry that, even with `info-center
  statistic-suppress` disabled, never correlated with a reproduced
  failure — a dead end, not connected to this bug.

## Diagnostic scripts

The scripts used to reproduce and isolate all of the above live in
`diagnostics/huawei_vrp/` (gitignored — local investigation tools, not
part of the library or its test suite):

- `sftp_path_matrix.py` — minimal repro: tries `OPEN(write)` across the
  four path spellings above, plus an SCP-protocol (`scp` package) upload
  attempt, on a tiny throwaway payload.
- `sftp_flash_and_path_check.py` — combines `display startup` + `dir`
  flash/space analysis (mirroring `flash.py`'s own arithmetic) with the
  same path-spelling matrix (with the warm-up `normalize(".")` fix
  applied), and an optional real-file upload gated on the space check.
