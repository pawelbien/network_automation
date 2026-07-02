# network_automation/tests/huawei_vrp/test_health_check.py

import pytest
from unittest.mock import MagicMock

from network_automation.platforms.huawei_vrp.cli_errors import CLIError
from network_automation.platforms.huawei_vrp.health_check import (
    _parse_cpu_usage,
    _parse_memory,
    _parse_alarm_active,
    _parse_interface_brief,
    get_cpu_usage,
    get_memory,
    get_alarm_active,
    get_interface_brief,
    collect_health_snapshot,
    evaluate_health,
    run_pre_upgrade_health_check,
)


# ---------- Shared device output helpers ----------

_DISPLAY_CPU_USAGE = "CPU Usage            : 12% Max: 45%\n"
_DISPLAY_MEMORY = "Memory Using Percentage Is: 50%\n"
_DISPLAY_ALARM_ACTIVE_NONE = "No alarm information.\n"
_DISPLAY_ALARM_ACTIVE_CRITICAL = (
    "Sequence   AlarmId  Severity  Date        Time      AlarmName   AlarmInfo\n"
    "1          100      Critical  2024-08-08  12:00:00  BoardFault  extra\n"
)
_DISPLAY_INTERFACE_BRIEF = (
    "PHY: Physical\n"
    "Interface                   PHY   Protocol\n"
    "GigabitEthernet0/0/0        up    up\n"
    "GigabitEthernet0/0/1        down  down\n"
)


# ---------- parsers ----------

def test_parse_cpu_usage():
    assert _parse_cpu_usage(_DISPLAY_CPU_USAGE) == {"cpu_usage_percent": 12.0}


def test_parse_cpu_usage_unparseable_raises():
    with pytest.raises(ValueError):
        _parse_cpu_usage("garbage output")


def test_parse_memory():
    assert _parse_memory(_DISPLAY_MEMORY) == {"memory_usage_percent": 50.0}


def test_parse_memory_unparseable_raises():
    with pytest.raises(ValueError):
        _parse_memory("garbage output")


def test_parse_alarm_active_none():
    assert _parse_alarm_active(_DISPLAY_ALARM_ACTIVE_NONE) == {"alarms": []}


def test_parse_alarm_active_critical():
    result = _parse_alarm_active(_DISPLAY_ALARM_ACTIVE_CRITICAL)
    assert result["alarms"] == [
        {"severity": "critical", "name": "BoardFault", "raw": "1          100      Critical  2024-08-08  12:00:00  BoardFault  extra"}
    ]


def test_parse_interface_brief():
    result = _parse_interface_brief(_DISPLAY_INTERFACE_BRIEF)
    assert result["interfaces"] == {
        "GigabitEthernet0/0/0": {"physical_status": "up", "protocol_status": "up"},
        "GigabitEthernet0/0/1": {"physical_status": "down", "protocol_status": "down"},
    }


# ---------- getters ----------

def test_get_cpu_usage_success():
    client = MagicMock()
    client.conn.send_command.return_value = _DISPLAY_CPU_USAGE
    assert get_cpu_usage(client) == {"cpu_usage_percent": 12.0}
    client.conn.send_command.assert_called_once_with("display cpu-usage")


def test_get_memory_success():
    client = MagicMock()
    client.conn.send_command.return_value = _DISPLAY_MEMORY
    assert get_memory(client) == {"memory_usage_percent": 50.0}


def test_get_alarm_active_success():
    client = MagicMock()
    client.conn.send_command.return_value = _DISPLAY_ALARM_ACTIVE_NONE
    assert get_alarm_active(client) == {"alarms": []}


def test_get_interface_brief_success():
    client = MagicMock()
    client.conn.send_command.return_value = _DISPLAY_INTERFACE_BRIEF
    result = get_interface_brief(client)
    assert len(result["interfaces"]) == 2


def test_get_cpu_usage_raises_cli_error():
    client = MagicMock()
    client.conn.send_command.return_value = "% Unrecognized command"
    with pytest.raises(CLIError):
        get_cpu_usage(client)


def test_collect_health_snapshot():
    client = MagicMock()
    client.conn.send_command.side_effect = [
        _DISPLAY_CPU_USAGE, _DISPLAY_MEMORY, _DISPLAY_ALARM_ACTIVE_NONE, _DISPLAY_INTERFACE_BRIEF,
    ]
    snapshot = collect_health_snapshot(client)
    assert snapshot == {
        "cpu_usage_percent": 12.0,
        "memory_usage_percent": 50.0,
        "alarms": [],
        "interfaces": {
            "GigabitEthernet0/0/0": {"physical_status": "up", "protocol_status": "up"},
            "GigabitEthernet0/0/1": {"physical_status": "down", "protocol_status": "down"},
        },
    }


