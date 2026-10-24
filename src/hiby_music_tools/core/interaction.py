"""Structured interaction boundary for long-running backend operations."""

from dataclasses import dataclass
from threading import Event
from typing import Callable


class Cancelled(Exception):
    """Operation cancelled at a safe boundary; callers report completed work."""


@dataclass(frozen=True)
class Progress:
    phase: str
    completed: int
    total: int | None
    current: str = ""


class Operation:
    """Frontends supply progress delivery and signal cancellation without input()."""

    def __init__(self, report: Callable[[Progress], None] | None = None):
        self.cancelled = Event()
        self.report = report or (lambda event: None)

    def cancel(self):
        self.cancelled.set()

    def checkpoint(self):
        if self.cancelled.is_set():
            raise Cancelled()

    def progress(self, phase, completed, total=None, current=""):
        self.checkpoint()
        self.report(Progress(phase, completed, total, current))
