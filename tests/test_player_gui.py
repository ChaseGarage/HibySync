"""Player QML/controller tests with an explicit fake audio service.

Real mpv decoding, timing, transitions, and output live in test_playback.py.
"""

import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['QT_QUICK_BACKEND'] = 'software'
from test_baseline import make_track

try:
    from PySide6.QtCore import QCoreApplication, QEvent, QPointF, Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQuick import QQuickItem
    from PySide6.QtTest import QTest
    from hiby_music_tools.gui.quick import create_engine
    from hiby_music_tools.gui.player_controller import PlayerController
    from hiby_music_tools.playback.service import PlaybackService
    from hiby_music_tools.playback import state as storage
    from hiby_music_tools.library.indexer import refresh
    QT = True
except ImportError:
    QT = False


if QT:
    class FakeAudio(PlaybackService):
        def __init__(self):
            super().__init__()
            self.calls = []

        def sync(self, entries, current, **kwargs):
            self.calls.append(('sync', [dict(e) for e in entries], current, kwargs))
            if kwargs.get('restart'):
                self.currentChanged.emit(current)
                self.properties.emit({'state': 'paused' if kwargs.get('paused') else 'playing',
                                      'time-pos': kwargs.get('position', 0), 'duration': 180})

        def pause(self, paused):
            self.calls.append(('pause', paused))
            self.properties.emit({'pause': paused})

        def stop(self):
            self.calls.append(('stop',))
            self.properties.emit({'state': 'stopped', 'time-pos': 0})

        def seek(self, value):
            self.calls.append(('seek', value))
            self.properties.emit({'time-pos': value})

        def volume(self, value):
            self.calls.append(('volume', value))

        def repeat(self, mode):
            self.calls.append(('repeat', mode))

        def close(self):
            self.calls.append(('close',))
            self.closed.emit()


