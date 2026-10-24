"""Real streamed temp-file sync through QML; audio service is explicitly fake."""
from pathlib import Path
import time
import unittest
from unittest import mock
import test_player_gui as helpers
from test_device import DeviceFixture

if helpers.QT:
    from PySide6.QtCore import QPointF
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    from hiby_music_tools.core.streaming import copy_stream


@unittest.skipUnless(helpers.QT, 'Install PySide6')
class DeviceSyncGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
    def wait(self, condition):
        # Give Python's IO worker the GIL as well as dispatching Qt events.
        # Repeated qWait calls can starve many short native filesystem syscalls.
        deadline = time.monotonic() + 12
        while not condition() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.005)
        self.assertTrue(condition())
        self.app.processEvents()
    idle = helpers.PlayerGuiTests.idle
    item = helpers.PlayerGuiTests.item
    click = helpers.PlayerGuiTests.click

    def setUp(self):
        helpers.PlayerGuiTests.setUp(self)
        root = self.root / 'sync-device'
        root.mkdir()
        self.fixture = DeviceFixture(root)
        self.fixture.source = self.music
        self.manager = self.engine.device_controller
        self.manager.devices = self.fixture.devices
        self.sync = self.manager.sync_controller
        self.sync.recovery_root = self.root / 'recovery'

    def cleanup(self):
        for obj in (self.engine.device_controller,self.engine.playlist_controller,
                    self.engine.deletion_controller,self.engine.metadata_controller): obj.shutdown()
        helpers.PlayerGuiTests.cleanup(self)

    def ready(self):
        self.wait(lambda:not self.manager.busy)
        self.idle()

    @staticmethod
    def slow_copy(source, destination, *, progress=lambda count:None, **kwargs):
        def advance(count):
            progress(count)
            time.sleep(.065)  # Simulated device latency AFTER a real write/fsync.
        return copy_stream(source,destination,progress=advance,**kwargs)

    def test_confirmation_requires_explicit_removal_consent_and_updates_summary(self):
        self.fixture.file(self.fixture.music,'old.mp3',b'device only')
        original = {p:p.read_bytes() for p in self.music.rglob('*') if p.is_file()}
        self.click('navigation_device')
        self.ready()
        self.assertTrue(self.sync.canStart)
        self.click('syncDeviceButton')
        self.ready()
        self.assertTrue(self.sync.confirmationOpen)
        self.assertFalse(self.item('confirmDeviceSync').isEnabled())
        self.sync.confirm(False)
        self.assertTrue((self.fixture.music/'old.mp3').exists())
        self.assertFalse(self.sync.viewOpen)
        self.click('deviceRemovalConsent')
        self.assertTrue(self.item('confirmDeviceSync').isEnabled())
        self.click('confirmDeviceSync')
        self.ready()
        self.assertEqual(self.sync.state,'complete',self.sync.report)
        self.assertEqual(self.sync.report['new'],3)
        self.assertEqual(self.sync.report['removed'],1)
        self.assertFalse((self.fixture.music/'old.mp3').exists())
        self.assertEqual(self.item('deviceSyncTitle').property('text'),'Sync Complete')
        self.assertTrue(Path(self.sync.report['recovery']).is_file())
        self.sync.copyLogPath()
        self.assertEqual(self.app.clipboard().text(), self.sync.report['recovery'])
        self.assertEqual(original,{p:p.read_bytes() for p in self.music.rglob('*') if p.is_file()})
        self.assertEqual(self.manager.summary['synced'],3)
        self.assertEqual(self.manager.summary['changes'],0)
        self.assertEqual(self.engine.load_errors,[])

    def test_normal_sync_with_matching_files_needs_no_verify_contents(self):
        rel = 'Artist/Album/0.wav'
        self.fixture.file(self.fixture.music, rel, (self.music / rel).read_bytes())
        with mock.patch('hiby_music_tools.device.preview.sha256_file',
                        side_effect=AssertionError('Normal GUI workflow must not hash the whole library')):
            self.click('navigation_device')
            self.ready()
            self.assertEqual(self.manager.summary['uncertain'], 1)
            self.assertTrue(self.item('syncDeviceButton').isEnabled())
            self.click('syncDeviceButton')
            self.ready()
            self.assertTrue(self.sync.confirmationOpen)
            self.assertFalse(self.sync.pending.verified)
            self.click('confirmDeviceSync')
            self.ready()
        self.assertEqual(self.sync.state, 'complete', self.sync.report)
        self.assertEqual(self.sync.report['new'], 2)

    def test_large_file_updates_live_bars_resize_navigation_and_cancel_then_retry(self):
        self.fixture.file(self.music,'Large/continuous.flac',b'X'*(8*1024*1024))
        self.player.albumAction(self.browser.model.rows[0]['id'],'play')
        self.idle()
        current = self.player.currentQueueId
        self.click('navigation_device'); self.ready()
        self.sync.request(); self.ready()
        values = []
        self.sync.progressChanged.connect(lambda: values.append(dict(self.sync.progress)))
        with mock.patch('hiby_music_tools.device.transports.copy_stream',side_effect=self.slow_copy):
            self.sync.confirm(False)
            self.wait(lambda: self.sync.progress['fileFraction'] > 0 and self.sync.progress['fileFraction'] < 1)
            self.assertTrue(self.sync.running)
            self.assertGreater(self.sync.progress['bytesDone'],0)
            for width,height in ((1600,900),(1200,800),(900,800),(750,700)):
                self.window.resize(width,height);QTest.qWait(25)
                button=self.item('cancelDeviceSync')
                point=button.mapToScene(QPointF(button.width(),button.height()))
                self.assertLessEqual(point.x(),width)
                self.assertLessEqual(point.y(),self.item('playerBar').y())
            self.importer.navigate('library');QTest.qWait(30)
            self.assertEqual(self.player.state,'playing')
            self.importer.navigate('device');QTest.qWait(30)
            self.assertTrue(self.sync.running)
            self.click('cancelDeviceSync')
            self.ready()
        self.assertEqual(self.sync.state,'cancelled',self.sync.report)
        self.assertFalse((self.fixture.music/'Large/continuous.flac').exists())
        self.assertEqual(self.player.currentQueueId,current)
        self.assertEqual(self.player.state,'playing')
        self.assertGreater(len({p['fileDone'] for p in values if p['fileDone'] is not None}),2)
        self.click('retryDeviceSync');self.ready()
        self.assertTrue(self.sync.confirmationOpen)
        self.click('confirmDeviceSync');self.ready()
        self.assertEqual(self.sync.state,'complete',self.sync.report)
        self.assertEqual((self.fixture.music/'Large/continuous.flac').read_bytes(),b'X'*(8*1024*1024))
        self.assertEqual(self.engine.load_errors,[])

    def test_changed_source_after_confirmation_returns_review_without_writing(self):
        self.click('navigation_device');self.ready()
        self.sync.request();self.ready()
        self.fixture.file(self.music,'late arrival.flac',b'new')
        self.click('confirmDeviceSync');self.ready()
        self.assertEqual(self.sync.state,'stale')
        self.assertEqual(list(self.fixture.music.rglob('*')),[])
        self.assertIn('changed after review',self.sync.report['errors'])
        self.assertEqual(self.engine.load_errors,[])
