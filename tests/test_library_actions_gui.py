"""Album menu placement, transient Apple feedback, and confirmed deletion."""

import os
import unittest
from unittest import mock
from threading import Event

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['QT_QUICK_BACKEND'] = 'software'
import test_player_gui as player_tests
QT = player_tests.QT
if QT:
    from PySide6.QtCore import QPointF
    from PySide6.QtTest import QTest
    from hiby_music_tools.library.playback import tracks


@unittest.skipUnless(QT, 'Install PySide6 for Library action tests')
class LibraryActionsGuiTests(unittest.TestCase):
    setUpClass = classmethod(player_tests.PlayerGuiTests.setUpClass.__func__)
    setUp = player_tests.PlayerGuiTests.setUp
    wait = player_tests.PlayerGuiTests.wait
    idle = player_tests.PlayerGuiTests.idle
    item = player_tests.PlayerGuiTests.item
    click = player_tests.PlayerGuiTests.click

    def cleanup(self):
        self.engine.deletion_controller.shutdown()
        self.engine.metadata_controller.shutdown()
        player_tests.PlayerGuiTests.cleanup(self)

    def test_album_menu_opens_under_its_button_at_both_window_sizes(self):
        self.idle()
        self.browser.openAlbum(self.browser.model.rows[0]['id'])
        self.idle()
        for width, height in ((1200, 800), (750, 700)):
            self.window.resize(width, height)
            QTest.qWait(40)
            button = self.item('albumActionsButton')
            self.click('albumActionsButton')
            content = self.item('albumActionsMenuContents')
            top_left = content.mapToScene(QPointF(-8, -8))
            anchor = button.mapToScene(QPointF(0, button.height() + 6))
            self.assertAlmostEqual(top_left.x(), anchor.x(), delta=1)
            self.assertAlmostEqual(top_left.y(), anchor.y(), delta=1)
            from PySide6.QtCore import Qt
            QTest.keyClick(self.window, Qt.Key.Key_Escape)
        self.assertEqual(self.engine.load_errors, [])

    def test_empty_apple_search_has_temporary_inline_error_and_no_layout_jump(self):
        self.idle()
        album = self.browser.model.rows[0]['id']
        editor = self.engine.metadata_controller
        editor.edit('album', album, False, True)
        self.wait(lambda: not editor.busy)
        listing = self.item('libraryEditorArtworkList')
        original_height = listing.height()
        original_rows = list(editor.artwork.rows)
        release = Event()
        def empty(*args):
            release.wait(3)
            return []
        with mock.patch('hiby_music_tools.gui.metadata_controller.search_apple', side_effect=empty):
            self.click('libraryAppleSearch')
            self.assertTrue(editor.artworkBusy)
            self.assertAlmostEqual(listing.height(), original_height, delta=1)
            release.set()
            self.wait(lambda: not editor.busy)
        self.assertEqual(editor.appleMessage, 'No matches found')
        self.assertEqual(editor.message, '')
        self.assertEqual(editor.artwork.rows, original_rows)
        self.assertAlmostEqual(listing.height(), original_height, delta=1)
        message = self.item('libraryAppleMessage')
        self.assertEqual(message.property('color').name(), '#e57e7e')
        button = self.item('libraryAppleSearch')
        self.assertGreaterEqual(message.mapToScene(QPointF()).x(), button.mapToScene(QPointF()).x() + button.width())
        editor.apple_timer.start(60)
        self.wait(lambda: editor.appleMessage == '')
        with mock.patch('hiby_music_tools.gui.metadata_controller.search_apple', side_effect=ValueError('Apple returned matches, but no covers could be downloaded. Try again.')):
            editor.searchApple('Artist', 'Album')
            self.wait(lambda: not editor.busy)
        self.assertEqual(editor.appleMessage, 'No matches found')
        self.assertFalse(editor.error)
        self.assertEqual(self.engine.load_errors, [])

    def test_song_delete_cancel_then_confirm_releases_player_and_repairs_queue(self):
        self.browser.setMode('songs')
        self.idle()
        row = self.browser.model.rows[0]
        self.player.playContext(row['id'])
        self.idle()
        self.player.trackAction(row['id'], 'append')  # Repeated queue instances.
        self.idle()
        deletion = self.engine.deletion_controller
        deletion.request('track', row['id'])
        self.wait(lambda: not deletion.busy)
        from pathlib import Path
        self.assertTrue(Path(row['path']).exists())
        self.assertEqual(self.player.state, 'playing')
        self.click('cancelLibraryDelete')
        self.assertTrue(Path(row['path']).exists())
        deletion.request('track', row['id'])
        self.wait(lambda: not deletion.busy)
        self.click('confirmLibraryDelete')
        self.wait(lambda: not deletion.busy)
        self.idle()
        self.assertFalse(Path(row['path']).exists())
        self.assertNotIn(row['id'], [e['id'] for e in self.player.queue.entries])
        self.assertIn(('release',), self.audio.calls)
        self.assertEqual(self.player.state, 'stopped')
        self.assertFalse(deletion.open)
        self.assertEqual(len(tracks(self.music, self.database)), 2)
        self.assertEqual(self.engine.load_errors, [])

    def test_album_delete_from_context_menu_returns_to_album_browser(self):
        self.idle()
        self.browser.openAlbum(self.browser.model.rows[0]['id'])
        self.idle()
        self.click('albumActionsButton')
        self.click('deleteLibraryAlbum')
        deletion = self.engine.deletion_controller
        self.wait(lambda: not deletion.busy)
        self.assertEqual(deletion.count, 3)
        self.click('confirmLibraryDelete')
        self.wait(lambda: not deletion.busy)
        self.idle()
        self.assertEqual(self.browser.mode, 'albums')
        self.assertEqual(self.browser.model.total, 0)
        self.assertEqual(self.engine.load_errors, [])
