"""Rendered Device dashboard; injected mount/USB inventory, no real device IO."""
from pathlib import Path
from threading import Event
import unittest
from unittest import mock
import test_player_gui as helpers
from test_device import DeviceFixture

if helpers.QT:
    from PySide6.QtCore import QPointF, QUrl
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication


@unittest.skipUnless(helpers.QT, 'Install PySide6')
class DeviceGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # This module runs before the retained Widgets tests in full discovery.
        # QApplication also supports Quick; QGuiApplication cannot create widgets.
        cls.app = QApplication.instance() or QApplication([])
    wait = helpers.PlayerGuiTests.wait
    idle = helpers.PlayerGuiTests.idle
    item = helpers.PlayerGuiTests.item
    click = helpers.PlayerGuiTests.click

    def setUp(self):
        helpers.PlayerGuiTests.setUp(self)
        base = self.root / 'device-fixture'
        base.mkdir()
        self.fixture = DeviceFixture(base, mtp=True)
        self.fixture.source = self.music
        self.manager = self.engine.device_controller
        self.manager.devices = self.fixture.devices

    def cleanup(self):
        for obj in (self.engine.device_controller, self.engine.playlist_controller,
                    self.engine.deletion_controller, self.engine.metadata_controller):
            obj.shutdown()
        helpers.PlayerGuiTests.cleanup(self)

    def device_idle(self):
        self.wait(lambda: not self.manager.busy)
        self.idle()

    def populate_device(self):
        f = self.fixture
        for number in (0, 1):
            path = f.music / f'Artist/Album/{number}.wav'
            path.parent.mkdir(parents=True, exist_ok=True)
            data = (self.music / f'Artist/Album/{number}.wav').read_bytes()
            path.write_bytes(data if number == 0 else data[:-1] + bytes([data[-1] ^ 1]))
        f.file(f.music, 'Old Artist/Old Album/obsolete.mp3', b'obsolete')
        f.file(f.music, 'device.db', b'keep')
        f.file(f.music.parent, 'Podcasts/podcast.mp3', b'outside Music')

    def test_real_comparison_expansion_preview_and_responsive_layout(self):
        self.populate_device()
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.click('navigation_device')
        self.device_idle()
        self.assertEqual(self.manager.status, 'Connected')
        self.assertEqual(self.manager.summary['uncertain'], 2)
        self.assertTrue(self.manager.canPreview)
        self.assertTrue(self.item('syncDeviceButton').isEnabled())
        self.click('verifyDeviceButton')
        self.device_idle()
        self.assertTrue(self.manager.complete)
        self.assertEqual(self.manager.summary['synced'], 1)
        self.assertEqual(self.manager.summary['transfer'], 2)
        self.assertEqual(self.manager.summary['remove'], 1)
        self.assertEqual(self.manager.summary['changes'], 3)
        self.assertTrue(self.manager.canPreview)
        self.assertEqual(self.manager.transport, 'MTP via GVFS/FUSE')
        self.manager.toggleGroup('new')
        self.assertTrue(any(r.get('relpath','').endswith('/2.wav') for r in self.manager.rows.rows))
        for width,height in ((1600,900),(1200,800),(900,800),(750,700)):
            self.window.resize(width,height)
            QTest.qWait(40)
            for name in ('refreshDeviceButton','previewDeviceButton','syncDeviceButton'):
                item = self.item(name)
                right = item.mapToScene(QPointF(item.width(),item.height()))
                self.assertLessEqual(right.x(), width)
                self.assertLessEqual(right.y(), self.item('playerBar').y())
                self.assertGreater(item.width(), 60)
        self.click('previewDeviceButton')
        self.assertTrue(self.manager.previewOpen)
        self.assertEqual(self.manager.previewRows.rowCount(), 3)
        self.click('closeDevicePreview')
        self.assertFalse(self.manager.previewOpen)
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        self.assertEqual(self.engine.load_errors, [])

    def test_disconnect_empty_and_manual_local_folder_rejection(self):
        self.click('navigation_device')
        self.device_idle()
        self.assertTrue(self.manager.canPreview)  # Three local tracks, empty device.
        self.manager.chooseFolder(QUrl.fromLocalFile(str(self.music)))
        self.device_idle()
        self.assertEqual(self.manager.status, 'Unavailable')
        self.assertFalse(self.manager.canPreview)
        self.assertIn('Ordinary local folders', self.manager.message)
        self.manager.chooseFolder(QUrl('mtp://device/Music'))
        self.assertIn('MTP URI', self.manager.message)
        self.manager.refresh(False)
        self.device_idle()
        (self.fixture.usb / 'idVendor').unlink()
        self.manager.checkConnection()
        self.device_idle()
        self.assertEqual(self.manager.status, 'Disconnected')
        self.assertEqual(self.manager.summary['changes'], 0)
        self.assertFalse(self.manager.canPreview)
        self.assertTrue(self.fixture.music.is_dir())
        self.assertEqual(self.engine.load_errors, [])

    def test_multiple_storages_manual_choice_and_source_change_invalidate_preview(self):
        extra = self.fixture.endpoint / 'Internal Storage/Music'
        extra.mkdir(parents=True)
        self.click('navigation_device')
        self.device_idle()
        self.assertIsNone(self.manager.target)
        self.assertEqual(self.manager.choices.rowCount(), 2)
        self.manager.chooseFolder(QUrl.fromLocalFile(str(self.fixture.music)))
        self.device_idle()
        self.assertTrue(self.manager.complete)
        self.manager.showPreview()
        self.assertTrue(self.manager.previewOpen)
        new_root = self.root / 'different-library'
        new_root.mkdir()
        self.importer.setPaths(str(self.root / 'inbox'), str(new_root))
        self.assertFalse(self.manager.previewOpen)
        self.assertFalse(self.manager.canPreview)
        self.assertIn('changed', self.manager.message)

    def test_cancellation_background_progress_and_playback_are_independent(self):
        self.populate_device()
        self.player.albumAction(self.browser.model.rows[0]['id'], 'play')
        self.idle()
        current = self.player.currentQueueId
        self.click('navigation_device')
        self.device_idle()
        release = Event()
        from hiby_music_tools.sync import sha256_file
        def slow(path, op):
            release.wait(3)
            return sha256_file(path, op)
        with mock.patch('hiby_music_tools.device.preview.sha256_file', side_effect=slow):
            try:
                self.manager.refresh(True)
                QTest.qWait(60)
                self.assertTrue(self.manager.comparing)
                self.window.resize(750,700)
                self.manager.cancel()
            finally:
                release.set()
            self.device_idle()
        self.assertIsNone(self.manager.plan)
        self.assertIn('cancelled', self.manager.message)
        self.assertEqual(self.player.state, 'playing')
        self.assertEqual(self.player.currentQueueId, current)
        self.assertEqual(self.engine.load_errors, [])

    def test_large_changes_list_is_virtualized_and_liveness_does_not_rescan_audio(self):
        f = self.fixture
        for i in range(2000):
            f.file(self.music, f'Large/{i:04}.flac', b'a')
        self.click('navigation_device')
        self.device_idle()
        self.assertEqual(self.manager.summary['transfer'], 2003)
        self.manager.toggleGroup('new')
        QTest.qWait(50)
        listing = self.item('deviceChangesList')
        self.assertEqual(self.manager.rows.rowCount(), 2004)
        self.assertLess(len(listing.property('contentItem').childItems()), 60)
        with mock.patch.object(f.devices, 'detect', side_effect=AssertionError('Poll must not redetect or scan music')):
            self.manager.checkConnection()
            self.device_idle()
        self.assertEqual(self.manager.status, 'Connected')
        self.assertEqual(self.engine.load_errors, [])

    def test_close_stops_poll_even_when_late_context_signals_arrive(self):
        self.click('navigation_device')
        self.device_idle()
        self.assertIs(self.manager.parent(), self.engine)
        self.assertTrue(self.manager.poll.isActive())
        self.assertTrue(self.manager.requestClose())
        self.assertFalse(self.manager.poll.isActive())
        self.importer.changed.emit()
        self.assertFalse(self.manager.poll.isActive())
