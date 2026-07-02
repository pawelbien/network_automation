# network_automation/tests/huawei_vrp/test_cli_errors.py

import pytest

from network_automation.platforms.huawei_vrp.cli_errors import (
    CLIError,
    _check_cli_output,
)


def test_check_cli_output_passes_on_normal_output():
    _check_cli_output("display version", "VRP (R) software, Version 5.170")


@pytest.mark.parametrize(
    "pattern",
    ["Error:", "% Unrecognized command", "% Wrong parameter"],
)
def test_check_cli_output_raises_on_known_error_patterns(pattern):
    output = f"{pattern} something went wrong"
    with pytest.raises(CLIError):
        _check_cli_output("display version", output)


def test_check_cli_output_raises_on_empty_output_by_default():
    with pytest.raises(CLIError, match="Empty or truncated"):
        _check_cli_output("display version", "")


def test_check_cli_output_raises_on_whitespace_only_output():
    with pytest.raises(CLIError, match="Empty or truncated"):
        _check_cli_output("display version", "   \n  ")


def test_check_cli_output_allows_empty_output_when_not_expected():
    _check_cli_output(
        "startup system-software flash:/x.cc", "", expect_content=False
    )


def test_check_cli_output_still_raises_on_error_pattern_when_content_not_expected():
    with pytest.raises(CLIError):
        _check_cli_output(
            "startup system-software flash:/x.cc",
            "% Wrong parameter",
            expect_content=False,
        )


def test_cli_error_is_a_runtime_error():
    # Backward compatibility: existing `pytest.raises(RuntimeError)` /
    # `except RuntimeError` call sites must keep working unchanged.
    assert issubclass(CLIError, RuntimeError)
