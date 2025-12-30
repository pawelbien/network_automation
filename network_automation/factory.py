# network_automation/factory.py

from network_automation.platforms.mikrotik_routeros.client import MikrotikRouterOS

_CLIENT_REGISTRY = {
    "mikrotik_routeros": MikrotikRouterOS,
    # "cisco_ios": CiscoIOS,
    # "juniper_junos": JuniperJunos,
}

def get_client(**params):
    # Extract out-of-band parameters (not related to platform/client API)
    logger = params.pop("logger", None)

    try:
        device_type = params.pop("device_type")
    except KeyError:
        raise ValueError("Missing required parameter: device_type")

    try:
        client_cls = _CLIENT_REGISTRY[device_type]
    except KeyError:
        raise ValueError(f"Unsupported device_type: {device_type}")

    return client_cls(
        logger=logger,
        **params,
    )
