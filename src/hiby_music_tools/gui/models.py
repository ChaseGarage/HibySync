"""Lazy table models avoid creating a widget for every scanned track."""

from PySide6.QtCore import QAbstractListModel, QAbstractTableModel, QSize, Qt
from PySide6.QtGui import QIcon, QPixmap


class AlbumModel(QAbstractListModel):
    def __init__(self, albums, parent=None):
        super().__init__(parent)
        self.albums = albums
        self.icons = {}

    def rowCount(self, parent=None):
        if parent is not None and parent.isValid():
            return 0
        return len(self.albums)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        album = self.albums[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return (f'{album.artist} — {album.title}\n'
                    f'{album.year} · {len(album.tracks)} tracks · {album.status}' +
                    (' · Skipped' if album.skip else ''))
        if role == Qt.ItemDataRole.UserRole:
            return album.status
        if role == Qt.ItemDataRole.SizeHintRole:
            return QSize(260, 76)
        if role == Qt.ItemDataRole.DecorationRole:
            art = album.tracks[0].selected_art
            if art:
                key = (art.path, art.index, art.origin)
                if key not in self.icons:
                    pixmap = QPixmap()
                    pixmap.loadFromData(art.thumbnail)
                    self.icons[key] = QIcon(pixmap)
                return self.icons[key]

    def refresh(self):
        if self.albums:
            self.dataChanged.emit(self.index(0), self.index(len(self.albums) - 1))


class PreviewModel(QAbstractTableModel):
    headers = ('Action', 'Source', 'Destination', 'Metadata changes', 'Artwork', 'Warnings')

    def __init__(self, rows, parent=None):
        super().__init__(parent)
        self.rows = rows

    def rowCount(self, parent=None):
        if parent is not None and parent.isValid():
            return 0
        return len(self.rows)

    def columnCount(self, parent=None):
        if parent is not None and parent.isValid():
            return 0
        return len(self.headers)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.headers[section]

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or role not in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            return None
        row = self.rows[index.row()]
        return str((row.action, row.source, row.destination, row.metadata_changes,
                    row.artwork_change, row.warning)[index.column()])
