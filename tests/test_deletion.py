"""Permanent deletion tests operate only on disposable indexed libraries."""

from pathlib import Path
import tempfile
import unittest
from unittest import mock

from test_baseline import make_track
from hiby_music_tools.core.interaction import Operation
from hiby_music_tools.library.indexer import refresh
from hiby_music_tools.library.queries import browse
from hiby_music_tools.library.playback import tracks
from hiby_music_tools.library.deletion import prepare, execute


class DeletionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='hiby-delete-')
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.root = self.base / 'music'
        self.database = self.base / 'cache/index.sqlite3'
        self.first = self.root / 'Artist/Album/one.wav'
        self.second = self.first.with_name('two.wav')
        make_track(self.first)
        make_track(self.second)
        self.cover = self.first.parent / 'cover.png'
        from PIL import Image
        Image.new('RGB', (40, 40), 'red').save(self.cover)
        refresh(self.root, self.database)
        self.rows = tracks(self.root, self.database)
        self.album = browse(self.root, self.database)['rows'][0]['id']

    def test_preparing_is_read_only_and_song_delete_keeps_other_files(self):
        before = self.first.read_bytes()
        plan = prepare(self.root, self.database, 'track', self.rows[0]['id'])
        self.assertEqual(self.first.read_bytes(), before)
        self.assertEqual(len(tracks(self.root, self.database)), 2)
        report = execute(plan)
        self.assertEqual(report.files[0]['status'], 'deleted')
        self.assertFalse(Path(plan.files[0]['path']).exists())
        self.assertTrue(Path(self.rows[1]['path']).exists())
        self.assertTrue(self.cover.exists())
        self.assertEqual(len(tracks(self.root, self.database)), 1)
        self.assertEqual(report.index_error, '')
        self.assertFalse((self.database.parent / 'maintenance').exists())

    def test_album_delete_removes_catalog_but_not_folder_images(self):
        report = execute(prepare(self.root, self.database, 'album', self.album))
        self.assertEqual(len(report.removed), 2)
        self.assertEqual(report.missing_albums, {self.album})
        self.assertFalse(self.first.exists())
        self.assertFalse(self.second.exists())
        self.assertTrue(self.cover.exists())
        self.assertEqual(browse(self.root, self.database)['total'], 0)
        self.assertEqual(browse(self.root, self.database, mode='artists')['total'], 0)

    def test_stale_modified_recreated_and_protected_files_are_retained(self):
        plan = prepare(self.root, self.database, 'track', self.rows[0]['id'])
        path = Path(plan.files[0]['path'])
        report = execute(plan, protected_paths=[path])
        self.assertEqual(report.files[0]['status'], 'failed')
        self.assertTrue(path.exists())
        path.write_bytes(path.read_bytes() + b'external change')
        report = execute(plan)
        self.assertFalse(report.removed)
        self.assertTrue(path.exists())
        conflict = prepare(self.root, self.database, 'track', self.rows[0]['id'])
        self.assertTrue(conflict.files[0]['error'])
        with self.assertRaises(ValueError):
            execute(conflict)
        path.unlink()
        missing = prepare(self.root, self.database, 'track', self.rows[0]['id'])
        make_track(path)
        report = execute(missing)
        self.assertFalse(report.removed)
        self.assertTrue(path.exists())

    def test_missing_files_prune_index_and_symlinks_are_blocked(self):
        path = Path(self.rows[0]['path'])
        path.unlink()
        report = execute(prepare(self.root, self.database, 'track', self.rows[0]['id']))
        self.assertEqual(report.files[0]['status'], 'missing')
        self.assertEqual(len(tracks(self.root, self.database)), 1)
        outside = self.base / 'outside.wav'
        make_track(outside)
        self.second.unlink()
        self.second.symlink_to(outside)
        conflict = prepare(self.root, self.database, 'track', self.rows[1]['id'])
        self.assertTrue(conflict.files[0]['error'])
        with self.assertRaises(ValueError):
            execute(conflict)
        self.assertTrue(outside.exists())

    def test_cancel_after_one_removal_reconciles_only_completed_files(self):
        plan = prepare(self.root, self.database, 'album', self.album)
        op = Operation()
        unlink = Path.unlink
        def remove(path, *args, **kwargs):
            unlink(path, *args, **kwargs)
            op.cancelled.set()
        with mock.patch.object(Path, 'unlink', remove):
            report = execute(plan, op)
        self.assertTrue(report.cancelled)
        self.assertEqual(len(report.removed), 1)
        self.assertEqual(len(tracks(self.root, self.database)), 1)
        self.assertEqual(sum(Path(r['path']).exists() for r in plan.files), 1)

    def test_delete_failure_keeps_file_and_index(self):
        plan = prepare(self.root, self.database, 'track', self.rows[0]['id'])
        with mock.patch.object(Path, 'unlink', side_effect=PermissionError('Access denied')):
            report = execute(plan)
        self.assertEqual(report.files[0]['status'], 'failed')
        self.assertEqual(len(tracks(self.root, self.database)), 2)
        self.assertTrue(Path(plan.files[0]['path']).exists())
