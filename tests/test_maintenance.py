"""Library writes use disposable fixtures, verified audio, and retained originals."""

import io
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from PIL import Image
from mutagen import File as MutagenFile
from mutagen.id3 import TIT2, TXXX
from mutagen.wave import WAVE

from test_baseline import make_track
from hiby_music_tools.core.artwork import preview, embedded_blobs
from hiby_music_tools.core.interaction import Operation
from hiby_music_tools.core.scan import read_track
from hiby_music_tools.core.tagging import read_genre
from hiby_music_tools.library.indexer import refresh
from hiby_music_tools.library.integrity import audio_fingerprint
from hiby_music_tools.library.maintenance import load_session, preview_session, execute
from hiby_music_tools.library.queries import browse
from hiby_music_tools.library.playback import tracks


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'Install FFmpeg for audio verification tests')
class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='hiby-maintenance-')
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.root = self.base / 'music'
        self.database = self.base / 'cache/index.sqlite3'
        self.seed = self.root / 'Artist/Album/one.wav'
        make_track(self.seed)

    def session(self, scope='album'):
        refresh(self.root, self.database)
        album = browse(self.root, self.database)['rows'][0]
        identifier = tracks(self.root, self.database)[0]['id'] if scope == 'track' else album['id']
        return load_session(self.root, self.database, scope, identifier)

    def test_tag_save_is_atomic_preserves_audio_art_and_unrelated_tags(self):
        audio = WAVE(self.seed)
        audio.tags['TXXX:custom'] = TXXX(desc='custom', text=['Keep this'])
        audio.save()
        before, payload = self.seed.read_bytes(), audio_fingerprint(self.seed)
        session = self.session('track')
        session.drafts[0].values.update(title='Changed', genre='Ambient', track_number='2/9', disc_number='1/2')
        plan = preview_session(session)
        self.assertEqual(self.seed.read_bytes(), before)
        report = execute(plan)
        self.assertEqual(report.files[0]['status'], 'saved', report.files)
        self.assertEqual(audio_fingerprint(self.seed), payload)
        self.assertEqual(read_genre(self.seed), 'Ambient')
        self.assertEqual(read_track(self.seed).original.title, 'Changed')
        self.assertEqual(str(WAVE(self.seed).tags['TXXX:custom']), 'Keep this')
        self.assertEqual(Path(report.files[0]['backup']).read_bytes(), before)
        self.assertEqual(report.updates[session.drafts[0].identifier]['title'], 'Changed')
        self.assertEqual(report.index_error, '')
        self.assertTrue((Path(report.recovery) / 'journal.jsonl').is_file())

    def test_bulk_shared_embedded_art_and_original_png_quality(self):
        other = self.seed.with_name('two.wav')
        shutil.copy2(self.seed, other)
        image = self.base / 'cover.png'
        Image.new('RGB', (1600, 1400), '#345678').save(image)
        png_before = image.read_bytes()
        from hiby_music_tools import sanitize
        sanitize.embed_folder_art(self.seed, image.read_bytes(), (1600, 1400), mime='image/png')
        session = self.session()
        art = next(d.track.artwork[0] for d in session.drafts if d.track.artwork)
        payloads = {d.track.path: audio_fingerprint(d.track.path) for d in session.drafts}
        for draft in session.drafts:
            draft.values.update(album='Corrected', album_artist='New album artist', genre='Electronic')
            draft.artwork = art
        report = execute(preview_session(session))
        self.assertEqual([r['status'] for r in report.files], ['saved', 'saved'], report.files)
        for draft in session.drafts:
            self.assertIn(image.read_bytes(), embedded_blobs(MutagenFile(draft.track.path)))
            self.assertEqual(audio_fingerprint(draft.track.path), payloads[draft.track.path])
            self.assertEqual(read_track(draft.track.path).original.track_artist, 'Track Artist')
        self.assertEqual(image.read_bytes(), png_before)

    def test_reorganization_opt_in_preview_collision_and_stable_ids(self):
        session = self.session('track')
        draft = session.drafts[0]
        draft.values['title'] = 'Renamed'
        tag_only = preview_session(session)
        self.assertEqual(tag_only.rows[0]['destination'], str(self.seed))
        plan = preview_session(session, True)
        destination = Path(plan.rows[0]['destination'])
        self.assertNotEqual(destination, self.seed)
        destination.parent.mkdir(parents=True)
        destination.write_bytes(b'unrelated file')
        blocked = preview_session(session, True)
        self.assertEqual(blocked.rows[0]['action'], 'blocked')
        report = execute(blocked)
        self.assertEqual(report.files[0]['status'], 'failed')
        self.assertEqual(destination.read_bytes(), b'unrelated file')
        destination.unlink()
        report = execute(preview_session(session, True))
        self.assertEqual(report.files[0]['status'], 'saved', report.files)
        self.assertFalse(self.seed.exists())
        self.assertTrue(destination.exists())
        self.assertEqual(report.index_error, '')
        self.assertEqual(tracks(self.root, self.database)[0]['id'], draft.identifier)
        self.assertEqual(report.updates[draft.identifier]['path'], str(destination))

    def test_stale_source_artwork_duplicates_and_protected_files(self):
        other = self.seed.with_name('two.wav')
        shutil.copy2(self.seed, other)
        session = self.session()
        for draft in session.drafts:
            draft.values['title'] = 'Identical destination'
        plan = preview_session(session, True)
        self.assertTrue(all(r['action'] == 'blocked' for r in plan.rows))
        session.drafts[1].included = False
        draft = session.drafts[0]
        plan = preview_session(session)
        report = execute(plan, protected_paths=[draft.track.path])
        self.assertEqual(report.files[0]['status'], 'skipped')
        audio = WAVE(draft.track.path)
        audio.tags['TIT2'] = TIT2(text=['External edit'])
        audio.save()
        report = execute(plan)
        self.assertEqual(report.files[0]['status'], 'failed')
        self.assertEqual(read_track(draft.track.path).original.title, 'External edit')

    def test_cancellation_retains_completed_saves_and_reconciles_index(self):
        for i in range(2):
            shutil.copy2(self.seed, self.seed.with_name(f'{i}.wav'))
        session = self.session()
        for draft in session.drafts:
            draft.values['genre'] = 'Jazz'
        op = Operation()
        original = __import__('hiby_music_tools.library.maintenance', fromlist=['commit_copy']).commit_copy
        def commit(*args, **kwargs):
            original(*args, **kwargs)
            op.cancelled.set()
        with mock.patch('hiby_music_tools.library.maintenance.commit_copy', side_effect=commit):
            report = execute(preview_session(session), operation=op)
        self.assertTrue(report.cancelled)
        self.assertEqual(len(report.files), 1)
        self.assertEqual(report.files[0]['status'], 'saved')
        self.assertEqual(len(report.updates), 1)
        self.assertEqual(sum(read_genre(d.track.path) == 'Jazz' for d in session.drafts), 1)

    def test_failure_before_publication_and_audio_corruption_keep_original(self):
        session = self.session('track')
        session.drafts[0].values['title'] = 'Pending'
        before = self.seed.read_bytes()
        with mock.patch('hiby_music_tools.library.maintenance.audio_fingerprint', side_effect=[('before', []), ('changed', [])]):
            report = execute(preview_session(session))
        self.assertEqual(report.files[0]['status'], 'failed')
        self.assertEqual(self.seed.read_bytes(), before)
        with mock.patch('hiby_music_tools.library.maintenance.commit_copy', side_effect=OSError('Simulated publication failure')):
            report = execute(preview_session(session))
        self.assertEqual(report.files[0]['status'], 'failed')
        self.assertEqual(self.seed.read_bytes(), before)
        self.assertEqual(Path(report.files[0]['backup']).read_bytes(), before)

    def test_supported_real_formats_metadata_and_audio_are_verified(self):
        for suffix, options in [('flac', ['-c:a', 'flac']), ('mp3', ['-c:a', 'libmp3lame']),
                                ('m4a', ['-c:a', 'aac']), ('ogg', ['-c:a', 'libvorbis']),
                                ('alac.m4a', ['-c:a', 'alac']),
                                ('opus', ['-c:a', 'libopus']), ('aiff', ['-c:a', 'pcm_s16be'])]:
            with self.subTest(suffix=suffix):
                path = self.root / 'Formats' / ('fixture.' + suffix)
                path.parent.mkdir(exist_ok=True)
                subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(self.seed), *options, str(path)], check=True)
                refresh(self.root, self.database)
                identifier = next(r['id'] for r in tracks(self.root, self.database) if r['path'] == str(path))
                session = load_session(self.root, self.database, 'track', identifier)
                before = audio_fingerprint(path)
                session.drafts[0].values.update(title='Updated', album='An album', album_artist='Owner',
                    track_artist='Contributor', year='2024', genre='Ambient', track_number='3/8', disc_number='1/2')
                report = execute(preview_session(session))
                self.assertEqual(report.files[0]['status'], 'saved', report.files)
                self.assertEqual(audio_fingerprint(path), before)
                self.assertEqual(read_genre(path), 'Ambient')

    def test_unselected_missing_tags_clear_genre_and_artist_grouping_warning(self):
        audio = WAVE(self.seed)
        audio.tags.clear()
        audio.save()
        session = self.session('track')
        self.assertEqual(session.drafts[0].original['title'], '')
        session.drafts[0].values.update(title='Named', genre='Jazz')
        report = execute(preview_session(session))
        self.assertEqual(report.files[0]['status'], 'saved')
        session = self.session('track')
        session.drafts[0].values['genre'] = ''
        report = execute(preview_session(session))
        self.assertEqual(read_genre(self.seed), '')
        self.assertEqual(report.files[0]['status'], 'saved')
        # An already-organized missing-artist path must not grow another
        # missing-author prefix on each reorganization.
        plan = preview_session(self.session('track'), True)
        execute(plan)
        plan = preview_session(self.session('track'), True)
        self.assertEqual(plan.rows[0]['source'], plan.rows[0]['destination'])

    def test_destination_race_and_stale_artwork_keep_original_files(self):
        session = self.session('track')
        session.drafts[0].values['title'] = 'Moved'
        plan = preview_session(session, True)
        target = Path(plan.rows[0]['destination'])
        target.parent.mkdir(parents=True)
        target.write_bytes(b'Created after preview')
        before = self.seed.read_bytes()
        report = execute(plan)
        self.assertEqual(report.files[0]['status'], 'failed')
        self.assertEqual(target.read_bytes(), b'Created after preview')
        self.assertEqual(self.seed.read_bytes(), before)
        art = self.base / 'art.png'
        Image.new('RGB', (800, 800), 'red').save(art)
        session.drafts[0].artwork = preview(art.read_bytes(), 'Manual', 'manual', art)
        plan = preview_session(session)
        Image.new('RGB', (800, 800), 'blue').save(art)
        report = execute(plan)
        self.assertEqual(report.files[0]['status'], 'failed')
        self.assertEqual(self.seed.read_bytes(), before)

    def test_explicit_artwork_optimization_and_nonfront_cover_preservation(self):
        from mutagen.id3 import APIC
        audio = WAVE(self.seed)
        back = io.BytesIO()
        Image.new('RGB', (64, 64), 'blue').save(back, 'PNG')
        audio.tags.add(APIC(mime='image/png', type=4, desc='Back', data=back.getvalue()))
        audio.save()
        image = self.base / 'cover.png'
        Image.new('RGB', (1800, 1400), 'red').save(image)
        original = image.read_bytes()
        session = self.session('track')
        draft = session.drafts[0]
        draft.artwork = preview(original, 'Manual', 'manual', image)
        draft.optimize = True
        report = execute(preview_session(session))
        self.assertEqual(report.files[0]['status'], 'saved')
        blobs = embedded_blobs(MutagenFile(self.seed))
        self.assertIn(back.getvalue(), blobs)
        front = next(frame.data for frame in WAVE(self.seed).tags.getall('APIC') if frame.type == 3)
        self.assertEqual(blobs[0], front)
        with Image.open(io.BytesIO(front)) as prepared:
            self.assertEqual(prepared.format, 'JPEG')
            self.assertLessEqual(max(prepared.size), 600)
        self.assertEqual(image.read_bytes(), original)

    def test_artist_merge_warning_and_index_failure_report_saved_files(self):
        session = self.session('track')
        session.drafts[0].values['album_artist'] = 'Track Artist'
        plan = preview_session(session)
        self.assertIn('already exists', plan.rows[0]['warning'])
        with mock.patch('hiby_music_tools.library.maintenance.refresh', side_effect=OSError('Index unavailable')):
            report = execute(plan)
        self.assertEqual(report.files[0]['status'], 'saved')
        self.assertEqual(read_track(self.seed).original.album_artist, 'Track Artist')
        self.assertIn(session.drafts[0].identifier, report.updates)
        self.assertEqual(report.index_error, 'Index unavailable')

    def test_reorganization_removes_stale_destination_index_record(self):
        session = self.session('track')
        draft = session.drafts[0]
        draft.values['title'] = 'Target'
        destination = Path(preview_session(session, True).rows[0]['destination'])
        make_track(destination)
        refresh(self.root, self.database)
        destination.unlink()  # A stale index entry must not steal the moved ID.
        report = execute(preview_session(session, True))
        self.assertEqual(report.files[0]['status'], 'saved')
        self.assertEqual(report.index_error, '')
        rows = tracks(self.root, self.database)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['id'], draft.identifier)
