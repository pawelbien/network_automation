# network_automation/tests/huawei_vrp/test_version.py

import pytest

from network_automation.platforms.huawei_vrp.version import (
    parse_firmware_version,
    is_firmware_newer,
    parse_patch_version,
    is_patch_newer,
    determine_operation_type,
    OPERATION_NONE,
    OPERATION_PATCH_ONLY,
    OPERATION_FIRMWARE_ONLY,
    OPERATION_FIRMWARE_AND_PATCH,
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


# ---------- parse_patch_version ----------

def test_parse_patch_version_embedded_in_device_string():
    # Real device string from `display patch-information`: "Patch version"
    # embeds a release-train prefix before the SPH<branch><letter><number>.
    assert parse_patch_version("ARV300R023SPH1b0") == (1, 1, 0)


def test_parse_patch_version_bare():
    assert parse_patch_version("SPH12c5") == (12, 2, 5)


def test_parse_patch_version_empty_raises():
    with pytest.raises(ValueError):
        parse_patch_version("")


def test_parse_patch_version_unparseable_raises():
    with pytest.raises(ValueError):
        parse_patch_version("not-a-patch-version")


# ---------- is_patch_newer ----------

def test_is_patch_newer_true():
    assert is_patch_newer("SPH1a0", "SPH1b0") is True


def test_is_patch_newer_false_when_equal():
    assert is_patch_newer("SPH1b0", "SPH1b0") is False


def test_is_patch_newer_false_when_older():
    assert is_patch_newer("SPH1b0", "SPH1a0") is False


def test_is_patch_newer_true_when_no_current_patch():
    assert is_patch_newer(None, "SPH1a0") is True


def test_is_patch_newer_unparseable_target_raises():
    with pytest.raises(ValueError):
        is_patch_newer(None, "not-a-patch-version")


# ---------- determine_operation_type ----------

def test_determine_operation_type_firmware_and_patch():
    result = determine_operation_type(
        "V300R023C00SPC100", "V300R024C00SPC100", "SPH1a0", "SPH1b0"
    )
    assert result == OPERATION_FIRMWARE_AND_PATCH


def test_determine_operation_type_firmware_only():
    result = determine_operation_type(
        "V300R023C00SPC100", "V300R024C00SPC100", None, None
    )
    assert result == OPERATION_FIRMWARE_ONLY


def test_determine_operation_type_patch_only():
    result = determine_operation_type(
        "V300R024C00SPC100", "V300R024C00SPC100", "SPH1a0", "SPH1b0"
    )
    assert result == OPERATION_PATCH_ONLY


def test_determine_operation_type_none():
    result = determine_operation_type(
        "V300R024C00SPC100", "V300R024C00SPC100", "SPH1b0", "SPH1b0"
    )
    assert result == OPERATION_NONE


def test_determine_operation_type_none_when_nothing_requested():
    result = determine_operation_type(
        "V300R024C00SPC100", "V300R024C00SPC100", None, None
    )
    assert result == OPERATION_NONE
