"""Mouse thumb buttons and source-stream labels against the rendered QML app."""
import builtins
import unittest
from unittest import mock
import test_player_gui as helpers

if helpers.QT:
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtTest import QTest
    from hiby_music_tools.playback.mpris import Mpris


@unittest.skipUnless(helpers.QT, 'Install PySide6')
class NavigationGuiTests(unittest.TestCase):
    setUpClass = classmethod(helpers.PlayerGuiTests.setUpClass.__func__)
    setUp = helpers.PlayerGuiTests.setUp
    wait = helpers.PlayerGuiTests.wait
    idle = helpers.PlayerGuiTests.idle
    item = helpers.PlayerGuiTests.item
    click = helpers.PlayerGuiTests.click

    def cleanup(self):
        for controller in (self.engine.playlist_controller, self.engine.deletion_controller, self.engine.metadata_controller):
            controller.shutdown()
        helpers.PlayerGuiTests.cleanup(self)

    def mouse(self, button):
        QTest.mouseClick(self.window, button, Qt.KeyboardModifier.NoModifier, QPointF(380, 450).toPoint())
        self.idle()

    def test_thumb_back_forward_restore_artist_album_and_sections_without_playback(self):
        self.idle()
        self.browser.setMode('artists')
        self.idle()
        artist = self.browser.model.rows[0]
        self.browser.openArtist(artist['id'], artist['name'])
        self.idle()
        album = self.browser.model.rows[0]['id']
        self.browser.openAlbum(album)
        self.idle()
        self.player.albumAction(album, 'play')
        self.idle()
        current = self.player.currentQueueId
        calls = len(self.audio.calls)
        self.mouse(Qt.MouseButton.BackButton)
        self.assertEqual(self.browser.mode, 'albums')
        self.assertEqual(self.browser.artistId, artist['id'])
        self.mouse(Qt.MouseButton.BackButton)
        self.assertEqual(self.browser.mode, 'artists')
        self.mouse(Qt.MouseButton.ForwardButton)
        self.assertEqual(self.browser.mode, 'albums')
        self.mouse(Qt.MouseButton.ForwardButton)
        self.assertEqual(self.browser.album['id'], album)
        self.importer.navigate('settings')
        self.idle()
        self.mouse(Qt.MouseButton.BackButton)
        self.assertEqual(self.importer.page, 'library')
        self.assertEqual(self.browser.album['id'], album)
        self.assertEqual(self.player.currentQueueId, current)
        self.assertEqual(self.player.state, 'playing')
        self.assertEqual(len(self.audio.calls), calls)
        self.assertEqual(self.engine.load_errors, [])

    def test_back_closes_queue_and_keeps_metadata_confirmation_explicit(self):
        self.idle()
        album = self.browser.model.rows[0]['id']
        self.browser.openAlbum(album)
        self.idle()
        self.click('playerQueue')
        self.assertTrue(self.item('queueDrawer').property('opened'))
        self.mouse(Qt.MouseButton.BackButton)
        self.assertFalse(self.item('queueDrawer').property('opened'))
        self.assertEqual(self.browser.mode, 'album')
        editor = self.engine.metadata_controller
        editor.edit('album', album, False)
        self.wait(lambda: not editor.busy)
        self.mouse(Qt.MouseButton.BackButton)
        self.assertTrue(editor.open)
        self.assertEqual(self.browser.mode, 'album')
        editor.dismiss()
        self.mouse(Qt.MouseButton.BackButton)
        self.assertEqual(self.browser.mode, 'albums')

    def test_back_during_album_loading_returns_to_its_artist(self):
        self.idle()
        self.browser.setMode('artists')
        self.idle()
        artist = self.browser.model.rows[0]
        self.browser.openArtist(artist['id'], artist['name'])
        self.idle()
        self.browser.openAlbum(self.browser.model.rows[0]['id'])
        # Send Back before processing the query worker's queued result.
        self.mouse(Qt.MouseButton.BackButton)
        self.assertEqual(self.browser.mode, 'albums')
        self.assertEqual(self.browser.artistId, artist['id'])

    def test_stream_label_is_green_source_information_at_all_sizes(self):
        self.idle()
        self.player.playRows([dict(id='source', path='/tmp/source.flac',title='Test',artist='A very long contributing artist name',
                                  sample_rate=44100,bit_depth=16,codec='FLAC',duration=120)])
        self.audio.audioChanged.emit({'current-ao':'pipewire','audio-out-params':{'samplerate':48000,'format':'float'}})
        for width, height in ((1600,900),(1200,800),(900,800),(750,700),(700,600)):
            self.window.resize(width,height)
            QTest.qWait(35)
            stream, artist = self.item('playerSourceStream'), self.item('playerArtistLink')
            self.assertEqual(stream.property('text'), '44.1kHz 16 bit')
            self.assertEqual(stream.property('color').name(), '#86ca96')
            self.assertGreaterEqual(stream.mapToScene(QPointF()).x(), artist.mapToScene(QPointF(artist.width(),0)).x())
            track = self.item('playerTrackRegion')
            self.assertLessEqual(stream.mapToScene(QPointF(stream.width(),0)).x(),track.mapToScene(QPointF(track.width(),0)).x() + 1)
        self.player.playRows([dict(id='lossy',path='/tmp/lossy.mp3',title='Lossy',artist='Artist',sample_rate=48000,codec='mp3')])
        self.assertEqual(self.player.sourceStream, '48kHz')
        self.player.playRows([dict(id='unknown',path='/tmp/unknown.wav',title='Unknown',artist='Artist')])
        self.assertEqual(self.player.sourceStream, '')
        self.assertEqual(self.engine.load_errors, [])

    def test_missing_mpris_dependency_has_install_instructions(self):
        original = builtins.__import__
        def missing(name, *args, **kwargs):
            if name.startswith('dbus_next'):
                raise ModuleNotFoundError("No module named 'dbus_next'", name='dbus_next')
            return original(name, *args, **kwargs)
        with mock.patch('builtins.__import__', side_effect=missing):
            service = Mpris(self.player, self.window, self.database.parent / 'artwork')
            try:
                self.wait(lambda: 'python-dbus-next' in self.player.mediaStatus)
                self.assertIn('Restart HibySync', self.player.mediaStatus)
            finally:
                service.shutdown()
