# network_automation/platforms/opnsense/progress.py

"""
Stage-detecting progress parser for OPNsense firmware operations.

`configctl firmware update`/`upgrade` transcripts routinely run to
1000-2000+ raw lines (package resolution, per-package fetch/extract
progress, migration scripts, ...) - unsuitable to forward line-by-line to
a Nautobot Job log. ProgressParser reduces that stream to a handful of
logical stage transitions, driven entirely off stable structural anchors
(command prefixes like "[n/N] ", "Fetching base-"/"Fetching kernel-") -
never exact package names/counts/versions, so it stays valid across future
OPNsense releases.

Deliberately I/O-free and framework-agnostic: takes one line of text in,
returns at most one human-readable stage message out. Knows nothing about
logging, files, or the SSH session - reusable as-is by update(), upgrade(),
and check_updates() in upgrade.py.

Reboot-related stages ("Reboot detected.", "Waiting for device...",
"Device is back online.") are intentionally NOT handled here - see
upgrade.py's _run_and_wait() docstring for why that signal isn't textual
and can't be observed by a line-in/message-out parser.
"""

import re

# Ordered by rank (index = rank); the parser only moves forward through
# this list, never backward, so out-of-order/duplicate anchor matches
# (pkg's own two-pass dependency resolution re-prints "will be affected",
# a mid-flight reboot can bounce back to an earlier-looking line, etc.)
# can't make an already-announced stage disappear or repeat.
_STAGES: list[tuple[str, str, re.Pattern]] = [
    (
        "repositories",
        "Updating repositories...",
        re.compile(r"Updating OPNsense repository catalogue"),
    ),
    (
        "dependencies",
        "Resolving dependencies...",
        re.compile(
            r"Checking for upgrades|Processing candidates|Checking integrity|"
            r"will be affected"
        ),
    ),
    (
        "downloading",
        "Downloading packages...",
        # Per-package fetches ("[n/N] Fetching foo.pkg: ... done") and the
        # major-upgrade OS image fetch ("Fetching base-X.txz"/"Fetching
        # kernel-X.txz"/"Fetching packages-X.tar", no "[n/N]" prefix, and
        # observed to happen *before* any repository/dependency activity).
        re.compile(r"^\[\d+/\d+\] Fetching|^Fetching (base|kernel|packages)-"),
    ),
    (
        "installing",
        "Installing packages...",
        re.compile(
            r"^\[\d+/\d+\] (Upgrading|Installing|Extracting|Reinstalling|"
            r"Deinstalling|Deleting)|"
            r"^(Installing|Extracting) (base|kernel|packages)-|"
            r"critical upgrade is in progress"
        ),
    ),
    (
        "post_install",
        "Running post-install tasks...",
        # "update script" (refresh.sh - config/model migrations, run after
        # every completed update AND upgrade) is matched deliberately, not
        # "upgrade script" (sanity.sh - a pre-reboot upgrade sanity check
        # that runs *before* packages are even installed; matching it here
        # would fast-forward past "installing" before it's even started).
        re.compile(
            r"^>>> Invoking update script|^Migrated OPNsense|"
            r"^==?> Running trigger:|Writing (firmware settings|trust bundles)|"
            r"Flushing all caches"
        ),
    ),
]


class ProgressParser:
    """
    Feed it complete lines one at a time; it returns the message for a
    stage the first time (and only the first time) that stage is reached.
    """

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        """Start a fresh epoch - all stages can be re-announced from here.

        Called after a detected reboot: OPNsense's backend can legitimately
        re-run earlier phases (e.g. repository catalogue update) once the
        device is back up, and that's new, useful progress information -
        not a regression to suppress.
        """
        self._highest_rank = -1

    def feed_line(self, line: str) -> str | None:
        for rank, (_key, message, pattern) in enumerate(_STAGES):
            if rank <= self._highest_rank:
                continue
            if pattern.search(line):
                self._highest_rank = rank
                return message
        return None
