# network_automation/tests/mikrotik_routeros/test_results.py

from network_automation.results import OperationResult

def test_operation_result_timing():
    result = OperationResult(success=True)

    result.mark_started()
    result.mark_finished()

    assert result.duration_seconds is not None
    assert result.duration_seconds >= 0
