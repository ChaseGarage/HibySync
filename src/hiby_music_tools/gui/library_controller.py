"""Library presentation bridge. Indexing and queries have independent workers."""

from pathlib import Path

from PySide6.QtCore import QObject, Property, QTimer, Signal, Slot

from hiby_music_tools.library.database import index_path
from hiby_music_tools.library.indexer import refresh
from hiby_music_tools.library.queries import browse, PAGE_SIZE
from hiby_music_tools.library.navigation import track_target
from .library_models import LibraryModel, LibraryArtworkProvider
from .workers import Task


class LibraryController(QObject):
    changed = Signal()
    safeToClose = Signal()
    navigationRequested = Signal()

    def __init__(self, source_controller, database=None):
        super().__init__()
        self.source_controller = source_controller
        self.database = database or index_path()
        self.provider = LibraryArtworkProvider(self.database.parent / 'artwork')
        self._root = str(Path(source_controller.library).expanduser().absolute())
        self._model = LibraryModel(self)
        self._model.moreRequested.connect(self.loadMore)
        self._mode = 'albums'
        self._search = ''
        self._sort = 'title'
        self._descending = False
        self._artist_id = self._artist_name = self._album_id = ''
        self._album = {}
        self._summary = dict(tracks=0, albums=0, artists=0, errors=0, scanned=False)
        self._message = ''
        self._error = False
        self._progress = 0.0
        self._phase = ''
        self.index_task = self.query_task = None
        self._navigation_tasks = set()
        self._navigation_version = 0
        self._pending = None
        self._version = 0
        self._active_request = None
        self._activated = False
        self._stale = False
        self._closing = False
        self._return = ('albums', '', '')
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(180)
        self.timer.timeout.connect(self._reload)

    model = Property(QObject, lambda self: self._model, constant=True)
    root = Property(str, lambda self: self._root, notify=changed)
    mode = Property(str, lambda self: self._mode, notify=changed)
    search = Property(str, lambda self: self._search, notify=changed)
    sort = Property(str, lambda self: self._sort, notify=changed)
    descending = Property(bool, lambda self: self._descending, notify=changed)
    artistName = Property(str, lambda self: self._artist_name, notify=changed)
    artistId = Property(str, lambda self: self._artist_id, notify=changed)
    album = Property('QVariantMap', lambda self: self._album, notify=changed)
    summary = Property('QVariantMap', lambda self: self._summary, notify=changed)
    message = Property(str, lambda self: self._message, notify=changed)
    error = Property(bool, lambda self: self._error, notify=changed)
    indexing = Property(bool, lambda self: self.index_task is not None, notify=changed)
    queryBusy = Property(bool, lambda self: self.query_task is not None or self._pending is not None, notify=changed)
    progress = Property(float, lambda self: self._progress, notify=changed)
    phase = Property(str, lambda self: self._phase, notify=changed)

    @Slot()
    def syncRoot(self):
        root = str(Path(self.source_controller.library).expanduser().absolute())
        if root == self._root:
            return
        self._cancel_navigation()
        self._root = root
        self._artist_id = self._artist_name = self._album_id = ''
        self._mode, self._album = 'albums', {}
        self._summary = dict(tracks=0, albums=0, artists=0, errors=0, scanned=False)
        if self.index_task:
            self.index_task.cancel()
        self._reload() if self._activated else self._model.replace([])
        self.changed.emit()

    @Slot()
    def markChanged(self):
        self._stale = True
        self._message = 'New imports are ready to index.'
        self.changed.emit()

    @Slot()
    def activate(self):
        if not self._activated:
            self._activated = True
            self._reload()
        if self._stale and not self.index_task:
            self.refresh(False)

    @Slot(str)
    def setMode(self, mode):
        if mode not in ('albums', 'artists', 'songs'):
            return
        self._mode = mode
        self._artist_id = self._artist_name = self._album_id = ''
        self._album = {}
        self._reload()

    @Slot(str)
    def setSearch(self, text):
        if text != self._search:
            self._search = text
            self.timer.start()

    @Slot(str)
    def sortBy(self, key):
        if key not in ('title', 'artist', 'album', 'year', 'duration'):
            return
        self._descending = not self._descending if key == self._sort else False
        self._sort = key
        self._reload()

    @Slot(str, str)
    def openArtist(self, identifier, name):
        self._artist_id, self._artist_name = identifier, name
        self._mode, self._album_id = 'albums', ''
        self._reload()

    @Slot(str)
    def openAlbum(self, identifier):
        if self._mode != 'album':
            self._return = self._mode, self._artist_id, self._artist_name
        self._album_id, self._mode = identifier, 'album'
        self._album = {}
        self._reload()

    @Slot(str)
    def visitAlbum(self, identifier):
        if not identifier or self._closing:
            return
        self._cancel_navigation()
        self._activated = True
        if self._mode != 'album' or self._album_id != identifier:
            self.openAlbum(identifier)
        self.navigationRequested.emit()

    @Slot(str, str)
    def visitArtist(self, identifier, name):
        if not identifier or self._closing:
            return
        self._cancel_navigation()
        self._activated = True
        self._search = ''
        self.openArtist(identifier, name)
        self.navigationRequested.emit()

    @Slot(str, str)
    def visitTrack(self, identifier, target):
        if not identifier or target not in ('artist', 'album') or self._closing:
            return
        self._cancel_navigation()
        version, root = self._navigation_version, self._root
        task = Task(lambda op: track_target(root, self.database, identifier=identifier,
                                           target=target, operation=op), self)
        self._navigation_tasks.add(task)
        def resolved(result):
            if self._closing or version != self._navigation_version or root != self._root:
                return
            if not result:
                self._message, self._error = 'This artist or album is no longer available in the configured library. Refresh the index.', True
                self.changed.emit()
                self.navigationRequested.emit()
            elif result['target'] == 'album':
                self.visitAlbum(result['id'])
            else:
                self.visitArtist(result['id'], result['name'])
        def failed(error):
            if not self._closing and version == self._navigation_version and root == self._root:
                self._message, self._error = error, True
                self.changed.emit()
                self.navigationRequested.emit()
        def finished():
            self._navigation_tasks.discard(task)
            task.deleteLater()
            self._maybe_close()
        task.result.connect(resolved)
        task.failed.connect(failed)
        task.finished.connect(finished)
        task.start()

    def _cancel_navigation(self):
        self._navigation_version += 1
        for task in self._navigation_tasks:
            task.cancel()

    @Slot()
    def back(self):
        if self._mode == 'album':
            self._mode, self._artist_id, self._artist_name = self._return
            self._album_id, self._album = '', {}
        elif self._artist_id:
            self._artist_id = self._artist_name = ''
            self._mode = 'artists'
        else:
            self._mode = 'albums'
        self._reload()

    def navigationState(self):
        return dict(mode=self._mode, search=self._search, sort=self._sort, descending=self._descending,
                    artist_id=self._artist_id, artist_name=self._artist_name,
                    album_id=self._album_id, return_to=self._return)

    def restoreNavigation(self, state):
        self._cancel_navigation()
        self._mode, self._search = state['mode'], state['search']
        self._sort, self._descending = state['sort'], state['descending']
        self._artist_id, self._artist_name = state['artist_id'], state['artist_name']
        self._album_id, self._return = state['album_id'], state['return_to']
        self._album = {}
        self._reload()

    @Slot()
    def _reload(self):
        self.timer.stop()
        if self._closing:
            return
        self._version += 1
        self._model.reset()
        self._enqueue(0, True)

    @Slot()
    def loadMore(self):
        if self.query_task or self._pending or self._closing or len(self._model.rows) >= self._model.total:
            return
        self._model.loading = True
        self._enqueue(len(self._model.rows), False)

    def _enqueue(self, offset, reset):
        request = dict(mode=self._mode, search='' if self._mode == 'album' else self._search,
                       sort=self._sort, descending=self._descending, artist_id=self._artist_id,
                       album_id=self._album_id, offset=offset, limit=PAGE_SIZE)
        self._pending = (self._version, self._root, request, reset)
        if self.query_task:
            self.query_task.cancel()
        else:
            self._start_query()
        self.changed.emit()

    def _start_query(self):
        self._active_request = self._pending
        self._pending = None
        version, root, request, reset = self._active_request
        self.query_task = Task(lambda op: browse(root, self.database, operation=op, **request), self)
        self.query_task.result.connect(self._query_result)
        self.query_task.failed.connect(self._query_error)
        self.query_task.finished.connect(self._query_finished)
        self.query_task.start()

    @Slot(object)
    def _query_result(self, result):
        version, root, request, reset = self._active_request
        if version != self._version or root != self._root or self._closing:
            return
        self._model.receive(result['rows'], result['total'], reset)
        self._summary, self._album = result['summary'], result['album']
        self.changed.emit()

    @Slot(str)
    def _query_error(self, error):
        if self._active_request[0] == self._version:
            self._message, self._error = error, True
            self.changed.emit()

    @Slot()
    def _query_finished(self):
        task, self.query_task = self.query_task, None
        task.deleteLater()
        if self._pending and not self._closing:
            self._start_query()
        else:
            self._model.loading = False
        self.changed.emit()
        self._maybe_close()

    @Slot(bool)
    def refresh(self, rebuild=False):
        if self.index_task or self._closing:
            return
        self._stale = False
        self._error, self._message, self._phase, self._progress = False, '', 'Finding library tracks', -1
        root = self._root
        self._index_root = root
        self.index_task = Task(lambda op: refresh(Path(root), self.database, rebuild=rebuild, operation=op), self)
        self.index_task.progress.connect(self._index_progress)
        self.index_task.result.connect(self._index_result)
        self.index_task.failed.connect(self._index_error)
        self.index_task.cancelled.connect(self._index_cancelled)
        self.index_task.finished.connect(self._index_finished)
        self.index_task.start()
        self.changed.emit()

    @Slot(object)
    def _index_progress(self, event):
        if self._index_root == self._root:
            self._phase = event.phase + (f' · {event.completed} / {event.total}' if event.total else '')
            self._progress = event.completed / max(1, event.total) if event.total is not None else -1
            self.changed.emit()

    @Slot(object)
    def _index_result(self, result):
        if self._index_root != self._root or self._closing:
            return
        self._message = f'{result.errors} unreadable tracks. Other music is available to browse.' if result.errors else ''
        self._reload()

    @Slot(str)
    def _index_error(self, message):
        if self._index_root == self._root:
            self._message, self._error = message, True
            self.changed.emit()

    @Slot()
    def _index_cancelled(self):
        self._message = 'Refresh cancelled. The previous index is unchanged.'
        self.changed.emit()

    @Slot()
    def _index_finished(self):
        task, self.index_task = self.index_task, None
        task.deleteLater()
        if self._stale and not self._closing and self._index_root == self._root:
            self.refresh(False)
        self.changed.emit()
        self._maybe_close()

    @Slot()
    def cancel(self):
        if self.index_task:
            self.index_task.cancel()

    def _maybe_close(self):
        if self._closing and not self.index_task and not self.query_task and not self._navigation_tasks:
            self.safeToClose.emit()

    @Slot(result=bool)
    def requestClose(self):
        self._closing = True
        self.timer.stop()
        self._pending = None
        for task in (self.index_task, self.query_task, *self._navigation_tasks):
            if task:
                task.cancel()
        return not self.index_task and not self.query_task and not self._navigation_tasks

    def shutdown(self):
        self.requestClose()
        for task in (self.index_task, self.query_task, *self._navigation_tasks):
            if task:
                task.wait()
