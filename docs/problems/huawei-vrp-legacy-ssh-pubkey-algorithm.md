# Huawei VRP: legacy SSH pubkey algorithm rejection surfaces as a connection timeout

Same root cause as Problem #2 in
[huawei-vrp-sftp-open-failure.md](huawei-vrp-sftp-open-failure.md) (some
VRP devices only accept the legacy `ssh-rsa` public-key signature, not
`rsa-sha2-256`/`512`), but observed through a plain Netmiko
`ConnectHandler()` connection (not SFTP), where it does not surface as a
clean auth failure.

## Symptom

Without `disabled_algorithms` set:

```
NetmikoTimeoutException: Unable to connect after 2 attempts.
```

No indication anywhere in this message that authentication, rather than
network reachability, is the problem.

## Root cause

paramiko tries `rsa-sha2-512` first (VRP doesn't send a
`server-sig-algs` list, so paramiko defaults to its own first preferred
algorithm), the device rejects it, and Netmiko wraps the resulting
`SSHException("Invalid key")` into its own `NetmikoTimeoutException` —
chained via `__context__`, not `__cause__`. `network_automation`'s own
`base_client.py` retry loop then discarded that entirely on its final
`raise`, leaving only the generic message above.

## Complication: connections shortly after a failed attempt get reset

A connection attempt made shortly after a failed auth attempt against
the same device gets `Connection reset by peer` during the SSH banner
read, before authentication is even attempted again — the device
appears to briefly reject new connections from the same source right
after a failed login, independent of which pubkey algorithm the next
attempt offers.

An isolated single failed attempt followed by an ~8s pause was sometimes
enough for a subsequent `disabled_algorithms` retry to succeed, but
rapid repeated testing against the same device (many connection attempts
within a short window while diagnosing this) pushed the same 8-10s pause
past the point of being enough — consistent with an escalating or
cumulative lockout, not a fixed per-failure window. Treat any specific
pause duration as a rough estimate, not a guaranteed constant, and avoid
rapid repeated connection attempts against a device suspected of this
problem.

## Fix

`base_client.py`'s `_classify_connect_failure()`/`_summarize_reasons()`
walk `__context__`/`__cause__` to report the real per-attempt reason
(distinguishing a device that responded and rejected the connection from
a genuinely unreachable one) instead of a blanket "may be offline".
Callers that need to recover the connection (not just diagnose it)
should use a single connection attempt (`connect_retries=1`, since
retrying with identical parameters cannot fix a deterministic
rejection), wait a cooldown, then retry once with `disabled_algorithms`.

## Takeaway

A `NetmikoTimeoutException` against an older VRP device is not
necessarily a real timeout — check `__context__`/`__cause__` (or the
classified message from `base_client.py`) before assuming the device is
offline. If it resolves to a bare `SSHException`/"Invalid key" or a
`Connection reset by peer` shortly after a failed attempt, suspect a
pubkey algorithm mismatch first (see Problem #2 in
[huawei-vrp-sftp-open-failure.md](huawei-vrp-sftp-open-failure.md)).
