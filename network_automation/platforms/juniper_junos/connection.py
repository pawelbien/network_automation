# network_automation/platforms/juniper_junos/connection.py

from netmiko.juniper.juniper import JuniperSSH


class JunosSSH(JuniperSSH):
    """
    Netmiko JuniperSSH with a session preparation that tolerates restricted
    login classes.

    Netmiko runs 'set cli complete-on-space off' unconditionally and waits
    for its echo. Junos hides commands a login class may not run and answers
    them with "syntax error, expecting <command>.", so the echo never matches
    and the connection fails with ReadTimeout. Here the command is
    best-effort: either reply ends the step. complete-on-space only expands
    abbreviated words, and this library always sends full command words.
    """

    def session_preparation(self) -> None:
        self._test_channel_read(pattern=r"[%>$#]")
        self.enter_cli_mode()

        self.set_terminal_width(command="set cli screen-width 511", pattern=r"Screen width set to")

        self.write_channel(self.normalize_cmd("set cli complete-on-space off"))
        self.read_until_pattern(pattern=r"Disabling complete-on-space|error", read_timeout=20)

        self.disable_paging(command="set cli screen-length 0", pattern=r"Screen length set to")
        self.set_base_prompt()
