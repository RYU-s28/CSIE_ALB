"""One coalescing worker for the non-authoritative Attendance copy."""
import logging
import threading


class MirrorWorker:
    def __init__(self, sync, retry_seconds=30):
        self.sync = sync
        self.retry_seconds = retry_seconds
        self._condition = threading.Condition()
        self._dirty = False
        self._stopping = False
        self._thread = None

    def request(self):
        with self._condition:
            if self._stopping:
                return
            self._dirty = True
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, name="attendance-mirror", daemon=True)
                self._thread.start()
            self._condition.notify_all()

    def _run(self):
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._dirty or self._stopping)
                if not self._dirty:
                    return
                self._dirty = False
            try:
                success = self.sync() is not False
            except Exception:
                logging.exception("Attendance mirror worker failed")
                success = False
            with self._condition:
                if not success and not self._stopping:
                    # Keep a retry pending, while allowing new writes to wake us.
                    self._condition.wait(timeout=self.retry_seconds)
                    self._dirty = True
                if self._stopping and not self._dirty:
                    return

    def close(self, timeout=5):
        with self._condition:
            self._stopping = True
            self._condition.notify_all()
            thread = self._thread
        if thread:
            thread.join(timeout=timeout)


_worker = None
_worker_lock = threading.Lock()


def request_mirror_sync():
    global _worker
    with _worker_lock:
        if _worker is None:
            from database.google_sheets import sync_attendance_mirror
            _worker = MirrorWorker(sync_attendance_mirror)
        _worker.request()


def close_mirror_worker():
    global _worker
    with _worker_lock:
        worker, _worker = _worker, None
    if worker:
        worker.close()
