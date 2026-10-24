"""Queue policy and real mpv IPC/PCM tests; never use the user's music."""

import json
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import time
import unittest
import wave

from test_baseline import make_track
from hiby_music_tools.playback.queue import MusicQueue
from hiby_music_tools.playback import state as storage
from hiby_music_tools.library.indexer import refresh
from hiby_music_tools.library.playback import tracks

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
try:
    from PySide6.QtCore import QCoreApplication, QEvent, QTimer
    from PySide6.QtGui import QGuiApplication
    from hiby_music_tools.playback.mpv import MpvService, arguments
    QT = True
except ImportError:
    QT = False


def tone(path, duration=1, rate=44100):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), 'wb') as stream:
        stream.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
        stream.writeframes(b''.join(struct.pack('<h', int(2000 * math.sin(i * 2 * math.pi * 440 / rate)))
                                   for i in range(int(rate * duration))))
    return dict(id=str(path), qid=path.stem, path=str(path), title=path.stem, artist='Fixture', duration=duration)


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.queue = MusicQueue()
        self.rows = [dict(id=str(i), path=f'/tmp/{i}.wav', title=str(i)) for i in range(12)]
        self.queue.replace(self.rows, '3')

    def test_independent_order_add_next_remove_reorder_and_duplicates(self):
        queue = self.queue
        self.assertEqual(queue.index, 3)
        self.rows.reverse()
        self.assertEqual(queue.entries[0]['id'], '0')
        current = queue.current
        queue.add([dict(id='3', path='/tmp/3.wav')], next_up=True)
        self.assertNotEqual(queue.entries[4]['qid'], current)
        queue.move(queue.entries[-1]['qid'], 0)
        self.assertEqual(queue.current, current)
        queue.remove(current)
        self.assertEqual(queue.entries[queue.index]['id'], '3')
        self.assertEqual(len({e['qid'] for e in queue.entries}), len(queue.entries))

    def test_shuffle_preserves_current_and_history_and_restores_order(self):
        queue = self.queue
        before = [e['qid'] for e in queue.entries]
        queue.set_shuffle(True)
        self.assertEqual([e['qid'] for e in queue.entries[:4]], before[:4])
        self.assertEqual(set(e['qid'] for e in queue.entries), set(before))
        queue.set_shuffle(False)
        self.assertEqual([e['qid'] for e in queue.entries], before)
        queue.replace(self.rows, '5', shuffle=True)
        self.assertEqual(queue.index, 0)
        self.assertEqual(queue.entries[0]['id'], '5')

    def test_repeat_off_all_one_and_manual_next(self):
        queue = self.queue
        queue.current = queue.entries[-1]['qid']
        self.assertEqual(queue.adjacent(1), '')
        queue.repeat = 'all'
        self.assertEqual(queue.adjacent(1), queue.entries[0]['qid'])
        queue.repeat = 'one'
        self.assertEqual(queue.adjacent(1, completed=True), queue.current)
        queue.current = queue.entries[1]['qid']
        self.assertEqual(queue.adjacent(1), queue.entries[2]['qid'])

    def test_atomic_state_round_trip_and_invalid_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state/player.json'
            self.queue.repeat = 'one'
            self.queue.set_shuffle(True)
            storage.save(path, dict(queue=self.queue.snapshot(), volume=87))
            restored = MusicQueue()
            restored.restore(storage.load(path)['queue'])
            self.assertEqual(restored.snapshot(), self.queue.snapshot())
            self.assertEqual(list(path.parent.iterdir()), [path])
            restored.restore(dict(version=1, entries=[{}, dict(qid='bad', id='a', path='https://example.com')]))
            self.assertEqual(restored.entries, [])
            path.write_text('[]')
            with self.assertRaises(ValueError):
                storage.load(path)

    def test_playback_context_uses_full_sql_order_and_album_disc_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'music'
            database = Path(directory) / 'index.sqlite3'
            for name in ('z', 'a', 'b'):
                make_track(root / 'Artist/Album' / (name + '.wav'))
            refresh(root, database)
            rows = tracks(root, database, sort='title', descending=True)
            self.assertEqual(len(rows), 3)
            self.assertEqual([Path(e['path']).stem for e in rows], ['a', 'b', 'z'])  # identical title, stable path tie-break
            self.assertEqual(len(tracks(root, database, search='Song')), 3)
            self.assertEqual(tracks(root, database, search='absent'), [])
            from hiby_music_tools.library.queries import browse
            album = browse(root, database)['rows'][0]
            self.assertEqual([e['id'] for e in tracks(root, database, mode='album', identifier=album['id'])],
                             [e['id'] for e in browse(root, database, mode='album', album_id=album['id'])['rows']])
            from mutagen.wave import WAVE
            from mutagen.id3 import TPE1
            audio = WAVE(root / 'Artist/Album/a.wav')
            audio.tags['TPE1'] = TPE1(text=['Guest'])
            audio.save()
            refresh(root, database)
            guest = next(e for e in browse(root, database, mode='artists')['rows'] if e['name'] == 'Guest')
            self.assertEqual(len(tracks(root, database, mode='artist', identifier=guest['id'])), 1)


