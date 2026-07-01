# network_automation/tests/huawei_vrp/test_version.py

import pytest

from network_automation.platforms.huawei_vrp.version import (
    parse_firmware_version,
    is_firmware_newer,
)


def test_parse_firmware_version():
    assert parse_firmware_version("V300R024C00SPC100") == (300, 24, 100)


def test_parse_firmware_version_lowercase():
    assert parse_firmware_version("v200r024c00spc500") == (200, 24, 500)


def test_parse_firmware_version_empty_raises():
    with pytest.raises(ValueError):
        parse_firmware_version("")


def test_parse_firmware_version_unparseable_raises():
    with pytest.raises(ValueError):
        parse_firmware_version("not-a-version")


def test_is_firmware_newer_true():
    assert is_firmware_newer("V300R024C00SPC100", "V300R024C00SPC200") is True


def test_is_firmware_newer_false_when_equal():
    assert is_firmware_newer("V300R024C00SPC100", "V300R024C00SPC100") is False


def test_is_firmware_newer_false_when_older():
    assert is_firmware_newer("V300R024C00SPC200", "V300R024C00SPC100") is False


def test_is_firmware_newer_compares_release_before_spc():
    # Higher release wins even with a lower spc.
    assert is_firmware_newer("V300R023C00SPC900", "V300R024C00SPC100") is True
