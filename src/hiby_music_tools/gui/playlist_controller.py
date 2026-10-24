"""Serialized playlist storage work and reviewable QML selection."""
from PySide6.QtCore import QObject, Property, Signal, Slot

from hiby_music_tools.library import playlists as store
from hiby_music_tools.library.playback import tracks
from .quick_models import RecordModel
from .workers import Task


class PlaylistController(QObject):
    changed = Signal()
    safeToClose = Signal()

    def __init__(self, browser, player, path=None):
        super().__init__()
        self.browser, self.player = browser, player
        self.path = path or store.playlist_path()
        self._lists, self._tracks = RecordModel(self), RecordModel(self)
        self._selected = self._name = self._message = ''
        self._picker = False
        self._pending = None
        self.task = None
        self._closing = False

    lists = Property(QObject, lambda self: self._lists, constant=True)
    model = Property(QObject, lambda self: self._tracks, constant=True)
    count = Property(int, lambda self: len(self._tracks.rows), notify=changed)
    selected = Property(str, lambda self: self._selected, notify=changed)
    name = Property(str, lambda self: self._name, notify=changed)
    message = Property(str, lambda self: self._message, notify=changed)
    busy = Property(bool, lambda self: self.task is not None, notify=changed)
    choosing = Property(bool, lambda self: self._picker, notify=changed)

    def _run(self, mutation=None, *, selected=None, play='', scope=None):
        if self.busy or self._closing:
            return
        identifier = self._selected if selected is None else selected
        root, database, path = self.browser.root, self.browser.database, self.path
        self._message = ''
        def work(op):
            active = identifier
            if scope:
                mode, key = scope
                rows = tracks(root, database, mode=mode, identifier=key, operation=op)
                if not rows:
                    raise ValueError('No indexed music in this selection. Refresh the Library.')
                store.add(path, active, root, rows)
            if mutation:
                active = mutation(active) or active
            op.checkpoint()
            details = store.detail(path, active, database, op) if active else dict(id='', name='', rows=[])
            return store.listing(path), details
        self.task = Task(work, self)
        def result(value):
            lists, details = value
            self._lists.replace(lists)
            self._selected, self._name = details['id'], details['name']
            self._tracks.replace(details['rows'])
            if scope:
                self._pending, self._picker = None, False
            if play:
                if self.player.maintenance:
                    self._message = 'Wait for file maintenance to finish before playing.'
                else:
                    rows = [r for r in details['rows'] if not r['missing'] and not r.get('error')]
                    if rows:
                        self.player.playRows(rows, shuffle=play == 'shuffle')
                    else:
                        self._message = 'No available tracks in this playlist. Refresh the Library.'
            self.changed.emit()
        self.task.result.connect(result)
        self.task.failed.connect(self._failed)
        self.task.finished.connect(self._finished)
        self.task.start()
        self.changed.emit()

    def _failed(self, message):
        self._message = message
        self.changed.emit()

    def _finished(self):
        task, self.task = self.task, None
        task.deleteLater()
        self.changed.emit()
        if self._closing:
            self.safeToClose.emit()

    @Slot()
    def refresh(self):
        self._run()

    @Slot(str)
    def open(self, identifier):
        self._run(selected=identifier)

    @Slot(str)
    def create(self, title):
        self._run(lambda _: store.create(self.path, title))

    @Slot(str)
    def rename(self, title):
        if self._selected:
            self._run(lambda key: store.rename(self.path, key, title))

    @Slot(str)
    def remove(self, entry):
        self._run(lambda key: store.remove(self.path, key, entry))

    @Slot(str, int)
    def move(self, entry, target):
        self._run(lambda key: store.move(self.path, key, entry, target))

    @Slot(bool)
    def play(self, shuffle=False):
        self._run(play='shuffle' if shuffle else 'play')

    @Slot(str, str)
    def choose(self, scope, identifier):
        if scope not in ('track', 'album', 'artist') or self.busy:
            return
        self._pending = (scope, identifier)
        self._picker = True
        self.refresh()
        self.changed.emit()

    @Slot(str)
    def addTo(self, identifier):
        if self._pending:
            self._run(selected=identifier, scope=self._pending)

    @Slot()
    def dismiss(self):
        self._pending, self._picker = None, False
        self.changed.emit()

    @Slot(result=bool)
    def requestClose(self):
        self._closing = True
        if self.task:
            self.task.cancel()
        return self.task is None

    def shutdown(self):
        self.requestClose()
        if self.task:
            self.task.wait()
