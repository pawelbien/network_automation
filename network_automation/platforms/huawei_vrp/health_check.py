# network_automation/platforms/huawei_vrp/health_check.py

"""
Huawei VRP device health: pre-upgrade baseline check and post-reboot
baseline comparisons.

Bundles both the raw display-command getters/parsers (cpu-usage, memory,
alarm active, interface brief, ip routing-table) and the policy layer
(threshold evaluation, abort/warn, baseline comparisons) in one module —
this is a single cohesive "device health" concern, distinct from info.py's
identity/startup-config concern.

Tier-1 style: no connection lifecycle, raises on failure.
"""

import re

from network_automation.platforms.huawei_vrp.cli_errors import _check_cli_output
from network_automation.platforms.huawei_vrp.debug_log import debug_log

DEFAULT_CPU_THRESHOLD_PERCENT = 80.0
DEFAULT_MEMORY_THRESHOLD_PERCENT = 80.0
DEFAULT_MAX_UNEXPECTED_DOWN_INTERFACES = 0

_ALARM_SEVERITIES = {"critical", "major"}


# -------------------------------------------------------
# Parsers (pure logic)
# -------------------------------------------------------

def _parse_cpu_usage(output: str) -> dict:
    """
    Parse 'display cpu-usage' output.

    Matches the first "CPU Usage:" occurrence, which on multi-plane devices
    (e.g. AR650 V300R024+) is the Control Plane figure — the one relevant
    to management/routing daemon stability, as opposed to the Data Plane
    figure that follows it. Accepts decimal values (e.g. "8.4%") since
    newer VRP releases report fractional percentages, not just integers.

    Returns {"cpu_usage_percent": float}.
    """
    m = re.search(r'CPU Usage\s*:\s*([\d.]+)%', output)
    if not m:
        raise ValueError(f"Could not parse CPU usage from output: {output!r}")
    return {"cpu_usage_percent": float(m.group(1))}


def _parse_memory(output: str) -> dict:
    """
    Parse 'display memory-usage' output.

    Returns {"memory_usage_percent": float}.
    """
    m = re.search(r'Memory Using Percentage Is:\s*(\d+)%', output)
    if not m:
        raise ValueError(f"Could not parse memory usage from output: {output!r}")
    return {"memory_usage_percent": float(m.group(1))}


_ALARM_LINE_RE = re.compile(
    r'^\s*\d+\s+\S+\s+(Critical|Major|Minor|Warning)\s+\S+\s+\S+\s+(\S+)'
)


def _parse_alarm_active(output: str) -> dict:
    """
    Parse 'display alarm active' output.

    Returns {"alarms": [{"severity": str, "name": str, "raw": str}, ...]}.
    An empty list is a valid, non-error state (no active alarms).
    """
    alarms = []
    for line in output.splitlines():
        m = _ALARM_LINE_RE.match(line)
        if m:
            alarms.append({
                "severity": m.group(1).lower(),
                "name": m.group(2),
                "raw": line.strip(),
            })
    return {"alarms": alarms}


_INTERFACE_LINE_RE = re.compile(
    r'^(?P<name>\S+)\s+(?P<phys>\*?down|up)\s+(?P<proto>\*?down|up)\b'
)


def _parse_interface_brief(output: str) -> dict:
    """
    Parse 'display interface brief' output.

    Returns {"interfaces": {name: {"physical_status": str, "protocol_status": str,
    "admin_down": bool}, ...}}. "physical_status"/"protocol_status" are always
    "up" or "down" (the "*" prefix VRP uses to mark administratively-down
    interfaces is stripped, not left embedded in the string); "admin_down" is
    True when either status was starred. Dict keyed by interface name (not a
    list) so callers can diff by key without re-sorting — see
    compare_interfaces_to_baseline().
    """
    interfaces = {}
    for line in output.splitlines():
        m = _INTERFACE_LINE_RE.match(line.strip())
        if not m:
            continue
        phys_raw = m.group("phys")
        proto_raw = m.group("proto")
        interfaces[m.group("name")] = {
            "physical_status": phys_raw.lstrip("*"),
            "protocol_status": proto_raw.lstrip("*"),
            "admin_down": phys_raw.startswith("*") or proto_raw.startswith("*"),
        }
    return {"interfaces": interfaces}


# -------------------------------------------------------
# Getters (Tier-1: no connect/disconnect)
# -------------------------------------------------------

