"""Dedicated mpv process, private Unix socket, structured asynchronous JSON IPC.

QProcess and QLocalSocket use Qt's event loop: no wait/read/poll loop blocks the
GUI. Queue reconciliation uses native playlist edits, preserving the playing
decoder when upcoming items are changed. No shell or terminal parsing is used.
"""

from collections import deque
import json
from pathlib import Path
import tempfile
import time

from PySide6.QtCore import QProcess, QTimer
from PySide6.QtNetwork import QLocalSocket

from .service import PlaybackService


def arguments(socket, *, output=None, device='auto'):
    args = ['--no-config', '--load-scripts=no', '--ytdl=no', '--idle=yes',
            '--terminal=no', '--input-terminal=no', '--input-default-bindings=no',
            '--osc=no', '--osd-level=0', '--video=no', '--audio-display=no',
            '--sub-auto=no', '--audio-file-auto=no', '--autoload-files=no', '--resume-playback=no',
            '--save-position-on-quit=no', '--speed=1', '--replaygain=no',
            '--audio-normalize-downmix=no', '--af=', '--gapless-audio=weak',
            '--audio-pitch-correction=no', '--volume=100', '--volume-max=100',
            *(['--ao=' + output] if output else ['--ao=pipewire,pulse,alsa'] if device == 'auto' else []),
            '--audio-device=' + device,
            '--audio-client-name=HibySync', '--input-ipc-server=' + str(socket)]
    return args


