"""Focused editor, previews, real temporary-library saves, and queue repair."""

import os
from pathlib import Path
import shutil
import unittest
from unittest import mock

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['QT_QUICK_BACKEND'] = 'software'
import test_player_gui as player_tests
QT = player_tests.QT
from test_baseline import make_track

if QT:
    from PySide6.QtCore import QUrl, Qt
    from PySide6.QtTest import QTest
    from PIL import Image
    from hiby_music_tools.core.artwork import preview
    from hiby_music_tools.core.scan import read_track
    from hiby_music_tools.core.tagging import read_genre
    from hiby_music_tools.library.queries import browse
    from hiby_music_tools.library.indexer import refresh


@unittest.skipUnless(QT and shutil.which('ffmpeg') and shutil.which('ffprobe'), 'Install PySide6 and FFmpeg for metadata editor tests')
class MetadataGuiTests(unittest.TestCase):
    setUpClass = classmethod(player_tests.PlayerGuiTests.setUpClass.__func__)
    setUp = player_tests.PlayerGuiTests.setUp
    wait = player_tests.PlayerGuiTests.wait
    idle = player_tests.PlayerGuiTests.idle
    item = player_tests.PlayerGuiTests.item
    click = player_tests.PlayerGuiTests.click

    def cleanup(self):
        self.engine.metadata_controller.shutdown()
        player_tests.PlayerGuiTests.cleanup(self)

    def editor_idle(self):
        self.wait(lambda: not self.engine.metadata_controller.busy)

    def open_track(self, *, organize=False):
        self.browser.setMode('songs')
        self.idle()
        row = self.browser.model.rows[0]
        editor = self.engine.metadata_controller
        editor.edit('track', row['id'], organize)
        self.editor_idle()
        self.assertTrue(self.item('libraryMetadataDialog').property('visible'))
        return editor, row

    def test_pending_editor_fields_preview_save_and_index_refresh(self):
        editor, row = self.open_track()
        source = Path(row['path'])
        before = source.read_bytes()
        field = self.item('libraryEdit_title')
        field.forceActiveFocus()
        QTest.keyClick(self.window, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        for letter in 'retitled':
            QTest.keyClick(self.window, Qt.Key(ord(letter.upper())), Qt.KeyboardModifier.ShiftModifier if letter.isupper() else Qt.KeyboardModifier.NoModifier)
        self.assertEqual(editor.current['values']['title'], 'retitled')
        self.assertEqual(source.read_bytes(), before)
        self.click('libraryEditPreview')
        self.editor_idle()
        self.assertEqual(editor.mode, 'preview')
        self.assertEqual(editor.affected, 1)
        self.assertIn('→ retitled', editor.preview.rows[0]['changes'])
        self.assertEqual(source.read_bytes(), before)
        self.click('libraryEditSave')
        self.editor_idle()
        self.idle()
        self.assertEqual(editor.report['saved'], 1, editor.results.rows)
        self.assertEqual(read_track(source).original.title, 'retitled')
        self.assertTrue(Path(editor.results.rows[0]['backup']).exists())
        self.assertEqual(next(r for r in self.browser.model.rows if r['id'] == row['id'])['title'], 'retitled')
        self.assertEqual(self.engine.load_errors, [])

    def test_save_releases_player_and_updates_queue_after_move(self):
        editor, row = self.open_track(organize=True)
        editor.dismiss()
        self.player.playContext(row['id'])
        self.idle()
        queue_id = self.player.currentQueueId
        editor.edit('track', row['id'], True)
        self.editor_idle()
        editor.setField('title', 'Moved song')
        editor.buildPreview()
        self.editor_idle()
        destination = editor.preview.rows[0]['destination']
        self.assertNotEqual(destination, row['path'])
        editor.save()
        self.editor_idle()
        self.assertIn(('release',), self.audio.calls)
        self.assertEqual(editor.report['saved'], 1, editor.results.rows)
        self.assertFalse(Path(row['path']).exists())
        self.assertTrue(Path(destination).exists())
        self.assertEqual(self.player.currentQueueId, queue_id)
        self.assertEqual(self.player.current['path'], destination)
        self.assertEqual(self.player.current['title'], 'Moved song')
        self.assertEqual(self.player.state, 'stopped')
        editor.dismiss()
        self.player.togglePause()
        self.assertEqual(self.audio.calls[-1][0], 'sync')
        self.assertEqual(self.audio.calls[-1][1][0]['path'], destination)
        self.assertEqual(self.engine.load_errors, [])

    def test_bulk_album_selection_artist_corrections_and_explicit_save(self):
        self.idle()
        album = browse(self.music, self.database)['rows'][0]
        editor = self.engine.metadata_controller
        editor.edit('album', album['id'], False)
        self.editor_idle()
        editor.setField('album', 'Corrected album')
        editor.setField('genre', 'Jazz')
        editor.applyAlbum()
        editor.toggleIncluded(2)
        editor.buildPreview()
        self.editor_idle()
        self.assertEqual(editor.affected, 2)
        self.assertEqual(editor.preview.rows[2]['action'], 'skip')
        editor.save()
        self.editor_idle()
        self.assertEqual(editor.report['saved'], 2)
        self.assertEqual(editor.report['skipped'], 1)
        editor.dismiss()
        owner = next(a for a in browse(self.music, self.database, mode='artists')['rows'] if a['name'] == 'Album Artist')
        editor.edit('artist', owner['id'], False)
        self.editor_idle()
        editor.renameArtist('Corrected owner', True, True)
        self.assertTrue(all(d.values['album_artist'] == 'Corrected owner' for d in editor.session.drafts))
        self.assertTrue(all(d.values['track_artist'] == 'Track Artist' for d in editor.session.drafts))
        editor.buildPreview()
        self.editor_idle()
        self.assertEqual(editor.affected, 3)
        editor.dismiss()  # Discarding artist corrections must not change files.
        self.assertTrue(all(read_track(p).original.album_artist == 'Album Artist' for p in self.music.rglob('*.wav')))
        self.assertEqual(self.engine.load_errors, [])

    def test_manual_and_online_artwork_full_preview_and_no_implicit_save(self):
        editor, row = self.open_track()
        path = self.root / 'large.png'
        Image.new('RGB', (1800, 1400), '#334455').save(path)
        before = Path(row['path']).read_bytes()
        editor.manualArtwork(QUrl.fromLocalFile(str(path)))
        self.editor_idle()
        self.assertEqual(editor.artwork.rows[0]['resolution'], '1800 × 1400')
        editor.showFullArtwork(0)
        self.editor_idle()
        self.assertTrue(editor.fullImage.startswith('image://editor-full/'))
        editor.closeFullArtwork()
        editor.useArtwork(0, False, False)
        self.assertEqual(Path(row['path']).read_bytes(), before)
        art = preview(path.read_bytes(), 'Online fixture', 'apple', path)
        with mock.patch('hiby_music_tools.gui.metadata_controller.search_apple', return_value=[art]) as search:
            editor.searchApple('Artist', 'Album')
            self.editor_idle()
            search.assert_called_once()
        editor.buildPreview()
        self.editor_idle()
        self.assertIn('Preserve original', editor.preview.rows[0]['artwork'])
        editor.save()
        self.editor_idle()
        from mutagen import File as MutagenFile
        from hiby_music_tools.core.artwork import embedded_blobs
        self.assertIn(path.read_bytes(), embedded_blobs(MutagenFile(row['path'])))
        self.assertEqual(self.engine.load_errors, [])

    def test_cancellation_while_releasing_playback_does_not_start_a_save(self):
        editor, row = self.open_track()
        original = Path(row['path']).read_bytes()
        editor.setField('title', 'Pending')
        editor.buildPreview()
        self.editor_idle()
        with mock.patch.object(self.audio, 'release') as release:
            editor.save()
            release.assert_called_once()
            self.assertTrue(editor.writing)
            self.assertTrue(self.player.maintenance)
            editor.cancel()
            self.audio.released.emit()
            self.editor_idle()
        self.assertFalse(self.player.maintenance)
        self.assertEqual(Path(row['path']).read_bytes(), original)
        self.assertEqual(editor.mode, 'preview')

    def test_artist_album_selection_and_responsive_editor_controls(self):
        self.idle()
        owner = next(a for a in browse(self.music, self.database, mode='artists')['rows'] if a['name'] == 'Album Artist')
        editor = self.engine.metadata_controller
        editor.edit('artist', owner['id'], False)
        self.editor_idle()
        editor.setSelection('all', False)
        self.assertEqual(editor.included, 0)
        editor.setSelection('album', True)
        self.assertEqual(editor.included, 3)
        for width, height in ((1200, 800), (750, 700)):
            self.window.resize(width, height)
            QTest.qWait(50)
            button = self.item('libraryEditPreview')
            from PySide6.QtCore import QPointF
            corner = button.mapToScene(QPointF(button.width(), button.height()))
            self.assertLessEqual(corner.x(), width)
            self.assertLessEqual(corner.y(), height)
        self.assertEqual(self.engine.load_errors, [])
