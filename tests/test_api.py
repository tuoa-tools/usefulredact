"""The local API: upload, verdict, findings, page image, export, the launch token,
and that the session's temporary copies are deleted when the app stops."""

from __future__ import annotations

import csv
import io
import json
import time

import pytest
from fastapi.testclient import TestClient

from app import main
from app.session import LOCK_NAME, PREFIX, Session, sweep_stale


def wait_done(client: TestClient, timeout: float = 120.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        session = client.get("/api/session").json()
        if session["documents"] and session["checking"] == 0:
            return session
        time.sleep(0.2)
    raise AssertionError("documents were not checked in time")


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.delenv("USEFULREDACT_TOKEN", raising=False)
    monkeypatch.delenv("USEFULREDACT_DESKTOP", raising=False)
    with TestClient(main.app) as c:
        yield c


def upload(client: TestClient, *paths) -> dict:
    files = [("files", (p.name, p.read_bytes(), "application/octet-stream")) for p in paths]
    response = client.post("/api/documents", files=files)
    assert response.status_code == 201, response.text
    return response.json()


def test_upload_verdict_findings_image_and_export(client, made):
    failed, _ = made["m3_drawn_box"]
    clean, _ = made["m7_control"]
    upload(client, failed, clean)
    session = wait_done(client)
    by_name = {d["name"]: d for d in session["documents"]}
    assert by_name[failed.name]["verdict"] == "FAIL_RECOVERABLE"
    assert by_name[failed.name]["counts"]["recoverable"] > 0

    detail = client.get(f"/api/documents/{by_name[failed.name]['id']}").json()
    assert detail["page_list"][0]["width"] == 595.0
    finding = next(f for f in detail["findings"] if f["kind"] == "recoverable")
    assert finding["page"] == 1 and len(finding["bbox"]) == 4 and finding["boxes"]

    image = client.get(f"/api/documents/{detail['id']}/pages/1/image?width=600")
    assert image.status_code == 200 and image.content.startswith(b"\x89PNG")
    assert image.headers["cache-control"] == "no-store"
    assert client.get(f"/api/documents/{detail['id']}/pages/9/image").status_code == 404

    exported = client.get("/api/export?kind=json")
    assert "attachment" in exported.headers["content-disposition"]
    payload = json.loads(exported.content)
    assert {d["path"] for d in payload["documents"]} == {
        failed.name,
        clean.name,
    }  # names, not paths
    rows = list(
        csv.DictReader(io.StringIO(client.get("/api/export?kind=findings").text.lstrip("﻿")))
    )
    assert any(r["kind"] == "recoverable" for r in rows)
    one = client.get(f"/api/export?kind=documents&doc_id={detail['id']}").text
    assert failed.name in one and clean.name not in one


def test_unsupported_files_are_skipped_not_stored(client, tmp_path):
    note = tmp_path / "notes.txt"
    note.write_text("hello")
    assert upload(client, note)["skipped"] == ["notes.txt"]
    assert client.get("/api/session").json()["documents"] == []
    assert client.get("/api/export").status_code == 409


def test_lists_recheck_every_document(client, made):
    path, letter = made["m1_none"]
    upload(client, path)
    wait_done(client)
    person = next(i.value for i in letter.items if i.type == "name")
    session = client.put("/api/lists", json={"watchlist": person, "ignore": ""}).json()
    assert session["watchlist"] == person
    session = wait_done(client)
    detail = client.get(f"/api/documents/{session['documents'][0]['id']}").json()
    assert any(f["detector"] == "watchlist" for f in detail["findings"])


def copies(folder, expected: int, timeout: float = 30.0) -> int:
    """How many copies are in the session folder, once it has settled. A copy the worker
    is reading is deleted when the worker lets go of it, which on Windows is the only
    time it can be."""

    def count() -> int:
        return sum(1 for p in folder.iterdir() if p.name != LOCK_NAME)

    deadline = time.monotonic() + timeout
    while count() != expected and time.monotonic() < deadline:
        time.sleep(0.1)
    return count()


def test_remove_and_clear_delete_the_copies(client, made):
    path, _ = made["m7_control"]
    upload(client, path, path)
    folder = client.app.state.session.dir
    assert copies(folder, 2) == 2
    first = client.get("/api/session").json()["documents"][0]["id"]
    # straight away, while the worker may still have the file open
    assert client.delete(f"/api/documents/{first}").status_code == 200
    assert [d["id"] for d in client.get("/api/session").json()["documents"]] != [first]
    assert copies(folder, 1) == 1
    client.delete("/api/documents")
    assert copies(folder, 0) == 0
    assert client.delete(f"/api/documents/{first}").status_code == 404


def test_a_copy_in_use_is_deleted_when_it_is_released(tmp_path, monkeypatch):
    """What Windows does to an open file, made to happen anywhere."""
    from pathlib import Path

    session = Session()
    try:
        held = session.dir / "held.pdf"
        held.write_bytes(b"x")
        real_unlink, refusals = Path.unlink, [1]

        def unlink(self, missing_ok=False):
            if self == held and refusals:
                refusals.pop()
                raise PermissionError(32, "being used by another process")
            return real_unlink(self, missing_ok=missing_ok)

        monkeypatch.setattr(Path, "unlink", unlink)
        session._delete(held)
        assert held.exists() and held in session._undeleted  # refused: remembered
        session._delete_waiting()
        assert not held.exists() and not session._undeleted  # released: gone
    finally:
        session.close()


def test_session_folder_is_deleted_on_shutdown(made):
    with TestClient(main.app) as c:
        upload(c, made["m7_control"][0])
        folder = c.app.state.session.dir
        assert folder.is_dir() and folder.name.startswith(PREFIX)
    assert not folder.exists()


def test_a_killed_sessions_folder_is_swept_at_the_next_start(tmp_path, monkeypatch):
    """A process that is killed cannot clean up. Its lock dies with it, so the next
    start can tell its folder from that of a session still running."""
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    running = Session()
    try:
        (running.dir / "doc.pdf").write_bytes(b"x")
        killed = tmp_path / f"{PREFIX}killed"
        killed.mkdir()
        (killed / LOCK_NAME).write_bytes(b"1")  # a lock file nobody holds any more
        (killed / "doc.pdf").write_bytes(b"x")

        sweep_stale(tmp_path)
        assert not killed.exists()  # swept at once, however new it is
        assert (running.dir / "doc.pdf").exists()  # a live session is left alone
    finally:
        running.close()
    assert not running.dir.exists()


def test_a_folder_left_by_a_clean_up_cut_short_is_swept(tmp_path):
    """Windows ends a process a few seconds after its console is closed. A clean-up cut
    off part-way can leave a copy behind with no lock file beside it; that must not wait
    a day to be swept. Only a folder made this instant is spared, since a session that is
    just starting makes its folder a moment before its lock."""
    import os

    cut_short, starting = tmp_path / f"{PREFIX}cutshort", tmp_path / f"{PREFIX}starting"
    cut_short.mkdir()
    (cut_short / "doc.pdf").write_bytes(b"a copy of someone's document")
    starting.mkdir()
    past = time.time() - 5 * 60
    os.utime(cut_short, (past, past))
    sweep_stale(tmp_path)
    assert not cut_short.exists() and starting.exists()


def test_close_keeps_the_lock_beside_a_copy_it_could_not_delete(tmp_path, monkeypatch):
    """If the worker will not let go in time, whatever is left must still be recognisable
    to the next start: the lock file stays with it."""
    import threading

    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    session = Session()
    release = threading.Event()
    stuck = threading.Thread(target=release.wait, daemon=True)  # a worker mid-document
    stuck.start()
    real_worker, session._thread = session._thread, stuck
    try:
        session.close(wait=0.1)
        assert not session._lock_file.closed  # still held: it dies with the process
    finally:
        release.set()
        session._queue.put(None)
        real_worker.join(timeout=5)
        session._lock_file.close()


def test_the_page_and_the_server_agree_on_the_idle_limit():
    """The page pings to say the tab is open; the server stops after IDLE_SECONDS without
    one. The page's copy of that number lives in frontend/src/lib/keepAlive.ts."""
    import re
    from pathlib import Path

    source = (Path(__file__).parents[1] / "frontend/src/lib/keepAlive.ts").read_text("utf-8")
    page_ms = int(re.search(r"SERVER_IDLE_MS = ([\d_]+)", source).group(1).replace("_", ""))
    assert page_ms == main.IDLE_SECONDS * 1000


def test_desktop_mode_needs_the_launch_token(monkeypatch):
    monkeypatch.setenv("USEFULREDACT_TOKEN", "s3cret")
    monkeypatch.setenv("USEFULREDACT_DESKTOP", "1")
    with TestClient(main.app, follow_redirects=False) as c:
        assert c.get("/api/health").status_code == 200  # the keep-alive is open
        assert c.get("/api/session").status_code == 401
        assert c.get("/launch?token=wrong").status_code == 403
        launched = c.get("/launch?token=s3cret")
        assert launched.status_code == 303 and "httponly" in launched.headers["set-cookie"].lower()
        assert c.get("/api/session").status_code == 200  # the cookie is now held
        assert c.get("/api/session", headers={main.HEADER: "s3cret"}).status_code == 200


def test_idle_shutdown_waits_for_work(monkeypatch):
    class State:
        desktop, idle_shutdown, last_ping = True, True, 0.0

        class session:
            busy = 1

    assert not main.idle_expired(State, 1000.0)  # still checking
    State.session.busy = 0
    assert main.idle_expired(State, 1000.0)
    State.idle_shutdown = False
    assert not main.idle_expired(State, 1000.0)
