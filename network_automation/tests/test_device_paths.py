# network_automation/tests/test_device_paths.py

from network_automation.device_paths import safe_device_name


def test_safe_device_name_short_name_unchanged():
    assert safe_device_name("test-backup", prefix="nauto_", suffix=".zip", max_length=64) == \
        "nauto_test-backup.zip"


def test_safe_device_name_falls_back_to_hash_when_too_long():
    long_name = "a" * 60
    assert len(f"nauto_{long_name}.zip") > 64

    result = safe_device_name(long_name, prefix="nauto_", suffix=".zip", max_length=64)

    assert len(result) <= 64
    assert result.startswith("nauto_")
    assert result.endswith(".zip")
    assert long_name not in result


def test_safe_device_name_hash_is_deterministic_and_name_sensitive():
    kwargs = dict(prefix="nauto_", suffix=".zip", max_length=64)
    assert safe_device_name("a" * 60, **kwargs) == safe_device_name("a" * 60, **kwargs)
    assert safe_device_name("a" * 60, **kwargs) != safe_device_name("b" * 60, **kwargs)


def test_safe_device_name_path_prefix_counts_toward_max_length():
    # 60-char name + "nauto_" (6) + ".zip" (4) = 70 chars, under 64 only
    # without the "flash:/" (7) path_prefix accounted for.
    name = "a" * 54
    without_path_prefix = safe_device_name(name, prefix="nauto_", suffix=".zip", max_length=64)
    with_path_prefix = safe_device_name(
        name, prefix="nauto_", suffix=".zip", max_length=64, path_prefix="flash:/",
    )

    assert without_path_prefix == f"nauto_{name}.zip"  # 64 chars, fits
    assert with_path_prefix != without_path_prefix  # 71 with prefix, falls back to hash
    assert with_path_prefix.startswith("nauto_")
    assert with_path_prefix.endswith(".zip")
