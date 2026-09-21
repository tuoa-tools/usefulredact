#!/usr/bin/env python3
"""Drive a built (or installed) UsefulRedact end to end through its API:

    python scripts/smoke_bundle.py dist/UsefulRedact.app/Contents/MacOS/UsefulRedact
    python scripts/smoke_bundle.py dist/UsefulRedact/UsefulRedact
    python scripts/smoke_bundle.py build/windows/python/python.exe -m app.launcher
    python scripts/smoke_bundle.py .venv/bin/usefulredact-app

It makes two documents of its own (nothing real is involved): a PDF with a black box drawn
over live text, and a picture of a page with an email address and a phone number on it.
Then it starts the app in server-only mode and checks, inside the bundle:

  - the OCR engine and the name model both load (their files made it in);
  - the PDF comes back FAIL_RECOVERABLE with the text recovered from under the box;
  - the picture comes back PI_VISIBLE, which only OCR can find;
  - a page image and the JSON report can be fetched, and the UI is served;
  - the API refuses a call without the launch secret;
  - the copies sit in a session folder while it runs, and the folder is gone after Quit.

Non-zero exit on any failure.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

HEADER = "x-usefulredact-token"
SECRET_NAME = "Kylie Nguyen"  # invented, like everything in the documents made below
SECRET_EMAIL = "kylie.nguyen85@mailbox.example"
SECRET_PHONE = "0412 345 678"


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def call(port: int, token: str | None, method: str, path: str, body=None, content_type=None):
    headers = {HEADER: token} if token else {}
    if content_type:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=body, method=method, headers=headers
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read()
        is_json = r.headers.get("content-type", "").startswith("application/json")
    return json.loads(raw) if is_json else raw


def multipart(files: list[Path]) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts = []
    for f in files:
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="{f.name}"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n".encode()
            + f.read_bytes()
            + b"\r\n"
        )
    body = b"".join(parts) + f"--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


def write_documents(folder: Path) -> tuple[Path, Path]:
    import pymupdf

    lines = [
        "Harbourline Water  -  account notice",
        f"Dear {SECRET_NAME},",
        f"Email: {SECRET_EMAIL}",
        f"Phone: {SECRET_PHONE}",
        "Your account was reviewed on 2 June 2026. No action is needed.",
    ]
    boxed = pymupdf.open()
    page = boxed.new_page(width=595, height=842)
    for i, line in enumerate(lines):
        page.insert_text((72, 100 + 26 * i), line, fontsize=12)
    plain = pymupdf.open()  # the same page before anyone "redacted" it, to photograph
    plain.insert_pdf(boxed)
    for needle in (SECRET_NAME, SECRET_EMAIL, SECRET_PHONE):
        for rect in page.search_for(needle):
            page.draw_rect(rect + (-1, -1, 1, 1), color=(0, 0, 0), fill=(0, 0, 0))
    pdf_path, png_path = folder / "boxed.pdf", folder / "scan.png"
    boxed.save(pdf_path)
    plain[0].get_pixmap(dpi=200, alpha=False).save(png_path)
    return pdf_path, png_path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", nargs="+", help="the app's executable (and arguments)")
    ap.add_argument("--timeout", type=float, default=300.0, help="seconds to wait for the checks")
    args = ap.parse_args()

    failures: list[str] = []

    def check(ok: bool, what: str) -> None:
        print(("ok    " if ok else "FAIL  ") + what)
        if not ok:
            failures.append(what)

    with tempfile.TemporaryDirectory(prefix="usefulredact-smoke-") as tmp:
        docs = Path(tmp) / "docs"
        app_temp = Path(tmp) / "app-temp"  # where the app under test will keep its session
        docs.mkdir()
        app_temp.mkdir()
        pdf_path, png_path = write_documents(docs)
        port, token = free_port(), secrets.token_urlsafe(24)
        env = dict(os.environ, USEFULREDACT_TOKEN=token)
        env.update(TMPDIR=str(app_temp), TEMP=str(app_temp), TMP=str(app_temp))
        proc = subprocess.Popen([*args.command, "--no-browser", "--port", str(port)], env=env)

        health = None
        for _ in range(900):  # a cold bundle on a slow disk can take a while
            time.sleep(0.2)
            if proc.poll() is not None:
                break
            try:
                health = call(port, None, "GET", "/api/health")
                break
            except Exception:  # noqa: BLE001 - not listening yet
                pass
        if health is None:
            print(f"the app did not start (exit code {proc.poll()})", file=sys.stderr)
            proc.kill()
            return 1
        print(f"started: version {health['version']}, desktop={health['desktop']}")
        try:
            deadline = time.time() + args.timeout
            while time.time() < deadline and (health["ocr"] is None or health["ner"] is None):
                time.sleep(0.5)
                health = call(port, None, "GET", "/api/health")
            check(health["ocr"] is True, f"the OCR engine loads ({health.get('ocr_error')})")
            check(health["ner"] is True, f"the name model loads ({health.get('ner_error')})")

            try:
                call(port, None, "GET", "/api/session")
                check(False, "the API refuses a call without the launch secret")
            except urllib.error.HTTPError as exc:
                check(exc.code == 401, "the API refuses a call without the launch secret")
            page = call(port, token, "GET", "/")
            check(b"<title>UsefulRedact</title>" in page, "the UI is served from inside the bundle")

            body, content_type = multipart([pdf_path, png_path])
            call(port, token, "POST", "/api/documents", body, content_type)
            sessions = list(app_temp.glob("usefulredact-session-*"))
            check(len(sessions) == 1, "the copies are in a session folder while it runs")

            session = call(port, token, "GET", "/api/session")
            while time.time() < deadline and session["checking"]:
                time.sleep(1)
                session = call(port, token, "GET", "/api/session")
            verdicts = {d["name"]: d for d in session["documents"]}
            check(
                verdicts["boxed.pdf"]["verdict"] == "FAIL_RECOVERABLE",
                f"a box over live text is FAIL_RECOVERABLE ({verdicts['boxed.pdf']['verdict']})",
            )
            check(
                verdicts["scan.png"]["verdict"] == "PI_VISIBLE",
                f"PI in a picture is found by OCR ({verdicts['scan.png']['verdict']})",
            )
            detail = call(port, token, "GET", f"/api/documents/{verdicts['boxed.pdf']['id']}")
            recovered = " ".join(
                f["text"] for f in detail["findings"] if f["kind"] == "recoverable"
            )
            check(SECRET_EMAIL in recovered, "the text under the box is recovered and reported")
            check(
                any(f["holds"] for f in detail["findings"] if f["kind"] == "recoverable"),
                "and it says what kind of PI that text holds",
            )
            scan = call(port, token, "GET", f"/api/documents/{verdicts['scan.png']['id']}")
            by = {f["detector"] for f in scan["findings"] if f["kind"] == "pi"}
            check(
                {"email", "phone_au"} <= by,
                f"the picture's email and phone are found ({sorted(by)})",
            )
            check(bool(by & {"name_label", "ner_person"}), "and the name in it")
            image = call(
                port, token, "GET", f"/api/documents/{detail['id']}/pages/1/image?width=600"
            )
            check(image[:4] == b"\x89PNG", "a page image is rendered")
            report = call(port, token, "GET", "/api/export?kind=json")
            if not isinstance(report, dict):  # `call` parses JSON when it is served as JSON
                report = json.loads(report)
            check(len(report["documents"]) == 2, "the JSON report has both documents")
        except Exception as exc:  # noqa: BLE001 - report it as a failure, then still quit
            check(False, f"unexpected error: {exc!r}")
        finally:
            try:
                call(port, token, "POST", "/api/quit")
            except Exception as exc:  # noqa: BLE001
                check(False, f"quit: {exc!r}")
            for _ in range(700):
                if proc.poll() is not None:
                    break
                time.sleep(0.1)
            if proc.poll() is None:
                check(False, "the app exits after Quit")
                proc.kill()
            else:
                check(True, f"the app exits after Quit (exit code {proc.returncode})")
            left = list(app_temp.glob("usefulredact-session-*"))
            check(not left, "nothing is kept: the session folder is gone after Quit")
    print(f"\n{'FAILED: ' + str(len(failures)) if failures else 'all checks passed'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
