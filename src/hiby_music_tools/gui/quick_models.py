"""Small role-based models and in-memory artwork for the QML presentation."""

import hashlib

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt
from PySide6.QtGui import QImage
from PySide6.QtQuick import QQuickImageProvider


class RecordModel(QAbstractListModel):
    RecordRole = Qt.ItemDataRole.UserRole + 1

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []

    def roleNames(self):
        return {self.RecordRole: b'record'}

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if index.isValid() and role == self.RecordRole:
            return self.rows[index.row()]
        return None

    def replace(self, rows):
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def update(self, row, values):
        self.rows[row] = {**self.rows[row], **values}
        self.dataChanged.emit(self.index(row), self.index(row), [self.RecordRole])


class ArtworkProvider(QQuickImageProvider):
    """Only exposes existing backend thumbnails; never opens arbitrary paths."""

    def __init__(self):
        super().__init__(QQuickImageProvider.ImageType.Image)
        self.images = {}

    def add(self, artwork):
        if artwork is None:
            return ''
        key = hashlib.sha256(artwork.thumbnail).hexdigest()
        if key not in self.images:
            self.images[key] = QImage.fromData(artwork.thumbnail)
        return f'image://artwork/{key}'

    def requestImage(self, identifier, size, requestedSize):
        image = self.images.get(identifier, QImage())
        size.setWidth(image.width())
        size.setHeight(image.height())
        return image
