# Huawei VRP: potential pitfalls with SFTP over paramiko

Short summary of problems encountered while uploading files (firmware
`.cc` / patch `.pat`) to a Huawei VRP device (tested on an AR650) via
`paramiko.SFTPClient`. Collected as a list of things to watch out for in
similar integrations in the future — this does not describe any
particular implementation or how it was fixed.

## Symptom

A write `OPEN` over SFTP fails immediately (in well under 0.1s) with a
raw SFTP status:

```
code=4 (SSH_FX_FAILURE)
text=''
```

The device closes the SFTP session right afterward. This does not depend
on the remote path's name/length or on the `OPEN` flags
(`CREATE|TRUNC`, `CREATE|APPEND`, `CREATE|EXCL`, explicit `0644`
attributes, etc.). The OpenSSH `sftp` command-line client, against the
same host/user/key, uploads the same file without issue — so the problem
is on the client (paramiko) side, not the device's.

## Problem #1: the device rejects the very first write `OPEN` on a freshly opened SFTP channel

This particular device rejects a write `OPEN` if it's the first request
sent on a freshly opened SFTP channel — regardless of path, flags,
attributes, or free flash space. Sending any read-only request first
(e.g. `normalize(".")`) on the same channel makes every subsequent write
on that channel succeed.

- OpenSSH's `sftp` binary always issues a `REALPATH(".")` immediately
  after opening an SFTP session (to establish its remote working
  directory), so it never hits this.
- `paramiko.SFTPClient` does **not** do this automatically (its internal
  `_cwd` stays `None` until something explicitly touches it — see
  `_adjust_cwd()` in `paramiko/sftp_client.py`). Code that calls
  `sftp.put()` as the very first operation on a freshly opened channel
  hits this every time.

**Takeaway**: before the first `put()`/`open()` on a newly opened SFTP
channel, always send some harmless read-only request first (e.g.
`normalize(".")`) — don't assume the first write will just work, even if
it does on other devices/vendors.

## Problem #2: paramiko >=5.0.0 cannot authenticate to this device at all

The device only supports the legacy `ssh-rsa` (SHA-1) public-key
signature algorithm; `disabled_algorithms={"pubkeys": ["rsa-sha2-512",
"rsa-sha2-256"]}` is required to avoid an outright `Authentication
failed` with the modern SHA-2 RSA variants.

paramiko 5.0.0's changelog states it "Removed RSA SHA-1 signature
verification support" — with the same `disabled_algorithms`, every
connection attempt fails with:

```
paramiko.ssh_exception.SSHException: An RSA key was specified, but no
RSA pubkey algorithms are configured!
```

paramiko 4.0.0, with identical connection code, authenticates
successfully every time.

**Takeaway**: when working with older network devices that require
RSA/SHA-1, pin an upper bound on the paramiko version
(`paramiko<5.0.0`) — without an explicit pin, a freshly provisioned
environment can silently resolve to an incompatible version.

## Problem #3: SFTP sharing a transport with an interactive shell channel hangs

Opening an SFTP channel on the same SSH transport that already has an
active interactive shell channel (e.g. a Netmiko CLI session) leads to a
hang on this device — not immediately, but after about 5 minutes.

Symptom: no immediate error. `sftp.put()` (even with a
`callback=...`) makes zero progress for about 5 minutes, with only
transport-level `keepalive@lag.net` requests visible in the debug log —
nothing SFTP-specific — after which the connection dies with
`Connection reset by peer` / `SSH session not active`.

Opening a *second, separate* session (e.g. via `ConnectHandler()`) in the
hope of avoiding shared state does **not** help — such libraries
typically always spin up their own interactive shell channel as part of
connecting (finding the prompt, running init commands, etc.), so the
"dedicated" connection reproduces the exact same condition (a shell
channel plus an SFTP channel on one transport), just with a new shell
session instead of the old one.

**Takeaway**: SFTP to devices of this kind should go over a completely
separate SSH connection (a plain `paramiko.SSHClient`, with no CLI
library in the background), not over a transport shared with an
interactive session — even a seemingly "new" session from the same CLI
library may open its own shell channel in the background and reproduce
the problem.