# ---------- evaluate_health ----------

_BASE_SNAPSHOT = {
    "cpu_usage_percent": 10.0,
    "memory_usage_percent": 10.0,
    "alarms": [],
    "interfaces": {
        "Gi0/0/0": {"physical_status": "up", "protocol_status": "up"},
    },
}


def _evaluate(snapshot, **overrides):
    kwargs = {
        "cpu_threshold_percent": 80.0,
        "memory_threshold_percent": 80.0,
        "max_unexpected_down_interfaces": 0,
    }
    kwargs.update(overrides)
    return evaluate_health(snapshot, **kwargs)


def test_evaluate_health_no_violations():
    result = _evaluate(_BASE_SNAPSHOT)
    assert result == {"violations": [], "passed": True}


def test_evaluate_health_cpu_violation():
    snapshot = {**_BASE_SNAPSHOT, "cpu_usage_percent": 90.0}
    result = _evaluate(snapshot)
    assert result["passed"] is False
    assert any("CPU" in v for v in result["violations"])


def test_evaluate_health_memory_violation():
    snapshot = {**_BASE_SNAPSHOT, "memory_usage_percent": 95.0}
    result = _evaluate(snapshot)
    assert result["passed"] is False
    assert any("Memory" in v for v in result["violations"])


def test_evaluate_health_critical_alarm_violation():
    snapshot = {**_BASE_SNAPSHOT, "alarms": [{"severity": "critical", "name": "X", "raw": "x"}]}
    result = _evaluate(snapshot)
    assert result["passed"] is False


def test_evaluate_health_major_alarm_violation():
    snapshot = {**_BASE_SNAPSHOT, "alarms": [{"severity": "major", "name": "X", "raw": "x"}]}
    result = _evaluate(snapshot)
    assert result["passed"] is False


def test_evaluate_health_minor_alarm_does_not_violate():
    snapshot = {**_BASE_SNAPSHOT, "alarms": [{"severity": "minor", "name": "X", "raw": "x"}]}
    result = _evaluate(snapshot)
    assert result["passed"] is True


def test_evaluate_health_too_many_down_interfaces():
    snapshot = {
        **_BASE_SNAPSHOT,
        "interfaces": {
            "Gi0/0/0": {"physical_status": "down", "protocol_status": "down"},
        },
    }
    result = _evaluate(snapshot, max_unexpected_down_interfaces=0)
    assert result["passed"] is False


def test_evaluate_health_down_interfaces_within_tolerance():
    snapshot = {
        **_BASE_SNAPSHOT,
        "interfaces": {
            "Gi0/0/0": {"physical_status": "down", "protocol_status": "down"},
        },
    }
    result = _evaluate(snapshot, max_unexpected_down_interfaces=1)
    assert result["passed"] is True


# ---------- run_pre_upgrade_health_check ----------

def _client_for_health_check(mocker, snapshot, mode="abort"):
    client = MagicMock()
    client.health_check_cpu_threshold = 80.0
    client.health_check_memory_threshold = 80.0
    client.health_check_max_down_interfaces = 0
    mocker.patch(
        "network_automation.platforms.huawei_vrp.health_check.collect_health_snapshot",
        return_value=snapshot,
    )
    return client


class _Result:
    def __init__(self):
        self.metadata = {}
        self.warnings = []


def test_run_pre_upgrade_health_check_passes_and_stores_baseline(mocker):
    client = _client_for_health_check(mocker, _BASE_SNAPSHOT)
    result = _Result()

    evaluation = run_pre_upgrade_health_check(client, result, mode="abort")

    assert evaluation["passed"] is True
    assert result.metadata["pre_upgrade_baseline_health"] == _BASE_SNAPSHOT
    assert "health_check_violations" not in result.metadata


def test_run_pre_upgrade_health_check_abort_mode_raises_before_mutation(mocker):
    bad_snapshot = {**_BASE_SNAPSHOT, "cpu_usage_percent": 99.0}
    client = _client_for_health_check(mocker, bad_snapshot, mode="abort")
    result = _Result()

    with pytest.raises(RuntimeError):
        run_pre_upgrade_health_check(client, result, mode="abort")

    # baseline is still recorded even on abort, for the report
    assert result.metadata["pre_upgrade_baseline_health"] == bad_snapshot
    assert result.metadata["health_check_violations"]


def test_run_pre_upgrade_health_check_warn_mode_does_not_raise(mocker):
    bad_snapshot = {**_BASE_SNAPSHOT, "cpu_usage_percent": 99.0}
    client = _client_for_health_check(mocker, bad_snapshot, mode="warn")
    result = _Result()

    evaluation = run_pre_upgrade_health_check(client, result, mode="warn")

    assert evaluation["passed"] is False
    assert result.warnings
    client.logger.warning.assert_called_once()
