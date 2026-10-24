"""Qt sync presentation: explicit consent, measured events, persistent results."""
from pathlib import Path
from PySide6.QtCore import QObject, Property, Signal, Slot
from PySide6.QtGui import QGuiApplication
from hiby_music_tools.device.preview import compare
from hiby_music_tools.device.execution import execute
from hiby_music_tools.device.events import SyncProgress
from hiby_music_tools.device.transports import make_transport
from hiby_music_tools.sync import human_bytes
from .quick_models import RecordModel


class DeviceSyncController(QObject):
    changed = Signal()
    progressChanged = Signal()

    def __init__(self, dashboard):
        super().__init__(dashboard)
        self.dashboard = dashboard
        self.transport_factory = make_transport
        self.recovery_root = None
        self.pending = None
        self._confirmation = self._view = False
        self._cancel_requested = False
        self._state = 'idle'
        self._report = {}
        self._progress = dict(state='Preparing', relpath='', title='', detail='', filesDone=0, filesTotal=0,
                              bytesDone=0, bytesTotal=0, bytesText='0 B / 0 B', fileDone=None, fileTotal=None,
                              fileBytesText='', overallFraction=0., fileFraction=-1., speed='')
        self._activity, self._confirmation_rows = RecordModel(self), RecordModel(self)
        self._indices, self._metadata = {}, {}

    confirmationOpen = Property(bool, lambda self: self._confirmation, notify=changed)
    viewOpen = Property(bool, lambda self: self._view, notify=changed)
    running = Property(bool, lambda self: self.dashboard.busy and self.dashboard._kind == 'sync', notify=changed)
    canStart = Property(bool, lambda self: self.dashboard.canPreview and not self.dashboard.source.busy and not self.dashboard.player.maintenance, notify=changed)
    state = Property(str, lambda self: self._state, notify=changed)
    cancelRequested = Property(bool, lambda self: self._cancel_requested, notify=changed)
    progress = Property('QVariantMap', lambda self: self._progress, notify=progressChanged)
    report = Property('QVariantMap', lambda self: self._report, notify=changed)
    activity = Property(QObject, lambda self: self._activity, constant=True)
    confirmationRows = Property(QObject, lambda self: self._confirmation_rows, constant=True)

    @Slot()
    def request(self):
        d = self.dashboard
        if d.busy or d._closing or not d.connected or d.source.busy or d.player.maintenance:
            return
        self.invalidate()
        self._view = False
        d._preview_open = False
        d.poll.stop()
        d._phase, d._progress = 'Preparing sync plan', -1
        verify = bool(d.plan and d.plan.verified)
        root, database, target, version = d.source.library, d.browser.database, d.target, d._version
        def prepared(plan):
            if d._closing or version != d._version:
                return
            d.applyPlan(plan)
            if not plan.complete:
                d._message = plan.blocked or 'Comparison has conflicts. Resolve them before synchronizing.'
            elif not plan.changes:
                d._message = 'Your music is up to date.'
            else:
                self.pending = plan
                self._confirmation_rows.replace([r for k in ('new','updated','remove') for r in plan.groups[k]])
                self._confirmation = True
            d.changed.emit()
            self.changed.emit()
        d._start(lambda op: compare(root, target, d.devices, verify=verify, database=database, operation=op), prepared, 'prepare')

    @Slot()
    def invalidate(self):
        self.pending, self._confirmation = None, False
        self.changed.emit()

    @Slot(bool)
    def confirm(self, removals=False):
        d, plan = self.dashboard, self.pending
        if not plan or not self._confirmation or d.busy or d._closing:
            return
        if d.source.busy or d.player.maintenance or Path(d.source.library).expanduser().resolve() != Path(plan.source) or d.target != plan.target:
            self.invalidate()
            d._message = 'Library/device state changed. Refresh and review again.'
            d.changed.emit()
            return
        if plan.groups['remove'] and not removals:
            d._message = 'Confirm the listed permanent removals before starting sync.'
            d.changed.emit()
            return
        self._confirmation, self.pending, self._view, self._state = False, None, True, 'syncing'
        self._cancel_requested = False
        self._report = {}
        self._activity.replace([])
        self._indices = {}
        self._metadata = {r['relpath']: r for k in ('new','updated','remove') for r in plan.groups[k]}
        self._progress = dict(self._progress, state='Revalidating', relpath='', title='', detail='', filesDone=0,
                              filesTotal=plan.changes, bytesDone=0, bytesTotal=plan.transfer_bytes,
                              bytesText=human_bytes(0) + ' / ' + human_bytes(plan.transfer_bytes),
                              fileDone=None,fileTotal=None,fileBytesText='',overallFraction=0.,fileFraction=-1.,speed='')
        self.progressChanged.emit()
        d.poll.stop()
        d._start(lambda op: execute(plan, d.devices, confirmed_removals=removals, operation=op,
                                   recovery_root=self.recovery_root, transport_factory=self.transport_factory), self.done, 'sync')
        self.changed.emit()

    def update(self, event):
        row = self._metadata.get(event.relpath, {})
        file_fraction = event.file_bytes / max(1,event.file_total) if event.file_bytes is not None and event.file_total is not None else -1.
        self._progress = dict(state=event.state,relpath=event.relpath,title=row.get('title') or Path(event.relpath).name,
            detail=row.get('detail',''),filesDone=event.files_completed,filesTotal=event.files_total,
            bytesDone=event.bytes_transferred,bytesTotal=event.bytes_total,
            bytesText=human_bytes(event.bytes_transferred) + ' / ' + human_bytes(event.bytes_total),
            fileDone=event.file_bytes,fileTotal=event.file_total,
            fileBytesText=(human_bytes(event.file_bytes) + ' / ' + human_bytes(event.file_total)) if event.file_bytes is not None and event.file_total is not None else '',
            overallFraction=event.bytes_transferred / max(1,event.bytes_total),fileFraction=file_fraction,
            speed=(human_bytes(event.speed) + '/s') if event.speed is not None else '')
        if event.relpath:
            status = 'Completed' if event.state == 'Completed' else 'Failed' if event.state == 'Failed' else 'In Progress'
            item = dict(row,relpath=event.relpath,title=row.get('title') or Path(event.relpath).name,
                        status=status,error=event.error,operation=event.operation)
            index = self._indices.get(event.relpath)
            if index is None:
                self._indices[event.relpath] = len(self._activity.rows)
                self._activity.append(item)
            elif self._activity.rows[index]['status'] != status or event.error:
                self._activity.update(index,item)
        self.progressChanged.emit()

    def done(self, report):
        d = self.dashboard
        self._state = report.state
        self._report = dict(state=report.state, errors='\n'.join(report.errors), recovery=report.recovery,
                            new=sum(r['kind']=='new' and r['status']=='Completed' for r in report.files),
                            updated=sum(r['kind']=='updated' and r['status']=='Completed' for r in report.files),
                            removed=sum(r['kind']=='remove' and r['status']=='Completed' for r in report.files),
                            failures=sum(r['status']=='Failed' for r in report.files),
                            skipped=sum(r['status']=='Skipped' for r in report.files))
        self._activity.replace([dict(r,operation=r['kind']) for r in report.files])
        if report.final_plan is not None:
            d.applyPlan(report.final_plan)
        else:
            d.plan = None
        if report.state == 'disconnected':
            d._status = 'Disconnected'
        d._message = 'Your music is up to date.' if report.state == 'complete' else '\n'.join(report.errors)
        self.changed.emit()
        d.changed.emit()

    def failed(self, error):
        self._state = 'error'
        self._report = dict(state='error',errors=error,recovery='',new=0,updated=0,removed=0,failures=1,skipped=0)
        self.changed.emit()

    @Slot()
    def dashboardView(self):
        if not self.running:
            self._view = False
            self.changed.emit()

    @Slot()
    def refresh(self):
        if not self.running:
            self._view = False
            self.changed.emit()
            self.dashboard.refresh(True)

    @Slot()
    def copyLogPath(self):
        if self._report.get('recovery'):
            QGuiApplication.clipboard().setText(self._report['recovery'])
