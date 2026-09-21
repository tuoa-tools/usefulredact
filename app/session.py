"""One session's documents: temporary copies, a worker that checks them, the results.

Nothing here outlives the process. Dropped files are copied into a private temporary
folder so the checker can read them; the folder is deleted when the app stops (and a
folder left behind by a crash is swept on the next start). The watchlist and ignore
list live in memory only.
"""

from __future__ import annotations

import logging
import queue
import shutil
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from usefulredact import ner, ocr
from usefulredact.models import DocResult
from usefulredact.pipeline import SUPPORTED_EXTS, check_document

log = logging.getLogger(__name__)
PREFIX = "usefulredact-session-"
STALE_SECONDS = 24 * 3600


@dataclass
class Doc:
    id: str
    name: str  # the file's own name, for display and reports; never used as a path
    path: Path
    status: str = "queued"  # queued | checking | done
    page_done: int = 0
    page_total: int = 0
    result: DocResult | None = None
    added: float = field(default_factory=time.time)


def sweep_stale(root: Path | None = None) -> None:
    """Delete session folders a crashed run left in the temp directory."""
    root = root or Path(tempfile.gettempdir())
    now = time.time()
    for folder in root.glob(f"{PREFIX}*"):
        try:
            if folder.is_dir() and now - folder.stat().st_mtime > STALE_SECONDS:
                shutil.rmtree(folder, ignore_errors=True)
        except OSError:
            pass


class Session:
    def __init__(self) -> None:
        sweep_stale()
        self.dir = Path(tempfile.mkdtemp(prefix=PREFIX))
        self.docs: dict[str, Doc] = {}
        self.watchlist = ""
        self.ignore = ""
        self.engines: dict[str, bool | None] = {"ocr": None, "ner": None}  # None: still loading
        self._lock = threading.Lock()
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._thread = threading.Thread(target=self._work, name="usefulredact-worker", daemon=True)
        self._thread.start()

    # ---------------------------------------------------------------- documents
    def add(self, name: str, source) -> Doc:
        """Copy an upload into the session folder and queue it."""
        doc_id = uuid.uuid4().hex[:12]
        suffix = Path(name).suffix.lower()
        path = self.dir / f"{doc_id}{suffix if suffix in SUPPORTED_EXTS else '.bin'}"
        with open(path, "wb") as handle:
            shutil.copyfileobj(source, handle)
        doc = Doc(id=doc_id, name=Path(name).name or "document", path=path)
        with self._lock:
            self.docs[doc_id] = doc
        self._queue.put(doc_id)
        return doc

    def get(self, doc_id: str) -> Doc | None:
        return self.docs.get(doc_id)

    def ordered(self) -> list[Doc]:
        return sorted(self.docs.values(), key=lambda d: d.added)

    def remove(self, doc_id: str) -> bool:
        with self._lock:
            doc = self.docs.pop(doc_id, None)
        if doc is None:
            return False
        doc.path.unlink(missing_ok=True)
        return True

    def clear(self) -> None:
        for doc_id in list(self.docs):
            self.remove(doc_id)

    def set_lists(self, watchlist: str, ignore: str) -> None:
        """New lists mean every verdict may change: check everything again."""
        self.watchlist, self.ignore = watchlist, ignore
        with self._lock:
            for doc in self.docs.values():
                doc.status, doc.result, doc.page_done, doc.page_total = "queued", None, 0, 0
                self._queue.put(doc.id)

    @property
    def busy(self) -> int:
        return sum(1 for d in self.docs.values() if d.status != "done")

    # ------------------------------------------------------------------- worker
    def _work(self) -> None:
        # Load the models here, off the event loop, before the first document needs them.
        self.engines["ocr"] = ocr.available()
        self.engines["ner"] = ner.available()
        while True:
            doc_id = self._queue.get()
            if doc_id is None:
                return
            doc = self.docs.get(doc_id)
            if doc is None or doc.status == "done":
                continue
            doc.status = "checking"
            watchlist, ignore = self.watchlist, self.ignore

            def progress(done: int, total: int, doc: Doc = doc) -> None:
                doc.page_done, doc.page_total = done, total

            result = check_document(doc.path, watchlist=watchlist, ignore=ignore, progress=progress)
            result.path = doc.name  # reports name the file as the person knows it
            if (watchlist, ignore) != (self.watchlist, self.ignore):
                continue  # the lists changed meanwhile; this document is queued again
            doc.result, doc.status = result, "done"

    def close(self) -> None:
        self._queue.put(None)
        self._thread.join(timeout=5)
        shutil.rmtree(self.dir, ignore_errors=True)
