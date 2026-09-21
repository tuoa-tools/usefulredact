"""Cleaning up when the console window is closed (Windows only).

Python's signal module gives Ctrl+C as SIGINT and Ctrl+Break as SIGBREAK, but not the
event Windows sends when the window's X is clicked, when the user logs off, or when the
machine shuts down. Those three arrive only through SetConsoleCtrlHandler. Without it a
closed window leaves the session's copies of the documents in the temporary folder until
the next start sweeps them away.

Windows ends the process a few seconds after the handler returns, so the handler has to
do its work at once and cannot wait on anything slow: see CONSOLE_CLOSE_WAIT_SECONDS in
session.py. Whatever could not be deleted in time is still covered by the sweep.
"""

from __future__ import annotations

import ctypes
import logging
import sys
from collections.abc import Callable

log = logging.getLogger(__name__)

CTRL_CLOSE_EVENT = 2  # the window's X
CTRL_LOGOFF_EVENT = 5
CTRL_SHUTDOWN_EVENT = 6
# Ctrl+C and Ctrl+Break are left out on purpose: the signal module already has them, and
# handling them here as well would run the clean-up twice.
ENDING_EVENTS = frozenset({CTRL_CLOSE_EVENT, CTRL_LOGOFF_EVENT, CTRL_SHUTDOWN_EVENT})

if sys.platform == "win32":
    from ctypes import wintypes

    _HANDLER_TYPE = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)
else:  # importing ctypes.wintypes raises anywhere else, so the module stays importable
    _HANDLER_TYPE = None

# Windows keeps the address, not the object: a collected callback is a call into freed
# memory, so every installed handler is held here for the life of the process.
_installed: list = []


def make_handler(cleanup: Callable[[], None]) -> Callable[[int], bool]:
    """The routine Windows calls, as plain Python so it can be tested on any platform.
    True means the event was handled; anything else is passed on to the next handler."""

    def handle(event: int) -> bool:
        if event not in ENDING_EVENTS:
            return False
        try:
            cleanup()
        except Exception:  # noqa: BLE001 - a handler that raises leaves the copies behind
            log.exception("cleaning up after the console window was closed")
        return True

    return handle


def install(cleanup: Callable[[], None]) -> bool:
    """Ask Windows to call cleanup when the window is closed, the user logs off or the
    machine shuts down. False on any other platform, or if Windows refused."""
    if sys.platform != "win32" or _HANDLER_TYPE is None:
        return False
    handler = _HANDLER_TYPE(make_handler(cleanup))
    _installed.append(handler)
    if not ctypes.windll.kernel32.SetConsoleCtrlHandler(handler, True):
        _installed.remove(handler)
        log.debug("SetConsoleCtrlHandler refused; a closed window leaves the sweep to it")
        return False
    return True
