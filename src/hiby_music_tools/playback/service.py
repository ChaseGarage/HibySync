"""Replaceable asynchronous playback boundary. No QML or library dependency."""

from PySide6.QtCore import QObject, Signal


class PlaybackService(QObject):
    properties = Signal(object)
    currentChanged = Signal(str)
    playbackError = Signal(str, str)
    ended = Signal()
    closed = Signal()

    def sync(self, entries, current, *, restart=False, paused=False, position=0):
        """Mirror queue; preserve playing audio for edits unless restart requested."""
        raise NotImplementedError

    def pause(self, paused):
        raise NotImplementedError

    def stop(self):
        raise NotImplementedError

    def seek(self, seconds):
        raise NotImplementedError

    def volume(self, value):
        raise NotImplementedError

    def repeat(self, mode):
        raise NotImplementedError

    def close(self):
        raise NotImplementedError
