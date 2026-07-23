# network_automation/tests/huawei_vrp/test_sftp_server_check.py

"""
Tests for _sftp_server_enabled() / _ensure_sftp_server_enabled() /
SftpServerDisabledError (upload.py) — the pre-flight check that fails
fast, with a clear error, when a device's SFTP server isn't enabled,
instead of 3 retries each ending in a bare 'Channel closed.'.
"""

from unittest.mock import MagicMock

import pytest

from network_automation.platforms.huawei_vrp.upload import (
    _sftp_server_enabled,
    _ensure_sftp_server_enabled,
    _dedicated_sftp,
    upload_with_retry,
    SftpServerDisabledError,
)


# -------------------------------------------------------
# _sftp_server_enabled (pure logic)
# -------------------------------------------------------

def test_sftp_server_enabled_true_for_exact_line():
    output = "sftp server enable\n"
    assert _sftp_server_enabled(output) is True


def test_sftp_server_enabled_true_with_surrounding_whitespace_and_other_lines():
    output = "some other config line\n  sftp server enable  \nmore config\n"
    assert _sftp_server_enabled(output) is True


def test_sftp_server_enabled_false_for_empty_output():
    assert _sftp_server_enabled("") is False


def test_sftp_server_enabled_false_when_explicitly_undone():
    # "undo sftp server enable" must NOT be mistaken for enabled — it's a
    # substring match risk this function deliberately avoids (exact-line
    # comparison, not `in` on the whole output).
    assert _sftp_server_enabled("undo sftp server enable\n") is False


def test_sftp_server_enabled_false_for_unrelated_sftp_lines():
    # Other sftp-related config present, but never the exact enable line.
    output = "sftp server source -a 10.0.0.1\nsftp client source -a 10.0.0.1\n"
    assert _sftp_server_enabled(output) is False


# -------------------------------------------------------
# _ensure_sftp_server_enabled
# -------------------------------------------------------

def test_ensure_sftp_server_enabled_raises_when_disabled():
    client = MagicMock()
    client.conn.send_command.return_value = ""

    with pytest.raises(SftpServerDisabledError, match="SFTP server is not enabled"):
        _ensure_sftp_server_enabled(client)

    client.conn.send_command.assert_called_once_with(
        "display current-configuration | include sftp"
    )


def test_ensure_sftp_server_enabled_passes_when_enabled():
    client = MagicMock()
    client.conn.send_command.return_value = "sftp server enable\n"

    _ensure_sftp_server_enabled(client)  # must not raise


# -------------------------------------------------------
# _dedicated_sftp(): checked before connecting at all
# -------------------------------------------------------

def test_dedicated_sftp_checks_before_connecting(mocker):
    client = MagicMock()
    client.conn.send_command.return_value = ""

    mock_connect = mocker.patch(
        "network_automation.platforms.huawei_vrp.upload._connect_dedicated",
    )

    with pytest.raises(SftpServerDisabledError):
        with _dedicated_sftp(client):
            pass

    mock_connect.assert_not_called()


# -------------------------------------------------------
# upload_with_retry(): SftpServerDisabledError is not retried
# -------------------------------------------------------

def test_upload_with_retry_does_not_retry_sftp_server_disabled(mocker, huawei_client, tmp_path):
    local_file = tmp_path / "fw.cc"
    local_file.write_bytes(b"firmware contents")

    huawei_client.conn = MagicMock()
    huawei_client.conn.send_command.return_value = ""  # SFTP not enabled

    mock_connect = mocker.patch(
        "network_automation.platforms.huawei_vrp.upload._connect_dedicated",
    )
    mock_sleep = mocker.patch("network_automation.platforms.huawei_vrp.upload.time.sleep")

    with pytest.raises(SftpServerDisabledError):
        upload_with_retry(
            huawei_client, files=[local_file], remote_dir="flash:/", timeout=30, retries=3,
        )

    # fails on the very first attempt — no retry, no connection ever attempted
    mock_connect.assert_not_called()
    mock_sleep.assert_not_called()
    assert huawei_client.conn.send_command.call_count == 1
