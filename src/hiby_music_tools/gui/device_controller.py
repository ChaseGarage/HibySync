"""Device dashboard and shared background-job lifecycle."""
from pathlib import Path
from PySide6.QtCore import QObject, Property, QTimer, QUrl, Signal, Slot

from hiby_music_tools.core.interaction import Cancelled
from hiby_music_tools.device.detection import LinuxDevices
from hiby_music_tools.device.preview import compare
from hiby_music_tools.device.events import SyncProgress, SyncOperation
from hiby_music_tools.sync import human_bytes
from .quick_models import RecordModel
from .workers import Task
from .device_sync import DeviceSyncController

GROUPS = [('new', 'New music', 'Add'), ('updated', 'Updated files', 'Update'),
          ('remove', 'Files to remove', 'Remove'),
          ('conflicts', 'Conflicts / errors', 'Review')]


class DeviceController(QObject):
    changed = Signal()
    safeToClose = Signal()

    def __init__(self, source, browser, player, devices=None):
        super().__init__()
        self.source, self.browser, self.player = source, browser, player
        self.devices = devices or LinuxDevices()
        self.plan = self.target = self.task = None
        self.sync_controller = DeviceSyncController(self)
        self._targets = {}
        self._choices, self._rows, self._preview = (RecordModel(self) for _ in range(3))
        self._summary = self._empty_summary()
        self._expanded = set()
        self._status, self._message, self._phase = 'Disconnected', 'Refresh to find your HiBy R1.', ''
        self._progress = 0.0
        self._active = self._activated = self._closing = self._preview_open = False
        self._version = 0
        self._kind = ''
        self._root = source.library
        self._was_maintenance = player.maintenance
        self.poll = QTimer(self)
        self.poll.setInterval(5000)
        self.poll.timeout.connect(self.checkConnection)
        source.changed.connect(self._context_changed)
        source.libraryChanged.connect(self.markStale)
        player.changed.connect(self._maintenance_changed)
        browser.catalogChanged.connect(self._catalog_changed)
        self.changed.connect(self.sync_controller.changed)

    sync = Property(QObject, lambda self: self.sync_controller, constant=True)
    status = Property(str, lambda self: self._status, notify=changed)
    message = Property(str, lambda self: self._message, notify=changed)
    phase = Property(str, lambda self: self._phase, notify=changed)
    progress = Property(float, lambda self: self._progress, notify=changed)
    busy = Property(bool, lambda self: self.task is not None, notify=changed)
    comparing = Property(bool, lambda self: self.task is not None and self._kind in ('refresh', 'prepare'), notify=changed)
    connected = Property(bool, lambda self: self._status == 'Connected' and self.target is not None, notify=changed)
    summary = Property('QVariantMap', lambda self: self._summary, notify=changed)
    rows = Property(QObject, lambda self: self._rows, constant=True)
    previewRows = Property(QObject, lambda self: self._preview, constant=True)
    choices = Property(QObject, lambda self: self._choices, constant=True)
    deviceName = Property(str, lambda self: self.target.name if self.target else 'HiBy R1', notify=changed)
    identity = Property(str, lambda self: self.target.identity if self.target else '', notify=changed)
    musicRoot = Property(str, lambda self: self.target.music if self.target else '', notify=changed)
    transport = Property(str, lambda self: self.target.transport if self.target else '', notify=changed)
    localRoot = Property(str, lambda self: self.source.library, notify=changed)
    complete = Property(bool, lambda self: self.plan is not None and self.plan.complete, notify=changed)
    canPreview = Property(bool, lambda self: self.connected and self.plan is not None and self.plan.complete and self.plan.changes > 0 and not self.busy, notify=changed)
    previewOpen = Property(bool, lambda self: self._preview_open, notify=changed)
    storage = Property(str, lambda self: self._storage_text(), notify=changed)

    @staticmethod
    def _empty_summary():
        return dict(synced=0, transfer=0, remove=0, uncertain=0, conflicts=0, changes=0,
                    transferSize=human_bytes(0), local=0, remote=0)

    def _storage_text(self):
        if self.plan and self.plan.storage:
            return human_bytes(self.plan.storage['free']) + ' free of ' + human_bytes(self.plan.storage['total'])
        return 'Storage capacity unavailable for this transport.' if self.target else ''

    def _context_changed(self):
        if self._closing:
            self.poll.stop()
            return
        if self.source.library != self._root:
            self._root = self.source.library
            self.markStale()
        self._active = self.source.page == 'device'
        if not self._active:
            self.poll.stop()
        elif self.target and not self.busy and not self.poll.isActive():
            self.poll.start()

    def _maintenance_changed(self):
        maintenance = self.player.maintenance
        if maintenance and not self._was_maintenance:
            self.markStale()
        self._was_maintenance = maintenance

    def _catalog_changed(self):
        if not (self.busy and self._kind == "sync"):
            self.markStale()

    @Slot()
    def markStale(self):
        self.sync_controller.invalidate()
        if self.busy and self._kind == "sync":
            self.task.cancel()
            self._message = "The local library changed. Stopping sync safely; review again afterward."
            self.changed.emit()
            return
        self._version += 1
        if self.task:
            self.task.cancel()
        self.plan, self._preview_open = None, False
        self._summary = self._empty_summary()
        self._rows.replace([])
        self._preview.replace([])
        self._message = 'The local library changed. Refresh to compare again.'
        self.changed.emit()

    @Slot()
    def activate(self):
        if self._closing:
            return
        self._active = True
        if not self._activated:
            self._activated = True
            self.refresh(False)
        else:
            self.checkConnection()

    def _start(self, function, result, kind):
        self._kind = kind
        self.task = Task(function, self, report_cancelled_result=kind == "sync")
        if kind == "sync":
            self.task.operation = SyncOperation(self.task.report_progress)
        self.task.result.connect(result)
        self.task.failed.connect(self._failed)
        self.task.cancelled.connect(self._cancelled)
        self.task.progress.connect(self._progress_changed)
        self.task.finished.connect(self._finished)
        self.task.start()
        self.changed.emit()

    @Slot(bool)
    def refresh(self, verify=False):
        self._refresh(verify)

    def _refresh(self, verify=False, *, key='', manual=''):
        if self.busy or self._closing:
            return
        if self.source.busy or self.player.maintenance:
            self._message = 'Finish Import or file maintenance before comparing.'
            self.changed.emit()
            return
        selected = key or (self.target.key if self.target else '')
        root, database = self.source.library, self.browser.database
        self.sync_controller.dashboardView()
        self.sync_controller.invalidate()
        self.plan, self._preview_open = None, False
        self._summary = self._empty_summary()
        self._rows.replace([])
        self._preview.replace([])
        self._phase, self._message, self._progress = 'Detecting HiBy R1', '', -1
        self._version += 1
        version = self._version
        def work(op):
            detection = self.devices.detect(op)
            target = None
            if manual:
                target = self.devices.select(detection, manual)
                if target is None:
                    return detection, None, None, 'That folder is not /Music on a validated, connected R1. Ordinary local folders and unmounted paths are refused.'
            elif selected:
                target = next((t for t in detection.targets if t.key == selected), None)
            if target is None and not manual and len(detection.targets) == 1:
                target = detection.targets[0]
            if target is None:
                return detection, None, None, ''
            try:
                plan = compare(root, target, self.devices, verify=verify, database=database, operation=op)
                return detection, target, plan, ''
            except Cancelled:
                raise
            except (OSError, ValueError) as exc:
                return detection, target, None, str(exc)
        def result(value):
            if version != self._version or self._closing:
                return
            detection, target, plan, error = value
            self._targets = {t.key: t for t in detection.targets}
            self._choices.replace([dict(key=t.key, name=t.name, music=t.music, identity=t.identity, storage=Path(t.music).parent.name) for t in detection.targets])
            self.target, self.plan = target, plan
            self._status = detection.status if not error and (target is not None or not detection.targets) else 'Unavailable'
            self._message = error or detection.message
            if plan:
                self.applyPlan(plan)
            if target and self._active:
                self.poll.start()
            self.changed.emit()
        self._start(work, result, 'refresh')

    def applyPlan(self, plan):
        self.plan = plan
        groups = plan.groups
        self._summary = dict(synced=plan.synced, transfer=len(groups['new']) + len(groups['updated']),
                             remove=len(groups['remove']), uncertain=len(groups['uncertain']),
                             conflicts=len(groups['conflicts']), changes=plan.changes,
                             transferSize=human_bytes(plan.transfer_bytes), local=plan.local_count, remote=plan.remote_count)
        self._message = plan.blocked or (f"{len(groups['conflicts'])} comparison conflict(s). Resolve them before syncing." if groups['conflicts'] else
                        (('No changes found. ' if not plan.changes else '') + f"{len(groups['uncertain'])} file(s) match by size. Verify contents is optional.") if groups['uncertain'] else
                        'Your music is up to date.' if plan.synced and not plan.changes else
                        'Both music folders are empty.' if not plan.local_count and not plan.remote_count else '')
        self._render_rows()
        if plan.complete:
            self._preview.replace([row for kind, _, _ in GROUPS for row in groups[kind]])

    def _render_rows(self):
        rows = []
        if self.plan:
            for kind, label, action in GROUPS:
                items = self.plan.groups[kind]
                if not items:
                    continue
                rows.append(dict(header=True, kind=kind, title=label, action=action, count=len(items),
                                 sizeText=human_bytes(sum(r['size'] for r in items)), expanded=kind in self._expanded))
                if kind in self._expanded:
                    rows.extend(dict(row, header=False, action=action) for row in items)
        self._rows.replace(rows)

    @Slot(str)
    def toggleGroup(self, kind):
        if kind in self._expanded:
            self._expanded.remove(kind)
        else:
            self._expanded.add(kind)
        self._render_rows()

    @Slot(str)
    def choose(self, key):
        if key in self._targets:
            self._refresh(False, key=key)

    @Slot(QUrl)
    def chooseFolder(self, url):
        if not url.isLocalFile():
            self._message = 'Choose the GVFS/FUSE mounted /Music folder. An MTP URI is not a local filesystem path.'
            self.changed.emit()
            return
        self._refresh(False, manual=url.toLocalFile())

    @Slot()
    def showPreview(self):
        if self.canPreview:
            self._preview_open = True
            self.changed.emit()

    @Slot()
    def closePreview(self):
        self._preview_open = False
        self.changed.emit()

    @Slot()
    def checkConnection(self):
        if self.busy or self._closing or not self.target:
            return
        target, version = self.target, self._version
        def result(status):
            if version != self._version:
                return
            if status != 'Connected':
                self.plan, self.target, self._preview_open = None, None, False
                self._rows.replace([])
                self._preview.replace([])
                self._summary = self._empty_summary()
                self._status, self._message = status, 'R1 disconnected or mount unavailable. Reconnect and Refresh.'
                self.poll.stop()
            self.changed.emit()
        self._start(lambda op: self.devices.status(target), result, 'poll')

    def _progress_changed(self, event):
        if isinstance(event, SyncProgress):
            self.sync_controller.update(event)
            return
        self._phase = event.phase + (' · ' + event.current if event.current else '')
        self._progress = event.completed / max(1, event.total) if event.total is not None else -1
        self.changed.emit()

    def _failed(self, message):
        if self._kind == "sync":
            self.sync_controller.failed(message)
        self.plan, self._status, self._message = None, 'Unavailable', message
        self._preview_open = False
        self._summary = self._empty_summary()
        self._rows.replace([])
        self._preview.replace([])
        self.changed.emit()

    def _cancelled(self):
        if not self._closing and self._kind in ('refresh', 'prepare'):
            self._message = 'Comparison cancelled. No device files were changed.'
            self.changed.emit()

    def _finished(self):
        task, self.task = self.task, None
        task.deleteLater()
        self.changed.emit()
        if self._closing:
            self.safeToClose.emit()
        elif self._active and self.target and self._status == "Connected":
            self.poll.start()

    @Slot()
    def cancel(self):
        if self.task:
            if self._kind == 'sync':
                self.sync_controller._cancel_requested = True
                self.sync_controller.changed.emit()
            self.task.cancel()

    @Slot(result=bool)
    def requestClose(self):
        self._closing = True
        self.poll.stop()
        self.cancel()
        return self.task is None

    def shutdown(self):
        self.requestClose()
        if self.task:
            self.task.wait()