class MpvService(PlaybackService):
    def __init__(self, parent=None, *, executable='mpv', output=None, extra_args=()):
        super().__init__(parent)
        self.executable, self.output, self.extra_args = executable, output, list(extra_args)
        self.process = QProcess(self)
        self.process.setStandardOutputFile(QProcess.nullDevice())
        self.process.setStandardErrorFile(QProcess.nullDevice())
        self.process.errorOccurred.connect(self._process_error)
        self.process.finished.connect(self._finished)
        self.socket = QLocalSocket(self)
        self.socket.connected.connect(self._connected)
        self.socket.readyRead.connect(self._read)
        self.socket.disconnected.connect(self._disconnected)
        self.retry = QTimer(self)
        self.retry.setInterval(25)
        self.retry.timeout.connect(self._connect)
        self.coalesce = QTimer(self)
        self.coalesce.setSingleShot(True)
        self.coalesce.setInterval(12)
        self.coalesce.timeout.connect(self._reconcile)
        self.plan_timer = QTimer(self)
        self.plan_timer.setSingleShot(True)
        self.plan_timer.timeout.connect(self._plan_step)
        self._plan = None
        self.watchdog = QTimer(self)
        self.watchdog.setInterval(1000)
        self.watchdog.timeout.connect(self._timeout)
        self.kill_timer = QTimer(self)
        self.kill_timer.setSingleShot(True)
        self.kill_timer.timeout.connect(self.process.kill)
        self._directory = None
        self._started = 0
        self._reported_failure = False
        self._connected_flag = False
        self._closing = False
        self._releasing = False
        self._buffer = b''
        self._serial = 0
        self._commands = deque()
        self._inflight = None
        self._actual = []
        self._desired = []
        self._ids = {}
        self._current = ''
        self._syncing = False
        self._revision = 0
        self._restart = None
        self._volume = 100
        self._repeat = 'off'
        self._stopped = True
        self._manual_stop = False
        self._pending_seek = 0
        self._failures = set()
        self._deferred_errors = []
        self._device = 'auto'
        self._audio = {}
        self._devices_known = False

    @property
    def running(self):
        return self.process.state() != QProcess.ProcessState.NotRunning

    def _ensure(self):
        if self._closing:
            return
        if self.running:
            return
        self._directory = tempfile.TemporaryDirectory(prefix='hibysync-mpv-')
        self._reported_failure = False
        self._socket_path = str(Path(self._directory.name) / 'ipc')
        self._started = time.monotonic()
        self.process.start(self.executable, [*arguments(self._socket_path, output=self.output, device=self._device), *self.extra_args])
        self.retry.start()

    def _connect(self):
        if self._closing:
            return
        if time.monotonic() - self._started > 8:
            self._fatal('mpv did not open its control socket.')
        elif self.socket.state() == QLocalSocket.LocalSocketState.UnconnectedState:
            self.socket.connectToServer(self._socket_path)

    def _connected(self):
        self.retry.stop()
        self._connected_flag = True
        self.watchdog.start()
        for index, name in enumerate(('time-pos', 'duration', 'pause', 'idle-active', 'paused-for-cache', 'volume')):
            self._command(['observe_property', index + 1, name])
        self._command(['set_property', 'volume', self._volume])
        self.repeat(self._repeat)
        for index, name in enumerate(('audio-device-list', 'current-ao', 'audio-out-params',
                                      'audio-params', 'audio-codec-name', 'audio-bitrate', 'audio-device')):
            self._command(['observe_property', 100 + index, name])
        self._reconcile()

    def _command(self, command, callback=None):
        self._commands.append((command, callback))
        self._pump()

    def _pump(self):
        if not self._connected_flag or self._inflight or not self._commands:
            return
        command, callback = self._commands.popleft()
        self._serial += 1
        self._inflight = (self._serial, callback, command, time.monotonic())
        data = json.dumps(dict(command=command, request_id=self._serial), ensure_ascii=False, separators=(',', ':'))
        self.socket.write(data.encode('utf-8') + b'\n')

    def _read(self):
        self._buffer += bytes(self.socket.readAll())
        if len(self._buffer) > 64 * 1024 * 1024:
            self._fatal('mpv sent an oversized IPC message.')
            return
        while b'\n' in self._buffer:
            line, self._buffer = self._buffer.split(b'\n', 1)
            try:
                event = json.loads(line)
                if isinstance(event, dict):
                    self._message(event)
            except (ValueError, UnicodeError):
                self._fatal('Invalid JSON from mpv.')
                return

    def _message(self, event):
        if 'request_id' in event:
            if self._inflight and event['request_id'] == self._inflight[0]:
                _, callback, command, _ = self._inflight
                self._inflight = None
                if event.get('error') != 'success' and not self._closing:
                    self.playbackError.emit(self._current, f"mpv {command[0]}: {event.get('error', 'command failed')}")
                if callback:
                    callback(event.get('data'))
                self._pump()
            return
        kind = event.get('event')
        if kind == 'property-change':
            name, value = event.get('name'), event.get('data')
            if name in ('audio-device-list', 'current-ao', 'audio-out-params', 'audio-params',
                        'audio-codec-name', 'audio-bitrate', 'audio-device'):
                self._audio[name] = value
                self.audioChanged.emit(dict(self._audio))
                if name == 'audio-device-list' and isinstance(value, list):
                    self._devices_known = True
                    if self._device != 'auto' and self._device not in {d.get('name') for d in value}:
                        self.playbackError.emit(self._current, 'Selected audio device is unavailable. Using the system default; press Play if playback stopped.')
                        self.select_device('auto')
            elif not self._syncing:
                self.properties.emit({name: value})
        elif kind == 'start-file':
            qid = self._ids.get(event.get('playlist_entry_id'))
            if qid and not self._syncing:
                self._current = qid
                self._stopped = False
                self.currentChanged.emit(qid)
                self.properties.emit({'state': 'loading', 'time-pos': 0})
        elif kind == 'file-loaded':
            self._command(['get_property', 'playlist'], self._playlist)
            if self._pending_seek:
                self.seek(self._pending_seek)
                self._pending_seek = 0
            self._status()
        elif kind == 'end-file' and event.get('reason') == 'error':
            if self._syncing:
                self._deferred_errors.append(event)
            else:
                self._file_error(event)
        elif kind == 'idle' and not self._syncing and not self._stopped:
            self._stopped = True
            self.ended.emit()

    def sync(self, entries, current, *, restart=False, paused=False, position=0):
        # Copy immutable queue data; QML never controls native playlist indices.
        self._desired = [dict(e) for e in entries]
        self._revision += 1
        if restart:
            self._restart = (current, paused, max(0, position))
            self._manual_stop = False
            self._failures.clear()
        if not entries and not self.running:
            return
        self._ensure()
        self.coalesce.start()

    def _file_error(self, event):
        qid = self._ids.get(event.get('playlist_entry_id'))
        if qid is None:
            return  # An unloaded entry from an older playback context.
        error = event.get('file_error') or event.get('error') or 'Unable to play this file'
        self.playbackError.emit(qid, str(error))
        self._failures.add(qid)
        if len(self._failures) >= len(self._actual) or error == 'audio output initialization failed':
            self.stop()

    def _reconcile(self):
        if not self._connected_flag or self._syncing or self._closing:
            return
        self._syncing = True
        self._plan = self._plan_commands()
        self._plan_step()

    def _plan_step(self):
        # Large/shuffled queues can require many native playlist edits. Yield
        # frequently so even constructing that command sequence stays responsive.
        deadline = time.monotonic() + 0.004
        try:
            while self._plan is not None and time.monotonic() < deadline:
                next(self._plan)
        except StopIteration:
            self._plan = None
        if self._plan is not None:
            self.plan_timer.start(0)

    def _plan_commands(self):
        revision = self._revision
        desired = list(self._desired)
        restart, self._restart = self._restart, None
        # If the current file survives, all edits happen in place without reload.
        desired_keys = {e['qid'] for e in desired}
        actual = list(self._actual)
        current_removed = self._current and self._current not in desired_keys
        if current_removed and not restart and not self._stopped:
            target = desired[min(len(desired) - 1, next((i for i, e in enumerate(actual) if e['qid'] == self._current), 0))]['qid'] if desired else ''
            restart = (target, False, 0)
        if (restart and (not actual or current_removed or not desired)) or (current_removed and self._stopped):
            self._command(['stop'])
            actual = []
            if not restart:
                self._current = ''
        for index in range(len(actual) - 1, -1, -1):
            if actual[index]['qid'] not in desired_keys:
                self._command(['playlist-remove', index])
                actual.pop(index)
            yield
        for index, entry in enumerate(desired):
            found = next((i for i in range(index, len(actual)) if actual[i]['qid'] == entry['qid']), -1)
            if found < 0:
                self._command(['loadfile', entry['path'], 'append'])
                actual.append(entry)
                found = len(actual) - 1
            if found != index:
                self._command(['playlist-move', found, index])
                actual.insert(index, actual.pop(found))
            yield
        self._actual = desired
        if restart and desired and not self._manual_stop:
            qid, paused, position = restart
            index = next((i for i, e in enumerate(desired) if e['qid'] == qid), 0)
            self._current = desired[index]['qid']
            self._pending_seek = position
            self._command(['set_property', 'pause', paused])
            self._command(['playlist-play-index', index])
            self._stopped = False
        elif not desired:
            self._command(['stop'])
            self._stopped = True
        def complete(data):
            self._syncing = False
            self._playlist(data)
            errors, self._deferred_errors = self._deferred_errors, []
            for event in errors:
                self._file_error(event)
            if revision != self._revision:
                self._reconcile()
            else:
                self._status()
        self._command(['get_property', 'playlist'], complete)

    def _playlist(self, playlist):
        if not isinstance(playlist, list) or len(playlist) != len(self._actual):
            return
        self._ids = {p['id']: e['qid'] for p, e in zip(playlist, self._actual) if 'id' in p}
        if not self._syncing:
            current = next((self._ids.get(p['id']) for p in playlist if p.get('playing') and p['id'] in self._ids), None)
            if current:
                self._current = current
                self.currentChanged.emit(current)

    def _status(self):
        # Read idle *after* pause: a very short file may already have ended by
        # the time file-loaded is delivered. Never resurrect it as playing.
        def paused(value):
            def idle(active):
                if self._syncing or self._closing:
                    return
                self.properties.emit({'state': 'stopped' if active or self._manual_stop else 'paused' if value else 'playing'})
                if active and not self._stopped:
                    self._stopped = True
                    self.ended.emit()
            self._command(['get_property', 'idle-active'], idle)
        self._command(['get_property', 'pause'], paused)

    def pause(self, paused):
        if self._connected_flag:
            self._command(['set_property', 'pause', bool(paused)])

    def refresh_devices(self):
        self._ensure()
        if self._connected_flag:
            self._command(['get_property', 'audio-device-list'], self._device_list)

    def _device_list(self, value):
        self._message({'event': 'property-change', 'name': 'audio-device-list', 'data': value})

    def select_device(self, name):
        if not isinstance(name, str) or not name or '\x00' in name:
            return
        self._device = name
        if self._connected_flag:
            # mpv schedules a local output reload. Explicit devices select their
            # own driver; clear the default driver preference first.
            if not self.output:
                self._command(['set_property', 'ao', 'pipewire,pulse,alsa' if name == 'auto' else ''])
            self._command(['set_property', 'audio-device', name])
        self._audio['audio-device'] = name
        self.audioChanged.emit(dict(self._audio))

    def seek(self, seconds):
        if self._connected_flag:
            self._command(['seek', max(0, float(seconds)), 'absolute+exact'])

    def volume(self, value):
        self._volume = max(0, min(100, float(value)))
        if self._connected_flag:
            self._command(['set_property', 'volume', self._volume])

    def repeat(self, mode):
        self._repeat = mode
        if self._connected_flag:
            self._command(['set_property', 'loop-file', 'inf' if mode == 'one' else 'no'])
            self._command(['set_property', 'loop-playlist', 'inf' if mode == 'all' else 'no'])

    def stop(self):
        self._stopped = True
        self._manual_stop = True
        if self._connected_flag:
            self._command(['playlist-play-index', 'none'])
        self.properties.emit({'state': 'stopped', 'time-pos': 0})

    def _timeout(self):
        if self._inflight and time.monotonic() - self._inflight[3] > 15:
            self._fatal('mpv stopped responding. Press Play to retry.')

    def _fatal(self, message):
        self._reported_failure = True
        self.playbackError.emit(self._current, message)
        self.properties.emit({'state': 'error'})
        self.retry.stop()
        if self.running:
            self.process.kill()

    def _process_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self._fatal('mpv is unavailable. Install it with: sudo pacman -S mpv')
            self._finished(-1, QProcess.ExitStatus.CrashExit)

    def _disconnected(self):
        was_connected = self._connected_flag
        self._connected_flag = False
        if was_connected and self.running and not self._closing and not self._releasing:
            self._fatal('Lost the mpv control connection. Press Play to retry.')

    def _finished(self, code, status):
        self.retry.stop()
        self.watchdog.stop()
        self.kill_timer.stop()
        self.plan_timer.stop()
        self._plan = None
        self.socket.abort()
        self._buffer = b''
        self._commands.clear()
        self._inflight = None
        self._connected_flag = self._syncing = False
        self._actual, self._ids = [], {}
        self._deferred_errors = []
        self._audio = {'audio-device': self._device}
        self._devices_known = False
        self.audioChanged.emit(dict(self._audio))
        if self._directory:
            self._directory.cleanup()
            self._directory = None
        if self._closing:
            self.closed.emit()
        elif self._releasing:
            self._releasing = False
            self.properties.emit({'state': 'stopped'})
            self.released.emit()
        elif not self._reported_failure:
            self.playbackError.emit(self._current, 'mpv exited unexpectedly. Press Play to retry.')
            self.properties.emit({'state': 'error'})

    def close(self):
        self._closing = True
        self.retry.stop()
        self.coalesce.stop()
        self.plan_timer.stop()
        self._plan = None
        if self.running:
            self._commands.clear()
            self._command(['quit'])
            self.kill_timer.start(1500)
        else:
            self.closed.emit()

    def release(self):
        self._releasing = True
        self.retry.stop()
        self.coalesce.stop()
        self.plan_timer.stop()
        self._plan = None
        self._commands.clear()
        if self.running:
            self._command(['quit'])
            self.kill_timer.start(1500)
        else:
            self._releasing = False
            self.released.emit()

    def can_write_unreferenced(self, paths):
        # A pending playlist edit could still have an old decoder/file open.
        if self._syncing or self._plan or self._commands or self._inflight or self._releasing:
            return False
        targets = {str(Path(path).resolve()) for path in paths}
        return not targets.intersection(str(Path(entry['path']).resolve())
                                        for entry in (*self._actual, *self._desired))

    def shutdown(self):
        """Only called after the GUI event loop exits, including abnormal exits."""
        self.close()
        if self.running and not self.process.waitForFinished(1800):
            self.process.kill()
            self.process.waitForFinished(1000)
