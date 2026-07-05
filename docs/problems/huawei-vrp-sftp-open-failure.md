# Huawei VRP: SFTP upload fails with immediate, empty SSH_FX_FAILURE

Status: root causes #1–3 are fixed in `upload.py` and confirmed by a real
~161MB firmware transfer against a live reference device — that same run
is what surfaced #4. Fix #4 (and #1–3 again) were then confirmed by a
second live run (~162MB transfer, `V300R023C00SPC100` → `V300R024C00SPC100`):
the transfer completed, size-verified, and `client.conn` survived the
~16-minute transfer without hitting the console idle-timeout. That same
run surfaced #5 (fixed, then re-triggered a fresh transfer per #6 below)
and then #7. A third live run confirmed #6 and #7 (upload and
`configure_next_startup` were correctly skipped as already-done) and
surfaced #8: `reboot()` silently failed to confirm the reboot prompt, so
the device never actually rebooted despite `upgrade()` reporting success.
#6, #7, and #8 were fixed, and a fourth live run (device freshly
downgraded back to `V300R023C00SPC100`, target file already on flash from
a prior run) surfaced #9: `save_configuration()`'s idle-based "y"
confirmation returned before VRP's own asynchronous "please wait" notice
had fully arrived, and the leftover text was then misread as the current
prompt by the very next command, hanging it for its full read_timeout.
#9 was fixed, and a fifth live run (same device/version pair) completed
`upgrade()` end-to-end with no errors, warnings, or timeouts anywhere in
the debug log: upload skipped (idempotent, MD5 match), MD5 verified,
`save`/`reboot` handled cleanly, a real ~292s reboot with the delayed
`[y/n]` prompt confirmed correctly, and post-reboot validation (version,
routing, interfaces, alarms) all passed —
`result.metadata['post_reboot_validation_passed'] == True`. All nine root
causes are now considered closed.

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

## Root cause #4: client.conn's CLI session dies from inactivity during a long transfer

Found on the first live run after fixing #1–3 (a real ~161MB firmware
upload that took several minutes). Symptom, in order:

1. The dedicated SFTP connection's `sftp.put()` genuinely took a long
   time (VRP itself is slow to write a large file to flash) — during
   which it logged nothing beyond the usual transport-level
   `keepalive@lag.net` global requests, which come from `client.conn`'s
   *own* connection (its `keepalive=30` device setting), not from the
   dedicated SFTP connection (which sets no keepalive at all).
2. The transfer itself appears to have completed successfully.
3. Immediately after, `upload_with_retry()` calls `verify_remote_file()`
   → `get_flash_info()` → `client.conn.send_command("dir")` — and this
   failed, with VRP itself reporting on the CLI: `Info: Configuration
   console time out, please retry to log on`. `client.conn`'s
   interactive session had been idle (no CLI traffic at all) for the
   entire duration of the transfer, and this device's **console**
   idle-timeout — a separate mechanism from the VTY idle-timeout, and
   *not* reset by the SSH-transport-level `keepalive@lag.net` requests,
   since those never touch the CLI application layer — killed it.
4. Because `upload_with_retry()` doesn't distinguish "the transfer
   failed" from "verification failed because of an unrelated dead CLI
   session," the whole attempt is treated as failed and retried.
5. The retry's `open(..., "wb")` is `CREATE|TRUNC`, so it **truncates
   the file that had just finished uploading successfully** and starts
   over from zero — confirmed live via `dir *.cc` on the device, showing
   the file shrink from its full expected size back down to a few MB
   right as the retry began. A likely-complete transfer was silently
   discarded.

**Fix**: `_keep_cli_alive_during()` in `upload.py` runs a background
thread that sends a harmless newline over `client.conn` every 60s
(`_CLI_KEEPALIVE_INTERVAL_SECONDS`, well under the observed timeout)
for the duration of the SFTP transfer in both `upload_files()` and
`upload_with_retry()`, and is always fully stopped and joined before
the `with` block exits — so nothing touches `client.conn` concurrently
once the caller (e.g. `verify_remote_file()`) needs it again. Best
effort: if `client.conn` is already dead, it gives up silently and lets
the real error surface at the actual point of use, same as before.

## Root cause #5: get_file_md5()'s default read_timeout is too short for large files

Found on the first live run after fixing #1–4 (the same ~162MB transfer
that confirmed #4). Symptom, in order:

1. The upload itself completed and passed `verify_remote_file()` (exists,
   correct size).
