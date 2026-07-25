# network_automation/tests/opnsense/test_progress.py

import os

import pytest

from network_automation.platforms.opnsense.progress import ProgressParser

_PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)
)))
_PRIV_UPDATE_LOG = os.path.join(_PACKAGE_ROOT, "priv_update.log")
_PRIV_UPGRADE_LOG = os.path.join(_PACKAGE_ROOT, "priv_upgrade.log")


# -------------------------------------------------------
# Per-stage anchor matching
# -------------------------------------------------------

@pytest.mark.parametrize(
    "line,expected_message",
    [
        ("Updating OPNsense repository catalogue...", "Updating repositories..."),
        ("Checking for upgrades (119 candidates): .......... done", "Resolving dependencies..."),
        ("Processing candidates (119 candidates): ...... done", "Resolving dependencies..."),
        ("Checking integrity... done (5 conflicting)", "Resolving dependencies..."),
        ("The following 116 package(s) will be affected (of 0 checked):", "Resolving dependencies..."),
        ("[1/116] Fetching unbound-1.25.1_1.pkg: .......... done", "Downloading packages..."),
        ("Fetching base-26.7-amd64.txz: .... done", "Downloading packages..."),
        ("Fetching kernel-26.7-amd64.txz: ... done", "Downloading packages..."),
        ("Fetching packages-26.7-amd64.tar: .......... done", "Downloading packages..."),
        ("[1/132] Upgrading easy-rsa from 3.2.4,1 to 3.2.6,1...", "Installing packages..."),
        ("[15/132] Installing colordiff-1.0.22...", "Installing packages..."),
        ("[22/132] Deinstalling opnsense-26.1...", "Installing packages..."),
        ("[1/272] Reinstalling icu-76.1,1...", "Installing packages..."),
        ("[37/37] Deleting files for python311-3.11.14: .......... done", "Installing packages..."),
        ("Extracting base-26.7-amd64.txz... done", "Installing packages..."),
        ("Installing kernel-26.7-amd64.txz...", "Installing packages..."),
        ("! A critical upgrade is in progress. !", "Installing packages..."),
        (">>> Invoking update script 'refresh.sh'", "Running post-install tasks..."),
        (r"Migrated OPNsense\Firewall\Filter from 1.0.4 to 1.0.5", "Running post-install tasks..."),
        ("==> Running trigger: gio-modules.ucl", "Running post-install tasks..."),
        ("Writing firmware settings: OPNsense", "Running post-install tasks..."),
        ("Writing trust bundles...done.", "Running post-install tasks..."),
        ("Flushing all caches...done.", "Running post-install tasks..."),
    ],
)
def test_feed_line_recognizes_stage_anchor(line, expected_message):
    parser = ProgressParser()
    assert parser.feed_line(line) == expected_message


@pytest.mark.parametrize(
    "line",
    [
        "",
        "Currently running OPNsense 26.1 (amd64) at Thu Jul 23 12:53:52 CEST 2026",
        "	py313-Babel: 2.18.0",
        "New packages to be INSTALLED:",
        "Number of packages to be upgraded: 64",
        "The process will require 511 MiB more space.",
        "Message from easy-rsa-3.2.6,1:",
        "===> Creating groups",
        "Using existing group 'hostd'",
        "***GOT REQUEST TO UPDATE***",
        "***DONE***",
        "Please reboot.",
        # sanity.sh is an upgrade *pre-flight* check that runs before any
        # packages are installed - must NOT be mistaken for the
        # post-install "update script" (refresh.sh) trigger.
        ">>> Invoking upgrade script 'sanity.sh'",
        "Passed all upgrade tests.",
    ],
)
def test_feed_line_ignores_noise(line):
    parser = ProgressParser()
    assert parser.feed_line(line) is None


# -------------------------------------------------------
# Monotonic / no-regression semantics
# -------------------------------------------------------

def test_feed_line_does_not_regress_to_an_earlier_stage():
    parser = ProgressParser()
    assert parser.feed_line("[1/1] Fetching foo.pkg: .. done") == "Downloading packages..."
    # A dependency-resolution-looking line arriving late (pkg's own
    # multi-pass conflict resolution re-prints this) must not bounce the
    # already-announced stage backward.
    assert parser.feed_line("Checking integrity... done (0 conflicting)") is None


def test_feed_line_suppresses_repeated_announcement_of_the_same_stage():
    parser = ProgressParser()
    assert parser.feed_line("Updating OPNsense repository catalogue...") == "Updating repositories..."
    assert parser.feed_line("Updating OPNsense repository catalogue...") is None


def test_feed_line_can_jump_ranks_when_intermediate_stages_have_no_matching_output():
    parser = ProgressParser()
    assert parser.feed_line("[1/1] Upgrading foo from 1.0 to 2.0...") == "Installing packages..."


def test_reset_allows_a_previously_seen_stage_to_be_announced_again():
    parser = ProgressParser()
    assert parser.feed_line("Updating OPNsense repository catalogue...") == "Updating repositories..."
    assert parser.feed_line("[1/1] Upgrading foo from 1.0 to 2.0...") == "Installing packages..."

    parser.reset()

    assert parser.feed_line("Updating OPNsense repository catalogue...") == "Updating repositories..."


def test_new_parser_instance_starts_with_no_stage_announced_yet():
    parser = ProgressParser()
    assert parser.feed_line("some unrelated noise") is None


# -------------------------------------------------------
# Smoke test against real captured transcripts
#
# priv_update.log / priv_upgrade.log are full terminal transcripts from
# real runs (see upgrade.py's module docstring / the plan that introduced
# this module) - the strongest available regression guard that the parser
# still reduces a real multi-hundred/thousand-line transcript down to the
# expected ordered stage sequence.
# -------------------------------------------------------

def _feed_file(path):
    """
    Feed every line of a captured transcript through a ProgressParser,
    calling reset() at the point _run_and_wait() itself would (when it
    detects a reboot occurred - see upgrade.py's "connection was lost and
    reconnected... assuming a reboot occurred" warning), and return the
    ordered list of emitted stage messages.
    """
    parser = ProgressParser()
    messages = []
    with open(path) as f:
        for line in f:
            line = line.rstrip("\n")
            if "assuming a reboot occurred" in line:
                parser.reset()
                continue
            message = parser.feed_line(line)
            if message:
                messages.append(message)
    return messages


@pytest.mark.skipif(
    not os.path.exists(_PRIV_UPDATE_LOG),
    reason="priv_update.log sample transcript not present in this checkout",
)
def test_smoke_priv_update_log_reduces_to_expected_stage_sequence():
    assert _feed_file(_PRIV_UPDATE_LOG) == [
        "Updating repositories...",
        "Resolving dependencies...",
        "Downloading packages...",
        "Installing packages...",
        "Running post-install tasks...",
    ]


@pytest.mark.skipif(
    not os.path.exists(_PRIV_UPGRADE_LOG),
    reason="priv_upgrade.log sample transcript not present in this checkout",
)
def test_smoke_priv_upgrade_log_reduces_to_expected_stage_sequence():
    # The major-upgrade transcript fetches/extracts a new base OS image
    # and reboots into it *before* any repository/package-catalog work
    # starts (see progress.py's module docstring) - so "Downloading
    # packages..."/"Installing packages..." are announced once for that,
    # then again for the real package set once repositories/dependencies
    # for the new branch are resolved after reboot.
    assert _feed_file(_PRIV_UPGRADE_LOG) == [
        "Downloading packages...",
        "Installing packages...",
        "Updating repositories...",
        "Resolving dependencies...",
        "Installing packages...",
        "Running post-install tasks...",
    ]
