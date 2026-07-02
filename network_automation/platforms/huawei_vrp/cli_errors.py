# network_automation/platforms/huawei_vrp/cli_errors.py

"""
Huawei VRP cross-cutting CLI-error validation.

Every command executed against the device must be checked for CLI-level
errors before its output is used, regardless of which phase it belongs to
(discovery, validation, transfer, configuration, post-reboot) — see
engineering_handbook/tmp/huawei_vrp_update.txt, "Command output validation
(cross-cutting rule)".

This is a Tier-1 style module: no connection lifecycle, pure functions that
take a command + its already-collected output and raise on error. It has no
dependencies on the rest of the huawei_vrp package (leaf module) so it can
be imported from run.py, info.py, upgrade.py, and client.py without cycle
risk.
"""


class CLIError(RuntimeError):
    """
    Raised when a VRP command's output contains a CLI-level error pattern
    (e.g. "% Unrecognized command") or unexpectedly empty/truncated output.

    Subclasses RuntimeError so all existing `except RuntimeError` /
    `pytest.raises(RuntimeError)` call sites keep working unchanged.
    Kept as a distinct type (not a bare RuntimeError) so future retry/lock/
    rollback logic can distinguish "device rejected the command" from other
    RuntimeError causes (e.g. verification-failure RuntimeErrors in
    upgrade.py) without string-matching on the message.
    """


_ERROR_PATTERNS = (
    "Error:",
    "% Unrecognized command",
    "% Wrong parameter",
)


def _check_cli_output(command: str, output: str, *, expect_content: bool = True) -> None:
    """
    Raise CLIError if `output` (the result of running `command`) shows a
    VRP CLI-level error, or — when expect_content is True — is empty or
    whitespace-only.

    - no connect/disconnect, no I/O: pure check over an already-collected
      string
    - case-sensitive substring match on the exact vendor patterns from the
      spec; VRP error prefixes are fixed-case CLI conventions, not free
      text, so case-sensitive matching avoids accidentally flagging
      legitimate output that happens to contain a lowercase "error:" inside
      e.g. a config line or log message
    - expect_content=False is for callers that intentionally tolerate
      empty output (e.g. a silent-on-success ack); it does NOT disable the
      CLI-error-pattern check, only the emptiness check
    """
    for pattern in _ERROR_PATTERNS:
        if pattern in output:
            raise CLIError(
                f"CLI error detected after running {command!r}: "
                f"output contains {pattern!r}. Full output: {output!r}"
            )

    if expect_content and not output.strip():
        raise CLIError(
            f"Empty or truncated output for command {command!r}, "
            "expected content."
        )