2. `verify_md5()` → `get_file_md5()` sent `display system file-md5
   flash:/<file>`. This device echoes a text progress spinner
   (`1%` ... `100%`) while it hashes the file on-device, which took ~13s
   for this ~162MB file — longer than Netmiko's default `send_command()`
   read_timeout (~10s).
3. `send_command()` raised `ReadTimeoutError: Pattern not detected:
   '<Huawei>' in output` partway through the spinner, even though the
   device was still working correctly and later produced a valid MD5 —
   this is the exception that actually reached the caller
   (`upgrade.py`'s example script printed "Upgrade failed: Pattern not
   detected: '<Huawei>' in output"). Confirmed by reading Netmiko's own
   source (`CiscoBaseConnection.cleanup()`, which `HuaweiBase` uses) that
   `client.disconnect()` cannot be a second, masking source of this same
   exception: `cleanup()` only ever does one `write_channel("quit" +
   RETURN)` with no read/pattern-match of its own, and `disconnect()`
   wraps `cleanup()` in a bare `try/except: pass` — so this was the
   original exception the whole time, not a disconnect-time one.

Confirmed the transfer itself was not at fault: the raw device output
captured before the timeout already contained a valid MD5
(`8e86b820c04ac9381f78f4fd5992a2d3` for
`flash:/AR650A_V300R024C00SPC100.cc` in this run).

**Fix**: `get_file_md5()` in `info.py` now passes `read_timeout=300` to
`send_command()`, matching the existing precedent in `flash.py`'s
`ensure_flash_space()` for the other known-slow VRP command
(re-pointing the backup startup image).

## Root cause #6: ensure_flash_space() deletes the just-uploaded target file itself

Found on the second live run (the one that confirmed fix #5), triggered
because that run started with the prior run's already-uploaded,
already-correct target file still on flash (that prior run never got
past the MD5 step, before fix #5). Symptom:

`calculate_required_space()` always assumes the target `.cc`/`.pat` is
about to be freshly uploaded, and if a file already exists on flash under
the exact target filename, it adds that file's size a second time as
`overwrite_margin` (reasoning: a fresh upload needs to coexist with the
old same-named file during transfer). This produced `required =
391889408` bytes against `free = 282726400` bytes — insufficient — solely
*because* the correct target file was already present, which triggered
`cleanup_flash()`. `cleanup_flash()`'s candidate list is any non-protected
`.cc`/`.pat` file (`protected_names` only covers the *current* unit's
startup/next-startup image and patch — not whatever `client.firmware_file`
/ `client.patch_file` are about to be uploaded), so it deleted
`AR650A_V300R024C00SPC100.cc` — the fully-transferred, MD5-correct target
file — before `_upload_pending()`'s idempotency check
(`file_already_on_flash()`) ever got a chance to see it and skip the
upload. Confirmed in `result.metadata`: `'flash_cleanup_performed': True,
'deleted_files': ['AR650A_V300R024C00SPC100.cc']`, followed by a full
second ~914s re-upload of the exact same bytes.

Wasteful (an extra ~15-minute transfer every run until the file is
finally consumed by `configure_next_startup`) but not data-lossy on its
own — unlike root cause #4, there was no partially-written file at risk,
since `cleanup_flash()` only deletes whole files, and the re-upload
starts clean. Not yet fixed: doing so would mean either excluding
`client.firmware_file`/`client.patch_file`'s target names from
`cleanup_flash()`'s candidates, or having `ensure_flash_space()` check
`file_already_on_flash()` first and skip straight past the space
calculation for files that are already correct.

## Root cause #7: configure_next_startup()'s default read_timeout is too short

Found on the same second live run, immediately after root cause #5's fix
let the MD5 step pass for the first time. Same failure class as #5, a
different command: `startup system-software flash:/<file>` — which VRP
itself flags as slow (`Info: Start processing. The check may take a long
time. Please wait...` / `Info: Software package verification is in
progress. Please wait...`, re-verifying the whole firmware package) — was
sent via plain `send_command()` with no `read_timeout`, so it hit
Netmiko's ~10s default and raised the same `ReadTimeoutError: Pattern not
detected: '<Huawei>' in output`, crashing `upgrade()` before it ever
reached `reboot()`.

Confirmed the command itself had actually succeeded on the device despite
the client-side timeout: a manual `display startup` on the device (run
from a separate session while investigating) showed `Next startup system
software: flash:/AR650A_V300R024C00SPC100.cc` already correctly set, even
though the script had crashed out with an exception right after issuing
that same command.

**Fix**: `configure_next_startup()` and `configure_next_startup_patch()`
(same `startup system-software` / `startup patch` verification pattern)
and `apply_patch()` (`patch load ... all run`, same shape of risk even
though patches are usually much smaller) in `upgrade.py` all now pass
`read_timeout=300` to their `send_command()` calls. `wait_for_reconnect()`
(explicit `read_timeout=10` inside its own polling retry loop) was checked
and is not at risk of this failure mode. `client.reboot()` was *also*
checked and assumed safe at the time (`send_command_timing`, not
pattern-matched, so the ~10s-default-too-short failure mode doesn't
apply to it) — that assumption turned out to be wrong in a different way;
see root cause #8.

## Root cause #8: reboot()'s send_command_timing() can return before the confirmation prompt even appears — silently skipping it

Found on the third live run (the one that confirmed fixes #6 and #7:
upload and `configure_next_startup` were both correctly skipped as
already-done). `upgrade()` reported `'rebooted': True,
'reboot_duration_seconds': 21.09` and then failed version verification
with `new_firmware` still `V300R023C00SPC100` — the device was still
running the old firmware. The user confirmed independently: the device
had not actually rebooted at all.

Sequence, reconstructed from the debug log:

1. `client.reboot()` sent `reboot` via `send_command_timing()`, whose
   completion detection is idle-time-based (returns once the channel has
   been quiet for `last_read`, default 2.0s) — not pattern-based.
2. VRP's response to `reboot` started with `Warning: The current next
   startup patch does not match the version of the current next startup
   system software!` and `Info: The system is comparing the
   configuration, please wait.` (this device still had the *old* patch,
   `AR650A_V300R023SPH1b0.pat`, configured as `next_startup_patch` — this
   was a `FIRMWARE_ONLY` operation, so nothing updated the patch slot),
   then paused for over 2 seconds before printing the actual `System will
   reboot! Continue? [y/n]:` prompt.
3. That pause was long enough for `send_command_timing()`'s idle-based
   heuristic to conclude the command was done, returning *before* the
   `[y/n]:` prompt was even printed. `reboot()`'s confirmation loop
   (`if "y/n" not in output.lower(): break`) checked the captured output —
   which was only the warning/info text — found no `"y/n"`, and broke
   immediately without ever sending `"y"`. Confirmed via the debug log:
   exactly one `send_command_timing response` line appears for the whole
   reboot sequence, and it doesn't contain the confirmation prompt.
4. `reboot()` fell through to `self.conn.disconnect()` with the device's
   `[y/n]:` prompt still dangling, unanswered, on that about-to-close
   session. VRP discards a pending confirmation when its session ends,
   so the reboot silently never happened.
5. `wait_for_reconnect()` then opened a *brand new* SSH session to the
   same, never-rebooted device and found it responsive within seconds —
   reported as a fast, successful 21-second reboot-and-reconnect, when in
   fact nothing had rebooted at all.

Side effect also visible in the log: `self.conn.disconnect()` itself
misbehaved afterward — Netmiko's `cleanup()` calls `check_config_mode()`,
which was fooled by the dangling `...[y/n]:` prompt text into thinking
the device was in config mode, so it then sent `return` (VRP's
exit-config-mode command) — producing `Error: Please choose 'YES' or
'NO' first before pressing 'Enter'.` in the log. Cosmetic once the real
fix is in (there's no dangling prompt to confuse `check_config_mode()`
if `reboot()` actually consumes it), not addressed separately.

**Fix**: `reboot()` now uses pattern-based `send_command(expect_string=...)`
instead of idle-based `send_command_timing()` for the initial `reboot`
send, waiting for the actual `[y/n]` prompt text (or the normal CLI
prompt, if none appears) rather than for the channel to go quiet — so a
mid-response pause like this device's "please wait" can no longer be
mistaken for completion. `read_timeout=300` for headroom. Sending the
confirming `"y"` is wrapped in a `try/except`, since the device dropping
the connection right after is the expected outcome once it's actually
rebooting, not an error.

### Follow-up: the "y" confirmation itself must NOT use pattern-matching

Fixed live on the very next run (the one that finally got a real reboot):
after sending `"y"`, VRP printed `Info: system is rebooting, please
wait...` and then **nothing else for over a minute**, without actually
closing the connection. Using `send_command(expect_string=...,
read_timeout=300)` for this step too (as first written) meant Netmiko
kept polling `read_channel()` every ~10-30ms for however much of that
300s was left, waiting for a prompt that was never coming —
flooding the log (the user had to Ctrl-C `priv_hua_update.py`) and
delaying `disconnect()` for no benefit, since there's nothing meaningful
left to wait for once the device is actually rebooting.

Unlike the initial `reboot` send (which genuinely needed to wait through
a slow, *bounded* pre-prompt delay), the `"y"` confirmation has no such
follow-up text to wait through — it's confirmed instantly, so idle-time
detection is the right tool: **`send_command_timing("y", read_timeout=15)`**
returns as soon as the channel goes quiet (typically within a couple of
seconds), with the short `read_timeout` only as a ceiling, not a target.
This mirrors `mikrotik_routeros/client.py`'s `reboot()`, which never
pattern-matches at all for its post-confirmation state — fire the `"y"`
and move on to `disconnect()`/`wait_for_reconnect()`.

Confirmed against a manual console session on the reference device — no
second `[y/n]` prompt, nothing else printed after confirming:

```
<Huawei>reboot
Info: The system is comparing the configuration, please wait.
System will reboot! Continue? [y/n]:y
Info: system is rebooting, please wait...
```

## Root cause #9: save_configuration()'s "y" confirmation returns before VRP's async "please wait" notice arrives, poisoning the next command's prompt detection

Found on the fourth live run (device manually downgraded back to
`V300R023C00SPC100`, target `.cc` still on flash from a prior run so
idempotency was expected to skip the upload). Symptom, reconstructed from
the debug log:

1. `save_configuration()` sent `save`, got the `Are you sure to
   continue?[Y/N]:` prompt within ~2s (fine), then sent `y` via
   `send_command_timing("y")` (idle-time detection, default 2.0s quiet
   window).
2. The channel went quiet for 2s right after the `y` echo, so
   `send_command_timing()` returned an empty response and
   `pre_upgrade_save_configuration` logged as finished after 4.4s total —
   *before* VRP had actually written anything else.
3. ~0.9s after that idle cutoff, VRP asynchronously printed `It will take
   several minutes to save configuration file, please wait...` on the
   same channel — arriving too late for the already-returned
   `send_command_timing()` call to see it, so it was never consumed by
   `save_configuration()` at all.
4. The very next command, `get_file_md5()`'s `send_command("display
   system file-md5 flash:/...")`, uses Netmiko's default
   `auto_find_prompt=True`, which calls `find_prompt()` *before* sending
   the command to determine the search pattern. `find_prompt()` read the
   still-pending `It will take several minutes...` line off the channel
   and mistook it for the current prompt: `[DEBUG] [find_prompt()]:
   prompt is It will take several minutes to save configuration file,
   please wait...`
5. `send_command()` then searched for that entire sentence, verbatim, as
   its completion pattern. It never reappears (the actual subsequent
   output is the MD5 progress spinner, the MD5 result, and the real
   `<Huawei>` prompt) — Netmiko's main read loop doesn't log a "Pattern
   found" line the way `find_prompt()`/`read_until_pattern()` do, so the
   MD5 command's own successful completion produced no confirmation log
   at all, and the loop just kept calling `read_channel()` roughly every
   30ms, logging an empty `[DEBUG] read_channel:` line each time, for the
   remainder of its `read_timeout=300` window — the "zalewanie" (flood)
   symptom reported live. Given enough time this would have ended in a
   `ReadTimeout`, not a hang forever, but 300s of pure debug-log noise for
   a command that had actually already finished 275+ seconds earlier is a
   real usability bug, and the same class of thing could poison any
   command that happens to run right after `save_configuration()`.

This is structurally the same shape of bug as root cause #8: VRP inserts
an asynchronous, bounded-but-variable "please wait" style notice, and an
idle-time-based (or last-line-based, for `find_prompt()`) completion
heuristic gets fooled into thinking it has the final answer before the
device is actually done talking.

**Fix**: `save_configuration()`'s "y" confirmation now uses
`client.conn.send_command("y", expect_string=r"[\]>]", read_timeout=300,
strip_prompt=False, strip_command=False)` instead of
`send_command_timing("y")`. This waits for the real prompt bracket to
reappear (bounded by 300s, matching VRP's own "several minutes" warning)
so the "please wait" notice is fully consumed as part of `save`'s own
response instead of leaking into whatever command runs next — and, since
Netmiko only invokes the risky `find_prompt()` probe when `expect_string`
is `None`, passing it explicitly here means that probe is never sent at
all for this step, mirroring the same reasoning already applied to the
initial `reboot` send in root cause #8's fix. The initial `save` send
itself was not changed — its `[Y/N]:` prompt arrived well within the
default idle window in every observed run, with no evidence of the same
race.

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
