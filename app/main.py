"""UsefulRedact's local API: drop documents in, watch them being checked, look at each
finding on its page, export the report. The UI polls /api/session while anything is
being checked.

Everything stays on this machine. The server listens on 127.0.0.1 only, and in desktop
mode answers only requests that carry this launch's secret (see launcher.py; the model
is UsefulText's). Uploaded copies and results live for the session and are deleted when
the app stops; the only files written are the reports a person exports.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

import pymupdf
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps
from pydantic import BaseModel

from app.session import Doc, Session
from usefulredact import __version__, ner, ocr, report
from usefulredact.models import VERDICT_MEANING
from usefulredact.pipeline import IMAGE_EXTS, SUPPORTED_EXTS

COOKIE = "usefulredact_token"
HEADER = "x-usefulredact-token"
IDLE_SECONDS = 120.0  # no /api/health ping for this long, and nothing to do: exit
IDLE_CHECK_SECONDS = 15.0
PAGE_WIDTH_DEFAULT, PAGE_WIDTH_MAX = 1400, 2400

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.session = Session()
    app.state.token = os.environ.get("USEFULREDACT_TOKEN") or None
    app.state.desktop = os.environ.get("USEFULREDACT_DESKTOP") == "1"
    app.state.quit_requested = False
    app.state.last_ping = time.monotonic()
    if not hasattr(app.state, "on_quit"):
        app.state.on_quit = None
    if not hasattr(app.state, "idle_shutdown"):
        app.state.idle_shutdown = False
    idle = asyncio.create_task(_idle_watch(app)) if app.state.desktop else None
    try:
        yield
    finally:
        if idle is not None:
            idle.cancel()
        app.state.session.close()  # the copies and the results go with it


def idle_expired(state, now: float) -> bool:
    """The page pings /api/health every minute, so two minutes of silence means the tab
    is gone. Documents still being checked keep the server alive until they are done."""
    if not getattr(state, "desktop", False) or not getattr(state, "idle_shutdown", False):
        return False
    if state.session.busy:
        return False
    return now - getattr(state, "last_ping", now) >= IDLE_SECONDS


async def _idle_watch(app: FastAPI) -> None:
    while True:
        await asyncio.sleep(IDLE_CHECK_SECONDS)
        if idle_expired(app.state, time.monotonic()):
            log.info("no UI for %.0f s and nothing to do: exiting", IDLE_SECONDS)
            app.state.quit_requested = True
            if app.state.on_quit:
                app.state.on_quit()
            return


app = FastAPI(title="UsefulRedact", version=__version__, lifespan=lifespan)


@app.middleware("http")
async def require_launch_token(request: Request, call_next):
    """In desktop mode every /api call must carry this launch's secret (cookie or header)."""
    token = getattr(request.app.state, "token", None)
    path = request.url.path
    if token and path.startswith("/api/") and path != "/api/health":
        supplied = request.cookies.get(COOKIE) or request.headers.get(HEADER)
        if supplied != token:
            return JSONResponse(
                status_code=401,
                content={
                    "detail": "This tab isn't connected to the app - start UsefulRedact again."
                },
            )
    return await call_next(request)


