"""One session's documents: temporary copies, a worker that checks them, the results.

Nothing here is meant to outlive the process. Dropped files are copied into a private
temporary folder so the checker can read them, and the folder is deleted when the app
stops: on quit, on Ctrl+C, on a termination signal, when the console window is closed
(see console_win.py), at interpreter exit. A process that is killed outright cannot
clean up after itself, so every start sweeps the folders of sessions whose owner is gone
(see _owner_is_gone). The watchlist and ignore list live in memory only.
"""

from __future__ import annotations

import atexit
import logging
import queue
import shutil
import sys
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
LOCK_NAME = ".lock"
UNLOCKED_GRACE_SECONDS = 60.0  # see _owner_is_gone
CLOSE_WAIT_SECONDS = 60.0  # a scanned page can take several seconds to finish
# Windows ends the process a few seconds after a console-close handler returns, so that
# road cannot afford the wait above: it takes what it can get and leaves the rest to the
# sweep at the next start.
CONSOLE_CLOSE_WAIT_SECONDS = 2.5


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


def _try_lock(handle) -> bool:
    """Take an exclusive lock on an open file without waiting. False if another process
    (or another handle in this one) holds it."""
    try:
        if sys.platform == "win32":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _owner_is_gone(folder: Path) -> bool:
    """A running session holds a lock on its folder's lock file for as long as it lives,
    and the operating system drops the lock when the process dies, however it dies. So a
    lock that can be taken means nobody is using the folder. (Asking whether a process id
    is alive is not an option: on Windows, os.kill(pid, 0) ends the process.)"""
    lock = folder / LOCK_NAME
    if not lock.exists():
        # A live session always has its lock file, so this is what is left of a clean-up
        # that was cut short. The grace is for the instant between a new session making
        # its folder and making its lock, when a second app starting must not take it.
        return time.time() - folder.stat().st_mtime > UNLOCKED_GRACE_SECONDS
    try:
        with open(lock, "r+b") as handle:
            return _try_lock(handle)
    except OSError:
        return False


def sweep_stale(root: Path | None = None) -> None:
    """Delete session folders left in the temp directory by a run that was killed or
    crashed before it could clean up. Runs at every start."""
    root = root or Path(tempfile.gettempdir())
    for folder in root.glob(f"{PREFIX}*"):
        try:
            if folder.is_dir() and _owner_is_gone(folder):
                shutil.rmtree(folder, ignore_errors=True)
        except OSError:
            pass


class Session:
    def __init__(self) -> None:
        sweep_stale()
        self.dir = Path(tempfile.mkdtemp(prefix=PREFIX))
        self._lock_file = open(self.dir / LOCK_NAME, "w+b")  # noqa: SIM115 - held for life
        self._lock_file.write(b"1")
        self._lock_file.flush()
        _try_lock(self._lock_file)
        atexit.register(self.close)  # an exit that skips the server's shutdown still cleans up
        self._closed = False
        self.docs: dict[str, Doc] = {}
        self.watchlist = ""
        self.ignore = ""
        self.engines: dict[str, bool | None] = {"ocr": None, "ner": None}  # None: still loading
        self._undeleted: set[Path] = set()  # copies that were in use when their removal was asked
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
        self._delete(doc.path)
        return True

    def _delete(self, path: Path) -> None:
        """Delete a copy now, or as soon as it can be. Windows will not delete a file
        that is open, and the worker may be reading this one: it is then deleted the
        moment the worker is done with it (see _work)."""
        try:
            path.unlink(missing_ok=True)
        except OSError:
            with self._lock:
                self._undeleted.add(path)

    def _delete_waiting(self) -> None:
        with self._lock:
            waiting, self._undeleted = self._undeleted, set()
        for path in waiting:
            self._delete(path)

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
            self._delete_waiting()  # the file is closed again: anything removed meanwhile can go
            result.path = doc.name  # reports name the file as the person knows it
            if (watchlist, ignore) != (self.watchlist, self.ignore):
                continue  # the lists changed meanwhile; this document is queued again
            doc.result, doc.status = result, "done"

    def close(self, wait: float = CLOSE_WAIT_SECONDS) -> None:
        """Stop the worker and delete every copy. The worker finishes the page it is on
        first, so the folder is not pulled from under an open file (Windows would refuse).

        `wait` is how long to give it. The console-close road passes a short one because
        Windows is about to end the process; a file the worker still holds then stays for
        the sweep, which is what the sweep is for."""
        if self._closed:
            return
        self._closed = True
        atexit.unregister(self.close)
        self.docs.clear()  # nothing further in the queue is worth checking
        self._queue.put(None)
        self._thread.join(timeout=wait)
        if self._thread.is_alive():
            # The worker still has a document open, which on Windows cannot be deleted, so
            # part of the folder is about to be left behind. Keep the lock file with it
            # (open, so it cannot be deleted either): the lock dies with the process, and
            # the next start then knows the folder at once for what it is.
            log.warning("a document was still being read; the next start deletes its copy")
        else:
            self._lock_file.close()  # releases the lock; Windows needs it closed to delete
        for _ in range(5):
            shutil.rmtree(self.dir, ignore_errors=True)
            if not self.dir.exists():
                return
            time.sleep(0.2)
        log.warning("the session folder could not be deleted now; the next start sweeps it")
