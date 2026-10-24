"""Focused Library editors and background review/save/artwork operations."""

from pathlib import Path

from PySide6.QtCore import QObject, Property, Signal, Slot, QUrl, QTimer

from hiby_music_tools.core.artwork import preview
from hiby_music_tools.core.apple_art import search_apple
from hiby_music_tools.library.maintenance import (FIELDS, ALBUM_FIELDS, load_session,
    preview_session, execute, artwork_bytes)
from .editor_artwork import EditorArtworkProvider
from .quick_models import RecordModel, ArtworkProvider
from .workers import Task


class MetadataController(QObject):
    changed = Signal()
    selectionChanged = Signal()
    safeToClose = Signal()
    appleMessageChanged = Signal()

    def __init__(self, browser, player):
        super().__init__()
        self.browser, self.player = browser, player
        self.provider = ArtworkProvider()
        self.full_provider = EditorArtworkProvider()
        self._tracks, self._artwork, self._preview, self._results = [RecordModel(self) for _ in range(4)]
        self.session = self.plan = self.task = None
        self._open = self._writing = self._closing = False
        self._mode, self._scope = 'edit', 'track'
        self._index = 0
        self._reorganize = False
        self._artwork_start = False
        self._message = self._phase = self._full_image = ''
        self._error = False
        self._report = {}
        self._art = []
        self._progress = -1.0
        self._pending_save = None
        self._cancel_waiting = False
        self._editor_root = ''
        self._task_kind = ''
        self._apple_message = ''
        self.apple_timer = QTimer(self)
        self.apple_timer.setSingleShot(True)
        self.apple_timer.setInterval(3500)
        self.apple_timer.timeout.connect(lambda: self._apple_notice(''))
        player.filesReleased.connect(self._released)

    open = Property(bool, lambda self: self._open, notify=changed)
    busy = Property(bool, lambda self: self.task is not None or self._writing, notify=changed)
    writing = Property(bool, lambda self: self._writing, notify=changed)
    mode = Property(str, lambda self: self._mode, notify=changed)
    scope = Property(str, lambda self: self._scope, notify=changed)
    tracks = Property(QObject, lambda self: self._tracks, constant=True)
    artwork = Property(QObject, lambda self: self._artwork, constant=True)
    preview = Property(QObject, lambda self: self._preview, constant=True)
    results = Property(QObject, lambda self: self._results, constant=True)
    current = Property('QVariantMap', lambda self: self._current(), notify=selectionChanged)
    artist = Property(str, lambda self: self.session.artist if self.session else '', notify=changed)
    included = Property(int, lambda self: sum(d.included for d in self.session.drafts) if self.session else 0, notify=changed)
    reorganize = Property(bool, lambda self: self._reorganize, notify=changed)
    artworkStart = Property(bool, lambda self: self._artwork_start, notify=changed)
    message = Property(str, lambda self: self._message, notify=changed)
    error = Property(bool, lambda self: self._error, notify=changed)
    phase = Property(str, lambda self: self._phase, notify=changed)
    progress = Property(float, lambda self: self._progress, notify=changed)
    report = Property('QVariantMap', lambda self: self._report, notify=changed)
    fullImage = Property(str, lambda self: self._full_image, notify=changed)
    canSave = Property(bool, lambda self: self.plan is not None and any(r['action'] == 'save' for r in self.plan.rows), notify=changed)
    affected = Property(int, lambda self: sum(r['action'] == 'save' for r in self.plan.rows) if self.plan else 0, notify=changed)
    artworkBusy = Property(bool, lambda self: self.task is not None and self._task_kind == 'apple', notify=changed)
    appleMessage = Property(str, lambda self: self._apple_message, notify=appleMessageChanged)

    def _current(self):
        if not self.session:
            return {}
        draft = self.session.drafts[self._index]
        return dict(values=dict(draft.values), original=dict(draft.original),
                    path=str(draft.track.path), index=self._index, error=draft.error,
                    artwork=draft.artwork.label if draft.artwork else 'Keep existing artwork')

    def _start(self, function, result, *, writing=False, kind=''):
        if self.task or self._closing:
            return
        self._task_kind = kind
        if kind != 'apple':
            self._message, self._error = '', False
        task = Task(function, self, report_cancelled_result=writing)
        self.task = task
        task.result.connect(result)
        task.failed.connect(self._failed)
        task.progress.connect(self._on_progress)
        task.cancelled.connect(self._cancelled)
        task.finished.connect(self._finished)
        task.start()
        self.changed.emit()

    @Slot(str, str, bool)
    @Slot(str, str, bool, bool)
    def edit(self, scope, identifier, reorganize=False, artwork=False):
        if self.task or self._writing or self._closing:
            return
        if self.browser.indexing or self.browser.source_controller.busy or self.player.busy or self.player.maintenance:
            self._open = True
            self._notice('Wait for the current scan, import, or playback update to finish before editing.', True)
            return
        self.session = self.plan = None
        self._index, self._scope, self._mode = 0, scope, 'edit'
        self._artwork_start = artwork
        self._reorganize, self._open = reorganize, True
        self._tracks.replace([])
        self._artwork.replace([])
        self._art = []
        self.provider.images.clear()
        self._full_image = ''
        self._apple_notice('')
        root, database = self.browser.root, self.browser.database
        self._editor_root = root
        self._start(lambda op: load_session(root, database, scope, identifier, op), self._loaded)

    def _loaded(self, session):
        self.session = session
        self._rows()
        self._add_art(session.artwork)
        self.selectionChanged.emit()

    def _rows(self):
        self._tracks.replace([dict(index=i, title=d.values['title'] or d.track.path.name,
                                   included=d.included, current=i == self._index)
                              for i, d in enumerate(self.session.drafts)])
        self.changed.emit()

    @Slot(int)
    def select(self, index):
        if self.session and not self.busy and 0 <= index < len(self.session.drafts):
            self._index = index
            self._rows()
            self.selectionChanged.emit()

    @Slot(int)
    def toggleIncluded(self, index):
        if self.session and not self.busy:
            draft = self.session.drafts[index]
            draft.included = not draft.included
            self.plan = None
            self._rows()

    @Slot(str, bool)
    def setSelection(self, scope, included):
        if not self.session or self.busy or scope not in ('all', 'album'):
            return
        album_id = self.session.drafts[self._index].album_id
        for draft in self.session.drafts:
            if scope == 'all' or draft.album_id == album_id:
                draft.included = included
        self.plan = None
        self._rows()

    @Slot(str, str)
    def setField(self, key, value):
        if self.session and not self.busy and key in FIELDS:
            self.session.drafts[self._index].values[key] = value
            self.plan = None
            self.selectionChanged.emit()

    @Slot()
    def applyAlbum(self):
        if self.session and not self.busy:
            source = self.session.drafts[self._index].values
            for draft in self.session.drafts:
                if draft.included:
                    draft.values.update({key: source[key] for key in ALBUM_FIELDS})
            self.plan = None
            self._rows()
            self.selectionChanged.emit()
            self._notice('Album artist, album, year, and genre applied to selected tracks.')

    @Slot(str, bool, bool)
    def renameArtist(self, name, track_artist, album_artist):
        if not self.session or self.busy or not name.strip():
            return
        from hiby_music_tools.library.database import folded
        for draft in self.session.drafts:
            if draft.included:
                for field, enabled in (('track_artist', track_artist), ('album_artist', album_artist)):
                    if enabled and folded(draft.original[field]) == folded(self.session.artist):
                        draft.values[field] = name.strip()
        self.plan = None
        self._rows()
        self.selectionChanged.emit()
        self._notice('Artist correction is pending. Preview the affected files before saving.')

    @Slot(bool)
    def setReorganize(self, enabled):
        if not self.busy:
            self._reorganize = enabled
            self.plan = None
            self.changed.emit()

    @Slot()
    def buildPreview(self):
        if self.session and not self.busy:
            session = self.session  # The worker snapshots it while editing is disabled.
            reorganize = self._reorganize
            self._start(lambda op: preview_session(session, reorganize, op), self._previewed)

    def _previewed(self, plan):
        self.plan = plan
        self._preview.replace(plan.rows)
        self._mode = 'preview'
        self.changed.emit()

    @Slot()
    def back(self):
        if not self.busy:
            self._mode = 'edit'
            self.plan = None
            self.changed.emit()

    @Slot()
    def save(self):
        if self._closing or self.busy or not self.canSave or self.browser.indexing or self.browser.source_controller.busy:
            return
        if self._editor_root != self.browser.root:
            self._notice('The configured library changed. Reopen the editor before saving.', True)
            return
        self._pending_save = self.plan
        self._writing = True
        self._phase = 'Releasing playback files'
        self.changed.emit()
        paths = [row[key] for row in self.plan.rows if row['action'] == 'save'
                 for key in ('source', 'destination')]
        self.player.beginMaintenance(paths)

    def _released(self):
        if self._cancel_waiting:
            self._cancel_waiting = False
            self._writing = False
            self.player.finishMaintenance({})
            self._notice('Save cancelled. No files were changed.')
            return
        if self._pending_save is None:
            return
        plan, self._pending_save = self._pending_save, None
        self._start(lambda op: execute(plan, operation=op), self._saved, writing=True)

    def _saved(self, report):
        self.player.finishMaintenance(report.updates)
        self._writing = False
        self._report = dict(recovery=report.recovery, indexError=report.index_error, cancelled=report.cancelled,
                            saved=sum(f['status'] == 'saved' for f in report.files),
                            failed=sum(f['status'] == 'failed' for f in report.files),
                            skipped=sum(f['status'] == 'skipped' for f in report.files),
                            unprocessed=len(self.plan.rows) - len(report.files))
        self._results.replace(report.files)
        self._mode = 'results'
        if report.updates:
            first = next(iter(report.updates.values()))
            if self.browser.mode == 'album' and first.get('album_id'):
                self.browser.visitAlbum(first['album_id'])
            elif self._scope == 'artist':
                self.browser.setMode('artists')
            else:
                self.browser._reload()
        self.changed.emit()

    def _add_art(self, candidates):
        known = {(a.thumbnail, a.width, a.height) for a in self._art}
        for art in candidates:
            key = art.thumbnail, art.width, art.height
            if key not in known:
                known.add(key)
                self._art.append(art)
        self._artwork.replace([dict(index=i, label=a.label, resolution=f'{a.width} × {a.height}',
                                    origin=a.origin, image=self.provider.add(a).replace('image://artwork/', 'image://editor-artwork/')) for i, a in enumerate(self._art)])
        self.changed.emit()

    @Slot(str, str)
    def searchApple(self, artist, album):
        if not self.busy:
            self._apple_notice('')
            self._start(lambda op: search_apple(artist, album, op), self._apple_results, kind='apple')

    def _apple_results(self, candidates):
        if candidates:
            self._add_art(candidates)
        else:
            self._apple_notice('No matches found')

    def _apple_notice(self, message):
        self.apple_timer.stop()
        self._apple_message = message
        if message:
            self.apple_timer.start()
        self.appleMessageChanged.emit()

    @Slot(QUrl)
    def manualArtwork(self, url):
        if self.busy or not url.isLocalFile():
            return
        path = Path(url.toLocalFile())
        def read(op):
            if path.stat().st_size > 32 * 1024 * 1024:
                raise ValueError('Artwork exceeds 32 MiB')
            return [preview(path.read_bytes(), path.name, 'manual', path)]
        self._start(read, self._add_art)

    @Slot(int, bool, bool)
    def useArtwork(self, index, all_selected, optimize):
        if not self.session or self.busy or not 0 <= index < len(self._art):
            return
        for i, draft in enumerate(self.session.drafts):
            if (all_selected and draft.included) or (not all_selected and i == self._index):
                draft.artwork, draft.optimize = self._art[index], optimize
        self.plan = None
        self.selectionChanged.emit()
        self._notice('Artwork selection is pending until Save.')

    @Slot(int)
    def showFullArtwork(self, index):
        if not self.busy and 0 <= index < len(self._art):
            art = self._art[index]
            self._start(lambda op: artwork_bytes(art), self._full_ready)

    def _full_ready(self, data):
        self._full_image = self.full_provider.add(data)
        self.changed.emit()

    @Slot()
    def closeFullArtwork(self):
        self._full_image = ''
        self.changed.emit()

    @Slot()
    def keepArtwork(self):
        if self.session and not self.busy:
            self.session.drafts[self._index].artwork = None
            self.plan = None
            self.selectionChanged.emit()

    def _notice(self, message, error=False):
        self._message, self._error = message, error
        self.changed.emit()

    def _failed(self, error):
        if self._task_kind == 'apple':
            self._apple_notice('No matches found' if 'no covers could be downloaded' in error else 'Artwork search failed')
            return
        if self._writing:
            self.player.finishMaintenance({})
            self._writing = False
        self._notice(error, True)

    def _cancelled(self):
        if self._task_kind == 'apple':
            self._apple_notice('Search cancelled')
            return
        if self._writing:
            self.player.finishMaintenance({})
            self._writing = False
        self._notice('Cancelled. No further files were changed.')

    def _on_progress(self, event):
        self._phase = event.phase + (' · ' + event.current if event.current else '')
        self._progress = event.completed / max(1, event.total) if event.total is not None else -1
        self.changed.emit()

    def _finished(self):
        task, self.task = self.task, None
        task.deleteLater()
        self.changed.emit()
        if self._closing:
            self.safeToClose.emit()

    @Slot()
    def cancel(self):
        if self._pending_save is not None:
            self._pending_save = None
            self._cancel_waiting = True
            self._phase = 'Save cancelled; finishing playback release'
            self.changed.emit()
        if self.task:
            self.task.cancel()

    @Slot()
    def dismiss(self):
        if not self.busy:
            self._open = False
            self.session = self.plan = None
            self.changed.emit()

    @Slot(result=bool)
    def requestClose(self):
        self._closing = True
        if self._pending_save is not None or self._cancel_waiting:
            self._pending_save = None
            self._cancel_waiting = False
            self._writing = False
            self.player.finishMaintenance({})
        self.cancel()
        return self.task is None and self._pending_save is None

    def shutdown(self):
        self.requestClose()
        if self.task:
            self.task.wait()
