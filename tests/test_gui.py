"""Offscreen Qt integration tests; optional when PySide6 is not installed."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from test_baseline import ROOT, make_track

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
try:
    from PySide6.QtCore import QCoreApplication, QEvent, QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from hiby_music_tools.gui.window import MainWindow
    from hiby_music_tools.core import scan
    HAS_QT = True
except ImportError:
    HAS_QT = False


@unittest.skipUnless(HAS_QT, 'Install the gui extra to run Qt tests')
class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='hiby-qt-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'inbox'
        self.source.mkdir()
        self.window = MainWindow(self.source, self.root / 'library')
        self.window.show()
        cache_patch = mock.patch('hiby_music_tools.core.scan.metadata_dir', return_value=self.root / 'cache')
        cache_patch.start()
        self.addCleanup(cache_patch.stop)
        self.addCleanup(self.close_window)

    def test_launcher_event_loop_exits_cleanly(self):
        script = '''
import sys
from PySide6.QtCore import QTimer
from hiby_music_tools.gui.window import MainWindow
from hiby_music_tools.gui.app import main
original = MainWindow.show
def show(window):
    original(window)
    QTimer.singleShot(20, window.close)
MainWindow.show = show
sys.argv = ['hibysync', '--widgets', '--inbox', sys.argv[1], '--library', sys.argv[2]]
raise SystemExit(main())
'''
        env = os.environ.copy()
        env['PYTHONPATH'] = str(ROOT / 'src')
        result = subprocess.run([sys.executable, '-c', script, str(self.source),
                                 str(self.root / 'library')], env=env, cwd=self.root,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def wait_for(self, condition, timeout=8):
        deadline = time.monotonic() + timeout
        while not condition() and time.monotonic() < deadline:
            QTest.qWait(10)
        self.assertTrue(condition(), 'Qt task did not finish in time')

    def close_window(self):
        if self.window.task:
            self.window.cancel()
            self.wait_for(lambda: self.window.task is None)
        self.window.close()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def test_scan_edit_filter_and_read_only_preview(self):
        path = self.source / 'album/song.wav'
        make_track(path)
        original = path.read_bytes()
        self.window.start_scan()
        self.wait_for(lambda: self.window.task is None)
        self.assertEqual(len(self.window.session.albums), 1)
        details = self.window.details
        self.assertIn('Song', details.original.toPlainText())
        details.artist.setText('Reviewed Artist')
        details.title.setText('Reviewed Album')
        details.apply_album()
        details.track_title.setText('Reviewed Song')
        details.track_number.setText('2')
        details.apply_track()
        self.window.filter.setCurrentText('Needs Review')
        self.assertEqual(self.window.proxy.rowCount(), 1)
        self.window.start_preview()
        self.wait_for(lambda: self.window.task is None)
        dialog = self.window.preview_dialog
        from PySide6.QtWidgets import QTableView
        model = dialog.findChild(QTableView).model()
        self.assertEqual(model.rowCount(), 1)
        row = model.rows[0]
        self.assertIn('Reviewed Artist/2020-Reviewed Album/Reviewed Song.wav', str(row.destination))
        self.assertIn('track_number', row.metadata_changes)
        self.assertEqual(path.read_bytes(), original)
        self.assertFalse((self.root / 'library').exists())
        dialog.close()
        self.window.library.setText(str(self.root / 'other-library'))
        self.assertFalse(self.window.preview_button.isEnabled())
        self.assertIn('Paths changed', self.window.message.text())

    def test_empty_scan_and_invalid_path_errors(self):
        self.window.start_scan()
        self.wait_for(lambda: self.window.task is None)
        self.assertEqual(self.window.session.albums, [])
        self.assertEqual(self.window.proxy.rowCount(), 0)
        self.window.session = None
        self.window.inbox.setText(str(self.root / 'absent'))
        self.window.start_scan()
        self.wait_for(lambda: self.window.task is None)
        self.assertIn('Error:', self.window.message.text())
        self.assertTrue(self.window.scan_button.isEnabled())

    def test_large_scan_keeps_event_loop_alive_and_can_cancel(self):
        seed = self.root / 'seed.wav'
        make_track(seed)
        for number in range(150):
            shutil.copy2(seed, self.source / f'{number:03}.wav')
        read_track = scan.read_track

        def slow_read(path):
            time.sleep(0.003)
            return read_track(path)

        ticks = []
        timer = QTimer()
        timer.timeout.connect(lambda: ticks.append(1))
        timer.start(5)
        with mock.patch.object(scan, 'read_track', side_effect=slow_read):
            self.window.start_scan()
            self.wait_for(lambda: len(ticks) >= 5)
            self.assertIsNotNone(self.window.task)
            self.window.cancel()
            self.wait_for(lambda: self.window.task is None)
        timer.stop()
        self.assertIsNone(self.window.session)
        self.assertIn('Cancelled', self.window.message.text())
        self.assertEqual(len(list(self.source.iterdir())), 150)

    def test_close_waits_for_worker_cancellation(self):
        make_track(self.source / 'song.wav')
        self.window.start_scan()
        self.window.close()
        self.wait_for(lambda: self.window.task is None)
        self.assertFalse(self.window.isVisible())


if __name__ == '__main__':
    unittest.main()
