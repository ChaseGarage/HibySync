"""Settings/playlists UI uses real temporary catalog, fake output explicitly."""
import unittest
import test_player_gui as helpers
from hiby_music_tools.library import playlists as store

if helpers.QT:
    from PySide6.QtTest import QTest
    from PySide6.QtCore import QPointF


@unittest.skipUnless(helpers.QT, 'Install PySide6')
class PolishGuiTests(unittest.TestCase):
    setUpClass = classmethod(helpers.PlayerGuiTests.setUpClass.__func__)
    wait = helpers.PlayerGuiTests.wait
    idle = helpers.PlayerGuiTests.idle
    item = helpers.PlayerGuiTests.item
    click = helpers.PlayerGuiTests.click

    def setUp(self):
        helpers.PlayerGuiTests.setUp(self)
        self.playlists = self.engine.playlist_controller
        self.playlists.path = self.root / 'state/playlists.sqlite3'

    def cleanup(self):
        self.engine.playlist_controller.shutdown()
        self.engine.deletion_controller.shutdown()
        self.engine.metadata_controller.shutdown()
        helpers.PlayerGuiTests.cleanup(self)

    def test_playlist_create_add_album_reorder_remove_play_and_restore(self):
        self.idle()
        self.click('libraryPlaylistsMode')
        self.wait(lambda: not self.playlists.busy)
        self.click('newPlaylist')
        self.item('playlistNameInput').setProperty('text', 'After dark')
        self.click('savePlaylistName')
        self.wait(lambda: not self.playlists.busy)
        key = self.playlists.selected
        self.assertTrue(key)
        self.assertEqual(self.playlists.name, 'After dark')
        self.browser.setMode('albums')
        self.idle()
        self.playlists.choose('album', self.browser.model.rows[0]['id'])
        self.wait(lambda: not self.playlists.busy)
        self.click('addToPlaylist_' + key)
        self.wait(lambda: not self.playlists.busy)
        self.assertFalse(self.playlists.choosing)
        self.assertFalse(self.item('libraryEmptyState').isVisible())
        self.assertEqual(self.playlists.count, 3)
        first = self.playlists.model.rows[0]['entryId']
        self.playlists.move(first, 2)
        self.wait(lambda: not self.playlists.busy)
        self.assertEqual(self.playlists.model.rows[-1]['entryId'], first)
        self.playlists.remove(first)
        self.wait(lambda: not self.playlists.busy)
        self.click('playPlaylist')
        self.wait(lambda: not self.playlists.busy)
        self.assertEqual(self.player.state, 'playing')
        self.assertEqual([r['id'] for r in self.player.queue.entries], [r['id'] for r in self.playlists.model.rows])
        self.playlists.rename('Late night')
        self.wait(lambda: not self.playlists.busy)
        self.assertEqual(store.listing(self.playlists.path)[0]['name'], 'Late night')
        for width, height in ((1600,900), (1200,800), (900,800), (750,700)):
            self.window.resize(width, height)
            QTest.qWait(35)
            listing = self.item('playlistList')
            self.assertGreater(listing.width(), 500)
            self.assertLessEqual(listing.mapToScene(QPointF(listing.width(),0)).x(), width)
        self.assertEqual(self.engine.load_errors, [])

    def test_audio_settings_show_separate_source_output_and_save_device(self):
        self.idle()
        self.player.playRows([dict(id='fixture',path='/tmp/fixture.flac',title='Fixture', artist='Artist',
                                   codec='flac',sample_rate=96000,bit_depth=24,duration=180)])
        self.audio.audioChanged.emit({'audio-device-list': [{'name':'auto','description':'Default'},
                                    {'name':'pipewire/test','description':'Test DAC'}],
                                    'current-ao':'pipewire','audio-out-params':{'samplerate':48000,'format':'float'}})
        calls = []
        self.audio.select_device = lambda name: calls.append(name)
        self.player.selectAudioDevice('pipewire/test')
        self.assertEqual(calls, ['pipewire/test'])
        self.player.selectAudioDevice('missing')
        self.assertEqual(len(calls),1)
        self.importer.navigate('settings')
        QTest.qWait(30)
        for width,height in ((1600,900),(1200,800),(900,800),(750,700)):
            self.window.resize(width,height)
            QTest.qWait(30)
            self.assertIn('96 kHz', self.item('audioSourceInfo').property('text'))
            self.assertIn('48 kHz', self.item('audioOutputInfo').property('text'))
        self.assertEqual(self.player.state, 'playing')
        self.assertEqual(self.engine.load_errors, [])
