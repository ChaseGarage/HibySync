"""Window-scoped mouse navigation history; never changes the playback queue."""
from PySide6.QtCore import QObject, QEvent, Property, QTimer, Signal, Slot, Qt


class Navigation(QObject):
    changed = Signal()
    backRequested = Signal()
    forwardRequested = Signal()

    def __init__(self, source, browser, playlists):
        super().__init__()
        self.source, self.browser, self.playlists = source, browser, playlists
        self._history, self._index = [], -1
        self._playlist_mode = self._restoring = False
        self._root = browser.root
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.record)
        for signal in (source.changed, browser.changed, playlists.changed):
            signal.connect(self.schedule)

    playlistMode = Property(bool, lambda self: self._playlist_mode, notify=changed)

    @Slot(bool)
    def setPlaylistsMode(self, enabled):
        if enabled != self._playlist_mode:
            self._playlist_mode = enabled
            self.changed.emit()
            self.schedule()

    def schedule(self):
        if not self._restoring:
            self.timer.start(0)

    def _snapshot(self):
        page = self.source.page
        state = dict(page=page)
        if page == 'library':
            state.update(library=self.browser.navigationState(), playlists=self._playlist_mode,
                         playlist=self.playlists.selected if self._playlist_mode else '')
        elif page in ('review', 'preview', 'complete'):
            state.update(session=id(self.source.session), album=self.source.album_index)
        return state

    @staticmethod
    def _location(state):
        if state['page'] == 'library':
            library = state['library']
            return ('library', 'playlists', state['playlist']) if state['playlists'] else (
                'library', library['mode'], library['artist_id'], library['album_id'])
        return state['page'], state.get('session'), state.get('album')

    def record(self):
        if self._restoring:
            return
        if self.browser.root != self._root:
            self._root = self.browser.root
            self._history, self._index = [], -1
        if self.source.page == 'library' and self._playlist_mode and self.playlists.busy:
            return  # Playlist selection resolves asynchronously; Library IDs do not.
        state = self._snapshot()
        if self._index >= 0 and self._location(self._history[self._index]) == self._location(state):
            self._history[self._index] = state  # Keep search/sort without a visit per keystroke.
            return
        self._history = self._history[:self._index + 1] + [state]
        self._history = self._history[-100:]
        self._index = len(self._history) - 1

    @Slot()
    def back(self):
        self._go(-1)

    @Slot()
    def forward(self):
        self._go(1)

    def _go(self, direction):
        if self.source.busy or self.browser._closing or self.playlists.busy:
            return
        self.record()
        index = self._index + direction
        while 0 <= index < len(self._history):
            state = self._history[index]
            if state.get('session', id(self.source.session)) == id(self.source.session):
                break
            index += direction  # A replaced Import review cannot be restored.
        if not 0 <= index < len(self._history):
            return
        self._restoring = True
        self.timer.stop()
        self._index = index
        try:
            if state['page'] == 'library':
                self.browser.restoreNavigation(state['library'])
                self.setPlaylistsMode(state['playlists'])
                if state['playlists'] and self.playlists.selected != state['playlist']:
                    self.playlists.open(state['playlist'])
            if state['page'] == 'review':
                self.source.openAlbum(state['album'])
            elif state['page'] in ('preview', 'complete'):
                self.source._page = state['page']
                self.source.changed.emit()
            else:
                self.source.navigate(state['page'])
        finally:
            self._restoring = False
        self.schedule()

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
            if event.button() in (Qt.MouseButton.BackButton, Qt.MouseButton.ForwardButton):
                if event.type() == QEvent.Type.MouseButtonPress:
                    (self.backRequested if event.button() == Qt.MouseButton.BackButton else self.forwardRequested).emit()
                return True  # Exactly once per press; leave all ordinary input alone.
        return False
