"""QML presentation tests with real fixtures and actual control activation."""

import os
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from PIL import Image
from test_baseline import ROOT, make_track

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['QT_QUICK_BACKEND'] = 'software'
try:
    from PySide6.QtCore import QCoreApplication, QEvent, QObject, QPointF, QTimer, Qt
    from PySide6.QtGui import QFontInfo, QFontMetricsF, QGuiApplication
    from PySide6.QtQuick import QQuickItem
    from PySide6.QtTest import QTest
    from hiby_music_tools.gui.quick import create_engine
    from hiby_music_tools.core import scan
    HAS_QUICK = True
except ImportError:
    HAS_QUICK = False


@unittest.skipUnless(HAS_QUICK, 'Install the gui extra to run QML tests')
class QuickTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QGuiApplication.instance() or QGuiApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='hiby-qml-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.inbox = self.root / 'inbox'
        self.inbox.mkdir()
        self.library = self.root / 'library'
        for module in ('scan', 'apple_art', 'importing'):
            patch = mock.patch(f'hiby_music_tools.core.{module}.metadata_dir', return_value=self.root / 'cache')
            patch.start()
            self.addCleanup(patch.stop)
        self.engine, self.controller = create_engine(self.inbox, self.library)
        self.controller.navigate('import')  # These tests exercise the Import workflow.
        self.assertTrue(self.engine.rootObjects(), '\n'.join(self.engine.load_errors))
        self.window = self.engine.rootObjects()[0]
        self.addCleanup(self.cleanup_engine)
        QTest.qWait(50)

    def cleanup_engine(self):
        self.controller.shutdown()
        self.engine.library_controller.shutdown()
        self.engine.player_controller.shutdown()
        self.app.processEvents()
        self.window.close()
        self.engine.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.controller.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def wait_for(self, condition):
        deadline = time.monotonic() + 8
        while not condition() and time.monotonic() < deadline:
            QTest.qWait(10)
        self.assertTrue(condition(), 'QML operation timed out')
        QTest.qWait(20)

    def item(self, name):
        item = self.window.findChild(QQuickItem, name)
        if item is None:
            # ListView delegates are owned by the visual tree, not necessarily
            # the QObject parent tree used by findChild.
            pending = [self.window.contentItem()]
            while pending:
                candidate = pending.pop()
                if candidate.objectName() == name:
                    item = candidate
                    break
                pending.extend(candidate.childItems())
        self.assertIsNotNone(item, name)
        return item

    def click(self, name):
        item = self.item(name)
        self.assertTrue(item.isVisible(), name)
        self.assertTrue(item.isEnabled(), name)
        position = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
        QTest.mouseClick(self.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, position)
        QTest.qWait(30)

    def fixture(self, cover=True):
        for number in range(2):
            make_track(self.inbox / 'Album' / f'{number + 1}.wav')
        if cover:
            Image.new('RGB', (640, 320), '#567970').save(self.inbox / 'Album/cover.jpg')

    def do_scan(self):
        self.controller.scan()
        self.wait_for(lambda: self.controller.task is None)
        self.assertTrue(self.controller.hasSession)

    def test_empty_shell_colors_typography_and_progressive_disclosure(self):
        self.assertEqual(self.window.property('color').name(), '#101113')
        font = self.window.property('font')
        self.assertFalse(QFontInfo(font).fixedPitch())
        metrics = QFontMetricsF(font)
        self.assertLess(metrics.horizontalAdvance('iiii'), metrics.horizontalAdvance('WWWW'))
        self.assertTrue(self.item('emptyScanButton').isVisible())
        self.assertFalse(self.item('albumArtistInput').isVisible())
        self.assertFalse(self.item('trackTitleInput').isVisible())
        self.assertEqual(self.controller.albums.rowCount(), 0)
        self.assertEqual(self.engine.load_errors, [])

    def test_qml_scan_album_edit_track_edit_and_preview_preserve_sources(self):
        self.fixture()
        before = {p: p.read_bytes() for p in self.inbox.rglob('*') if p.is_file()}
        self.click('emptyScanButton')
        self.wait_for(lambda: self.controller.task is None)
        self.assertEqual(self.controller.summary['ready'], 1)
        scan_button = self.item('scanButton')
        self.assertGreater(scan_button.mapToScene(QPointF()).x(), self.window.width() * 0.8)
        self.click('albumRow0')
        self.assertEqual(self.controller.page, 'review')
        self.assertFalse(self.item('albumArtistInput').isVisible())
        self.click('editAlbumButton')
        self.item('albumArtistInput').setProperty('text', 'Reviewed Artist')
        self.item('albumTitleInput').setProperty('text', 'Reviewed Album')
        self.click('applyAlbumButton')
        self.assertEqual(self.controller.album['title'], 'Reviewed Album')
        self.assertFalse(self.item('albumArtistInput').isVisible())
        self.click('trackRow0')
        self.assertTrue(self.item('trackTitleInput').isVisible())
        self.item('trackTitleInput').setProperty('text', 'Reviewed Song')
        self.item('trackNumberInput').setProperty('text', '3')
        self.click('applyTrackButton')
        self.assertEqual(self.controller.track['title'], 'Reviewed Song')
        self.assertFalse(self.item('trackTitleInput').isVisible())
        self.controller.preview()
        self.wait_for(lambda: self.controller.task is None)
        self.assertEqual(self.controller.page, 'preview')
        self.assertIn('Reviewed Artist/2020-Reviewed Album/Reviewed Song.wav', self.controller.plan.rows[0]['destination'])
        self.assertIn('track_number', self.controller.plan.rows[0]['metadata'])
        self.assertEqual(before, {p: p.read_bytes() for p in self.inbox.rglob('*') if p.is_file()})
        self.assertFalse(self.library.exists())
        self.assertFalse((self.root / 'cache').exists())
        self.assertEqual(self.engine.load_errors, [])

    def test_artwork_skip_filter_and_folder_changes(self):
        self.fixture()
        self.do_scan()
        self.click('albumRow0')
        self.click('changeArtworkButton')
        self.assertEqual(self.controller.artwork.rowCount(), 1)
        self.click('artCandidate0')
        self.click('useAlbumArtworkButton')
        album = self.controller.session.albums[0]
        self.assertTrue(all(t.selected_art.path.name == 'cover.jpg' for t in album.tracks))
        self.click('skipAlbumButton')
        self.assertTrue(album.skip)
        self.controller.preview()
        self.wait_for(lambda: self.controller.task is None)
        self.assertTrue(all(row['action'] == 'Skip' for row in self.controller.plan.rows))
        self.controller.setFilter('Error')
        self.assertEqual(self.controller.albums.rowCount(), 0)
        self.controller.setFilter('Ready')
        self.assertEqual(self.controller.albums.rowCount(), 1)
        self.controller.setPaths(str(self.inbox), str(self.root / 'other'))
        self.assertFalse(self.controller.pathsMatch)
        self.controller.preview()
        self.assertIsNone(self.controller.task)
        self.assertEqual(self.engine.load_errors, [])

    def test_pending_edits_require_rescan_confirmation(self):
        self.fixture()
        self.do_scan()
        self.controller.openAlbum(0)
        self.controller.applyAlbum('New Artist', 'New Album', '2001')
        calls = []
        self.controller.scanConfirmationRequired.connect(lambda: calls.append(True))
        self.controller.scan()
        self.assertEqual(calls, [True])
        self.assertIsNone(self.controller.task)
        self.assertEqual(self.controller.album['title'], 'New Album')
        self.controller.confirmScan()
        self.wait_for(lambda: self.controller.task is None)
        self.assertFalse(self.controller.dirty)
        self.assertEqual(self.controller.session.albums[0].title, 'Album')

    def test_worker_cancellation_and_close_keep_ui_responsive(self):
        source = self.root / 'seed.wav'
        make_track(source)
        for index in range(100):
            shutil.copy2(source, self.inbox / f'{index}.wav')
        read = scan.read_track
        def slow_read(path):
            time.sleep(0.004)
            return read(path)
        ticks = []
        timer = QTimer()
        timer.timeout.connect(lambda: ticks.append(True))
        timer.start(5)
        with mock.patch.object(scan, 'read_track', side_effect=slow_read):
            self.controller.scan()
            self.wait_for(lambda: len(ticks) > 5)
            self.assertIsNotNone(self.controller.task)
            self.window.close()
            self.wait_for(lambda: self.controller.task is None)
        timer.stop()
        self.assertFalse(self.window.isVisible())
        self.assertFalse(self.controller.hasSession)
        self.assertEqual(len(list(self.inbox.iterdir())), 100)

    def test_empty_invalid_folder_and_resizing(self):
        self.do_scan()
        self.assertEqual(self.controller.summary['tracks'], 0)
        self.controller.setPaths(str(self.root / 'absent'), str(self.library))
        self.controller.scan()
        self.wait_for(lambda: self.controller.task is None)
        self.assertEqual(self.controller.messageKind, 'error')
        self.assertIn('does not exist', self.controller.message)
        self.window.resize(800, 600)
        QTest.qWait(40)
        self.controller.navigate('settings')
        QTest.qWait(40)
        self.assertEqual(self.engine.load_errors, [])

    def test_small_window_review_remains_scrollable(self):
        self.fixture()
        self.do_scan()
        self.controller.openAlbum(0)
        self.window.resize(800, 600)
        QTest.qWait(50)
        self.click('editAlbumButton')
        page = self.item('reviewPage')
        self.assertGreater(page.property('contentHeight'), page.height())
        page.setProperty('contentY', page.property('contentHeight') - page.height())
        QTest.qWait(40)
        button = self.item('applyAlbumButton')
        position = button.mapToScene(QPointF(button.width() / 2, button.height() / 2))
        self.assertGreater(position.y(), 76)
        self.assertLess(position.y(), self.window.height())
        self.assertEqual(self.engine.load_errors, [])

    def test_default_launcher_runs_qml_and_exits_cleanly(self):
        script = '''
import sys
from PySide6.QtCore import QTimer
from hiby_music_tools.gui import quick
from hiby_music_tools.gui.app import main
original = quick.create_engine
def create(*args, **kwargs):
    engine, controller = original(*args, **kwargs)
    assert engine.rootObjects(), engine.load_errors
    QTimer.singleShot(30, engine.rootObjects()[0].close)
    return engine, controller
quick.create_engine = create
sys.argv = ['hibysync', '--inbox', sys.argv[1], '--library', sys.argv[2]]
raise SystemExit(main())
'''
        env = os.environ.copy()
        env['PYTHONPATH'] = str(ROOT / 'src')
        env['QT_SCALE_FACTOR'] = '1.5'
        result = subprocess.run([sys.executable, '-c', script, str(self.inbox), str(self.library)],
                                env=env, cwd=self.root, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_apple_search_selection_and_confirmed_import_through_qml(self):
        from hiby_music_tools import online_art
        self.fixture(cover=False)
        before = {p: p.read_bytes() for p in self.inbox.rglob('*') if p.is_file()}
        self.do_scan()
        self.click('albumRow0')
        self.click('changeArtworkButton')
        document = {'results': [dict(artistName='Album Artist', collectionName='Album',
                                     artworkUrl100='https://is1-ssl.mzstatic.com/100x100bb.jpg')]}
        output = io.BytesIO()
        Image.new('RGB', (1200, 1200), 'red').save(output, 'JPEG')
        def request(url, **kwargs):
            return json.dumps(document).encode() if '/search?' in url else output.getvalue()
        with mock.patch.object(online_art, 'request_bytes', side_effect=request):
            self.click('appleArtworkTab')
            self.wait_for(lambda: self.controller.task is None)
            self.assertEqual(self.item('searchAppleButton').property('text'), 'Refresh')
            self.click('searchAppleButton')
            self.wait_for(lambda: self.controller.task is None)
        self.assertEqual(self.controller.artwork.rowCount(), 1)
        self.assertIsNone(self.controller.session.albums[0].tracks[0].selected_art)
        self.click('artCandidate0')
        self.click('useAlbumArtworkButton')
        self.assertTrue(all(t.selected_art.origin == 'apple' for t in self.controller.session.albums[0].tracks))
        self.controller.navigate('import')
        self.click('previewButton')
        self.wait_for(lambda: self.controller.task is None)
        self.assertTrue(self.controller.canImport)
        self.assertFalse(self.library.exists())
        self.click('importCopiesButton')
        self.assertFalse(self.library.exists())
        self.click('confirmImportButton')
        self.wait_for(lambda: self.controller.task is None)
        self.assertEqual(self.controller.page, 'complete')
        self.assertEqual(self.controller.importSummary['imported'], 2, self.controller.importSummary)
        self.assertEqual(self.controller.importSummary['failed'], 0)
        self.assertFalse(self.controller.dirty)
        self.assertFalse(self.controller.canImport)
        self.assertEqual(len(list(self.library.rglob('*.wav'))), 2)
        self.assertEqual(self.controller.importSummary['removed'], len(before))
        self.assertEqual(self.controller.importSummary['retained'], 0)
        self.assertEqual(self.controller.albums.rowCount(), 0)
        self.assertTrue(all(not path.exists() for path in before))
        self.assertEqual(self.engine.load_errors, [])

    def test_apple_failure_keeps_current_artwork(self):
        from hiby_music_tools import online_art
        self.fixture()
        self.do_scan()
        track = self.controller.session.albums[0].tracks[0]
        original = track.selected_art
        self.click('albumRow0')
        self.click('changeArtworkButton')
        with mock.patch.object(online_art, 'request_bytes', side_effect=OSError('offline')):
            self.click('appleArtworkTab')
            self.wait_for(lambda: self.controller.task is None)
        self.assertEqual(track.selected_art, original)
        self.assertTrue(self.controller.artworkError)
        self.assertIn('offline', self.controller.artworkMessage)
        self.assertEqual(self.engine.load_errors, [])

    def test_conflict_choice_and_import_cancellation_report(self):
        from hiby_music_tools.core import importing
        from hiby_music_tools.core.review import build_plan
        self.fixture()
        self.do_scan()
        row = build_plan(self.controller.session)[0]
        row.destination.parent.mkdir(parents=True)
        row.destination.write_bytes(b'previous library version')
        self.controller.preview()
        self.wait_for(lambda: self.controller.task is None)
        self.assertEqual(self.controller.plan.rows[0]['policy'], 'keep')
        self.click('conflictPolicy0')
        self.assertEqual(self.controller.replacementCount, 1)
        commit = importing.commit_copy
        def cancel_after_copy(*args):
            commit(*args)
            self.controller.task.operation.cancelled.set()
        with mock.patch.object(importing, 'commit_copy', side_effect=cancel_after_copy):
            self.click('importCopiesButton')
            self.click('confirmImportButton')
            self.wait_for(lambda: self.controller.task is None)
        report = self.controller.importSummary
        self.assertTrue(report['cancelled'])
        self.assertEqual(report['replaced'], 1, report)
        self.assertEqual(report['remaining'], 1)
        self.assertTrue(Path(report['recovery']).is_dir())
        self.assertEqual(self.engine.load_errors, [])


if __name__ == '__main__':
    unittest.main()
