# network_automation/platforms/opnsense/exceptions.py

"""
Custom exceptions for the OPNsense platform.
"""


class OPNsenseShellError(RuntimeError):
    """
    Raised when entering the FreeBSD shell from OPNsense's numbered console
    menu (skip_menu=False) fails - e.g. the expected shell prompt is not
    observed after sending the menu option. Subclasses RuntimeError for
    consistency with the exception style used across other platforms
    (huawei_vrp's CLIError, DeviceBusyError, DowngradeRejectedError).
    """


class OPNsenseFirmwareError(RuntimeError):
    """
    Raised when a `configctl firmware` operation (check/update/upgrade)
    can't be completed or interpreted:

    - the backend is already busy (`running()` reports "busy") when
      update()/upgrade()/check_updates() is about to start one - OPNsense's
      own `flock -n` would reject a second concurrent run anyway, this
      just fails fast with a clear message instead of racing it;
    - the poll loop exceeds `firmware_poll_timeout` without `running()`
      reporting "ready";
    - the final log contains neither a `***DONE***` nor a `***REBOOT***`
      marker, so the outcome of the operation can't be determined.
    """
