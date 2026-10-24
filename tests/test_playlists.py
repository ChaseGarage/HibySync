"""Persistent playlists use disposable catalogs and audio files only."""
from pathlib import Path
import tempfile
import unittest

from test_baseline import make_track
from hiby_music_tools.library import playlists as p
from hiby_music_tools.library.indexer import refresh
from hiby_music_tools.library.playback import tracks


class PlaylistTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='hiby-playlists-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root, self.db, self.store = self.base / 'music', self.base / 'index.sqlite3', self.base / 'state/playlists.sqlite3'
        for i in range(3): make_track(self.root / f'Artist/Album/{i}.wav')
        refresh(self.root, self.db)
        self.rows = tracks(self.root, self.db)
        self.key = p.create(self.store, 'Evening')

    def test_persistence_duplicate_entries_order_rename_remove(self):
        p.add(self.store, self.key, self.root, self.rows + self.rows[:1])
        result = p.detail(self.store, self.key, self.db)
        self.assertEqual([r['id'] for r in result['rows']], [r['id'] for r in self.rows + self.rows[:1]])
        self.assertEqual(len({r['entryId'] for r in result['rows']}), 4)
        entry = result['rows'][-1]['entryId']
        p.move(self.store, self.key, entry, 0)
        self.assertEqual(p.detail(self.store, self.key, self.db)['rows'][0]['entryId'], entry)
        p.rename(self.store, self.key, 'Night')
        self.assertEqual(p.listing(self.store)[0]['name'], 'Night')
        p.remove(self.store, self.key, entry)
        self.assertEqual(p.listing(self.store)[0]['count'], 3)
        with self.assertRaises(ValueError): p.rename(self.store, self.key, ' ')
        self.assertEqual(p.listing(self.store)[0]['name'], 'Night')

    def test_moved_files_and_rebuild_keep_references_missing_files_stay_visible(self):
        p.add(self.store, self.key, self.root, self.rows)
        before = Path(self.rows[0]['path'])
        after = before.with_name('renamed.wav')
        before.rename(after)
        refresh(self.root, self.db, rebuild=True)
        details = p.detail(self.store, self.key, self.db)['rows']
        self.assertEqual(details[0]['path'], str(after))
        self.assertFalse(details[0]['missing'])
        after.unlink()
        refresh(self.root, self.db)
        self.assertTrue(p.detail(self.store, self.key, self.db)['rows'][0]['missing'])
        self.assertEqual(p.listing(self.store)[0]['count'], 3)
        self.assertEqual(len(p.detail(self.store, self.key, self.base / 'absent.sqlite3')['rows']), 3)

    def test_large_playlist_and_multiple_roots_are_resolved_by_id(self):
        p.add(self.store, self.key, self.root, self.rows * 700)
        result = p.detail(self.store, self.key, self.db)
        self.assertEqual(len(result['rows']), 2100)
        self.assertFalse(any(r['missing'] for r in result['rows']))
        other = p.create(self.store, 'Other')
        p.add(self.store, other, self.base / 'another-root', self.rows)
        self.assertTrue(all(r['missing'] for r in p.detail(self.store, other, self.db)['rows']))
        # Entries from one playlist cannot be removed through another.
        entry = result['rows'][0]['entryId']
        p.remove(self.store, other, entry)
        self.assertEqual(p.listing(self.store)[0]['count'], 2100)
