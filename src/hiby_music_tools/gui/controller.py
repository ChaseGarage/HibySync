"""QML-facing session controller. Processing stays in the existing core services."""

from dataclasses import replace
from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import QObject, Property, QUrl, Signal, Slot

from hiby_music_tools.core.review import build_plan, edit_album
from hiby_music_tools.core.scan import scan_inbox
from hiby_music_tools.core.apple_art import search_apple
from hiby_music_tools.core.importing import execute_import
from hiby_music_tools.paths import library_dir
from .quick_models import ArtworkProvider, RecordModel
from .workers import Task


class ReviewController(QObject):
    changed = Signal()
    selectionChanged = Signal()
    scanConfirmationRequired = Signal()
    safeToClose = Signal()
    previewReady = Signal()
    importConfirmationRequired = Signal()
    libraryChanged = Signal()

    def __init__(self, inbox=None, library=None, parent=None):
        super().__init__(parent)
        self.session = None
        self.task = None
        self.closing = False
        self.provider = ArtworkProvider()
        self._albums = RecordModel(self)
        self._tracks = RecordModel(self)
        self._artwork = RecordModel(self)
        self._plan = RecordModel(self)
        self._results = RecordModel(self)
        self._preview_rows = None
        self._replacements = set()
        self._import_summary = {}
        self._art_mode = 'local'
        self._art_message = ''
        self._art_error = False
        self._inbox = str(inbox or Path.home() / 'Music/Nicotine')
        self._library = str(library or library_dir())
        self._page = 'import'
        self._filter = 'All'
        self.album_index = -1
        self.track_index = -1
        self.art_track_index = 0
        self._album = {}
        self._track = {}
        self._summary = dict(albums=0, tracks=0, ready=0, review=0, errors=0, skipped=0)
        self._message = ''
        self._message_kind = 'info'
        self._progress = 0.0
        self._operation_label = ''
        self._dirty = False

    albums = Property(QObject, lambda self: self._albums, constant=True)
    tracks = Property(QObject, lambda self: self._tracks, constant=True)
    artwork = Property(QObject, lambda self: self._artwork, constant=True)
    plan = Property(QObject, lambda self: self._plan, constant=True)
    results = Property(QObject, lambda self: self._results, constant=True)
    importSummary = Property('QVariantMap', lambda self: self._import_summary, notify=changed)
    artworkMode = Property(str, lambda self: self._art_mode, notify=changed)
    artworkMessage = Property(str, lambda self: self._art_message, notify=changed)
    artworkError = Property(bool, lambda self: self._art_error, notify=changed)
    artworkBusy = Property(bool, lambda self: self.task is not None and self._kind == 'artwork', notify=changed)
    canImport = Property(bool, lambda self: self._can_import(), notify=changed)
    replacementCount = Property(int, lambda self: len(self._replacements), notify=changed)
    inbox = Property(str, lambda self: self._inbox, notify=changed)
    library = Property(str, lambda self: self._library, notify=changed)
    page = Property(str, lambda self: self._page, notify=changed)
    filter = Property(str, lambda self: self._filter, notify=changed)
    busy = Property(bool, lambda self: self.task is not None, notify=changed)
    hasSession = Property(bool, lambda self: self.session is not None, notify=changed)
    summary = Property('QVariantMap', lambda self: self._summary, notify=changed)
    album = Property('QVariantMap', lambda self: self._album, notify=selectionChanged)
    track = Property('QVariantMap', lambda self: self._track, notify=selectionChanged)
    message = Property(str, lambda self: self._message, notify=changed)
    messageKind = Property(str, lambda self: self._message_kind, notify=changed)
    progress = Property(float, lambda self: self._progress, notify=changed)
    operationLabel = Property(str, lambda self: self._operation_label, notify=changed)
    dirty = Property(bool, lambda self: self._dirty, notify=changed)
    pathsMatch = Property(bool, lambda self: self._paths_match(), notify=changed)

    def _paths_match(self):
        return self.session is not None and (
            Path(self._inbox).expanduser().absolute() == self.session.source and
            Path(self._library).expanduser().absolute() == self.session.library)

    def _can_import(self):
        return bool(self._preview_rows and self._paths_match() and not self.task and
                    any(row.action not in ('Skip', 'Blocked') for row in self._preview_rows))

    def _invalidate_preview(self):
        self._preview_rows = None
        self._replacements.clear()
        self._plan.replace([])

    @Slot(str, result=str)
    def displayPath(self, path):
        home = str(Path.home())
        return '~' + path[len(home):] if path == home or path.startswith(home + '/') else path

    @Slot(str, result=QUrl)
    def folderUrl(self, path):
        return QUrl.fromLocalFile(str(Path(path).expanduser().absolute()))

    @Slot(QUrl, result=str)
    def folderPath(self, url):
        return url.toLocalFile()

    @Slot(str, str)
    def setPaths(self, inbox, library):
        if self.task:
            return
        if not inbox.strip() or not library.strip():
            self._message, self._message_kind = 'Choose both an incoming folder and a library folder.', 'error'
            self.changed.emit()
            return
        self._inbox, self._library = inbox.strip(), library.strip()
        self._invalidate_preview()
        if not self._paths_match() and self.session:
            self._message = 'Folders changed. Scan again to update this review.'
            self._message_kind = 'warning'
        self.changed.emit()

    @Slot(str)
    def navigate(self, page):
        if page in ('import', 'library', 'device', 'settings'):
            self._page = page
            self.changed.emit()

    @Slot(str)
    def setFilter(self, value):
        if value in ('All', 'Needs Review', 'Ready', 'Error'):
            self._filter = value
            self._refresh_albums()
            self.changed.emit()

    def _refresh_albums(self):
        albums = self.session.albums if self.session else []
        records = []
        summary = dict(albums=len(albums), tracks=sum(len(a.tracks) for a in albums),
                       ready=0, review=0, errors=0, skipped=0)
        for index, album in enumerate(albums):
            status = album.status
            summary[{'Ready': 'ready', 'Needs Review': 'review', 'Error': 'errors'}[status]] += 1
            summary['skipped'] += int(album.skip)
            if self._filter == 'All' or status == self._filter:
                records.append(dict(albumIndex=index, artist=album.artist, title=album.title,
                                    year=album.year, count=len(album.tracks), status=status,
                                    skipped=album.skip, image=self.provider.add(album.tracks[0].selected_art)))
        self._summary = summary
        self._albums.replace(records)

    def _current_album(self):
        if self.session and 0 <= self.album_index < len(self.session.albums):
            return self.session.albums[self.album_index]
        return None

    def _refresh_selection(self):
        album = self._current_album()
        self._album, self._track = {}, {}
        records = []
        if album:
            meta = album.tracks[0].proposed
            issues = sorted({issue for t in album.tracks for issue in ([t.error] if t.error else t.reasons)})
            self._album = dict(artist=album.artist, title=album.title, year=album.year,
                               albumArtist=meta.album_artist or meta.artist or '',
                               albumTitle=meta.album or '', releaseYear=meta.year or '',
                               status=album.status, count=len(album.tracks), skipped=album.skip,
                               issues='\n'.join(issues), image=self.provider.add(album.tracks[0].selected_art),
                               mixed=len({(t.proposed.album_artist, t.proposed.album, t.proposed.year)
                                          for t in album.tracks}) > 1)
            for index, track in enumerate(album.tracks):
                records.append(dict(trackIndex=index, title=track.proposed.title or track.path.stem,
                                    artist=track.proposed.track_artist or 'Missing artist',
                                    number=track.track_number or str(index + 1),
                                    status='Error' if track.error else 'Needs Review' if track.reasons else 'Ready',
                                    edited=track.proposed != track.original or
                                    track.track_number != track.original_track_number or
                                    track.disc_number != track.original_disc_number))
            if 0 <= self.track_index < len(album.tracks):
                track = album.tracks[self.track_index]
                original = track.original
                self._track = dict(index=self.track_index, title=track.proposed.title or '', artist=track.proposed.track_artist or '',
                                   number=track.track_number, disc=track.disc_number,
                                   filename=track.path.name, provenance=track.provenance,
                                   issues=track.error or '\n'.join(track.reasons),
                                   original=(f'Album artist: {original.album_artist or "—"}\n'
                                             f'Album: {original.album or "—"}\nYear: {original.year or "—"}\n'
                                             f'Artist: {original.track_artist or "—"}\n'
                                             f'Title: {original.title or "—"}\n'
                                             f'Track: {track.original_track_number or "—"}\n'
                                             f'Disc: {track.original_disc_number or "—"}'))
        self._tracks.replace(records)
        self.selectionChanged.emit()

    @Slot(int)
    def openAlbum(self, index):
        if self.task or not self.session or not 0 <= index < len(self.session.albums):
            return
        self.album_index, self.track_index = index, -1
        self._refresh_selection()
        self._page = 'review'
        self.changed.emit()

    @Slot(int)
    def selectTrack(self, index):
        album = self._current_album()
        if not self.task and album and 0 <= index < len(album.tracks):
            self.track_index = index
            self._refresh_selection()

    def _edited(self):
        self._dirty = True
        self._invalidate_preview()
        self._message = ''
        self._refresh_albums()
        self._refresh_selection()
        self.changed.emit()

    @Slot(str, str, str)
    def applyAlbum(self, artist, title, year):
        album = self._current_album()
        if album and not self.task:
            edit_album(album, artist.strip(), title.strip(), year.strip())
            self._edited()

    @Slot(str, str, str, str)
    def applyTrack(self, artist, title, number, disc):
        album = self._current_album()
        if album and not self.task and 0 <= self.track_index < len(album.tracks):
            track = album.tracks[self.track_index]
            artist = artist.strip() or None
            track.proposed = replace(track.proposed, track_artist=artist,
                                     artist=track.proposed.album_artist or artist,
                                     title=title.strip() or None)
            track.track_number, track.disc_number = number.strip(), disc.strip()
            track.provenance = 'Manual edit'
            self._edited()

    @Slot()
    def toggleSkip(self):
        album = self._current_album()
        if album and not self.task:
            album.skip = not album.skip
            self._edited()

    @Slot(int)
    def prepareArtwork(self, index):
        album = self._current_album()
        if not album or self.task:
            return
        self.art_track_index = max(0, index)
        if self.art_track_index >= len(album.tracks):
            return
        track = album.tracks[self.art_track_index]
        candidates = list(track.artwork)
        if track.selected_art and track.selected_art not in candidates:
            candidates.append(track.selected_art)
        self._candidates = candidates
        self._art_mode = 'apple' if track.selected_art and track.selected_art.origin == 'apple' else 'local'
        self._art_message = ''
        self._art_error = False
        self._publish_artwork()
        self.changed.emit()

    def _publish_artwork(self):
        track = self._current_album().tracks[self.art_track_index]
        self._artwork.replace([dict(candidateIndex=i, label=art.label, origin=art.origin,
                                   dimensions=f'{art.width} × {art.height}',
                                   image=self.provider.add(art), selected=art == track.selected_art)
                              for i, art in enumerate(self._candidates)
                              if (art.origin == 'apple') == (self._art_mode == 'apple')])

    @Slot(str)
    def setArtworkMode(self, mode):
        if mode in ('local', 'apple') and self._current_album():
            self._art_mode = mode
            self._publish_artwork()
            self.changed.emit()

    @Slot(str, str)
    def searchApple(self, artist, album):
        if self.task or not self._current_album():
            return
        self._art_mode = 'apple'
        self._art_message, self._art_error = 'Searching Apple artwork…', False
        self._start(lambda op: search_apple(artist, album, op), 'artwork')

    @Slot(int, bool)
    def applyArtwork(self, index, entire_album):
        album = self._current_album()
        candidates = getattr(self, '_candidates', [])
        if album and not self.task and 0 <= index < len(candidates):
            tracks = album.tracks if entire_album else [album.tracks[self.art_track_index]]
            for track in tracks:
                track.selected_art = candidates[index]
                track.artwork_approved = True
            self._edited()

    @Slot()
    def scan(self):
        if self.task:
            return
        if self._dirty:
            self.scanConfirmationRequired.emit()
        else:
            self.confirmScan()

    @Slot()
    def confirmScan(self):
        if not self.task:
            source, library = Path(self._inbox), Path(self._library)
            self._start(lambda op: scan_inbox(source, library, op), 'scan')

    @Slot()
    def preview(self):
        if self._paths_match() and not self.task:
            self._start(lambda op: build_plan(self.session, op), 'preview')

    @Slot(str, str)
    def setConflict(self, source, policy):
        if self.task or self._preview_rows is None or policy not in ('keep', 'replace'):
            return
        for index, row in enumerate(self._preview_rows):
            if str(row.source) == source and row.exists and row.action not in ('Skip', 'Blocked'):
                if policy == 'replace':
                    self._replacements.add(source)
                else:
                    self._replacements.discard(source)
                self._plan.update(index, {'policy': policy})
                self.changed.emit()
                break

    @Slot()
    def requestImport(self):
        if self._can_import():
            self.importConfirmationRequired.emit()

    @Slot()
    def confirmImport(self):
        if self._can_import():
            session, rows, replacements = deepcopy(self.session), list(self._preview_rows), set(self._replacements)
            self._start(lambda op: execute_import(session, rows, replacements, op, remove_sources=True), 'import')

    def _start(self, function, kind):
        self._kind = kind
        self._message = ''
        self._progress = -1
        self._operation_label = {'scan': 'Scanning incoming music', 'preview': 'Preparing import preview',
                                 'artwork': 'Searching Apple artwork', 'import': 'Preparing verified import'}[kind]
        self.task = Task(function, self, report_cancelled_result=kind == 'import')
        self.task.progress.connect(self._on_progress)
        self.task.result.connect(self._on_result)
        self.task.failed.connect(self._on_error)
        self.task.cancelled.connect(self._on_cancelled)
        self.task.finished.connect(self._on_finished)
        self.changed.emit()
        self.task.start()

    @Slot(object)
    def _on_progress(self, event):
        self._progress = event.completed / max(1, event.total) if event.total is not None else -1
        count = f' · {event.completed} / {event.total}' if event.total else ''
        current = f' · {Path(event.current).name}' if event.current else ''
        self._operation_label = event.phase + count + current
        if self._kind == 'artwork':
            self._art_message = self._operation_label
        self.changed.emit()

    @Slot(object)
    def _on_result(self, value):
        if self.closing:
            return
        if self._kind == 'scan':
            self.session = value
            self._inbox, self._library = str(value.source), str(value.library)
            self.album_index, self.track_index = -1, -1
            self._dirty = False
            self._invalidate_preview()
            self._page = 'import'
            self._message = '\n'.join(value.warnings)
            self._message_kind = 'warning'
            self._refresh_albums()
            self._refresh_selection()
        elif self._kind == 'preview':
            self._preview_rows = value
            self._replacements.clear()
            self._plan.replace([dict(source=str(row.source), filename=row.source.name,
                                     destination=str(row.destination), metadata=row.metadata_changes,
                                     artwork=row.artwork_change, warning=row.warning,
                                     action=('Conflict' if row.exists else 'Import') if row.action == 'Pending review' else row.action,
                                     conflict=row.exists and row.action not in ('Skip', 'Blocked'), policy='keep')
                                for row in value])
            self._page = 'preview'
            self.previewReady.emit()
        elif self._kind == 'artwork':
            track = self._current_album().tracks[self.art_track_index]
            for art in value:
                if art not in self._candidates:
                    self._candidates.append(art)
                if art not in track.artwork:
                    track.artwork.append(art)
            self._publish_artwork()
            self._art_message = (f'{len(value)} Apple cover(s) found. Choose one to apply.' if value else
                                 'No matching Apple covers found. Try another artist or album name.')
            self._art_error = False
        elif self._kind == 'import':
            if any(item.action in ('imported', 'replaced') for item in value.files):
                self.libraryChanged.emit()
            self._results.replace([dict(filename=result.source.name, source=str(result.source),
                                        destination=str(result.destination), action=result.action,
                                        error=result.error, sourceRemoved=result.source_removed,
                                        cleanupError=result.cleanup_error) for result in value.files])
            self._import_summary = dict(**value.counts, total=value.total, cancelled=value.cancelled,
                                        remaining=value.total - len(value.files), errors='\n'.join(value.errors),
                                        recovery=value.recovery, library=self._library, inbox=self._inbox,
                                        removed=value.removed, retained=value.total - value.removed,
                                        cleanupErrors=sum(bool(item.cleanup_error) for item in value.files))
            removed = {item.source for item in value.files if item.source_removed}
            for album in self.session.albums:
                album.tracks[:] = [track for track in album.tracks if track.path not in removed]
            self.session.albums[:] = [album for album in self.session.albums if album.tracks]
            self.album_index, self.track_index = -1, -1
            self._refresh_albums()
            self._refresh_selection()
            if not self.session.albums:
                self._dirty = False
            self._invalidate_preview()
            self._page = 'complete'
        self.changed.emit()

    @Slot(str)
    def _on_error(self, message):
        if self._kind == 'artwork':
            self._art_message, self._art_error = message, True
            self.changed.emit()
            return
        if self._kind == 'import':
            self._invalidate_preview()
        self._message, self._message_kind = message, 'error'
        self.changed.emit()

    @Slot()
    def _on_cancelled(self):
        if self._kind == 'artwork':
            self._art_message, self._art_error = 'Artwork search cancelled. Existing covers are unchanged.', False
            self.changed.emit()
            return
        self._message, self._message_kind = 'Cancelled. Your previous review is unchanged.', 'info'
        self.changed.emit()

    @Slot()
    def _on_finished(self):
        task, self.task = self.task, None
        task.deleteLater()
        self.changed.emit()
        if self.closing:
            self.safeToClose.emit()

    @Slot()
    def cancel(self):
        if self.task:
            self.task.cancel()
            self._operation_label = 'Cancelling after the current request…' if self._kind == 'artwork' else 'Cancelling after the current file…'
            if self._kind == 'artwork':
                self._art_message = self._operation_label
            self.changed.emit()

    @Slot(result=bool)
    def requestClose(self):
        if self.task:
            self.closing = True
            self.cancel()
            return False
        return True

    def shutdown(self):
        self.closing = True
        if self.task:
            self.task.cancel()
            self.task.wait()