def get_cpu_usage(client) -> dict:
    """Runs: display cpu-usage. — no connect/disconnect."""
    command = "display cpu-usage"
    debug_log(client, "send_command: %s", command)
    output = client.conn.send_command(command)
    debug_log(client, "send_command response: %s", output)
    _check_cli_output(command, output)
    return _parse_cpu_usage(output)


def get_memory(client) -> dict:
    """Runs: display memory-usage. — no connect/disconnect."""
    command = "display memory-usage"
    debug_log(client, "send_command: %s", command)
    output = client.conn.send_command(command)
    debug_log(client, "send_command response: %s", output)
    _check_cli_output(command, output)
    return _parse_memory(output)


def get_alarm_active(client) -> dict:
    """
    Runs: display alarm active. — no connect/disconnect.

    expect_content=False: "no active alarms" is a legitimately terse/empty
    device response, not a CLI error.
    """
    command = "display alarm active"
    debug_log(client, "send_command: %s", command)
    output = client.conn.send_command(command)
    debug_log(client, "send_command response: %s", output)
    _check_cli_output(command, output, expect_content=False)
    return _parse_alarm_active(output)


def get_interface_brief(client) -> dict:
    """Runs: display interface brief. — no connect/disconnect."""
    command = "display interface brief"
    debug_log(client, "send_command: %s", command)
    output = client.conn.send_command(command)
    debug_log(client, "send_command response: %s", output)
    _check_cli_output(command, output)
    return _parse_interface_brief(output)


def collect_health_snapshot(client) -> dict:
    """
    Run all four health getters and return a unified snapshot.

    Returns {"cpu_usage_percent", "memory_usage_percent", "alarms", "interfaces"}.

    - no connect/disconnect
    """
    snapshot = {}
    snapshot.update(get_cpu_usage(client))
    snapshot.update(get_memory(client))
    snapshot.update(get_alarm_active(client))
    snapshot.update(get_interface_brief(client))
    return snapshot


# -------------------------------------------------------
# Policy: threshold evaluation, abort/warn
# -------------------------------------------------------

def evaluate_health(
    snapshot: dict,
    *,
    cpu_threshold_percent: float,
    memory_threshold_percent: float,
    max_unexpected_down_interfaces: int,
) -> dict:
    """
    Pure evaluation against configured thresholds — no device I/O.

    Interfaces with admin_down=True (administratively shut down, VRP's "*down")
    are excluded from the down-interface count entirely — they're an
    intentional operator choice, not a fault, so no amount of them blocks
    the upgrade regardless of max_unexpected_down_interfaces.

    Returns {"violations": [str, ...], "passed": bool}.
    """
    violations = []

    if snapshot["cpu_usage_percent"] > cpu_threshold_percent:
        violations.append(
            f"CPU usage {snapshot['cpu_usage_percent']}% exceeds threshold "
            f"{cpu_threshold_percent}%"
        )

    if snapshot["memory_usage_percent"] > memory_threshold_percent:
        violations.append(
            f"Memory usage {snapshot['memory_usage_percent']}% exceeds "
            f"threshold {memory_threshold_percent}%"
        )

    critical_alarms = [
        a for a in snapshot["alarms"] if a["severity"] in _ALARM_SEVERITIES
    ]
    if critical_alarms:
        names = ", ".join(a["name"] for a in critical_alarms)
        violations.append(f"Critical/major active alarms present: {names}")

    down_count = sum(
        1 for iface in snapshot["interfaces"].values()
        if not iface.get("admin_down", False)
        and (iface["physical_status"] != "up" or iface["protocol_status"] != "up")
    )
    if down_count > max_unexpected_down_interfaces:
        violations.append(
            f"{down_count} interface(s) down, exceeds allowed "
            f"{max_unexpected_down_interfaces}"
        )

    return {"violations": violations, "passed": not violations}


_ROUTE_COUNT_RE = re.compile(r'Routes\s*:\s*(\d+)')
_DEFAULT_ROUTE_RE = re.compile(r'^\s*0\.0\.0\.0/0\s', re.MULTILINE)


