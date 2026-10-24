"""Thread-safe cancellation and structured, measured sync events."""
from contextlib import contextmanager
from dataclasses import dataclass
from threading import RLock
import hashlib
from hiby_music_tools.core.interaction import Operation


class Disconnected(OSError):
    pass


class SyncOperation(Operation):
    def __init__(self, report=None):
        super().__init__(report)
        self._lock, self._hooks, self._shield = RLock(), [], 0

    def cancel(self):
        self.cancelled.set()
        with self._lock:
            for hook in self._hooks:
                hook()  # Gio.Cancellable.cancel is explicitly thread-safe.

    def checkpoint(self):
        if not self._shield:
            super().checkpoint()

    @contextmanager
    def bind(self, hook):
        with self._lock:
            active = not self._shield
            if active:
                self._hooks.append(hook)
                if self.cancelled.is_set():
                    hook()
        try:
            yield
        finally:
            if active:
                with self._lock:
                    self._hooks.remove(hook)

    @contextmanager
    def publication(self, recover=False):
        """Finish or restore a replacement once publication starts; never pause."""
        if not recover:
            self.checkpoint()
        self._shield += 1
        try:
            yield
        finally:
            self._shield -= 1


@dataclass(frozen=True)
class SyncProgress:
    relpath: str
    operation: str
    state: str
    file_bytes: int | None
    file_total: int | None
    files_completed: int
    files_total: int
    bytes_transferred: int
    bytes_total: int
    error: str = ''
    speed: float | None = None

    @property
    def identifier(self):
        return hashlib.sha256(self.relpath.encode()).hexdigest() if self.relpath else ''

    @property
    def phase(self):
        return self.state

    @property
    def completed(self):
        return self.file_bytes

    @property
    def total(self):
        return self.file_total
