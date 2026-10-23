"""Qt bridge for core operations; presentation stays on the UI thread."""

from PySide6.QtCore import QThread, Signal
import time

from hiby_music_tools.core.interaction import Cancelled, Operation


class Task(QThread):
    progress = Signal(object)
    result = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, function, parent=None, report_cancelled_result=False):
        super().__init__(parent)
        self.function = function
        self.report_cancelled_result = report_cancelled_result
        self.last_report = 0.0
        self.operation = Operation(self.report_progress)

    def report_progress(self, event):
        now = time.monotonic()
        if now - self.last_report > 0.05 or event.completed == event.total:
            self.progress.emit(event)
            self.last_report = now

    def run(self):
        try:
            value = self.function(self.operation)
            if not self.report_cancelled_result:
                self.operation.checkpoint()
            self.result.emit(value)
        except Cancelled:
            self.cancelled.emit()
        except Exception as exc:
            self.failed.emit(str(exc))

    def cancel(self):
        self.operation.cancelled.set()
