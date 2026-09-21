"""Desktop entry point: start the server on a free localhost port and open the app in a
browser tab.

Security model for a local app (UsefulText's): the API only answers requests carrying
this launch's secret, delivered once via /launch?token=... which sets an HttpOnly
SameSite=Strict cookie. Other websites can't send that cookie, and CORS blocks them from
reading anything anyway. The server binds to 127.0.0.1, so nothing off this machine can
reach it at all.

Shutdown: there is no window of its own to close, so the server exits by itself once the
page has stopped pinging /api/health for two minutes and nothing is being checked. Ctrl+C,
a termination signal and /api/quit do the same. Closing the console the app was started
from, logging off and shutting down take a separate road (console_win.py), because Windows
sends console control events rather than signals and then ends the process within seconds.
Either way the session's temporary folder is deleted; a process killed outright leaves it
for the next start to sweep.

Nothing is logged to a file: a log that named documents would outlive the session.
"""

from __future__ import annotations

import argparse
import logging
import os
import secrets
import signal
import socket
import sys
import threading
import time
import webbrowser

from app import console_win

log = logging.getLogger(__name__)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def launch_url(port: int, token: str) -> str:
    return f"http://127.0.0.1:{port}/launch?token={token}"


def _clean_up(app) -> None:
    """Delete this session's copies of the documents, with only seconds to do it in."""
    from app.session import CONSOLE_CLOSE_WAIT_SECONDS  # imported late: --help stays quick

    session = getattr(app.state, "session", None)
    if session is not None:
        session.close(wait=CONSOLE_CLOSE_WAIT_SECONDS)


def wait_until_started(server, thread: threading.Thread, timeout: float = 30.0) -> bool:
    """True once uvicorn is accepting connections; False if it died or timed out."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if server.started:
            return True
        if not thread.is_alive():
            return False
        time.sleep(0.05)
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="usefulredact-app",
        description="UsefulRedact: check whether redaction holds. Runs on this machine only.",
    )
    parser.add_argument("--port", type=int, default=0, help="listen port (default: any free one)")
    parser.add_argument(
        "--no-browser", action="store_true", help="only run the server; open nothing"
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    port = args.port or free_port()
    token = secrets.token_urlsafe(32)
    os.environ["USEFULREDACT_TOKEN"] = token
    os.environ["USEFULREDACT_DESKTOP"] = "1"
    os.environ["USEFULREDACT_CORS_ORIGINS"] = f"http://127.0.0.1:{port}"

    import uvicorn

    from app.main import app  # after the environment is set

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_config=None, access_log=False)
    server = uvicorn.Server(config)

    def quit_all() -> None:
        server.should_exit = True

    app.state.on_quit = quit_all
    # uvicorn only installs signal handlers when it runs in the main thread, and here it
    # does not: without this, `kill` would end the process with the session folder
    # (the copies of the documents) still on disk.
    signal.signal(signal.SIGTERM, lambda *_: quit_all())
    if hasattr(signal, "SIGBREAK"):  # Ctrl+Break on Windows
        signal.signal(signal.SIGBREAK, lambda *_: quit_all())
    app.state.idle_shutdown = not args.no_browser  # a tab can be closed without telling us
    url = launch_url(port, token)

    thread = threading.Thread(target=server.run, name="usefulredact-server", daemon=True)
    thread.start()
    try:
        if not wait_until_started(server, thread):
            log.error("the server did not start")
            return 1
        # Closing the console window, logging off and shutting down never reach the
        # handlers above: Windows sends console control events, which the signal module
        # does not carry. Asking uvicorn to stop would be no use either, as the process
        # is ended a few seconds later, so the session is closed here and now.
        console_win.install(lambda: _clean_up(app))
        # flush: with the output piped or redirected, a buffered line would never show
        print(
            f"UsefulRedact {app.version} is running on this machine only.\nOpen: {url}",
            flush=True,
        )
        if not args.no_browser:
            webbrowser.open(url)
        while thread.is_alive():
            thread.join(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.should_exit = True
        thread.join(timeout=15)
        log.info("stopped; the session's temporary files are deleted")
    return 0


if __name__ == "__main__":
    sys.exit(main())
