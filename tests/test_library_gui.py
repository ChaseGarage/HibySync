"""Offscreen Library browsing, background indexing, and paged model integration."""

import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest import mock
import uuid

from PIL import Image
from mutagen.id3 import TALB, TIT2, TPE1, TPE2, TPOS, TRCK
from mutagen.wave import WAVE
from test_baseline import make_track

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['QT_QUICK_BACKEND'] = 'software'
try:
    from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, QSize, QTimer, Qt
    from PySide6.QtGui import QGuiApplication, QWheelEvent
    from PySide6.QtQuick import QQuickItem
    from PySide6.QtTest import QTest
    from hiby_music_tools.gui.quick import create_engine
    from hiby_music_tools.gui.library_models import LibraryArtworkProvider
    from hiby_music_tools.library import indexer
    from hiby_music_tools.library.database import connect
    from hiby_music_tools.library.queries import PAGE_SIZE
    HAS_QT = True
except ImportError:
    HAS_QT = False


@unittest.skipUnless(HAS_QT, 'Install PySide6 for QML integration tests')
class LibraryGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QGuiApplication.instance() or QGuiApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='hiby-library-qt-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.music = self.root / 'music'
        self.music.mkdir()
        self.db = self.root / 'cache/index.sqlite3'
        self.engine, self.importer = create_engine(self.root / 'inbox', self.music, library_database=self.db)
        self.assertTrue(self.engine.rootObjects(), self.engine.load_errors)
        self.window = self.engine.rootObjects()[0]
        self.browser = self.engine.library_controller
        self.addCleanup(self.cleanup_engine)
        QTest.qWait(40)

    def cleanup_engine(self):
        self.browser.shutdown()
        self.importer.shutdown()
        self.app.processEvents()
        self.window.close()
        self.engine.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.browser.deleteLater()
        self.importer.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def wait_for(self, condition):
        deadline = time.monotonic() + 12
        while not condition() and time.monotonic() < deadline:
            QTest.qWait(10)
        self.assertTrue(condition(), 'Library worker did not finish')
        QTest.qWait(25)

    def idle(self):
        self.wait_for(lambda: self.browser.index_task is None and self.browser.query_task is None
                      and self.browser._pending is None and not self.browser.timer.isActive())

    def item(self, name):
        result = self.window.findChild(QQuickItem, name)
        if result is None:
            pending = [self.window.contentItem()]
            while pending:
                candidate = pending.pop()
                if candidate.objectName() == name:
                    result = candidate
                    break
                pending.extend(candidate.childItems())
        self.assertIsNotNone(result, name)
        return result

    def click(self, name):
        item = self.item(name)
        self.assertTrue(item.isVisible(), name)
        self.assertTrue(item.isEnabled(), name)
        point = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
        QTest.mouseClick(self.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
        QTest.qWait(30)

    def track(self, relative='Artist/Double/CD1/one.wav', *, title='Alpha', artist='Artist', album='Double', disc='1'):
        path = self.music / relative
        make_track(path)
        audio = WAVE(path)
        for key, value in (('TIT2', TIT2(text=[title])), ('TPE1', TPE1(text=[artist])),
                           ('TPE2', TPE2(text=['Artist'])), ('TALB', TALB(text=[album])),
                           ('TPOS', TPOS(text=[disc])), ('TRCK', TRCK(text=['1']))):
            audio.tags[key] = value
        audio.save()
        return path

    def test_grid_artist_album_detail_song_search_and_sort(self):
        one = self.track()
        self.track('Artist/Double/CD2/two.wav', title='Beta', artist='Guest', disc='2')
        self.track('Artist/Second/three.wav', title='Zebra', album='Second')
        Image.new('RGB', (900, 900), 'blue').save(one.parent.parent / 'cover.jpg')
        before = {p: p.read_bytes() for p in self.music.rglob('*') if p.is_file()}
        self.assertFalse(self.db.exists())  # Startup reads the index; it does not scan music.
        self.click('navigation_library')
        self.idle()
        self.assertFalse(self.db.exists())
        self.click('libraryRefreshButton')
        self.idle()
        self.assertEqual(self.browser.summary['tracks'], 3)
        self.assertEqual(self.browser.model.total, 2)
        album = next(row for row in self.browser.model.rows if row['title'] == 'Double')
        self.click('libraryAlbum_' + album['id'])
        self.idle()
        self.assertEqual(self.browser.mode, 'album')
        self.assertTrue(self.browser.album['multiDisc'])
        self.assertEqual(self.browser.album['track_count'], 2)
        self.assertEqual([row['disc_sort'] for row in self.browser.model.rows], [1, 2])
        self.click('libraryBackButton')
        self.idle()
        self.click('libraryArtistsMode')
        self.idle()
        guest = next(row for row in self.browser.model.rows if row['name'] == 'Guest')
        self.click('libraryArtist_' + guest['id'])
        self.idle()
        self.assertEqual(self.browser.artistName, 'Guest')
        self.assertEqual(self.browser.model.total, 1)
        self.click('librarySongsMode')
        self.idle()
        self.assertEqual(self.browser.model.total, 3)
        self.item('librarySearchInput').setProperty('text', 'Guest')
        self.idle()
        self.assertEqual(self.browser.model.total, 1)
        self.assertEqual(self.browser.model.rows[0]['title'], 'Beta')
        self.click('sortLibraryArtist')
        self.idle()
        self.assertEqual(self.browser.sort, 'artist')
        self.window.resize(800, 600)
        QTest.qWait(50)
        self.assertEqual(self.engine.load_errors, [])
        self.assertEqual(before, {p: p.read_bytes() for p in self.music.rglob('*') if p.is_file()})

    def test_paged_song_model_does_not_load_entire_large_catalog(self):
        self.track()
        indexer.refresh(self.music, self.db)
        with connect(self.db, write=True) as con:
            seed = dict(con.execute('SELECT * FROM tracks').fetchone())
            keys = list(seed)
            values = []
            for i in range(3000):
                row = {**seed, 'id': str(uuid.uuid4()), 'relpath': f'synthetic/{i}.wav',
                       'title': f'Track {i:05}', 'title_sort': f'track {i:05}', 'search_text': f'track {i:05}'}
                values.append([row[key] for key in keys])
            con.executemany(f'INSERT INTO tracks({",".join(keys)}) VALUES({",".join("?" for _ in keys)})', values)
            con.commit()
        self.click('navigation_library')
        self.idle()
        self.click('librarySongsMode')
        self.idle()
        self.assertEqual(self.browser.model.total, 3001)
        initial = len(self.browser.model.rows)
        self.assertLessEqual(initial, PAGE_SIZE * 2)
        self.browser.loadMore()
        self.idle()
        self.assertGreater(len(self.browser.model.rows), initial)
        self.assertLess(len(self.browser.model.rows), self.browser.model.total)
        self.browser.setSearch('track 02999')
        self.idle()
        self.assertEqual(self.browser.model.total, 1)
        self.assertEqual(self.engine.load_errors, [])

    def test_queries_work_during_refresh_and_cancel_rolls_back(self):
        seed = self.track()
        indexer.refresh(self.music, self.db)
        self.click('navigation_library')
        self.idle()
        for index in range(180):
            shutil.copy2(seed, seed.parent / f'{index:04}.wav')
        reader = indexer.read_metadata
        def slow_read(*args):
            time.sleep(0.004)
            return reader(*args)
        ticks = []
        timer = QTimer()
        timer.timeout.connect(lambda: ticks.append(True))
        timer.start(5)
        with mock.patch.object(indexer, 'read_metadata', side_effect=slow_read):
            self.click('libraryRefreshButton')
            self.wait_for(lambda: len(ticks) >= 5)
            self.assertIsNotNone(self.browser.index_task)
            self.browser.setMode('songs')
            self.wait_for(lambda: self.browser.query_task is None)
            self.assertEqual(self.browser.model.total, 1)
            self.browser.cancel()
            self.idle()
        timer.stop()
        self.assertIn('cancelled', self.browser.message)
        self.assertEqual(self.browser.model.total, 1)
        self.assertEqual(len(list(self.music.rglob('*.wav'))), 181)
        self.assertEqual(self.engine.load_errors, [])

    def test_configured_path_changes_and_import_staleness(self):
        self.track()
        self.click('navigation_library')
        self.click('libraryRefreshButton')
        self.idle()
        other = self.root / 'other-library'
        other.mkdir()
        self.importer.setPaths(str(self.root / 'inbox'), str(other))
        self.idle()
        self.assertEqual(self.browser.root, str(other))
        self.assertEqual(self.browser.model.total, 0)
        self.importer.libraryChanged.emit()
        self.browser.activate()
        self.idle()
        self.assertTrue(self.browser.summary['scanned'])
        self.assertEqual(self.browser.summary['tracks'], 0)

    def test_thumbnail_provider_is_bounded_and_rejects_full_size_cache_files(self):
        directory = self.root / 'thumbs'
        directory.mkdir()
        provider = LibraryArtworkProvider(directory, capacity=4)
        for i in range(8):
            key = f'{i:064x}'
            Image.new('RGB', (48, 48), 'blue').save(directory / (key + '.png'))
            image = provider.requestImage(key, QSize(), QSize(48, 48))
            self.assertEqual(image.width(), 48)
        self.assertEqual(len(provider.images), 4)
        key = 'f' * 64
        Image.new('RGB', (1000, 1000)).save(directory / (key + '.png'))
        self.assertTrue(provider.requestImage(key, QSize(), QSize()).isNull())
        self.assertTrue(provider.requestImage('../outside', QSize(), QSize()).isNull())

    def test_library_is_startup_page_and_reads_cached_index_without_scanning(self):
        self.assertEqual(self.importer.page, 'library')
        self.idle()
        self.assertFalse(self.db.exists())
        self.track()
        indexer.refresh(self.music, self.db)
        with mock.patch('hiby_music_tools.gui.library_controller.refresh',
                        side_effect=AssertionError('Startup must not scan music')):
            engine, importer = create_engine(self.root / 'inbox', self.music, library_database=self.db)
            browser = engine.library_controller
            try:
                self.assertEqual(importer.page, 'library')
                self.wait_for(lambda: browser.query_task is None and browser.summary['tracks'] == 1)
                self.assertEqual(browser.model.total, 1)
                self.assertIsNone(browser.index_task)
                self.assertFalse(browser.error)
                self.assertIsNone(importer.session)
                self.assertEqual(engine.load_errors, [])
            finally:
                browser.shutdown()
                engine.player_controller.shutdown()
                importer.shutdown()
                engine.rootObjects()[0].close()
                engine.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                browser.deleteLater()
                importer.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_mouse_wheel_scrolls_substantially_faster_in_real_song_list(self):
        seed = self.track()
        for index in range(150):
            shutil.copy2(seed, seed.parent / f'wheel-{index}.wav')
        indexer.refresh(self.music, self.db)
        hints = QGuiApplication.styleHints()
        configured = hints.wheelScrollLines()
        self.assertGreaterEqual(configured, 9)
        def distance(lines):
            hints.setWheelScrollLines(lines)
            # Flickable reads the wheel distance when the view is constructed.
            self.browser.setMode('artists')
            self.idle()
            self.browser.setMode('songs')
            self.idle()
            view = self.item('librarySongList')
            point = view.mapToScene(QPointF(view.width() / 3, view.height() / 2))
            origin = view.property('contentY')
            event = QWheelEvent(point, self.window.mapToGlobal(point.toPoint()), QPoint(), QPoint(0, -120),
                                Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                                Qt.ScrollPhase.NoScrollPhase, False)
            event.setTimestamp(1000)
            QCoreApplication.sendEvent(self.window, event)
            QTest.qWait(450)
            return view.property('contentY') - origin
        try:
            standard, faster = distance(3), distance(configured)
            self.assertGreater(standard, 0)
            self.assertGreater(faster, standard * 2, (standard, faster))
            self.assertGreater(faster, 100)
        finally:
            hints.setWheelScrollLines(configured)
        self.assertEqual(self.engine.load_errors, [])

    def test_close_cancels_index_worker_before_destroying_window(self):
        seed = self.track()
        for index in range(80):
            shutil.copy2(seed, seed.parent / f'copy-{index}.wav')
        self.click('navigation_library')
        self.idle()
        reader = indexer.read_metadata
        def slow_read(*args):
            time.sleep(0.004)
            return reader(*args)
        with mock.patch.object(indexer, 'read_metadata', side_effect=slow_read):
            self.browser.refresh(False)
            QTest.qWait(30)
            self.assertIsNotNone(self.browser.index_task)
            self.window.close()
            self.wait_for(lambda: self.browser.index_task is None and self.browser.query_task is None)
        self.assertFalse(self.window.isVisible())
        self.assertEqual(len(list(self.music.rglob('*.wav'))), 81)
        self.assertEqual(self.engine.load_errors, [])


if __name__ == '__main__':
    unittest.main()
