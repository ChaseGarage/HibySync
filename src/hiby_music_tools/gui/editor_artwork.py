"""Asynchronous full-resolution previews, separate from small Library covers."""

import hashlib
from threading import Lock

from PySide6.QtGui import QImage
from PySide6.QtQuick import QQuickImageProvider


class EditorArtworkProvider(QQuickImageProvider):
    def __init__(self):
        super().__init__(QQuickImageProvider.Image, QQuickImageProvider.ForceAsynchronousImageLoading)
        self.lock = Lock()
        self.data = {}

    def add(self, data):
        key = hashlib.sha256(data).hexdigest()
        with self.lock:
            self.data = {key: data}
        return 'image://editor-full/' + key

    def requestImage(self, identifier, size, requestedSize):
        with self.lock:
            data = self.data.get(identifier, b'')
        result = QImage.fromData(data)
        size.setWidth(result.width())
        size.setHeight(result.height())
        return result
