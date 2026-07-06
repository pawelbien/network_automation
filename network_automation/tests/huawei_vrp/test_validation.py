# network_automation/tests/huawei_vrp/test_validation.py

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from network_automation.platforms.huawei_vrp.validation import (
    validate_firmware_hardware_compatibility,
    validate_patch_firmware_compatibility,
    validate_upgrade_inputs,
    warn_if_downgrade,
)
from network_automation.platforms.huawei_vrp.version import (
    OPERATION_FIRMWARE_AND_PATCH,
    OPERATION_FIRMWARE_ONLY,
    OPERATION_PATCH_ONLY,
)


def _client(**kwargs):
    defaults = dict(
        firmware_file="/tmp/AR650A_V300R024C00SPC200.cc",
        firmware_version="V300R024C00SPC200",
        patch_file="/tmp/AR650A_V300R024SPH1b0.pat",
        patch_version="ARV300R024SPH1b0",
        logger=MagicMock(),
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


# ---------- validate_upgrade_inputs: filename format ----------

def test_validate_upgrade_inputs_rejects_bad_firmware_extension():
    client = _client(firmware_file="/tmp/AR650A_V300R024C00SPC200.bin")

    with pytest.raises(ValueError, match="firmware filename"):
        validate_upgrade_inputs(
            client, unit_model="AR651", operation_type=OPERATION_FIRMWARE_ONLY
        )


def test_validate_upgrade_inputs_rejects_bad_patch_extension():
    client = _client(patch_file="/tmp/AR650A_V300R024SPH1b0.zip")

    with pytest.raises(ValueError, match="patch filename"):
        validate_upgrade_inputs(
            client, unit_model="AR651", operation_type=OPERATION_PATCH_ONLY
        )


def test_validate_upgrade_inputs_accepts_well_formed_names():
    client = _client()

    validate_upgrade_inputs(
        client, unit_model="AR651", operation_type=OPERATION_FIRMWARE_AND_PATCH
    )  # must not raise


def test_validate_upgrade_inputs_skips_patch_checks_for_firmware_only():
    client = _client(patch_file="/tmp/bad-name.zip", patch_version=None)

    validate_upgrade_inputs(
        client, unit_model="AR651", operation_type=OPERATION_FIRMWARE_ONLY
    )  # must not raise — patch not part of this operation


def test_validate_upgrade_inputs_skips_firmware_checks_for_patch_only():
    client = _client(firmware_file="/tmp/bad-name.zip")

    validate_upgrade_inputs(
        client, unit_model="AR651", operation_type=OPERATION_PATCH_ONLY
    )  # must not raise — firmware not part of this operation


# ---------- validate_firmware_hardware_compatibility ----------

def test_validate_firmware_hardware_compatibility_same_family_ok():
    # "AR650A" family "AR" vs. unit model "AR651" family "AR" -- same
    # platform line, different SKU digit, which is a realistic match.
    validate_firmware_hardware_compatibility(
        "AR650A_V300R024C00SPC200.cc", "AR651"
    )  # must not raise


def test_validate_firmware_hardware_compatibility_different_family_raises():
    with pytest.raises(ValueError, match="hardware"):
        validate_firmware_hardware_compatibility(
            "S6730_V300R024C00SPC200.cc", "AR651"
        )


def test_validate_firmware_hardware_compatibility_skips_unrecognized_filename():
    # Doesn't match the structured naming convention -- nothing to compare.
    validate_firmware_hardware_compatibility(
        "custom-firmware-image.cc", "AR651"
    )  # must not raise


# ---------- validate_patch_firmware_compatibility ----------

def test_validate_patch_firmware_compatibility_matching_release_ok():
    validate_patch_firmware_compatibility(
        "AR650A_V300R024SPH1b0.pat", "V300R024C00SPC200"
    )  # must not raise


def test_validate_patch_firmware_compatibility_mismatched_release_raises():
    with pytest.raises(ValueError, match="release train"):
        validate_patch_firmware_compatibility(
            "AR650A_V300R023SPH1b0.pat", "V300R024C00SPC200"
        )


def test_validate_patch_firmware_compatibility_no_letter_suffix_matching_release_ok():
    # Letter-less "SPH<branch>" naming convention (e.g. "SPH221"), confirmed
    # live against a real AR650 device.
    validate_patch_firmware_compatibility(
        "AR650A_V300R024SPH221.pat", "V300R024C00SPC200"
    )  # must not raise


def test_validate_patch_firmware_compatibility_no_letter_suffix_mismatched_release_raises():
    with pytest.raises(ValueError, match="release train"):
        validate_patch_firmware_compatibility(
            "AR650A_V300R023SPH221.pat", "V300R024C00SPC200"
        )


def test_validate_patch_firmware_compatibility_skips_unrecognized_filename():
    validate_patch_firmware_compatibility(
        "custom-patch.pat", "V300R024C00SPC200"
    )  # must not raise


# ---------- warn_if_downgrade ----------

def test_warn_if_downgrade_false_when_upgrading():
    client = _client()
    result = warn_if_downgrade(
        client, "V300R024C00SPC100", "V300R024C00SPC200", None, None
    )
    assert result is False
    client.logger.warning.assert_not_called()


def test_warn_if_downgrade_true_and_logs_when_firmware_older():
    client = _client()
    result = warn_if_downgrade(
        client, "V300R024C00SPC200", "V300R024C00SPC100", None, None
    )
    assert result is True
    client.logger.warning.assert_called_once()


def test_warn_if_downgrade_true_and_logs_when_patch_older():
    client = _client()
    result = warn_if_downgrade(
        client, "V300R024C00SPC100", "V300R024C00SPC100", "SPH1b0", "SPH1a0"
    )
    assert result is True
    client.logger.warning.assert_called_once()
