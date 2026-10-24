"""Replaceable asynchronous playback boundary. No QML or library dependency."""

from PySide6.QtCore import QObject, Signal


class PlaybackService(QObject):
    properties = Signal(object)
    currentChanged = Signal(str)
    playbackError = Signal(str, str)
    ended = Signal()
    closed = Signal()
    released = Signal()
    audioChanged = Signal(object)

    def refresh_devices(self):
        """Optional device enumeration; implementations publish audioChanged."""

    def select_device(self, name):
        """Select a backend device ID, without changing system configuration."""

    def can_write_unreferenced(self, paths):
        """Conservative default: a frontend must release the backend first."""
        return False

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

    def release(self):
        """Release all file handles before maintenance; reusable afterwards."""
        raise NotImplementedError
