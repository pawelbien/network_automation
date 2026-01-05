# network_automation/tests/mikrotik_routeros/test_upgrade_result.py

from network_automation.results import OperationResult

def test_upgrade_returns_result(monkeypatch, mikrotik_client):
    monkeypatch.setattr(
        mikrotik_client,
        "connect",
        lambda: None,
    )

    monkeypatch.setattr(
        mikrotik_client,
        "disconnect",
        lambda: None,
    )

    monkeypatch.setattr(
        "network_automation.platforms.mikrotik_routeros.upgrade.download_firmware",
        lambda client: None,
    )

    monkeypatch.setattr(
        "network_automation.platforms.mikrotik_routeros.upgrade.get_info",
        lambda client: ("x86_64", client.version),
    )

    monkeypatch.setattr(
        mikrotik_client,
        "reboot",
        lambda: None,
    )

    monkeypatch.setattr(
        mikrotik_client,
        "wait_for_reconnect",
        lambda: mikrotik_client.conn,
    )

    result = mikrotik_client.upgrade(return_result=True)

    assert isinstance(result, OperationResult)
    assert result.success is True
    assert result.operation == "upgrade"
