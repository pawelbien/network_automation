# network_automation/factory.py

from network_automation.context import ExecutionContext
from network_automation.platforms.huawei_vrp.client import HuaweiVRP
from network_automation.platforms.mikrotik_routeros.client import MikrotikRouterOS

_PLATFORM_REGISTRY = {
    "huawei": HuaweiVRP,
    "mikrotik_routeros": MikrotikRouterOS,
    # "cisco_ios": CiscoIOS,
    # "juniper_junos": JuniperJunos,
}

def get_client(**params):
    """
    Create and return a platform client.

    Required parameter:
      device_type  — platform identifier: "mikrotik_routeros" or "huawei".

    Execution context (optional, mutually exclusive):
      context      — pre-built ExecutionContext instance; if provided, the
                     logger/device_name/job_id/metadata/dry_run params below
                     are ignored.
      logger       — custom logger; defaults to the standard Python logger.
      device_name  — label attached to log messages.
      job_id       — job identifier attached to log messages.
      metadata     — arbitrary dict stored on the context.
      dry_run      — when True the client skips destructive operations.

    All remaining keyword arguments are forwarded to the platform client
    constructor (host, username, password, …).
    """
    # -------------------------------------------------
    # ExecutionContext handling
    # -------------------------------------------------

    context = params.pop("context", None)

    if context is None:
        context = ExecutionContext(
            logger=params.pop("logger", None),
            device_name=params.pop("device_name", None),
            job_id=params.pop("job_id", None),
            metadata=params.pop("metadata", None),
            dry_run=params.pop("dry_run", False),
        )

    # -------------------------------------------------
    # Platform selection
    # -------------------------------------------------

    try:
        device_type = params.pop("device_type")
    except KeyError:
        raise ValueError("Missing required parameter: device_type")

    try:
        client_cls = _PLATFORM_REGISTRY[device_type]
    except KeyError:
        raise ValueError(f"Unsupported device_type: {device_type}")

    # -------------------------------------------------
    # Client creation
    # -------------------------------------------------

    return client_cls(
        context=context,
        **params,   # ← ONLY platform-specific params remain
    )
