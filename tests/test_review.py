"""Read-only backend regressions using generated audio and image fixtures."""

import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from mutagen.id3 import APIC, TRCK
from mutagen.wave import WAVE
from PIL import Image

from test_baseline import make_track
from hiby_music_tools import sanitize
from hiby_music_tools.core.interaction import Cancelled, Operation
from hiby_music_tools.core.review import build_plan, edit_album
from hiby_music_tools.core.scan import scan_inbox


class ReviewTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='hiby-review-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source, self.library = self.root / 'inbox', self.root / 'library'
        self.source.mkdir()
        self.cache = self.root / 'corrections.json'
        patch = mock.patch('socket.socket.connect', side_effect=AssertionError('Network forbidden'))
        patch.start()
        self.addCleanup(patch.stop)

    def scan(self, op=None):
        return scan_inbox(self.source, self.library, op, self.cache)

    def track(self, relative='album/song.wav', embedded=False):
        path = self.source / relative
        make_track(path)
        if embedded:
            image = io.BytesIO()
            Image.new('RGB', (700, 350), 'blue').save(image, 'JPEG')
            audio = WAVE(path)
            audio.tags.add(APIC(mime='image/jpeg', type=3, data=image.getvalue()))
            audio.save()
        return path

    def snapshot(self):
        return {str(p.relative_to(self.root)): (p.read_bytes(), p.stat().st_mtime_ns)
                for p in self.root.rglob('*') if p.is_file()}

    def test_real_metadata_artwork_progress_and_no_writes(self):
        track = self.track(embedded=True)
        Image.new('RGB', (64, 64), 'red').save(track.parent / 'cover.png')
        before = self.snapshot()
        events = []
        session = self.scan(Operation(events.append))
        album = session.albums[0]
        self.assertEqual(album.status, 'Ready')
        self.assertEqual(album.artist, 'Album Artist')
        self.assertEqual(album.tracks[0].original.title, 'Song')
        self.assertEqual(album.tracks[0].selected_art.origin, 'embedded')
        self.assertEqual(len(album.tracks[0].artwork), 2)
        row = build_plan(session)[0]
        self.assertEqual(row.destination, self.library / 'Album Artist/2020-Album/Song.wav')
        self.assertEqual(events[-1].completed, 1)
        self.assertEqual(before, self.snapshot())
        self.assertFalse(self.library.exists())
        self.assertFalse(self.cache.exists())

    def test_manual_album_changes_preserve_originals_and_track_artists(self):
        self.track('album/one.wav')
        self.track('album/two.wav')
        session = self.scan()
        album = session.albums[0]
        edit_album(album, 'New Artist', 'New Album', '')
        self.assertEqual(album.status, 'Needs Review')
        for track in album.tracks:
            self.assertEqual(track.original.album, 'Album')
            self.assertEqual(track.proposed.track_artist, 'Track Artist')
        rows = build_plan(session)
        self.assertEqual(rows[0].destination.parent, self.library / 'New Artist/New Album')
        self.assertNotEqual(rows[0].destination, rows[1].destination)
        self.assertIn('New Album', rows[0].metadata_changes)
        album.skip = True
        self.assertTrue(all(row.action == 'Skip' for row in build_plan(session)))

    def test_missing_tags_and_broken_audio_are_reviewable(self):
        path = self.track()
        audio = WAVE(path)
        audio.tags.clear()
        audio.save()
        (path.parent / 'broken.mp3').write_bytes(b'not audio')
        session = self.scan()
        tracks = [t for a in session.albums for t in a.tracks]
        missing = next(t for t in tracks if t.path == path)
        self.assertIn('artist is missing', missing.reasons)
        self.assertIn('year is missing', missing.reasons)
        self.assertTrue(any(a.status == 'Error' for a in session.albums))
        self.assertTrue(any(row.action == 'Blocked' for row in build_plan(session)))

    def test_suspicious_artist_and_incomplete_album(self):
        path = self.track()
        audio = WAVE(path)
        audio.tags['TPE2'].text = ['example.com']
        audio.tags.add(TRCK(text=['1/10']))
        audio.save()
        album = self.scan().albums[0]
        self.assertEqual(album.status, 'Needs Review')
        self.assertTrue(any('web/domain' in reason for reason in album.tracks[0].reasons))
        self.assertTrue(any('Incomplete album' in reason for reason in album.tracks[0].reasons))

    def test_approved_cache_is_read_without_updates(self):
        path = self.track()
        correction = dict(artist='Correct Artist', album_artist='Correct Artist',
                          title='Correct Title', album='Correct Album', year='1999')
        self.cache.write_text(json.dumps({sanitize.cache_key(path, self.source): correction}))
        before = self.snapshot()
        track = self.scan().albums[0].tracks[0]
        self.assertEqual(track.original.title, 'Song')
        self.assertEqual(track.proposed.title, 'Correct Title')
        self.assertIn('approved', track.provenance)
        self.assertEqual(before, self.snapshot())

    def test_conflicts_are_warnings_and_not_duplicates(self):
        self.track()
        session = self.scan()
        destination = build_plan(session)[0].destination
        destination.parent.mkdir(parents=True)
        destination.write_bytes(b'existing')
        self.assertIn('duplicate comparison pending', build_plan(session)[0].warning)
        self.assertEqual(destination.read_bytes(), b'existing')

    def test_empty_invalid_nested_and_cancelled_scans(self):
        self.assertEqual(self.scan().albums, [])
        for source, library in ((self.library, self.source), (self.source, self.source),
                                (self.root, self.source), (self.source, self.source / 'nested')):
            with self.assertRaises(ValueError):
                scan_inbox(source, library)
        op = Operation()
        op.cancelled.set()
        with self.assertRaises(Cancelled):
            self.scan(op)

    def test_symlinks_are_not_followed(self):
        outside = self.root / 'outside.wav'
        make_track(outside)
        (self.source / 'linked.wav').symlink_to(outside)
        (self.source / 'loop').symlink_to(self.source, target_is_directory=True)
        self.assertEqual(self.scan().albums, [])

    def test_unreadable_file_and_bad_cache_report_errors(self):
        path = self.track()
        self.cache.write_text('invalid json')
        with mock.patch('hiby_music_tools.core.scan.MutagenFile', side_effect=PermissionError('unreadable')):
            session = self.scan()
        self.assertEqual(session.albums[0].status, 'Error')
        self.assertIn('unreadable', session.albums[0].tracks[0].error)
        self.assertIn('correction cache', session.warnings[0])

    def test_folder_art_is_used_when_embedded_art_is_missing(self):
        path = self.track()
        Image.new('RGB', (300, 600)).save(path.parent / 'cover.jpg')
        track = self.scan().albums[0].tracks[0]
        self.assertEqual(track.selected_art.origin, 'folder')
        self.assertEqual((track.selected_art.width, track.selected_art.height), (300, 600))
        self.assertEqual(self.scan().albums[0].status, 'Ready')

    def test_explicit_cover_choice_resolves_artwork_ambiguity_only(self):
        path = self.track()
        for name in ('one.png', 'two.png'):
            Image.new('RGB', (64, 64)).save(path.parent / name)
        album = self.scan().albums[0]
        track = album.tracks[0]
        self.assertEqual(album.status, 'Needs Review')
        track.selected_art = track.artwork[0]
        track.artwork_approved = True
        self.assertEqual(album.status, 'Ready')
        track.proposed.year = None
        self.assertEqual(album.status, 'Needs Review')

    def test_invalid_manual_numbers_and_malformed_saved_corrections(self):
        path = self.track()
        correction = dict(artist='Artist', album_artist='Artist', title='Title',
                          album='Album', year=1999)
        self.cache.write_text(json.dumps({sanitize.cache_key(path, self.source): correction}))
        album = self.scan().albums[0]
        self.assertEqual(album.tracks[0].proposed.year, '2020')
        self.assertIn('invalid field types', ';'.join(album.tracks[0].warnings))
        for number in ('²', '1/2/3', '9' * 5000):
            album.tracks[0].track_number = number
            self.assertEqual(album.status, 'Needs Review')
            self.assertIn('invalid track number', album.tracks[0].reasons)


if __name__ == '__main__':
    unittest.main()
