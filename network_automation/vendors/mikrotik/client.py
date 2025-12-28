import time
import logging
from netmiko import ConnectHandler, NetmikoTimeoutException, NetmikoAuthenticationException
from network_automation.vendors.mikrotik.info import get_info
from network_automation.vendors.mikrotik.backup import run_backup
from network_automation.vendors.mikrotik.upgrade import upgrade as upgrade_helper


class Mikrotik:

    def __init__(
        self,
        host,
        username,
        key_file,
        passphrase,
        firmware_version,
        repo_url="https://download.mikrotik.com/routeros",
        port=22,
        log_file="mikrotik_update.log",
        connect_retries=2,
        connect_delay=2,        
        reconnect_timeout=180,
        reconnect_delay=10

    ):

        self.device = {
            "device_type": "mikrotik_routeros",
            "host": host,
            "username": username,
            "use_keys": True,
            "key_file": key_file,
            "passphrase": passphrase,
            "port": port,
        }

        self.host = host
        self.username = username
        self.key_file = key_file
        self.passphrase = passphrase
        self.version = firmware_version
        self.repo_url = repo_url.rstrip("/")
        # Connection retry config
        self.connect_retries = connect_retries
        self.connect_delay = connect_delay
        # Reconnect after reboot config
        self.reconnect_timeout = reconnect_timeout
        self.reconnect_delay = reconnect_delay



        self.conn = None
        self.arch = None
        self.current_version = None
        self.firmware_file = None
        self.setup_logging(log_file)

    # -------------------------------------------------------
    # Logging
    # -------------------------------------------------------

    def setup_logging(self, log_file, level=logging.INFO):
        """Setup console and file logging without duplicating handlers."""
        self.logger = logging.getLogger(f"MikroTikUpdater-{self.host}")
        self.logger.setLevel(level)

        # Prevent duplicate handlers if called multiple times
        if self.logger.handlers:
            return

        fmt = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s",
            "%Y-%m-%d %H:%M:%S"
        )

        # Console handler
        ch = logging.StreamHandler()
        ch.setLevel(level)
        ch.setFormatter(fmt)
        self.logger.addHandler(ch)

        # File handler
        fh = logging.FileHandler(log_file)
        fh.setLevel(level)
        fh.setFormatter(fmt)
        self.logger.addHandler(fh)

    # -------------------------------------------------------
    # Connection handling
    # -------------------------------------------------------

    def connect(self):
        """Attempt SSH connection with retry logic."""
        attempt = 1

        while attempt <= self.connect_retries:
            self.logger.info(
                f"Connecting to {self.host} (attempt {attempt}/{self.connect_retries})..."
            )

            try:
                self.conn = ConnectHandler(**self.device)
                self.logger.info("Connected successfully.")
                return
            except NetmikoTimeoutException:
                self.logger.warning(
                    f"Connection timeout to {self.host}. Device may be offline."
                )
            except NetmikoAuthenticationException:
                self.logger.error(
                    f"Authentication failed for {self.host}. Check SSH key/passphrase."
                )
                raise
            except Exception as e:
                self.logger.error(f"Unexpected connection error: {e}")

            if attempt < self.connect_retries:
                self.logger.info(f"Retrying in {self.connect_delay} seconds...")
                time.sleep(self.connect_delay)

            attempt += 1

        raise NetmikoTimeoutException(
            f"Unable to connect to {self.host} after {self.connect_retries} attempts."
        )

    def disconnect(self):
        """Close SSH connection."""
        if self.conn:
            try:
                self.conn.disconnect()
            except:
                pass
            self.conn = None

    # -------------------------------------------------------
    # System info parsing
    # -------------------------------------------------------

    def get_info(self):
        """Read architecture and version using helper."""
        arch, version = get_info(self)
        self.arch = arch
        self.current_version = version

        self.logger.info(f"Architecture: {self.arch}")
        self.logger.info(f"Current version: {self.current_version}")

    # -------------------------------------------------------
    # Backup
    # -------------------------------------------------------

    def backup(self, name):
        """Run backup using helper."""
        return run_backup(self, name)


    # -------------------------------------------------------
    # Reboot & reconnect
    # -------------------------------------------------------

    def reboot(self):
        """Stable reboot for RouterOS 7.x (no hanging)."""
        self.logger.info("Rebooting device...")

        out = self.conn.send_command_timing("/system reboot")

        # Your environment: always "Reboot, yes? [y/N]:"
        if "[y/n" in out.lower():
            self.conn.send_command_timing("y")
        else:
            # Sometimes Netmiko captures only partial buffer, so check again
            time.sleep(0.3)
            out2 = self.conn.send_command_timing("")
            if "[y/n" in out2.lower():
                self.conn.send_command_timing("y")
            else:
                self.logger.warning("Reboot prompt not detected — sending 'y' anyway.")
                self.conn.send_command_timing("y")

        # Router closes SSH immediately afterward — that's expected.
        try:
            self.conn.disconnect()
        except:
            pass

        self.conn = None

    def wait_for_reconnect(self):
        """Wait until RouterOS is reachable via SSH and CLI is ready."""
        self.logger.info(f"Waiting for {self.host} to reconnect...")

        start = time.time()

        while True:
            if time.time() - start > self.reconnect_timeout:
                raise TimeoutError(
                    f"Device did not reconnect within {self.reconnect_timeout} seconds."
                )

            conn = None
            try:
                conn = ConnectHandler(**self.device)

                # Give RouterOS a moment to finish CLI init
                time.sleep(1.0)

                out = conn.send_command("/system resource print", delay_factor=2)

                if "version" in out.lower():
                    self.logger.info("Device fully online (SSH + CLI ready).")
                    return conn   # ← NIE zamykamy!

            except Exception:
                pass

            # Not ready yet → close and retry
            if conn:
                try:
                    conn.disconnect()
                except:
                    pass

            time.sleep(self.reconnect_delay)

    # -------------------------------------------------------
    # Final version check
    # -------------------------------------------------------

    def check_version(self):
        """Re-use get_info() logic to obtain version after reboot."""
        self.get_info()
        self.logger.info(f"Version after reboot: {self.current_version}")
        return self.current_version

    # -------------------------------------------------------
    # Main upgrade workflow
    # -------------------------------------------------------

    def upgrade(self):
        """Run firmware upgrade using helper."""
        return upgrade_helper(self)