@unittest.skipUnless(QT and shutil.which('mpv'), 'Install PySide6 and mpv for real IPC tests')
class MpvTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QGuiApplication.instance() or QGuiApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='hiby-mpv-test-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.services = []
        self.addCleanup(self.cleanup_services)

    def cleanup_services(self):
        for service in self.services:
            service.shutdown()
            service.deleteLater()
        self.app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def service(self, **kwargs):
        service = MpvService(**kwargs)
        self.services.append(service)
        service.errors = []
        service.values = {}
        service.currents = []
        service.playbackError.connect(lambda qid, message: service.errors.append((qid, message)))
        service.properties.connect(service.values.update)
        service.currentChanged.connect(service.currents.append)
        return service

    def wait(self, condition, timeout=12):
        deadline = time.monotonic() + timeout
        while not condition() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.003)
        self.assertTrue(condition(), 'mpv did not reach the expected state')

    def test_predictable_configuration_no_forced_rate_or_format(self):
        args = arguments('/tmp/private/ipc')
        for option in ('--no-config', '--load-scripts=no', '--af=', '--speed=1', '--replaygain=no', '--gapless-audio=weak'):
            self.assertIn(option, args)
        self.assertFalse(any(a.startswith(('--audio-samplerate=', '--audio-format=')) for a in args))
        self.assertIn('--ao=pipewire,pulse,alsa', args)

    def test_real_decoding_produces_nonzero_pcm_for_supported_formats(self):
        if not shutil.which('ffmpeg'):
            self.skipTest('FFmpeg creates codec fixtures')
        source = self.root / 'source.wav'
        tone(source, .35)
        cases = [('wav', []), ('flac', ['-c:a', 'flac']), ('mp3', ['-c:a', 'libmp3lame']),
                 ('m4a', ['-c:a', 'aac']), ('alac.m4a', ['-c:a', 'alac']),
                 ('aac', ['-c:a', 'aac']), ('ogg', ['-c:a', 'libvorbis'])]
        for suffix, options in cases:
            with self.subTest(format=suffix):
                path = self.root / ('fixture.' + suffix)
                subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(source), *options, str(path)], check=True)
                output = self.root / (suffix + '.pcm.wav')
                service = self.service(output='pcm', extra_args=['--ao-pcm-file=' + str(output)])
                entry = dict(qid=suffix, path=str(path))
                service.sync([entry], suffix, restart=True)
                self.wait(lambda: output.exists() and output.stat().st_size > 1000)
                self.wait(lambda: not service._syncing and service.values.get('state') == 'stopped')
                service.shutdown()
                data = output.read_bytes()
                self.assertGreater(sum(value != 0 for value in data[100:]), 1000)
                if suffix in ('wav', 'flac', 'alac.m4a'):
                    # Verify the software PCM path preserves a lossless fixture;
                    # this does not assert anything about the PipeWire/DAC path.
                    with wave.open(str(output), 'rb') as decoded, wave.open(str(source), 'rb') as original:
                        self.assertEqual(decoded.getframerate(), original.getframerate())
                        self.assertEqual(decoded.getsampwidth(), original.getsampwidth())
                        self.assertEqual(decoded.readframes(decoded.getnframes()), original.readframes(original.getnframes()))
                self.assertEqual(service.errors, [])

    def test_pause_seek_resume_volume_stop_and_clean_shutdown(self):
        entry = tone(self.root / 'spaces " unicode é\n$(touch nope).wav', 8)
        service = self.service(output='null')  # real timed decoder, no audio hardware
        service.sync([entry], entry['qid'], restart=True)
        self.wait(lambda: service.values.get('time-pos', 0) and service.values['time-pos'] > .1)
        service.pause(True)
        self.wait(lambda: service.values.get('pause') is True)
        service.seek(4)
        self.wait(lambda: (service.values.get('time-pos') or 0) > 3.9)
        service.volume(73)
        self.wait(lambda: service.values.get('volume') == 73)
        service.pause(False)
        self.wait(lambda: service.values.get('pause') is False)
        directory = service._directory.name
        service.shutdown()
        self.assertFalse(service.running)
        self.assertFalse(Path(directory).exists())
        self.assertFalse((self.root / 'nope').exists())

    def test_native_completion_repeat_missing_files_and_rapid_switching(self):
        entries = [tone(self.root / f'{i}.wav', .5) for i in range(3)]
        service = self.service(output='null')
        service.sync(entries, entries[0]['qid'], restart=True)
        self.wait(lambda: entries[-1]['qid'] in service.currents)
        self.wait(lambda: service.values.get('idle-active') is True or service.values.get('state') == 'stopped')
        service.repeat('one')
        service.sync(entries, entries[1]['qid'], restart=True)
        self.wait(lambda: service._current == entries[1]['qid'] and not service._syncing)
        until = time.monotonic() + 1.1
        while time.monotonic() < until:
            self.app.processEvents(); time.sleep(.005)
        self.assertEqual(service._current, entries[1]['qid'])
        service.repeat('all')
        service.sync(entries, entries[-1]['qid'], restart=True)
        self.wait(lambda: service._current == entries[-1]['qid'] and not service._syncing)
        self.wait(lambda: service._current == entries[0]['qid'])
        service.repeat('off')
        missing = dict(qid='missing', path=str(self.root / 'missing.wav'))
        service.sync([missing, *entries], 'missing', restart=True)
        self.wait(lambda: any(qid == 'missing' for qid, _ in service.errors))
        self.wait(lambda: service._current == entries[0]['qid'])
        for entry in entries * 3:
            service.sync(entries, entry['qid'], restart=True)
        self.wait(lambda: not service._syncing and service._current == entries[-1]['qid'])
        service.shutdown()
        self.assertFalse(service.running)

    def test_upcoming_queue_edits_keep_decoder_position(self):
        entries = [tone(self.root / f'long{i}.wav', 5) for i in range(3)]
        service = self.service(output='null')
        service.sync(entries, entries[0]['qid'], restart=True)
        self.wait(lambda: (service.values.get('time-pos') or 0) > .2)
        position = service.values['time-pos']
        service.sync([entries[2], entries[0]], entries[0]['qid'])
        self.wait(lambda: not service._syncing and [e['qid'] for e in service._actual] == [entries[2]['qid'], entries[0]['qid']])
        self.assertEqual(service._current, entries[0]['qid'])
        self.assertGreaterEqual(service.values['time-pos'], position)
        service.stop()
        self.wait(lambda: service.values.get('state') == 'stopped')

    def test_missing_engine_reports_actionable_error(self):
        service = self.service(executable='/nonexistent/hibysync-mpv')
        service.sync([dict(qid='x', path='/tmp/missing.wav')], 'x', restart=True)
        self.wait(lambda: bool(service.errors))
        self.assertIn('sudo pacman -S mpv', service.errors[0][1])
        self.assertIn('sudo pacman -S mpv', service.errors[-1][1])

    def test_window_shutdown_during_real_playback_and_backend_disconnect(self):
        from hiby_music_tools.gui.quick import create_engine
        music = self.root / 'music'
        tone(music / 'track.wav', 5)
        database = self.root / 'index.sqlite3'
        refresh(music, database)
        service = self.service(output='null')
        engine, importer = create_engine(self.root / 'inbox', music, library_database=database,
                                         playback_service=service, player_state=self.root / 'player.json')
        player, browser = engine.player_controller, engine.library_controller
        try:
            window = engine.rootObjects()[0]
            self.wait(lambda: not player.busy)
            player.trackAction(tracks(music, database)[0]['id'], 'play')
            self.wait(lambda: player.position > .1)
            before = player.position
            current = player.currentQueueId
            for width, height, section in ((1600, 900, 'library'), (1200, 800, 'import'),
                                            (900, 800, 'device'), (750, 700, 'library')):
                window.resize(width, height)
                importer.navigate(section)
                self.app.processEvents()
                self.assertEqual(player.state, 'playing')
                self.assertEqual(player.currentQueueId, current)
            self.wait(lambda: player.position > before)
            service.socket.abort()
            self.wait(lambda: player.state == 'error' and not service.running)
            self.assertIn('control connection', player.error)
            player.togglePause()  # retry starts a fresh process with the same queue
            self.wait(lambda: service.running and player.position > .1)
            window.close()
            self.wait(lambda: not window.isVisible() and not service.running)
            self.assertTrue((self.root / 'player.json').exists())
            self.assertEqual(engine.load_errors, [])
        finally:
            player.shutdown()
            browser.shutdown()
            importer.shutdown()
            engine.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            for obj in (player, browser, importer):
                obj.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_library_save_releases_real_mpv_and_repaired_queue_plays_moved_file(self):
        from hiby_music_tools.gui.quick import create_engine
        music = self.root / 'music'
        tone(music / 'track.wav', 5)
        database = self.root / 'index.sqlite3'
        refresh(music, database)
        service = self.service(output='null')
        engine, importer = create_engine(self.root / 'inbox', music, library_database=database,
                                         playback_service=service, player_state=self.root / 'player.json')
        player, browser, editor = engine.player_controller, engine.library_controller, engine.metadata_controller
        released = []
        service.released.connect(lambda: released.append(not service.running))
        try:
            self.wait(lambda: not player.busy)
            row = tracks(music, database)[0]
            player.trackAction(row['id'], 'play')
            self.wait(lambda: player.position > .1)
            editor.edit('track', row['id'], True)
            self.wait(lambda: not editor.busy)
            editor.setField('title', 'Renamed while listening')
            editor.buildPreview()
            self.wait(lambda: not editor.busy)
            destination = editor.preview.rows[0]['destination']
            editor.save()
            self.wait(lambda: not editor.busy)
            self.assertEqual(released, [True])
            self.assertEqual(editor.report['saved'], 1, editor.results.rows)
            self.assertFalse(Path(row['path']).exists())
            self.assertEqual(player.current['path'], destination)
            self.assertEqual(player.state, 'stopped')
            editor.dismiss()
            player.togglePause()
            self.wait(lambda: player.state == 'playing' and player.position > .4)
            self.assertEqual(service.errors, [])
            self.assertEqual(engine.load_errors, [])
        finally:
            editor.shutdown()
            player.shutdown()
            browser.shutdown()
            importer.shutdown()
            engine.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            for obj in (editor, player, browser, importer):
                obj.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_unrelated_metadata_save_and_library_refresh_keep_real_playback_running(self):
        from hiby_music_tools.gui.quick import create_engine
        music = self.root / 'music'
        tone(music / 'listening.wav', 12)
        tone(music / 'other.wav', 1)
        database = self.root / 'index.sqlite3'
        refresh(music, database)
        service = self.service(output='null')
        engine, importer = create_engine(self.root / 'inbox', music, library_database=database,
                                         playback_service=service, player_state=self.root / 'player.json')
        player, browser, editor = engine.player_controller, engine.library_controller, engine.metadata_controller
        released = []
        service.released.connect(lambda: released.append(True))
        try:
            self.wait(lambda: not player.busy)
            rows = tracks(music, database)
            player.trackAction(rows[0]['id'], 'play')
            self.wait(lambda: player.position > .1 and not service._syncing and not service._commands and not service._inflight)
            before, qid = player.position, player.currentQueueId
            browser.refresh(False)
            self.wait(lambda: not browser.indexing)
            self.assertEqual(player.currentQueueId, qid)
            editor.edit('track', rows[1]['id'], False)
            self.wait(lambda: not editor.busy)
            editor.setField('title', 'Unrelated correction')
            editor.buildPreview()
            self.wait(lambda: not editor.busy)
            self.assertTrue(service.can_write_unreferenced([rows[1]['path']]))
            editor.save()
            self.wait(lambda: not editor.busy)
            self.assertEqual(editor.report['saved'], 1, editor.results.rows)
            self.assertEqual(released, [])
            self.assertEqual(player.state, 'playing')
            self.assertEqual(player.currentQueueId, qid)
            self.wait(lambda: player.position > before)
            self.assertEqual(service.errors, [])
        finally:
            for obj in (engine.playlist_controller, engine.deletion_controller, editor, player, browser, importer):
                obj.shutdown()
            engine.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            for obj in (editor, player, browser, importer): obj.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_delete_releases_real_mpv_and_surviving_queue_plays(self):
        from hiby_music_tools.gui.quick import create_engine
        music = self.root / 'music'
        tone(music / 'first.wav', 5)
        tone(music / 'second.wav', 5)
        database = self.root / 'index.sqlite3'
        refresh(music, database)
        service = self.service(output='null')
        engine, importer = create_engine(self.root / 'inbox', music, library_database=database,
                                         playback_service=service, player_state=self.root / 'player.json')
        player, browser = engine.player_controller, engine.library_controller
        editor, deletion = engine.metadata_controller, engine.deletion_controller
        released = []
        service.released.connect(lambda: released.append(not service.running))
        try:
            self.wait(lambda: not player.busy)
            rows = tracks(music, database)
            player.trackAction(rows[0]['id'], 'play')
            self.wait(lambda: player.position > .1)
            player.trackAction(rows[1]['id'], 'append')
            self.wait(lambda: not player.busy)
            deletion.request('track', rows[0]['id'])
            self.wait(lambda: not deletion.busy)
            self.assertTrue(Path(rows[0]['path']).exists())
            deletion.confirm()
            self.wait(lambda: not deletion.busy)
            self.assertEqual(released, [True])
            self.assertFalse(Path(rows[0]['path']).exists())
            self.assertEqual(len(tracks(music, database)), 1)
            self.assertEqual(player.current['id'], rows[1]['id'])
            self.assertEqual(player.state, 'stopped')
            player.togglePause()
            self.wait(lambda: player.state == 'playing' and player.position > .2)
            self.assertEqual(service.errors, [])
            self.assertEqual(engine.load_errors, [])
        finally:
            for obj in (deletion, editor, player, browser, importer):
                obj.shutdown()
            engine.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            for obj in (deletion, editor, player, browser, importer):
                obj.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_pipewire_output_integration_when_explicitly_requested(self):
        if os.environ.get('HIBYSYNC_TEST_PIPEWIRE') != '1':
            self.skipTest('Opt in with HIBYSYNC_TEST_PIPEWIRE=1 for a short audible tone')
        entry = tone(self.root / 'pipewire.wav', 2)
        service = self.service(output='pipewire')
        service.volume(20)
        service.sync([entry], entry['qid'], restart=True)
        self.wait(lambda: (service.values.get('time-pos') or 0) > .2)
        result = {}
        service._command(['get_property', 'current-ao'], lambda value: result.update(ao=value))
        service._command(['get_property', 'audio-out-params'], lambda value: result.update(params=value))
        self.wait(lambda: 'params' in result)
        self.assertEqual(result['ao'], 'pipewire')
        self.assertGreater(result['params']['samplerate'], 0)
        self.assertEqual(service.errors, [])

    def test_device_enumeration_selection_and_confirmed_output_diagnostics(self):
        service = self.service(output='null')
        audio = []
        service.audioChanged.connect(lambda data: audio.append(data))
        service.refresh_devices()
        self.wait(lambda: any(isinstance(d.get('audio-device-list'), list) for d in audio))
        self.assertIn('auto', {d['name'] for d in audio[-1]['audio-device-list']})
        entry = tone(self.root / 'diagnostic.wav', 3, rate=48000)
        service.sync([entry], entry['qid'], restart=True)
        self.wait(lambda: any(d.get('audio-out-params') for d in audio))
        self.assertEqual(audio[-1]['current-ao'], 'null')
        self.assertEqual(audio[-1]['audio-params']['samplerate'], 48000)
        service.select_device('auto')
        self.wait(lambda: audio[-1].get('audio-device') == 'auto')
        service._device = 'pipewire/disconnected-fixture'
        service._device_list([{'name':'auto','description':'Default'}])
        self.assertEqual(service._device, 'auto')
        self.assertTrue(any('unavailable' in error for _, error in service.errors))

    def test_default_driver_preference_can_be_reset_without_playing_audio(self):
        service = self.service()
        service.refresh_devices()
        self.wait(lambda: service._connected_flag and 'audio-device-list' in service._audio)
        service.select_device('auto')
        result = []
        service._command(['get_property', 'audio-device'], result.append)
        self.wait(lambda: bool(result))
        self.assertEqual(result, ['auto'])
        self.assertEqual(service.errors, [])

    def test_large_queue_planning_yields_and_stop_never_restarts(self):
        entry = tone(self.root / 'large.wav', 5)
        service = self.service(output='null')
        entries = [dict(entry, qid=str(i)) for i in range(3000)]
        ticks = []
        timer = QTimer()
        timer.timeout.connect(lambda: ticks.append(True))
        timer.start(5)
        service.sync(entries, '0')  # queue only; never starts the tone
        self.wait(lambda: service._connected_flag and not service._syncing and len(service._actual) == len(entries), timeout=20)
        self.assertGreater(len(ticks), 5)
        service.sync(entries, '1', restart=True)
        service.stop()  # Stop while the coalesced play request is still pending.
        self.wait(lambda: not service._syncing and service._manual_stop)
        timer.stop()
        service._command(['get_property', 'idle-active'], lambda value: service.values.update(test_idle=value))
        self.wait(lambda: 'test_idle' in service.values)
        self.assertTrue(service.values['test_idle'])
