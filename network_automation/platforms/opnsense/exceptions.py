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
