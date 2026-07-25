# network_automation/platforms/opnsense/detail_log.py

"""
Per-device detailed diagnostic log file for OPNsense firmware operations.

Separate concern from progress.py's stage messages (user-facing, sent to
the INFO logger / Nautobot Job log) and from debug_log.py's DEBUG-level
diagnostics (gated by client.context.debug_log, routed through the same
logger as everything else): this module writes every raw line received
from the device, every reconnect attempt, and every exception (with full
traceback) to a local file - for troubleshooting only, never forwarded to
the Job log.

Gated by client.debug_log_dir (an OPNsense.__init__ parameter, None by
default - opt-in, matching context.debug_log's default). DetailLog never
raises: a failure to create the directory or open the file degrades to a
silent no-op object rather than aborting an operation that is otherwise
succeeding - same philosophy as BaseClient._safe_log_info().
"""

import os
import re
import traceback
from contextlib import contextmanager
from datetime import datetime

_SLUG_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _slug(value: str) -> str:
    return _SLUG_RE.sub("_", value).strip("_") or "device"


def _device_label(client) -> str:
    context = getattr(client, "context", None)
    device_name = getattr(context, "device_name", None)
    return device_name or client.host


class DetailLog:
    """
    Write-only, best-effort diagnostic log. `raw()` and `event()` never
    raise; construct via open_detail_log() rather than directly.
    """

    def __init__(self, file_handle, path: str | None = None) -> None:
        self._fh = file_handle
        self.path = path

    def _write(self, text: str) -> None:
        if self._fh is None:
            return
        try:
            # Local time, matching the millisecond-precision "YYYY-MM-DD
            # HH:MM:SS,mmm" format logging.Formatter's default asctime
            # produces (see the INFO logger's own timestamps) - not UTC,
            # so entries here line up directly with the INFO log when
            # cross-referencing the two during troubleshooting.
            now = datetime.now()
            timestamp = now.strftime("%Y-%m-%d %H:%M:%S,") + f"{now.microsecond // 1000:03d}"
            self._fh.write(f"{timestamp} {text}\n")
            self._fh.flush()
        except Exception:
            pass

    def raw(self, line: str) -> None:
        """Record one raw line received from the device, verbatim."""
        self._write(line)

    def event(self, msg: str, *args) -> None:
        """Record a diagnostic event (reconnect attempt, state transition, ...)."""
        try:
            rendered = msg % args if args else msg
        except Exception:
            rendered = msg
        self._write(f"[EVENT] {rendered}")

    def exception(self, exc: BaseException) -> None:
        """Record an exception with its full stack trace."""
        trace = "".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        )
        self._write(f"[EXCEPTION]\n{trace.rstrip()}")

    def close(self) -> None:
        if self._fh is None:
            return
        try:
            self._fh.close()
        except Exception:
            pass
        self._fh = None


class _NullDetailLog(DetailLog):
    """No-op stand-in used when debug_log_dir is unset or unusable."""

    def __init__(self) -> None:
        super().__init__(None, None)


@contextmanager
def open_detail_log(client, action_name: str):
    """
    Open (overwrite-mode) the detail log file for this device+action and
    yield a DetailLog writing to it. Falls back to a no-op DetailLog if
    client.debug_log_dir is None/empty or the file can't be opened.

    The file path is deterministic per device+action (no timestamp
    component), so each new operation for the same device overwrites the
    previous run's file rather than appending to or accumulating them.
    """
    debug_log_dir = getattr(client, "debug_log_dir", None)
    file_handle = None
    path = None

    if debug_log_dir:
        try:
            os.makedirs(debug_log_dir, exist_ok=True)
            filename = f"{_slug(_device_label(client))}_{_slug(action_name)}.log"
            path = os.path.join(debug_log_dir, filename)
            file_handle = open(path, "w", encoding="utf-8")
        except Exception:
            file_handle = None
            path = None

    dlog = DetailLog(file_handle, path) if file_handle is not None else _NullDetailLog()
    try:
        yield dlog
    finally:
        dlog.close()
