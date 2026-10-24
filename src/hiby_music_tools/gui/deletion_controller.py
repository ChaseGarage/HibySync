"""Permanent deletion confirmation and background execution; no implicit writes."""

from PySide6.QtCore import QObject, Property, QTimer, Signal, Slot

from hiby_music_tools.library.deletion import prepare, execute
from .quick_models import RecordModel
from .workers import Task


class DeletionController(QObject):
    changed = Signal()
    safeToClose = Signal()

    def __init__(self, browser, player, editor):
        super().__init__()
        self.browser, self.player, self.editor = browser, player, editor
        self.plan = self.task = None
        self._rows = RecordModel(self)
        self._open = self._waiting = self._closing = False
        self._state = 'confirm'
        self._message = self._phase = self._notice = ''
        self._requested_root = ''
        self._cancel_waiting = False
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(4000)
        self.timer.timeout.connect(self._clear_notice)
        player.filesReleased.connect(self._released)

    open = Property(bool, lambda self: self._open, notify=changed)
    busy = Property(bool, lambda self: self.task is not None or self._waiting, notify=changed)
    state = Property(str, lambda self: self._state, notify=changed)
    rows = Property(QObject, lambda self: self._rows, constant=True)
    label = Property(str, lambda self: self.plan.label if self.plan else '', notify=changed)
    scope = Property(str, lambda self: self.plan.scope if self.plan else 'track', notify=changed)
    count = Property(int, lambda self: len(self.plan.files) if self.plan else 0, notify=changed)
    canConfirm = Property(bool, lambda self: self.plan is not None and not self.busy and not any(r['error'] for r in self.plan.files), notify=changed)
    message = Property(str, lambda self: self._message, notify=changed)
    phase = Property(str, lambda self: self._phase, notify=changed)
    notice = Property(str, lambda self: self._notice, notify=changed)

    def _clear_notice(self):
        self._notice = ''
        self.changed.emit()

    def _start(self, function, result, *, writing=False):
        self.task = Task(function, self, report_cancelled_result=writing)
        self.task.result.connect(result)
        self.task.failed.connect(self._failed)
        self.task.cancelled.connect(lambda: self._failed('Deletion cancelled; no further files were removed.'))
        self.task.progress.connect(self._progress)
        self.task.finished.connect(self._finished)
        self.task.start()
        self.changed.emit()

    @Slot(str, str)
    def request(self, scope, identifier):
        if self.busy or self._closing:
            return
        self.plan = None
        self._message = ''
        self._rows.replace([])
        self._state, self._open = 'confirm', True
        if (self.browser.indexing or self.browser.source_controller.busy or self.player.busy
                or self.player.maintenance or self.editor.open):
            self._message = 'Finish the current task and close the editor before deleting files.'
            self.changed.emit()
            return
        self._requested_root = self.browser.root
        database = self.browser.database
        root = self._requested_root
        self._start(lambda op: prepare(root, database, scope, identifier, op), self._prepared)

    def _prepared(self, plan):
        self.plan = plan
        self._rows.replace([dict(path=r['path'], status=r['status'], error=r['error']) for r in plan.files])
        if any(r['error'] for r in plan.files):
            self._message = 'Some files changed or cannot be accessed. Refresh the Library before deleting.'
        self.changed.emit()

    @Slot()
    def confirm(self):
        if self._closing or not self.canConfirm:
            return
        if (self.browser.root != self._requested_root or self.browser.indexing
                or self.browser.source_controller.busy or self.player.busy or self.player.maintenance):
            self._message = 'Library state changed. Cancel and review the selection again.'
            self.changed.emit()
            return
        self._waiting = True
        self._state = 'deleting'
        self._phase = 'Releasing playback files'
        self.changed.emit()
        self.player.beginMaintenance()

    def _released(self):
        if not self._waiting:
            return
        self._waiting = False
        if self._cancel_waiting or self._closing:
            self._cancel_waiting = False
            self.player.finishDeletion(set())
            self._state = 'confirm'
            self.changed.emit()
            return
        plan = self.plan
        self._start(lambda op: execute(plan, op), self._done, writing=True)

    def _done(self, report):
        self.player.finishDeletion(report.removed)
        self._rows.replace([dict(path=r['path'], status=r['status'], error=r['error'] or r['warning']) for r in report.files])
        failed = sum(r['status'] == 'failed' for r in report.files)
        deleted = sum(r['status'] == 'deleted' for r in report.files)
        unprocessed = len(self.plan.files) - len(report.files)
        if report.removed:
            if self.browser.mode == 'album' and self.browser._album_id in report.missing_albums:
                self.browser.setMode('albums')
            else:
                self.browser._reload()
        warning = any(r['warning'] for r in report.files)
        if failed or report.cancelled or report.index_error or warning:
            self._state = 'results'
            self._message = f'{deleted} deleted · {failed} failed · {unprocessed} unprocessed'
            if report.index_error:
                self._message += '\nFiles removed, but the index update failed. Refresh the Library: ' + report.index_error
        else:
            self._open = False
            self._notice = f'{deleted} audio file(s) permanently deleted.' if deleted else 'Missing files removed from the Library index.'
            self.timer.start()
        self.changed.emit()

    def _failed(self, message):
        if self.player.maintenance and self._state == 'deleting':
            self.player.finishDeletion(set())
        self._waiting = False
        self._state, self._message = 'results', message
        self.changed.emit()

    def _progress(self, event):
        self._phase = event.phase + (f' · {event.completed}/{event.total}' if event.total else '')
        self.changed.emit()

    def _finished(self):
        task, self.task = self.task, None
        task.deleteLater()
        self.changed.emit()
        if self._closing:
            self.safeToClose.emit()

    @Slot()
    def dismiss(self):
        if not self.busy:
            self._open = False
            self.plan = None
            self.changed.emit()

    @Slot()
    def cancel(self):
        if self._waiting:
            self._cancel_waiting = True
        if self.task:
            self.task.cancel()

    @Slot(result=bool)
    def requestClose(self):
        self._closing = True
        if self._waiting:
            self._waiting = self._cancel_waiting = False
            self.player.finishDeletion(set())
        self.cancel()
        return self.task is None

    def shutdown(self):
        self.requestClose()
        if self.task:
            self.task.wait()
