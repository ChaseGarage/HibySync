"""Paged QML rows and bounded asynchronous loading of cached library thumbnails."""

from collections import OrderedDict
import re
from threading import Lock

from PySide6.QtCore import QModelIndex, Property, Signal
from PySide6.QtGui import QImage, QImageReader
from PySide6.QtQuick import QQuickImageProvider

from .quick_models import RecordModel


class LibraryModel(RecordModel):
    moreRequested = Signal()
    stateChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._total = 0
        self.loading = False

    total = Property(int, lambda self: self._total, notify=stateChanged)

    def reset(self):
        self.loading = True
        self._total = 0
        self.replace([])
        self.stateChanged.emit()

    def receive(self, rows, total, reset):
        self._total = total
        if reset:
            self.replace(rows)
        elif rows:
            start = len(self.rows)
            self.beginInsertRows(QModelIndex(), start, start + len(rows) - 1)
            self.rows.extend(rows)
            self.endInsertRows()
        self.stateChanged.emit()

    def canFetchMore(self, parent=None):
        return not (parent and parent.isValid()) and not self.loading and len(self.rows) < self._total

    def fetchMore(self, parent=None):
        if self.canFetchMore(parent):
            self.loading = True
            self.moreRequested.emit()


class LibraryArtworkProvider(QQuickImageProvider):
    """Reads only generated <=240px PNGs, never original audio or cover files."""

    def __init__(self, directory, capacity=128):
        super().__init__(QQuickImageProvider.ImageType.Image,
                         QQuickImageProvider.Flag.ForceAsynchronousImageLoading)
        self.directory = directory
        self.capacity = capacity
        self.images = OrderedDict()
        self.lock = Lock()

    def requestImage(self, identifier, size, requestedSize):
        image = QImage()
        if re.fullmatch(r'[a-f0-9]{64}', identifier):
            with self.lock:
                if identifier in self.images:
                    image = self.images.pop(identifier)
                    self.images[identifier] = image
                else:
                    path = self.directory / (identifier + '.png')
                    try:
                        if path.is_file() and path.stat().st_size <= 1024 * 1024:
                            reader = QImageReader(str(path))
                            bounds = reader.size()
                            if 0 < bounds.width() <= 240 and 0 < bounds.height() <= 240:
                                image = reader.read()
                    except OSError:
                        pass
                    if not image.isNull():
                        self.images[identifier] = image
                        while len(self.images) > self.capacity:
                            self.images.popitem(last=False)
        size.setWidth(image.width())
        size.setHeight(image.height())
        return image
