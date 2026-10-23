"""Qt player presentation; queue policy and IPC implementation remain separate."""

import math

from PySide6.QtCore import QObject, Property, QTimer, Signal, Slot

from hiby_music_tools.library.playback import tracks
from hiby_music_tools.playback.queue import MusicQueue
from hiby_music_tools.playback.mpv import MpvService
from hiby_music_tools.playback import state as storage
from .quick_models import RecordModel
from .workers import Task


class PlayerController(QObject):
    changed = Signal()
    trackChanged = Signal()
    stateChanged = Signal()
    positionChanged = Signal()
    safeToClose = Signal()

    def __init__(self, browser, *, service=None, state_file=None, persist=True):
        super().__init__()
        self.browser = browser
        self.service = service or MpvService(self)
        self.queue = MusicQueue()
        self._model = RecordModel(self)
        self._current_track = {}
        self._state = 'stopped'
        self._position = self._duration = 0.0
        self._volume = 100.0
        self._error = ''
        self._closing = self._service_closed = False
        self._close_waiting = False
        self._dirty = False
        self._revision = 0
        self._restore_revision = 0
        self._restoring = False
        self._resume_position = 0
        self._state_file = state_file or storage.state_path()
        self._persist = persist
        self.task = self.restore_task = self.save_task = None
        self._tasks = set()
        self._pending_save = None
        self.service.properties.connect(self._properties)
        self.service.currentChanged.connect(self._current)
        self.service.playbackError.connect(self._failed)
        self.service.ended.connect(self._ended)
        self.service.closed.connect(self._closed)
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(600)
        self.save_timer.timeout.connect(self._save)
        self.position_timer = QTimer(self)
        self.position_timer.setInterval(15000)
        self.position_timer.timeout.connect(self._schedule_save)
        self.close_timer = QTimer(self)
        self.close_timer.setSingleShot(True)
        self.close_timer.timeout.connect(self.safeToClose)
        if persist:
            self._restoring = True
            self.restore_task = Task(lambda op: storage.load(self._state_file), self)
            self.restore_task.result.connect(self._restored)
            self.restore_task.failed.connect(lambda error: self._notice('Could not restore player state: ' + error))
            self.restore_task.finished.connect(self._restore_finished)
            self.restore_task.start()

    model = Property(QObject, lambda self: self._model, constant=True)
    current = Property('QVariantMap', lambda self: self._current_track, notify=trackChanged)
    currentTrackId = Property(str, lambda self: self._current_track.get('id', ''), notify=trackChanged)
    currentQueueId = Property(str, lambda self: self.queue.current, notify=trackChanged)
    count = Property(int, lambda self: len(self.queue.entries), notify=changed)
    state = Property(str, lambda self: self._state, notify=stateChanged)
    position = Property(float, lambda self: self._position, notify=positionChanged)
    duration = Property(float, lambda self: self._duration or float(self._current_track.get('duration') or 0), notify=positionChanged)
    volume = Property(float, lambda self: self._volume, notify=changed)
    shuffle = Property(bool, lambda self: self.queue.shuffle, notify=changed)
    repeat = Property(str, lambda self: self.queue.repeat, notify=changed)
    error = Property(str, lambda self: self._error, notify=changed)
    busy = Property(bool, lambda self: self.task is not None or self._restoring, notify=changed)

    def _notice(self, error):
        self._error = error
        self.changed.emit()

    def _queue_changed(self, *, restart=False, paused=False, position=0, sync=True):
        self._current_track = next((e for e in self.queue.entries if e['qid'] == self.queue.current), {})
        self._model.replace([dict(e, current=e['qid'] == self.queue.current) for e in self.queue.entries])
        self.trackChanged.emit()
        self.stateChanged.emit()
        self.positionChanged.emit()
        if sync:
            self.service.sync(self.queue.entries, self.queue.current, restart=restart, paused=paused, position=position)
        self.changed.emit()
        self._schedule_save()

    def _request(self, mode, identifier, action, selected=''):
        if self._closing:
            return
        self._revision += 1
        revision = self._revision
        if self.task:
            self.task.cancel()
        request = dict(mode=mode, identifier=identifier,
                       search=self.browser.search if mode == 'songs' else '',
                       sort=self.browser.sort, descending=self.browser.descending)
        root, database = self.browser.root, self.browser.database
        task = Task(lambda op: tracks(root, database, operation=op, **request), self)
        self.task = task
        self._tasks.add(task)
        task.result.connect(lambda rows: self._context(rows, action, selected, revision))
        task.failed.connect(lambda error: self._notice(error) if revision == self._revision else None)
        task.finished.connect(lambda: self._task_finished(task))
        task.start()
        self.changed.emit()

    def _task_finished(self, task):
        self._tasks.discard(task)
        if task == self.task:
            self.task = None
        task.deleteLater()
        self.changed.emit()
        self._maybe_close()

    def _context(self, rows, action, selected, revision):
        if revision != self._revision or self._closing:
            return
        if not rows:
            self._notice('No indexed tracks in this selection. Refresh the library if files have changed.')
            return
        if selected and not any(row['id'] == selected for row in rows):
            self._notice('The selected track no longer matches this view. Refresh the selection and try again.')
            return
        self._error = ''
        if action in ('play', 'shuffle'):
            self.queue.replace(rows, selected, shuffle=action == 'shuffle')
            self._position = self._duration = self._resume_position = 0
            self._state = 'loading'
            self._queue_changed(restart=True)
        else:
            self.queue.add(rows, next_up=action == 'next')
            # Adding to an idle queue never begins playback.
            self._queue_changed()

    @Slot(str)
    def playContext(self, selected):
        mode = 'album' if self.browser.mode == 'album' else 'songs'
        self._request(mode, self.browser._album_id if mode == 'album' else '', 'play', selected)

    @Slot(str)
    def toggleTrack(self, identifier):
        """One row action shared by all Library views; retain the live queue."""
        if identifier == self.currentTrackId:
            if self._state != 'loading':
                self.togglePause()
        elif not self.busy:
            self.playContext(identifier)

    @Slot(str, str)
    def trackAction(self, identifier, action):
        if action in ('play', 'append', 'next'):
            self._request('track', identifier, action, identifier)

    @Slot(str, str)
    def albumAction(self, identifier, action):
        if action in ('play', 'shuffle', 'append', 'next'):
            self._request('album', identifier, action)

    @Slot(str, str)
    def artistAction(self, identifier, action):
        if action in ('play', 'shuffle', 'append', 'next'):
            self._request('artist', identifier, action)

    @Slot()
    def togglePause(self):
        if self._state in ('playing', 'paused', 'buffering'):
            self.service.pause(self._state != 'paused')
        elif self.queue.entries:
            self._error = ''
            self._state = 'loading'
            self._position = self._resume_position
            self._duration = 0
            self._queue_changed(restart=True, position=self._resume_position)
            self._resume_position = 0

    @Slot()
    def stop(self):
        self.service.stop()
        self._position = self._resume_position = 0
        self._state = 'stopped'
        self.stateChanged.emit()
        self.positionChanged.emit()
        self.changed.emit()
        self._schedule_save()

    @Slot(float)
    def seek(self, seconds):
        if math.isfinite(seconds) and self._state in ('playing', 'paused', 'buffering'):
            self.service.seek(max(0, min(self.duration, seconds)))

    @Slot(float)
    def setVolume(self, value):
        if math.isfinite(value):
            self._volume = max(0, min(100, value))
            self.service.volume(self._volume)
            self.changed.emit()
            self._schedule_save()

    @Slot()
    def next(self):
        self._select_adjacent(1)

    @Slot()
    def previous(self):
        if self._position > 3 and self._state in ('playing', 'paused'):
            self.service.seek(0)
        else:
            self._select_adjacent(-1)

    def _select_adjacent(self, direction):
        target = self.queue.adjacent(direction)
        if target:
            self.playEntry(target)
        elif direction > 0:
            self.stop()

    @Slot(str)
    def playEntry(self, qid):
        if any(e['qid'] == qid for e in self.queue.entries):
            self.queue.current = qid
            self._state = 'loading'
            self._position = self._duration = self._resume_position = 0
            self._error = ''
            self._queue_changed(restart=True)

    @Slot(str)
    def remove(self, qid):
        was_current = qid == self.queue.current
        playing = self._state in ('playing', 'paused', 'loading', 'buffering')
        paused = self._state == 'paused'
        self.queue.remove(qid)
        if was_current:
            self._position = self._duration = self._resume_position = 0
        if not self.queue.entries:
            self.stop()
        self._queue_changed(restart=was_current and playing and bool(self.queue.entries), paused=paused)

    @Slot(str, int)
    def move(self, qid, target):
        self.queue.move(qid, target)
        self._queue_changed()

    @Slot()
    def clear(self):
        self.stop()
        self.queue.entries, self.queue.current, self.queue._order = [], '', []
        self._queue_changed()

    @Slot()
    def toggleShuffle(self):
        self.queue.set_shuffle(not self.queue.shuffle)
        self._queue_changed(sync=self._state != 'stopped')

    @Slot()
    def cycleRepeat(self):
        self.queue.repeat = {'off': 'all', 'all': 'one', 'one': 'off'}[self.queue.repeat]
        self.service.repeat(self.queue.repeat)
        self.changed.emit()
        self._schedule_save()

    def _current(self, qid):
        if qid != self.queue.current and any(e['qid'] == qid for e in self.queue.entries):
            self.queue.current = qid
            self._position = self._duration = 0
            self._queue_changed(sync=False)

    def _properties(self, data):
        previous = self._state, self._position, self._duration
        if 'time-pos' in data and data['time-pos'] is not None:
            self._position = max(0, float(data['time-pos']))
        if 'duration' in data and data['duration'] is not None:
            self._duration = max(0, float(data['duration']))
        if 'state' in data:
            self._state = data['state']
        elif data.get('idle-active') is True:
            self._state = 'stopped'
        elif data.get('paused-for-cache') is True:
            self._state = 'buffering'
        elif 'pause' in data and self.queue.entries and self._state not in ('stopped', 'error'):
            self._state = 'paused' if data['pause'] else 'playing'
        elif data.get('idle-active') is False and self._state == 'loading':
            self._state = 'playing'
        if self._state == 'playing':
            self.position_timer.start() if not self.position_timer.isActive() else None
        else:
            self.position_timer.stop()
        if self._state != previous[0]:
            self.stateChanged.emit()
        if (self._position, self._duration) != previous[1:]:
            self.positionChanged.emit()

    def _failed(self, qid, error):
        title = next((e['title'] for e in self.queue.entries if e['qid'] == qid), '')
        self._notice((title + ': ' if title else '') + error)

    def _ended(self):
        self._state = 'stopped'
        self._position = self._resume_position = 0
        self.stateChanged.emit()
        self.positionChanged.emit()
        self.changed.emit()
        self._schedule_save()

    @Slot()
    def dismissError(self):
        self._notice('')

    def _restored(self, data):
        if self._revision != self._restore_revision or self._dirty or self._closing:
            return
        try:
            self.queue.restore(data.get('queue', {}))
            self._current_track = next((e for e in self.queue.entries if e['qid'] == self.queue.current), {})
            volume = float(data.get('volume', 100))
            self._volume = max(0, min(100, volume)) if math.isfinite(volume) else 100
            position = float(data.get('position', 0))
            self._resume_position = max(0, position) if math.isfinite(position) else 0
            self._position = self._resume_position
            self.service.volume(self._volume)
            self.service.repeat(self.queue.repeat)
            self._model.replace([dict(e, current=e['qid'] == self.queue.current) for e in self.queue.entries])
        except (TypeError, ValueError, KeyError) as error:
            self._notice('Could not restore player state: ' + str(error))
        self.trackChanged.emit()
        self.positionChanged.emit()
        self.changed.emit()

    def _restore_finished(self):
        self.restore_task.deleteLater()
        self.restore_task = None
        self._restoring = False
        self.changed.emit()
        self._maybe_close()

    def _schedule_save(self):
        self._dirty = True
        if self._persist and not self._closing:
            self.save_timer.start()

    def _save(self):
        if not self._persist or not self._dirty:
            return
        snapshot = dict(queue=self.queue.snapshot(), volume=self._volume,
                        position=self._position if self._state != 'stopped' else self._resume_position)
        # Detach dictionaries from future queue edits before crossing threads.
        snapshot['queue'] = {**snapshot['queue'], 'entries': [dict(e) for e in self.queue.entries],
                             'order': list(self.queue._order)}
        self._pending_save = snapshot
        self._start_save()

    def _start_save(self):
        if self.save_task or self._pending_save is None:
            return
        snapshot, self._pending_save = self._pending_save, None
        self.save_task = Task(lambda op: storage.save(self._state_file, snapshot), self)
        self.save_task.failed.connect(lambda error: self._notice('Could not save player state: ' + error))
        self.save_task.finished.connect(self._save_finished)
        self.save_task.start()

    def _save_finished(self):
        self.save_task.deleteLater()
        self.save_task = None
        self._start_save()
        self._maybe_close()

    def _closed(self):
        self._service_closed = True
        self._maybe_close()

    def _maybe_close(self):
        if self._close_waiting and self._service_closed and not any((self._tasks, self.restore_task, self.save_task, self._pending_save)):
            self._close_waiting = False
            self.close_timer.start(0)

    @Slot(result=bool)
    def requestClose(self):
        if not self._closing:
            self._closing = True
            self.save_timer.stop()
            self.position_timer.stop()
            self._save()
            for task in self._tasks:
                task.cancel()
            self.service.close()
        ready = self._service_closed and not any((self._tasks, self.restore_task, self.save_task, self._pending_save))
        self._close_waiting = not ready
        return ready

    def shutdown(self):
        self.requestClose()
        if hasattr(self.service, 'shutdown'):
            self.service.shutdown()
        for task in (*self._tasks, self.restore_task, self.save_task):
            if task:
                task.wait()
        if self._pending_save:
            storage.save(self._state_file, self._pending_save)
