# network_automation/platforms/dcn_os/client.py

from network_automation.base_client import BaseClient
from network_automation.context import ExecutionContext
from network_automation.platforms.dcn_os.info import read_info, extract_discovery_facts


class DcnOS(BaseClient):
    """
    Platform client for DCN (DC YunKe Networks) switches running DCN OS.

    DCN OS has no Netmiko driver; its CLI is Cisco-like and works with
    Netmiko's cisco_ios driver (session starts in privileged mode, paging
    and width commands are accepted). The DCN OS SSH server only accepts
    ssh-rsa signatures for RSA keys, so key-based logins need
    disabled_algorithms={"pubkeys": ["rsa-sha2-512", "rsa-sha2-256"]}.
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
        reconnect_timeout=300,
        reconnect_delay=10,
        disabled_algorithms: dict | None = None,
        *,
        context: ExecutionContext | None = None,
    ):
        super().__init__(
            context=context,
            connect_retries=connect_retries,
            connect_delay=connect_delay,
        )

        self.device = {
            "device_type": "cisco_ios",
            "host": host,
            "username": username,
            "password": password,
            "key_file": key_file,
            "passphrase": passphrase,
            "use_keys": use_keys,
            "port": port,
            "disabled_algorithms": disabled_algorithms,
        }

        self.host = host
        self.username = username
        self.current_version = None

        self.reconnect_timeout = reconnect_timeout
        self.reconnect_delay = reconnect_delay

    # -------------------------------------------------------
    # System info
    # -------------------------------------------------------

    def get_info(self, *, return_result: bool = False):
        """Read device info and populate current_version on the client."""
        return read_info(self, return_result=return_result)

    def get_discovery_facts(self, *, return_result: bool = False):
        """
        Read serial number, software version, model and DevType ID for
        CMDB sync (Device Discovery). Reuses get_info()'s connect/disconnect
        lifecycle.
        """
        result = self.get_info(return_result=True)
        facts = extract_discovery_facts(result.metadata["units"])
        if return_result:
            result.metadata.update(facts)
            return result
        return facts