@unittest.skipUnless(QT, 'Install PySide6 for player presentation tests')
class PlayerGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QGuiApplication.instance() or QGuiApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='hiby-player-qt-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.music = self.root / 'music'
        self.audio = FakeAudio()
        for index, title in enumerate(('Zulu', 'Alpha', 'Echo')):
            path = self.music / 'Artist/Album' / f'{index}.wav'
            make_track(path)
            from mutagen.wave import WAVE
            from mutagen.id3 import TIT2, TRCK
            audio = WAVE(path)
            audio.tags['TIT2'] = TIT2(text=[title])
            audio.tags['TRCK'] = TRCK(text=[str(index + 1)])
            audio.save()
        self.database = self.root / 'index.sqlite3'
        refresh(self.music, self.database)
        with mock.patch('hiby_music_tools.gui.quick.PlayerController',
                        side_effect=lambda browser, **kwargs: PlayerController(browser, service=self.audio, persist=False)):
            self.engine, self.importer = create_engine(self.root / 'inbox', self.music, library_database=self.database)
        self.browser, self.player = self.engine.library_controller, self.engine.player_controller
        self.window = self.engine.rootObjects()[0]
        self.addCleanup(self.cleanup)
        QTest.qWait(40)

    def cleanup(self):
        self.player.shutdown()
        self.browser.shutdown()
        self.importer.shutdown()
        self.app.processEvents()
        self.window.close()
        self.engine.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        for obj in (self.player, self.browser, self.importer, self.audio):
            obj.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def wait(self, condition):
        deadline = time.monotonic() + 10
        while not condition() and time.monotonic() < deadline:
            QTest.qWait(10)
        self.assertTrue(condition())
        QTest.qWait(20)

    def idle(self):
        self.wait(lambda: not self.player.busy and self.browser.query_task is None
                  and not self.browser._navigation_tasks
                  and self.browser._pending is None and not self.browser.timer.isActive())

    def item(self, name):
        from PySide6.QtCore import QObject
        # Delegates are visually parented to the view but are not necessarily
        # QObject children of the window. Prefer live visual items, then popups.
        pending = [self.window.contentItem()]
        visual = []
        while pending:
            item = pending.pop()
            if item.objectName() == name:
                return item
            visual.append(item)
            pending.extend(item.childItems())
        for item in [self.window, *visual]:
            nested = item.findChild(QObject, name)
            if nested is not None:
                return nested
        self.fail('Missing QML item: ' + name)

    def click(self, name, double=False):
        item = self.item(name)
        point = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
        function = QTest.mouseDClick if double else QTest.mouseClick
        function(self.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
        QTest.qWait(35)

    def test_double_click_filtered_sorted_context_and_persistent_bar(self):
        self.click('navigation_library')
        self.browser.setMode('songs')
        self.idle()
        self.browser.sortBy('title')  # descending
        self.idle()
        rows = list(self.browser.model.rows)
        self.click('librarySong_' + rows[1]['id'], double=True)
        self.idle()
        self.assertEqual([e['id'] for e in self.player.queue.entries], [e['id'] for e in rows])
        self.assertEqual(self.player.currentTrackId, rows[1]['id'])
        self.assertEqual(self.player.state, 'playing')
        self.click('playerPlayPause')
        self.assertEqual(self.player.state, 'paused')
        self.click('playerPlayPause')
        self.assertEqual(self.player.state, 'playing')
        self.player.seek(30)
        self.assertEqual(self.player.position, 30)
        self.player.setVolume(80)
        self.assertEqual(self.player.volume, 80)
        self.click('navigation_import')
        self.assertTrue(self.item('playerBar').isVisible())
        self.assertEqual(self.player.state, 'playing')
        self.click('navigation_device')
        self.assertEqual(self.player.state, 'playing')
        self.assertEqual(self.engine.load_errors, [])

    def test_album_actions_queue_edits_and_current_selection(self):
        self.click('navigation_library')
        self.idle()
        album = self.browser.model.rows[0]
        self.browser.openAlbum(album['id'])
        self.idle()
        self.click('playLibraryAlbum')
        self.idle()
        self.assertEqual([e['title'] for e in self.player.queue.entries], ['Zulu', 'Alpha', 'Echo'])
        current = self.player.currentQueueId
        self.click('playerQueue')
        self.assertTrue(self.item('queueDrawer').property('visible'))
        last = self.player.queue.entries[-1]['qid']
        self.player.move(last, 1)
        self.assertEqual(self.player.currentQueueId, current)
        self.assertEqual(self.player.queue.entries[1]['qid'], last)
        self.player.next()
        self.assertEqual(self.player.currentQueueId, last)
        self.player.previous()
        self.assertEqual(self.player.currentQueueId, current)
        self.player.toggleShuffle()
        self.assertTrue(self.player.shuffle)
        self.player.cycleRepeat()
        self.assertEqual(self.player.repeat, 'all')
        self.player.remove(current)
        self.assertNotEqual(self.player.currentQueueId, current)
        self.player.clear()
        self.assertEqual(self.player.count, 0)
        self.assertEqual(self.player.state, 'stopped')
        self.assertEqual(self.engine.load_errors, [])

    def test_add_next_does_not_start_idle_queue_and_reports_errors(self):
        self.click('navigation_library')
        self.browser.setMode('songs')
        self.idle()
        rows = self.browser.model.rows
        self.player.trackAction(rows[0]['id'], 'append')
        self.idle()
        self.assertEqual(self.player.state, 'stopped')
        self.player.togglePause()
        self.player.trackAction(rows[1]['id'], 'next')
        self.idle()
        self.assertEqual(self.player.queue.entries[1]['id'], rows[1]['id'])
        self.audio.playbackError.emit(self.player.currentQueueId, 'Audio device unavailable')
        self.assertIn('Audio device unavailable', self.player.error)
        self.player.next()
        self.assertEqual(self.player.currentTrackId, rows[1]['id'])
        self.assertEqual(self.player.error, '')

    def test_restore_preferences_and_queue_without_autoplay(self):
        self.click('navigation_library')
        self.browser.setMode('songs')
        self.idle()
        self.player.trackAction(self.browser.model.rows[0]['id'], 'play')
        self.idle()
        self.player.setVolume(84)
        self.player.cycleRepeat()
        self.player.toggleShuffle()
        self.player.seek(18)
        state = self.root / 'state/player.json'
        self.player._persist = True
        self.player._state_file = state
        self.player._save()
        self.wait(lambda: self.player.save_task is None)
        saved = storage.load(state)
        self.assertEqual(saved['position'], 18)
        audio = FakeAudio()
        restored = PlayerController(self.browser, service=audio, state_file=state)
        self.wait(lambda: not restored.busy)
        self.assertEqual(restored.state, 'stopped')
        self.assertEqual(restored.volume, 84)
        self.assertEqual(restored.repeat, 'all')
        self.assertTrue(restored.shuffle)
        self.assertEqual(restored.position, 18)
        self.assertFalse(any(call[0] == 'sync' for call in audio.calls))
        restored.togglePause()
        self.assertEqual(audio.calls[-1][-1]['position'], 18)
        restored.shutdown()
        restored.deleteLater()
        audio.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_row_selection_and_single_control_operation_with_live_state(self):
        self.click('navigation_library')
        self.browser.setMode('songs')
        self.idle()
        rows = list(self.browser.model.rows)
        self.click('librarySong_' + rows[0]['id'])
        self.assertEqual(self.player.count, 0)
        row = self.item('librarySong_' + rows[0]['id'])
        self.assertTrue(row.property('selected'))
        self.audio.calls.clear()
        self.click('playSong_' + rows[0]['id'])
        self.idle()
        self.assertEqual(len([call for call in self.audio.calls if call[0] == 'sync']), 1)
        self.assertTrue(row.property('playing'))
        queue_ids = [e['qid'] for e in self.player.queue.entries]
        self.click('playSong_' + rows[0]['id'])
        self.assertEqual(self.audio.calls[-1], ('pause', True))
        self.assertTrue(row.property('paused'))
        self.click('playSong_' + rows[0]['id'])
        self.assertEqual(self.audio.calls[-1], ('pause', False))
        self.assertEqual([e['qid'] for e in self.player.queue.entries], queue_ids)
        self.player.next()
        self.assertFalse(row.property('loaded'))
        active = self.item('librarySong_' + self.player.currentTrackId)
        self.assertTrue(active.property('playing'))
        self.player.toggleShuffle()
        self.assertTrue(active.property('playing'))
        self.player.playEntry(self.player.queue.entries[-1]['qid'])
        self.assertTrue(self.item('librarySong_' + self.player.currentTrackId).property('playing'))
        self.player.stop()
        self.assertFalse(self.item('librarySong_' + self.player.currentTrackId).property('loaded'))
        self.assertEqual(self.engine.load_errors, [])

    def test_keyboard_navigation_enter_space_and_editable_focus(self):
        self.click('navigation_library')
        self.browser.setMode('songs')
        self.idle()
        rows = list(self.browser.model.rows)
        self.click('librarySong_' + rows[0]['id'])
        QTest.keyClick(self.window, Qt.Key.Key_Down)
        self.assertTrue(self.item('librarySong_' + rows[1]['id']).property('selected'))
        QTest.keyClick(self.window, Qt.Key.Key_Return)
        self.idle()
        self.assertEqual(self.player.currentTrackId, rows[1]['id'])
        self.assertEqual(len([c for c in self.audio.calls if c[0] == 'sync']), 1)
        QTest.keyClick(self.window, Qt.Key.Key_Space)
        self.assertEqual(self.player.state, 'paused')
        QTest.keyClick(self.window, Qt.Key.Key_Space)
        self.assertEqual(self.player.state, 'playing')
        control = self.item('playSong_' + rows[1]['id'])
        control.forceActiveFocus()
        before = len([c for c in self.audio.calls if c[0] == 'pause'])
        QTest.keyClick(self.window, Qt.Key.Key_Return)
        self.assertEqual(len([c for c in self.audio.calls if c[0] == 'pause']), before + 1)
        self.assertEqual(self.player.state, 'paused')
        search = self.item('librarySearchInput')
        search.forceActiveFocus()
        for letter in 'one two':
            QTest.keyClick(self.window, Qt.Key.Key_Space if letter == ' ' else Qt.Key(ord(letter.upper())))
        self.assertEqual(search.property('text'), 'one two')
        self.assertEqual(self.player.state, 'paused')
        self.assertEqual(len([c for c in self.audio.calls if c[0] == 'pause']), before + 1)
        self.browser.setSearch('')
        self.idle()
        self.click('songMenu_' + rows[0]['id'])
        self.assertTrue(self.item('librarySong_' + rows[0]['id']).property('menuOpen'))
        QTest.keyClick(self.window, Qt.Key.Key_Escape)
        QTest.qWait(30)
        self.assertFalse(self.item('librarySong_' + rows[0]['id']).property('menuOpen'))
        make_track(self.root / 'inbox/Album/song.wav')
        self.importer.scan()
        self.wait(lambda: self.importer.task is None)
        self.importer.openAlbum(0)
        self.click('editAlbumButton')
        editor = self.item('albumArtistInput')
        original = editor.property('text')
        editor.forceActiveFocus()
        QTest.keyClick(self.window, Qt.Key.Key_End)
        QTest.keyClick(self.window, Qt.Key.Key_Space)
        self.assertEqual(editor.property('text'), original + ' ')
        self.assertEqual(self.player.state, 'paused')
        self.assertEqual(self.engine.load_errors, [])

    def test_responsive_layout_columns_alignment_and_transport_center(self):
        self.click('navigation_library')
        self.browser.setMode('songs')
        self.idle()
        identifier = self.browser.model.rows[0]['id']
        self.player.playContext(identifier)
        self.idle()
        self.audio.calls.clear()
        for width, height in ((1600, 900), (1200, 800), (900, 800), (750, 700), (1200, 800)):
            with self.subTest(width=width):
                self.window.resize(width, height)
                QTest.qWait(60)
                row = self.item('librarySong_' + identifier)
                self.assertEqual(self.window.width(), width)
                self.assertTrue(row.property('playing'))
                self.assertGreaterEqual(row.width(), width - 200)
                for name in ('playerPlayPause', 'playerPrevious', 'playerNext', 'playerQueue', 'playerSeek', 'playSong_' + identifier, 'songMenu_' + identifier):
                    item = self.item(name)
                    point = item.mapToScene(QPointF(0, 0))
                    self.assertTrue(item.isVisible(), name)
                    self.assertGreaterEqual(point.x(), 0, name)
                    self.assertLessEqual(point.x() + item.width(), width + 1, name)
                    self.assertLessEqual(point.y() + item.height(), height + 1, name)
                    self.assertGreaterEqual(item.height(), 28, name)
                artist = self.item('songArtist_' + identifier)
                header = self.item('sortLibraryArtist')
                self.assertAlmostEqual(artist.mapToScene(QPointF()).x(), header.mapToScene(QPointF()).x(), delta=1)
                self.assertEqual(self.item('songAlbum_' + identifier).isVisible(), row.width() >= 880)
                self.assertEqual(self.item('songYear_' + identifier).isVisible(), row.width() >= 1100)
                if width >= 1200:
                    transport = self.item('playerTransport')
                    self.assertAlmostEqual(transport.mapToScene(QPointF(transport.width() / 2, 0)).x(), width / 2, delta=1)
                else:
                    self.click('playerOptions')
                    self.assertTrue(self.item('playerVolumeCompact').isVisible())
                    QTest.keyClick(self.window, Qt.Key.Key_Escape)
        self.assertFalse(any(c[0] in ('sync', 'pause', 'stop') for c in self.audio.calls))
        self.assertEqual(self.engine.load_errors, [])

    def test_seek_click_drag_live_updates_keyboard_and_track_change(self):
        self.click('navigation_library')
        self.browser.setMode('songs')
        self.idle()
        self.player.playContext(self.browser.model.rows[0]['id'])
        self.idle()
        slider = self.item('playerSeek')
        def point(fraction):
            return slider.mapToScene(QPointF(slider.width() * fraction, slider.height() / 2)).toPoint()
        self.audio.calls.clear()
        QTest.mouseClick(self.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point(.75))
        self.assertEqual(len([c for c in self.audio.calls if c[0] == 'seek']), 1)
        self.assertAlmostEqual(self.player.position, 135, delta=4)
        self.audio.calls.clear()
        QTest.mousePress(self.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point(.25))
        QTest.mouseMove(self.window, point(.6))
        held = slider.property('value')
        for index in range(20):
            self.audio.properties.emit({'time-pos': 5 + index / 10})
        self.assertAlmostEqual(slider.property('value'), held, delta=.01)
        QTest.mouseRelease(self.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point(.6))
        self.assertEqual(len([c for c in self.audio.calls if c[0] == 'seek']), 1)
        self.assertAlmostEqual(self.player.position, held, delta=.01)
        self.audio.properties.emit({'time-pos': held + 1})
        self.assertAlmostEqual(slider.property('value'), held + 1, delta=.01)
        slider.forceActiveFocus()
        QTest.keyClick(self.window, Qt.Key.Key_Left)
        self.assertAlmostEqual(self.player.position, held - 4, delta=.01)
        self.audio.calls.clear()
        QTest.mousePress(self.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point(.5))
        self.player.next()
        QTest.mouseRelease(self.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point(.5))
        self.assertFalse(any(c[0] == 'seek' for c in self.audio.calls))
        self.assertEqual(self.engine.load_errors, [])

    def test_position_updates_do_not_refresh_track_state_or_models(self):
        self.click('navigation_library')
        self.browser.setMode('songs')
        self.idle()
        self.player.playContext(self.browser.model.rows[0]['id'])
        self.idle()
        events = dict(track=[], state=[], position=[], queue=[], library=[])
        self.player.trackChanged.connect(lambda: events['track'].append(True))
        self.player.stateChanged.connect(lambda: events['state'].append(True))
        self.player.positionChanged.connect(lambda: events['position'].append(True))
        self.player.model.modelReset.connect(lambda: events['queue'].append(True))
        self.browser.model.modelReset.connect(lambda: events['library'].append(True))
        with mock.patch('hiby_music_tools.gui.player_controller.tracks', side_effect=AssertionError('Position must not query the index')):
            for index in range(1, 201):
                self.audio.properties.emit({'time-pos': index / 10})
            QTest.qWait(40)
        self.assertEqual(len(events['position']), 200)
        for name in ('track', 'state', 'queue', 'library'):
            self.assertEqual(events[name], [], name)
        self.assertEqual(self.engine.load_errors, [])

    def test_album_single_scroll_virtualization_and_identity_after_navigation(self):
        import shutil
        seed = self.music / 'Artist/Album/0.wav'
        for index in range(75):
            shutil.copy2(seed, seed.parent / f'added-{index}.wav')
        refresh(self.music, self.database)
        self.click('navigation_library')
        self.idle()
        album = self.browser.model.rows[0]
        self.browser.openAlbum(album['id'])
        self.idle()
        self.click('playLibraryAlbum')
        self.idle()
        current_id = self.player.currentTrackId
        # All added files have the same title, but only one stable ID is active.
        listing = self.item('libraryAlbumTracks')
        current = self.item('librarySong_' + current_id)
        self.assertTrue(current.property('playing'))
        other = next(r for r in self.browser.model.rows if r['id'] != current_id and r['title'] == self.player.current['title'])
        self.assertFalse(self.item('librarySong_' + other['id']).property('playing'))
        listing.setProperty('contentY', 800)
        QTest.qWait(50)
        play = self.item('playLibraryAlbum')
        self.assertLess(play.mapToScene(QPointF()).y(), 0)
        visible_rows = [obj for obj in self.window.findChildren(QQuickItem) if obj.objectName().startswith('librarySong_')]
        self.assertLess(len(visible_rows), len(self.browser.model.rows))
        self.click('navigation_import')
        self.assertEqual(self.player.state, 'playing')
        self.click('navigation_library')
        self.idle()
        self.assertTrue(self.item('librarySong_' + current_id).property('playing'))
        self.player.togglePause()
        self.assertTrue(self.item('librarySong_' + current_id).property('paused'))
        self.assertEqual(self.engine.load_errors, [])

    def click_link(self, name):
        item = self.item(name)
        point = item.mapToScene(QPointF(min(item.width(), item.property('paintedWidth')) / 2, item.height() / 2)).toPoint()
        QTest.mouseMove(self.window, QPointF(5, 90).toPoint())
        QTest.qWait(10)
        self.assertFalse(item.property('hovered'))
        QTest.mouseMove(self.window, point)
        QTest.qWait(15)
        self.assertTrue(item.property('hovered'))
        self.assertTrue(item.property('font').underline())
        QTest.mouseClick(self.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
        self.idle()

    def test_artist_album_links_hover_navigation_and_unmodified_playback(self):
        self.click('navigation_library')
        self.browser.setMode('songs')
        self.idle()
        row = self.browser.model.rows[0]
        self.player.playContext(row['id'])
        self.idle()
        queue = [entry['qid'] for entry in self.player.queue.entries]
        self.audio.calls.clear()
        self.click_link('songAlbum_' + row['id'])
        self.assertEqual(self.browser.mode, 'album')
        self.assertEqual(self.browser.album['id'], row['album_id'])
        self.click_link('albumHeaderTitle')  # Opening the same album retains Back.
        self.browser.back()
        self.idle()
        self.assertEqual(self.browser.mode, 'songs')
        self.browser.setSearch(row['title'])
        self.idle()
        self.click_link('songArtist_' + row['id'])
        self.assertEqual(self.browser.artistName, row['artist'])
        self.assertEqual(self.browser.search, '')
        album = self.browser.model.rows[0]
        self.click_link('albumTitle_' + album['id'])
        self.assertEqual(self.browser.album['id'], album['id'])
        self.click_link('albumHeaderArtist')
        self.assertEqual(self.browser.artistName, 'Album Artist')
        album = self.browser.model.rows[0]
        self.click_link('albumArtist_' + album['id'])
        self.assertEqual(self.browser.mode, 'albums')
        self.assertEqual(self.browser.artistName, 'Album Artist')
        self.assertEqual(self.player.state, 'playing')
        self.assertEqual([entry['qid'] for entry in self.player.queue.entries], queue)
        self.assertEqual(self.audio.calls, [])
        self.assertEqual(self.engine.load_errors, [])

    def test_player_and_queue_links_navigate_from_other_sections(self):
        self.click('navigation_library')
        self.browser.setMode('songs')
        self.idle()
        row = self.browser.model.rows[0]
        self.player.playContext(row['id'])
        self.idle()
        self.click('navigation_import')
        self.audio.calls.clear()
        self.click_link('playerArtistLink')
        self.assertEqual(self.importer.page, 'library')
        self.assertEqual(self.browser.artistName, row['artist'])
        self.click('navigation_device')
        self.click_link('playerAlbumLink')
        self.assertEqual(self.importer.page, 'library')
        self.assertEqual(self.browser.album['id'], row['album_id'])
        self.click('playerQueue')
        self.click_link('queueArtist_' + self.player.currentQueueId)
        self.assertFalse(self.item('queueDrawer').property('visible'))
        self.assertEqual(self.browser.artistName, row['artist'])
        self.assertEqual(self.player.state, 'playing')
        self.assertEqual(self.audio.calls, [])
        self.assertEqual(self.engine.load_errors, [])

    def test_navigation_resolves_ids_without_audio_reads_and_keyboard_link(self):
        from hiby_music_tools.library.navigation import track_target
        self.click('navigation_library')
        self.browser.setMode('songs')
        self.idle()
        row = self.browser.model.rows[0]
        target = track_target(self.music, self.database, identifier=row['id'], target='artist')
        self.assertEqual(target['name'], row['artist'])
        self.assertEqual(track_target(self.music, self.database, identifier='missing', target='album'), {})
        self.assertEqual(track_target(self.root / 'other', self.database, identifier=row['id'], target='artist'), {})
        with self.assertRaises(ValueError):
            track_target(self.music, self.database, identifier=row['id'], target='invalid')
        link = self.item('songArtist_' + row['id'])
        link.forceActiveFocus()
        self.assertTrue(link.property('font').underline())
        QTest.keyClick(self.window, Qt.Key.Key_Return)
        self.idle()
        self.assertEqual(self.browser.artistId, target['id'])
        self.assertEqual(self.player.count, 0)
        self.assertEqual(self.engine.load_errors, [])

    def test_pending_navigation_is_cancelled_by_new_destination_and_close(self):
        from threading import Event
        from hiby_music_tools.library.navigation import track_target
        self.click('navigation_library')
        self.browser.setMode('songs')
        self.idle()
        row = self.browser.model.rows[0]
        started, release = Event(), Event()
        def slow_lookup(*args, operation, **kwargs):
            started.set()
            while not release.wait(.005):
                operation.checkpoint()
            return track_target(*args, operation=operation, **kwargs)
        with mock.patch('hiby_music_tools.gui.library_controller.track_target', side_effect=slow_lookup):
            self.browser.visitTrack(row['id'], 'artist')
            self.wait(started.is_set)
            self.browser.visitAlbum(row['album_id'])
            release.set()
            self.idle()
            self.assertEqual(self.browser.mode, 'album')
            self.assertEqual(self.browser.album['id'], row['album_id'])
            started.clear()
            release.clear()
            self.browser.visitTrack(row['id'], 'artist')
            self.wait(started.is_set)
            self.window.close()
            self.wait(lambda: not self.window.isVisible() and not self.browser._navigation_tasks)
        self.assertEqual(self.engine.load_errors, [])
