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
from app.session import PREFIX, sweep_stale


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
    deadline = time.monotonic() + timeout
    while len(list(folder.iterdir())) != expected and time.monotonic() < deadline:
        time.sleep(0.1)
    return len(list(folder.iterdir()))


def test_remove_and_clear_delete_the_copies(client, made):
    path, _ = made["m7_control"]
    upload(client, path, path)
    folder = client.app.state.session.dir
    assert len(list(folder.iterdir())) == 2
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

    from app.session import Session

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


def test_stale_session_folders_are_swept(tmp_path):
    import os

    old, fresh = tmp_path / f"{PREFIX}old", tmp_path / f"{PREFIX}fresh"
    old.mkdir()
    fresh.mkdir()
    past = time.time() - 3 * 24 * 3600
    os.utime(old, (past, past))
    sweep_stale(tmp_path)
    assert not old.exists() and fresh.exists()


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
