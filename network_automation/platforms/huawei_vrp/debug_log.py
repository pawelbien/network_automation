# network_automation/platforms/huawei_vrp/debug_log.py

"""
Opt-in DEBUG-level diagnostics for HuaweiVRP operations.

Gated exclusively by client.context.debug_log (never by the logger's own
level) — client.context.logger may be a duck-typed object (e.g. a Nautobot
Job logger) that doesn't filter by level at all, so relying on standard
logging.DEBUG would leak verbose output into production logs regardless of
setLevel(). debug_log() is the single source of truth for whether these
diagnostics are emitted; the default (debug_log=False) produces zero
behavior change.

Never pass client.device, client.password, client.passphrase, or
client.key_file to these functions — only command strings, raw CLI
responses, filenames, and result.metadata.

Tier-1 helpers (flash.py, health_check.py getters, etc.) are tested with
minimal fake clients exposing only .conn/.logger, with no .context — so
these functions look up .context defensively (getattr, default False)
rather than requiring it, preserving that "helpers need no lifecycle"
contract instead of forcing every caller to grow a .context attribute.
"""

import time
from contextlib import contextmanager


def _debug_enabled(client) -> bool:
    context = getattr(client, "context", None)
    return bool(getattr(context, "debug_log", False))


def debug_log(client, msg, *args):
    """Emit at DEBUG level only when client.context.debug_log is enabled."""
    if _debug_enabled(client):
        client.logger.debug(msg, *args)


@contextmanager
def debug_timed_step(client, step_name):
    """Log start/finish + elapsed time of a step, only when debug_log is enabled."""
    if not _debug_enabled(client):
        yield
        return

    start = time.monotonic()
    client.logger.debug("%s: starting", step_name)
    try:
        yield
    finally:
        client.logger.debug("%s: finished in %.3fs", step_name, time.monotonic() - start)
