# network_automation/platforms/huawei_vrp/client.py

from network_automation.base_client import BaseClient
from network_automation.context import ExecutionContext
from network_automation.platforms.huawei_vrp.run import run as run_helper


class HuaweiVRP(BaseClient):
    """
    Platform client for Huawei VRP devices (Netmiko driver "huawei").
    """

    def __init__(
        self,
        host,
        username,
        password: str | None = None,
        key_file: str | None = None,
        passphrase: str | None = None,
        use_keys: bool = False,
        port=22,
        connect_retries=2,
        connect_delay=2,
        *,
        context: ExecutionContext | None = None,
    ):
        super().__init__(
            context=context,
            connect_retries=connect_retries,
            connect_delay=connect_delay,
        )

        self.device = {
            "device_type": "huawei",
            "host": host,
            "username": username,
            "password": password,
            "key_file": key_file,
            "passphrase": passphrase,
            "use_keys": use_keys,
            "port": port,
        }

        self.host = host
        self.username = username

    def run(self, commands, *, return_result: bool = False):
        return run_helper(
            self,
            commands,
            return_result=return_result,
        )