_origins = os.environ.get(
    "USEFULREDACT_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _origins.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------- views
def _session(request: Request) -> Session:
    return request.app.state.session


def _doc(request: Request, doc_id: str) -> Doc:
    doc = _session(request).get(doc_id)
    if doc is None:
        raise HTTPException(404, "No such document in this session")
    return doc


def _summary(doc: Doc) -> dict:
    view = {
        "id": doc.id,
        "name": doc.name,
        "status": doc.status,
        "page_done": doc.page_done,
        "page_total": doc.page_total,
        "verdict": None,
        "meaning": None,
        "error": "",
        "pages": 0,
        "counts": {"recoverable": 0, "pi": 0, "context": 0, "low_confidence": 0},
    }
    if doc.result is not None:
        result = doc.result
        view |= {
            "verdict": result.verdict,
            "meaning": VERDICT_MEANING[result.verdict],
            "error": result.error,
            "pages": len(result.pages),
        }
        for finding in result.findings:
            view["counts"][finding.kind] = view["counts"].get(finding.kind, 0) + 1
    return view


def _session_view(request: Request) -> dict:
    session = _session(request)
    return {
        "watchlist": session.watchlist,
        "ignore": session.ignore,
        "checking": session.busy,
        "documents": [_summary(d) for d in session.ordered()],
    }


# ---------------------------------------------------------- launch, health, quit
@app.get("/launch")
async def launch(token: str, request: Request) -> RedirectResponse:
    """Where the launcher points the browser: remember the launch secret, then show the app."""
    if not request.app.state.token or token != request.app.state.token:
        raise HTTPException(403, "Wrong launch token")
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(COOKIE, token, httponly=True, samesite="strict")
    return response


@app.get("/api/health")
async def health(request: Request) -> dict:
    """Also the UI's keep-alive: the page calls this every minute (see idle_expired)."""
    state = request.app.state
    state.last_ping = time.monotonic()
    return {
        "status": "ok",
        "version": __version__,
        "desktop": bool(state.desktop),
        # null while the models are still loading (the worker thread loads them)
        "ocr": state.session.engines["ocr"],
        "ocr_error": ocr.import_error(),
        "ner": state.session.engines["ner"],
        "ner_error": ner.load_error(),
        "checking": state.session.busy,
        "quit_requested": bool(state.quit_requested),
    }


@app.post("/api/quit")
async def quit_app(request: Request) -> dict:
    state = request.app.state
    if not state.desktop:
        raise HTTPException(400, "Not running as the desktop app")
    state.quit_requested = True
    if state.on_quit:
        state.on_quit()
    return {"ok": True}


# ---------------------------------------------------------------------- session
@app.get("/api/session")
async def get_session(request: Request) -> dict:
    return _session_view(request)


class Lists(BaseModel):
    watchlist: str = ""
    ignore: str = ""


@app.put("/api/lists")
async def set_lists(lists: Lists, request: Request) -> dict:
    """Held in memory for this session only. Changing them checks every document again."""
    _session(request).set_lists(lists.watchlist, lists.ignore)
    return _session_view(request)


@app.post("/api/documents", status_code=201)
async def add_documents(
    request: Request, files: Annotated[list[UploadFile], File(description="PDF, PNG or JPG")]
) -> dict:
    session = _session(request)
    skipped = []
    for upload in files:
        name = Path(upload.filename or "document").name
        if Path(name).suffix.lower() not in SUPPORTED_EXTS:
            skipped.append(name)
            continue
        session.add(name, upload.file)
    return _session_view(request) | {"skipped": skipped}


@app.delete("/api/documents")
async def clear_documents(request: Request) -> dict:
    _session(request).clear()
    return _session_view(request)


@app.get("/api/documents/{doc_id}")
async def get_document(doc_id: str, request: Request) -> dict:
    doc = _doc(request, doc_id)
    view = _summary(doc)
    if doc.result is not None:
        view["page_list"] = [p.to_dict() for p in doc.result.pages]
        view["findings"] = [f.to_dict() | {"id": i} for i, f in enumerate(doc.result.findings)]
    return view


@app.delete("/api/documents/{doc_id}")
async def remove_document(doc_id: str, request: Request) -> dict:
    if not _session(request).remove(doc_id):
        raise HTTPException(404, "No such document in this session")
    return _session_view(request)


def _render_page(path: Path, number: int, width: int, annotations: bool) -> bytes:
    if path.suffix.lower() in IMAGE_EXTS:
        with Image.open(path) as opened:
            img = ImageOps.exif_transpose(opened).convert("RGB")
        if img.width > width:
            img = img.resize((width, round(img.height * width / img.width)), Image.LANCZOS)
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        return buffer.getvalue()
    with pymupdf.open(path) as pdf:
        if not 1 <= number <= pdf.page_count:
            raise HTTPException(404, "No such page")
        page = pdf[number - 1]
        zoom = width / page.rect.width
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False, annots=annotations)
        return pix.tobytes("png")


@app.get("/api/documents/{doc_id}/pages/{number}/image")
async def page_image(
    doc_id: str,
    number: int,
    request: Request,
    width: int = PAGE_WIDTH_DEFAULT,
    annotations: bool = True,
) -> Response:
    """The page as a picture. `annotations=false` draws a PDF page without its annotations,
    which is all it takes to see what an annotation was covering."""
    doc = _doc(request, doc_id)
    width = max(200, min(width, PAGE_WIDTH_MAX))
    png = await asyncio.to_thread(_render_page, doc.path, number, width, annotations)
    return Response(png, media_type="image/png", headers={"Cache-Control": "no-store"})


# ----------------------------------------------------------------------- export
@app.get("/api/export")
async def export(
    request: Request,
    kind: Literal["json", "findings", "documents"] = "json",
    doc_id: str | None = None,
) -> Response:
    """The report as a download: everything checked so far, or one document."""
    session = _session(request)
    docs = [_doc(request, doc_id)] if doc_id else session.ordered()
    results = [d.result for d in docs if d.result is not None]
    if not results:
        raise HTTPException(409, "Nothing has been checked yet")
    stamp = time.strftime("%Y%m%d-%H%M")
    if kind == "json":
        body, media, name = report.to_json(results), "application/json", f"report-{stamp}.json"
    elif kind == "findings":
        body, media, name = report.findings_csv(results), "text/csv", f"findings-{stamp}.csv"
    else:
        body, media, name = report.documents_csv(results), "text/csv", f"documents-{stamp}.csv"
    if media == "text/csv":
        body = "﻿" + body  # so Excel on Windows reads accented names correctly
    headers = {
        "Content-Disposition": f'attachment; filename="usefulredact-{name}"',
        "Cache-Control": "no-store",
    }
    return Response(body.encode("utf-8"), media_type=media, headers=headers)


# --------------------------------------------------------------------------- UI
_static = Path(__file__).parent / "static"
if _static.is_dir():
    app.mount("/", StaticFiles(directory=_static, html=True), name="ui")
else:

    @app.get("/", response_class=HTMLResponse)
    async def ui_not_built() -> str:
        return (
            "<h1>UsefulRedact</h1><p>The API is running, but the UI has not been built.</p>"
            "<pre>cd frontend\nnpm ci\nnpm run build</pre><p>Then start the app again.</p>"
        )
