"""Authoritative-file indexing and paged SQL browsing in temporary libraries."""

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock
import uuid

from mutagen.id3 import TALB, TDRC, TPE1, TPE2, TPOS, TRCK
from mutagen.wave import WAVE
from PIL import Image

from test_baseline import make_track
from hiby_music_tools.core.interaction import Cancelled, Operation
from hiby_music_tools.library import indexer
from hiby_music_tools.library.database import connect
from hiby_music_tools.library.queries import browse, PAGE_SIZE


class LibraryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='hiby-library-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.music = self.root / 'music'
        self.music.mkdir()
        self.db = self.root / 'cache/index.sqlite3'

    def track(self, relative='Artist/Album/song.wav', *, album='Album', artist='Singer',
              album_artist='Artist', year='2020', number='1', disc='1', title='Song'):
        path = self.music / relative
        make_track(path)
        audio = WAVE(path)
        for name in ('TALB', 'TDRC', 'TPE1', 'TPE2', 'TRCK', 'TPOS', 'TIT2'):
            audio.tags.delall(name)
        from mutagen.id3 import TIT2
        for frame, value in ((TALB, album), (TDRC, year), (TPE1, artist), (TPE2, album_artist),
                             (TRCK, number), (TPOS, disc), (TIT2, title)):
            if value:
                audio.tags.add(frame(text=[value]))
        audio.save()
        return path

    def refresh(self, **kwargs):
        return indexer.refresh(self.music, self.db, **kwargs)

    def query(self, **kwargs):
        return browse(self.music, self.db, **kwargs)

    def snapshot(self):
        return {str(path.relative_to(self.music)): (path.read_bytes(), path.stat().st_mtime_ns)
                for path in self.music.rglob('*') if path.is_file()}

    def test_metadata_technical_properties_and_no_audio_writes(self):
        path = self.track()
        Image.new('RGB', (1200, 800), 'blue').save(path.parent / 'cover.jpg')
        before = self.snapshot()
        report = self.refresh()
        self.assertEqual((report.tracks, report.albums, report.errors), (1, 1, 0))
        row = self.query(mode='songs')['rows'][0]
        self.assertEqual(row['path'], str(path))
        self.assertEqual(row['artist'], 'Singer')
        self.assertEqual(row['album_artist'], 'Artist')
        self.assertEqual(row['year'], '2020')
        self.assertEqual(row['sample_rate'], 8000)
        self.assertEqual(row['bit_depth'], 16)
        self.assertEqual(row['format'], 'WAV')
        self.assertGreater(row['duration'], 0)
        self.assertEqual(row['size'], path.stat().st_size)
        self.assertEqual(row['mtime_ns'], path.stat().st_mtime_ns)
        self.assertEqual(row['art_origin'], 'folder')
        with Image.open(self.db.parent / 'artwork' / (row['art_key'] + '.png')) as thumbnail:
            self.assertLessEqual(max(thumbnail.size), 240)
        self.assertEqual(before, self.snapshot())

    def test_incremental_refresh_and_rebuild_preserve_identifiers(self):
        self.track()
        self.refresh()
        song = self.query(mode='songs')['rows'][0]
        album = self.query()['rows'][0]
        with mock.patch.object(indexer, 'read_metadata', side_effect=AssertionError('unchanged file reopened')):
            result = self.refresh()
        self.assertEqual((result.processed, result.unchanged), (0, 1))
        self.assertEqual(self.refresh(rebuild=True).processed, 1)
        self.assertEqual(self.query(mode='songs')['rows'][0]['id'], song['id'])
        self.assertEqual(self.query()['rows'][0]['id'], album['id'])

    def test_add_update_remove_and_rename_do_not_accumulate_rows(self):
        path = self.track()
        self.refresh()
        original = self.query(mode='songs')['rows'][0]
        renamed = path.with_name('renamed.wav')
        path.rename(renamed)
        self.refresh()
        row = self.query(mode='songs')['rows'][0]
        self.assertEqual(row['id'], original['id'])
        self.assertEqual(row['path'], str(renamed))
        audio = WAVE(renamed)
        audio.tags['TALB'] = TALB(text=['Changed Album'])
        audio.save()
        self.assertEqual(self.refresh().processed, 1)
        self.assertEqual(self.query(mode='songs')['rows'][0]['id'], original['id'])
        extra = self.track('Artist/Other/second.wav', album='Other')
        self.assertEqual(self.refresh().tracks, 2)
        renamed.unlink()
        result = self.refresh()
        self.assertEqual(result.removed, 1)
        self.assertEqual(self.query(mode='songs')['total'], 1)
        self.assertEqual(self.query()['rows'][0]['title'], 'Other')
        extra.unlink()
        self.refresh()
        self.assertEqual(self.query()['total'], 0)
        self.assertEqual(self.query(mode='artists')['total'], 0)

    def test_album_artist_compilations_and_multi_disc_grouping(self):
        self.track('Artist/Album/CD1/a.wav', artist='Contributor One', number='1/2', disc='1/2')
        self.track('Artist/Album/CD2/b.wav', artist='Contributor Two', number='1/2', disc='2/2', year='')
        self.track('Artist/Second/c.wav', album='Second', title='Song')
        self.refresh()
        albums = self.query()['rows']
        self.assertEqual(len(albums), 2)
        album = next(a for a in albums if a['title'] == 'Album')
        self.assertEqual(album['track_count'], 2)
        self.assertEqual(album['artist'], 'Artist')
        detail = self.query(mode='album', album_id=album['id'])
        self.assertTrue(detail['album']['multiDisc'])
        self.assertEqual([t['disc_sort'] for t in detail['rows']], [1, 2])
        self.assertTrue(all(t['discHeader'] for t in detail['rows']))
        artists = self.query(mode='artists')['rows']
        contributor = next(a for a in artists if a['name'] == 'Contributor Two')
        self.assertEqual(self.query(artist_id=contributor['id'])['total'], 1)

    def test_missing_album_artist_does_not_split_compilation_by_contributor(self):
        self.track('Mix/CD1/a.wav', album='Mix', artist='A', album_artist='', disc='1')
        self.track('Mix/CD2/b.wav', album='Mix', artist='B', album_artist='', disc='2')
        self.refresh()
        albums = self.query()['rows']
        self.assertEqual(len(albums), 1)
        self.assertEqual(albums[0]['artist'], 'Various Artists')
        self.assertEqual(albums[0]['track_count'], 2)

    def test_missing_tags_duplicate_titles_and_corrupt_files(self):
        self.track('unknown-a/a.wav', album='', artist='', album_artist='', year='')
        self.track('unknown-b/b.wav', album='', artist='', album_artist='', year='')
        (self.music / 'broken.mp3').write_bytes(b'not audio')
        result = self.refresh()
        self.assertEqual(result.errors, 1)
        self.assertEqual(self.query(mode='songs')['total'], 3)
        self.assertEqual(self.query()['total'], 3)
        self.assertEqual(len({t['id'] for t in self.query(mode='songs')['rows']}), 3)

    def test_folder_art_changes_and_missing_cached_thumbnail_are_incremental(self):
        path = self.track()
        self.refresh()
        self.assertEqual(self.query()['rows'][0]['art_key'], '')
        image = path.parent / 'cover.png'
        Image.new('RGB', (400, 400), 'red').save(image)
        self.assertEqual(self.refresh().processed, 1)
        first_key = self.query()['rows'][0]['art_key']
        Image.new('RGB', (400, 400), 'green').save(image)
        self.refresh()
        second_key = self.query()['rows'][0]['art_key']
        self.assertNotEqual(first_key, second_key)
        (self.db.parent / 'artwork' / (second_key + '.png')).unlink()
        self.assertEqual(self.refresh().processed, 1)

    def test_embedded_art_is_deduplicated_and_rebuild_repairs_thumbnail(self):
        import io
        from mutagen.id3 import APIC
        from hiby_music_tools.library import metadata
        picture = io.BytesIO()
        Image.new('RGB', (900, 900), 'purple').save(picture, 'JPEG')
        for name in ('one.wav', 'two.wav'):
            path = self.track('Artist/Album/' + name)
            audio = WAVE(path)
            audio.tags.add(APIC(mime='image/jpeg', type=3, data=picture.getvalue()))
            audio.save()
        before = self.snapshot()
        with mock.patch.object(metadata, 'preview', wraps=metadata.preview) as decode:
            self.refresh()
        self.assertEqual(decode.call_count, 1)
        rows = self.query(mode='songs')['rows']
        self.assertEqual(rows[0]['art_key'], rows[1]['art_key'])
        self.assertEqual(rows[0]['art_origin'], 'embedded')
        cached = self.db.parent / 'artwork' / (rows[0]['art_key'] + '.png')
        cached.write_bytes(b'corrupt cache')
        self.refresh(rebuild=True)
        with Image.open(cached) as image:
            self.assertEqual(image.size, (240, 240))
        self.assertEqual(before, self.snapshot())

    def test_cancellation_and_unreadable_directory_preserve_previous_index(self):
        self.track()
        self.refresh()
        self.track('new/song.wav', album='New')
        op = Operation()
        def stop(event):
            if event.phase == 'Reading library metadata' and event.completed == 1:
                op.cancelled.set()
        op.report = stop
        with self.assertRaises(Cancelled):
            self.refresh(operation=op)
        self.assertEqual(self.query(mode='songs')['total'], 1)
        def unreadable(*args, **kwargs):
            kwargs['onerror'](PermissionError('directory unreadable'))
            yield
        with mock.patch.object(indexer.os, 'walk', side_effect=unreadable):
            with self.assertRaises(OSError):
                self.refresh()
        self.assertEqual(self.query(mode='songs')['total'], 1)

    def test_unicode_search_sorting_and_pagination_use_sql_only(self):
        self.track(title='Straße 100%', artist='Björk')
        self.track('Second/z.wav', title='Zebra', artist='Zulu', album='Second', year='2002')
        self.refresh()
        with mock.patch.object(indexer, 'read_metadata', side_effect=AssertionError('query read music')):
            self.assertEqual(self.query(mode='songs', search='STRASSE')['total'], 1)
            self.assertEqual(self.query(mode='songs', search='BJÖRK')['total'], 1)
            self.assertEqual(self.query(mode='songs', search='%')['total'], 1)
            self.assertEqual(self.query(search='Zebra')['total'], 1)
            rows = self.query(mode='songs', sort='year')['rows']
            self.assertEqual([t['year'] for t in rows], ['2002', '2020'])
            self.assertEqual(len(self.query(mode='songs', limit=1, offset=1)['rows']), 1)
            self.assertEqual(self.query(mode='songs', search="';DROP TABLE tracks;")['total'], 0)

    def test_large_catalog_queries_are_bounded(self):
        self.track()
        self.refresh()
        with connect(self.db, write=True) as con:
            seed = dict(con.execute('SELECT * FROM tracks').fetchone())
            columns = list(seed)
            records = []
            for index in range(20000):
                record = {**seed, 'id': str(uuid.uuid5(uuid.NAMESPACE_OID, str(index))),
                          'relpath': f'synthetic/{index}.flac', 'title': f'Track {index:05}',
                          'title_sort': f'track {index:05}', 'search_text': f'track {index:05}',
                          'duration': index % 500}
                records.append([record[key] for key in columns])
            con.executemany(f'INSERT INTO tracks({",".join(columns)}) VALUES({",".join("?" for _ in columns)})', records)
            con.commit()
        first = self.query(mode='songs')
        self.assertEqual(first['total'], 20001)
        self.assertEqual(len(first['rows']), PAGE_SIZE)
        self.assertEqual(self.query(mode='songs', search='track 19999')['total'], 1)
        descending = self.query(mode='songs', sort='duration', descending=True)['rows']
        self.assertEqual(descending[0]['duration'], 499)

    def test_empty_missing_and_separate_roots(self):
        self.assertEqual(self.query()['total'], 0)
        self.assertFalse(self.db.exists())
        self.refresh()
        self.assertTrue(self.query()['summary']['scanned'])
        with self.assertRaises(ValueError):
            indexer.refresh(self.root / 'absent', self.db)
        with self.assertRaises(ValueError):
            indexer.refresh(self.music, self.music / 'index.sqlite3')
        other = self.root / 'other'
        other.mkdir()
        make_track(other / 'song.wav')
        indexer.refresh(other, self.db)
        self.assertEqual(self.query()['total'], 0)
        self.assertEqual(browse(other, self.db)['total'], 1)

    @unittest.skipUnless(shutil.which('ffmpeg'), 'ffmpeg generates optional format fixtures')
    def test_mp3_flac_mp4_alac_ogg_aiff_and_opus_metadata(self):
        seed = self.track()
        for suffix in ('mp3', 'flac', 'm4a', 'ogg', 'aiff', 'opus'):
            result = subprocess.run(['ffmpeg', '-loglevel', 'error', '-i', str(seed),
                                     str(seed.parent / ('converted.' + suffix))], capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run(['ffmpeg', '-loglevel', 'error', '-i', str(seed), '-c:a', 'alac',
                                 str(seed.parent / 'lossless.m4a')], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run(['ffmpeg', '-loglevel', 'error', '-f', 'lavfi', '-i',
                                 'anullsrc=r=44100:cl=stereo', '-t', '1', str(seed.parent / 'raw.aac')],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.refresh()
        self.assertEqual(result.tracks, 9)
        self.assertEqual(result.errors, 0)
        rows = self.query(mode='songs')['rows']
        self.assertTrue(all(t['duration'] for t in rows))
        self.assertTrue(all(t['sample_rate'] for t in rows if t['format'] != 'OPUS'))
        alac = next(t for t in rows if 'lossless.m4a' in t['path'])
        self.assertIn('alac', alac['codec'].lower())
        self.assertIsNotNone(alac['bit_depth'])