def _parse_ip_routing_table(output: str) -> dict:
    """
    Parse 'display ip routing-table' output.

    Returns {"route_count": int, "has_default_route": bool}. Minimal parse —
    post-reboot validation only needs to prove routing was restored, not
    full table introspection.
    """
    m = _ROUTE_COUNT_RE.search(output)
    if not m:
        raise ValueError(
            f"Could not parse route count from 'display ip routing-table' "
            f"output: {output!r}"
        )
    return {
        "route_count": int(m.group(1)),
        "has_default_route": bool(_DEFAULT_ROUTE_RE.search(output)),
    }


def get_ip_routing_table(client) -> dict:
    """Runs: display ip routing-table. — no connect/disconnect."""
    command = "display ip routing-table"
    debug_log(client, "send_command: %s", command)
    output = client.conn.send_command(command)
    debug_log(client, "send_command response: %s", output)
    _check_cli_output(command, output)
    return _parse_ip_routing_table(output)


# -------------------------------------------------------
# Post-reboot baseline comparisons (Faza 11)
# -------------------------------------------------------

def compare_interfaces_to_baseline(baseline: dict, current: dict) -> dict:
    """
    Compare current interface status against the pre-upgrade baseline.

    A "new failure" is an interface that was up (both physical and
    protocol) in the baseline but is no longer up (or is missing) in
    current. Interfaces present only in current are ignored (informational,
    not a failure — e.g. a newly-detected interface after upgrade).

    Returns {"new_failures": [name, ...], "passed": bool}.
    """
    baseline_interfaces = baseline.get("interfaces", {})
    current_interfaces = current.get("interfaces", {})

    new_failures = []
    for name, status in baseline_interfaces.items():
        was_up = status["physical_status"] == "up" and status["protocol_status"] == "up"
        if not was_up:
            continue

        current_status = current_interfaces.get(name)
        is_up = (
            current_status is not None
            and current_status["physical_status"] == "up"
            and current_status["protocol_status"] == "up"
        )
        if not is_up:
            new_failures.append(name)

    return {"new_failures": new_failures, "passed": not new_failures}


def compare_health_to_baseline(baseline: dict, current: dict) -> dict:
    """
    Compare current alarms against the pre-upgrade baseline.

    passed=False only when a NEW critical/major alarm appears that wasn't
    already present in the baseline — an alarm present in both is not
    "new". CPU/memory are not compared here (the spec defines no separate
    post-reboot threshold distinct from the pre-upgrade one).

    Returns {"new_alarms": [...], "passed": bool}.
    """
    baseline_alarms = {(a["severity"], a["name"]) for a in baseline.get("alarms", [])}
    new_alarms = [
        a for a in current.get("alarms", [])
        if a["severity"] in _ALARM_SEVERITIES
        and (a["severity"], a["name"]) not in baseline_alarms
    ]
    return {"new_alarms": new_alarms, "passed": not new_alarms}


def validate_routing_restored(routing_info: dict) -> dict:
    """
    Returns {"passed": bool} — True if the routing table has at least one
    route, taken as evidence that routing was restored post-reboot.
    """
    return {"passed": routing_info.get("route_count", 0) > 0}


def run_pre_upgrade_health_check(client, result, *, mode: str) -> dict:
    """
    Collect a baseline health snapshot and evaluate it against
    client.health_check_cpu_threshold / health_check_memory_threshold /
    health_check_max_down_interfaces.

    Always runs and always evaluates — never silently skipped, regardless
    of mode. mode="abort" (default): violations raise RuntimeError before
    any state change. mode="warn": violations are logged at warning level
    and appended to result.warnings; execution continues.

    Always stores result.metadata["pre_upgrade_baseline_health"] = snapshot
    (both modes, used later by post-reboot baseline comparisons).
    result.metadata["health_check_violations"] is only set when violations
    occurred.

    - no connect/disconnect
    """
    snapshot = collect_health_snapshot(client)
    evaluation = evaluate_health(
        snapshot,
        cpu_threshold_percent=client.health_check_cpu_threshold,
        memory_threshold_percent=client.health_check_memory_threshold,
        max_unexpected_down_interfaces=client.health_check_max_down_interfaces,
    )

    result.metadata["pre_upgrade_baseline_health"] = snapshot

    if not evaluation["passed"]:
        result.metadata["health_check_violations"] = evaluation["violations"]
        message = "Pre-upgrade health check failed: " + "; ".join(evaluation["violations"])

        if mode == "abort":
            raise RuntimeError(message)

        client.logger.warning(message)
        result.warnings.append(message)

    return evaluation
