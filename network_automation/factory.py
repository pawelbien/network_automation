# network_automation/factory.py

from network_automation.context import ExecutionContext
from network_automation.platforms.mikrotik_routeros.client import MikrotikRouterOS

_PLATFORM_REGISTRY = {
    "mikrotik_routeros": MikrotikRouterOS,
    # "cisco_ios": CiscoIOS,
    # "juniper_junos": JuniperJunos,
}

def get_client(**params):
    # Execution context (preferred)
    context = params.pop("context", None)

    # Backward compatibility: logger without context
    if context is None:
        logger = params.pop("logger", None)
        context = ExecutionContext(logger=logger)

    try:
        device_type = params.pop("device_type")
    except KeyError:
        raise ValueError("Missing required parameter: device_type")

    try:
        client_cls = _PLATFORM_REGISTRY[device_type]
    except KeyError:
        raise ValueError(f"Unsupported device_type: {device_type}")

    return client_cls(
        context=context,
        **params,
    )