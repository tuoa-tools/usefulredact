"""Closing the console window: the routine Windows calls, and the short clean-up it has
time for.

The click itself cannot be tested from here - no console control event can be generated
for CTRL_CLOSE_EVENT, and on Windows 11 the window belongs to the terminal rather than to
the process - so what is tested is the routine Windows calls and what it does. The event
numbers are Microsoft's and do not vary, so these run on every platform.
"""

from __future__ import annotations

import sys
import time

import pytest

from app import console_win
from app.launcher import _clean_up
from app.session import CONSOLE_CLOSE_WAIT_SECONDS, Session


class FakeApp:
    """Stands in for the FastAPI app: the clean-up only looks at app.state.session."""

    def __init__(self, session=None):
        self.state = type("state", (), {})()
        if session is not None:
            self.state.session = session


def test_ending_events_are_handled():
    """The X, a log off and a shut down all mean the same thing: clean up now."""
    ran = []
    handle = console_win.make_handler(lambda: ran.append(True))

    for event in (
        console_win.CTRL_CLOSE_EVENT,
        console_win.CTRL_LOGOFF_EVENT,
        console_win.CTRL_SHUTDOWN_EVENT,
    ):
        assert handle(event) is True

    assert len(ran) == 3


def test_ctrl_c_and_break_are_left_to_the_signal_module():
    """They already have handlers there; claiming them here would clean up twice."""
    ran = []
    handle = console_win.make_handler(lambda: ran.append(True))

    assert handle(0) is False  # CTRL_C_EVENT
    assert handle(1) is False  # CTRL_BREAK_EVENT
    assert ran == []


def test_a_failing_clean_up_does_not_raise_into_windows():
    """A handler that raises would leave the copies behind and take the process with it."""

    def boom():
        raise OSError("the folder was busy")

    handle = console_win.make_handler(boom)
    assert handle(console_win.CTRL_CLOSE_EVENT) is True


def test_install_only_claims_to_work_on_windows():
    assert console_win.install(lambda: None) == (sys.platform == "win32")


def test_clean_up_deletes_the_session_folder(monkeypatch, tmp_path):
    """What the handler actually does: the copies of the documents go."""
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    session = Session()
    folder = session.dir
    (folder / "doc.pdf").write_bytes(b"a copy of someone's document")

    _clean_up(FakeApp(session))

    assert not folder.exists()


def test_clean_up_returns_within_the_few_seconds_windows_gives(monkeypatch, tmp_path):
    """Windows ends the process shortly after the handler returns, so this road cannot
    wait the full CLOSE_WAIT_SECONDS: it would be cut off part-way through a delete."""
    assert CONSOLE_CLOSE_WAIT_SECONDS <= 3.0

    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    session = Session()
    (session.dir / "doc.pdf").write_bytes(b"x")

    started = time.monotonic()
    _clean_up(FakeApp(session))
    assert time.monotonic() - started < 5.0


def test_clean_up_with_no_session_does_nothing():
    """The window can be closed before the server has finished starting."""
    _clean_up(FakeApp())  # no session on the state at all


@pytest.mark.skipif(sys.platform != "win32", reason="SetConsoleCtrlHandler is Windows only")
def test_windows_accepts_the_handler():
    assert console_win.install(lambda: None) is True
