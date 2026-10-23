"""Verified imports and selective cleanup against disposable libraries."""

from pathlib import Path
import tempfile
import shutil
import subprocess
import unittest
from unittest import mock

from mutagen.wave import WAVE
from PIL import Image
from test_baseline import make_track

from hiby_music_tools.core.artwork import preview as art_preview
from hiby_music_tools.core.importing import execute_import
from hiby_music_tools.core import importing
from hiby_music_tools.core.interaction import Operation
from hiby_music_tools.core.review import build_plan, edit_album
from hiby_music_tools.core.scan import scan_inbox


class ImportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='hiby-execution-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.inbox, self.library = self.root / 'inbox', self.root / 'library'
        for name in ('one.wav', 'two.wav'):
            make_track(self.inbox / 'Album' / name)
        (self.inbox / 'notes.txt').write_text('keep me')
        self.session = scan_inbox(self.inbox, self.library, correction_cache=self.root / 'cache.json')
        self.before = {p: p.read_bytes() for p in self.inbox.rglob('*') if p.is_file()}

    def run_import(self, plan=None, replacements=None, op=None, remove_sources=False):
        return execute_import(self.session, plan if plan is not None else build_plan(self.session),
                              replacements, op, self.root / 'staging', remove_sources=remove_sources)

    def assert_sources_unchanged(self):
        self.assertEqual(self.before, {p: p.read_bytes() for p in self.inbox.rglob('*') if p.is_file()})

    def test_edits_selected_artwork_and_verified_duplicates(self):
        album = self.session.albums[0]
        edit_album(album, 'Reviewed Artist', 'Reviewed Album', '1999')
        album.tracks[0].track_number = '1/2'
        album.tracks[1].track_number = '2/2'
        album.tracks[0].disc_number = '1'
        image = self.root / 'apple.img'
        Image.new('RGB', (1200, 900), 'red').save(image, 'JPEG')
        art = art_preview(image.read_bytes(), 'Apple album', 'apple', image)
        for track in album.tracks:
            track.selected_art = art
        events = []
        plan = build_plan(self.session)
        report = self.run_import(plan, op=Operation(events.append))
        self.assertEqual(report.counts['imported'], 2, report)
        self.assertEqual(report.errors, [])
        audio = WAVE(plan[0].destination)
        self.assertEqual(str(audio.tags['TPE2']), 'Reviewed Artist')
        self.assertEqual(str(audio.tags['TPE1']), 'Track Artist')
        self.assertEqual(str(audio.tags['TDRC']), '1999')
        self.assertEqual(str(audio.tags['TRCK']), '1/2')
        import io
        with Image.open(io.BytesIO(audio.tags.getall('APIC')[0].data)) as cover:
            self.assertEqual(cover.size, (600, 450))
            self.assertEqual(cover.format, 'JPEG')
        self.assertTrue(any(e.phase == 'Importing verified tracks' for e in events))
        duplicates = self.run_import()
        self.assertEqual(duplicates.counts['duplicate'], 2, duplicates)
        self.assert_sources_unchanged()

    def test_existing_files_are_kept_unless_replacement_is_explicit(self):
        plan = build_plan(self.session)
        destination = plan[0].destination
        destination.parent.mkdir(parents=True)
        destination.write_bytes(b'existing library version')
        report = self.run_import()
        self.assertEqual(report.counts['skipped'], 1)
        self.assertEqual(destination.read_bytes(), b'existing library version')
        replacements = {str(plan[0].source)}
        replaced = self.run_import(replacements=replacements)
        self.assertEqual(replaced.counts['replaced'], 1, replaced)
        self.assertTrue(Path(replaced.recovery).is_dir())
        self.assertTrue(any(p.read_bytes() == b'existing library version'
                            for p in Path(replaced.recovery).rglob('*') if p.is_file()))
        self.assert_sources_unchanged()

    def test_cancellation_reports_completed_work(self):
        op = Operation()
        commit = importing.commit_copy
        def cancel_after_copy(*args):
            commit(*args)
            op.cancelled.set()
        with mock.patch.object(importing, 'commit_copy', side_effect=cancel_after_copy):
            report = self.run_import(op=op)
        self.assertTrue(report.cancelled)
        self.assertEqual(report.counts['imported'], 1)
        self.assert_sources_unchanged()

    def test_stale_source_and_destination_are_rejected(self):
        plan = build_plan(self.session)
        plan[0].source.write_bytes(plan[0].source.read_bytes() + b'changed')
        report = self.run_import(plan)
        self.assertIn('Source changed', ';'.join(report.errors))
        self.assertFalse(self.library.exists())
        # Fresh scan, then change a destination after preview.
        self.session = scan_inbox(self.inbox, self.library, correction_cache=self.root / 'cache.json')
        plan = build_plan(self.session)
        plan[0].destination.parent.mkdir(parents=True)
        plan[0].destination.write_bytes(b'new file arrived')
        report = self.run_import(plan)
        self.assertIn('Preview', ';'.join(report.errors))
        self.assertEqual(plan[0].destination.read_bytes(), b'new file arrived')

    def test_changed_artwork_and_symlink_destinations_are_rejected(self):
        path = self.root / 'art.png'
        Image.new('RGB', (64, 64)).save(path)
        self.session.albums[0].tracks[0].selected_art = art_preview(path.read_bytes(), 'Cover', 'folder', path)
        plan = build_plan(self.session)
        Image.new('RGB', (128, 128)).save(path)
        report = self.run_import(plan)
        self.assertIn('artwork changed', ';'.join(report.errors))
        self.assertFalse(self.library.exists())
        self.session.albums[0].tracks[0].selected_art = None
        self.library.mkdir()
        outside = self.root / 'outside'
        outside.mkdir()
        (self.library / 'Album Artist').symlink_to(outside, target_is_directory=True)
        report = self.run_import()
        self.assertIn('symlink', ';'.join(report.errors))
        self.assertEqual(list(outside.iterdir()), [])
        self.assert_sources_unchanged()

    def test_bad_track_is_retained_while_valid_tracks_can_import(self):
        bad = self.inbox / 'bad.mp3'
        bad.write_bytes(b'broken')
        self.session = scan_inbox(self.inbox, self.library, correction_cache=self.root / 'cache.json')
        report = self.run_import()
        self.assertEqual(report.counts['failed'], 1)
        self.assertEqual(report.counts['imported'], 2)
        self.assertEqual(bad.read_bytes(), b'broken')

    def test_failed_replacement_verification_restores_existing_file(self):
        row = build_plan(self.session)[0]
        row.destination.parent.mkdir(parents=True)
        row.destination.write_bytes(b'original library version')
        identical = importing.importer.files_identical
        def fail_final(src, dst):
            return False if dst == row.destination else identical(src, dst)
        with mock.patch.object(importing.importer, 'files_identical', side_effect=fail_final):
            report = self.run_import(replacements={str(row.source)})
        self.assertEqual(report.counts['failed'], 1, report)
        self.assertEqual(row.destination.read_bytes(), b'original library version')
        self.assertTrue(Path(report.recovery).exists())
        self.assert_sources_unchanged()

    def test_skip_and_prepare_failures_do_not_remove_inbox_files(self):
        self.session.albums[0].skip = True
        self.assertEqual(self.run_import().counts['skipped'], 2)
        self.assertFalse(self.library.exists())
        self.session.albums[0].skip = False
        with mock.patch.object(importing, 'stage_track', side_effect=OSError('disk full')):
            report = self.run_import()
        self.assertEqual(report.counts['failed'], 2)
        self.assertFalse(self.library.exists())
        self.assert_sources_unchanged()

    def test_file_arriving_at_publish_time_is_never_overwritten(self):
        destination = build_plan(self.session)[0].destination
        link = importing.os.link
        def arrive_before_publish(src, dst):
            if dst == destination:
                destination.write_bytes(b'arrived during import')
            return link(src, dst)
        with mock.patch.object(importing.os, 'link', side_effect=arrive_before_publish):
            report = self.run_import()
        self.assertEqual(report.counts['failed'], 1)
        self.assertEqual(report.counts['imported'], 1)
        self.assertEqual(destination.read_bytes(), b'arrived during import')
        self.assert_sources_unchanged()

    def test_cleanup_removes_only_verified_tracks_and_keeps_skips_and_notes(self):
        tracks = self.session.albums[0].tracks
        tracks[1].skip = True
        report = self.run_import(remove_sources=True)
        self.assertEqual(report.removed, 1, report)
        self.assertFalse(tracks[0].path.exists())
        self.assertTrue(tracks[1].path.exists())
        self.assertEqual((self.inbox / 'notes.txt').read_text(), 'keep me')
        self.assertEqual(report.counts['imported'], 1)
        self.assertEqual(report.counts['skipped'], 1)

    def test_cleanup_removes_verified_duplicates(self):
        self.assertEqual(self.run_import().counts['imported'], 2)
        report = self.run_import(remove_sources=True)
        self.assertEqual(report.counts['duplicate'], 2)
        self.assertEqual(report.removed, 2)
        self.assertEqual(list(self.inbox.rglob('*.wav')), [])

    def test_cleanup_retains_changed_source_and_damaged_destination(self):
        tracks = self.session.albums[0].tracks
        commit = importing.commit_copy
        def changed_after_copy(*args):
            commit(*args)
            if args[1].name == 'Song.wav':
                tracks[0].path.write_bytes(b'a new download replaced this source')
            else:
                args[1].write_bytes(b'destination changed after import')
        with mock.patch.object(importing, 'commit_copy', side_effect=changed_after_copy):
            report = self.run_import(remove_sources=True)
        self.assertEqual(report.removed, 0)
        self.assertTrue(all(track.path.exists() for track in tracks))
        self.assertTrue(all(result.cleanup_error for result in report.files))

    def test_cancelled_copy_does_not_start_cleanup(self):
        op = Operation()
        commit = importing.commit_copy
        def cancel_after_copy(*args):
            commit(*args)
            op.cancelled.set()
        with mock.patch.object(importing, 'commit_copy', side_effect=cancel_after_copy):
            report = self.run_import(op=op, remove_sources=True)
        self.assertTrue(report.cancelled)
        self.assertEqual(report.removed, 0)
        self.assert_sources_unchanged()

    def test_cleanup_permission_failure_is_reported_without_hiding_import(self):
        unlink = Path.unlink
        def deny_source(path, *args, **kwargs):
            if self.inbox in path.parents:
                raise PermissionError('source is read-only')
            return unlink(path, *args, **kwargs)
        with mock.patch.object(Path, 'unlink', deny_source):
            report = self.run_import(remove_sources=True)
        self.assertEqual(report.counts['imported'], 2)
        self.assertEqual(report.removed, 0)
        self.assertTrue(all('read-only' in result.cleanup_error for result in report.files))
        self.assert_sources_unchanged()

    def test_cleanup_keeps_conflicts_and_new_downloads(self):
        row = build_plan(self.session)[0]
        row.destination.parent.mkdir(parents=True)
        row.destination.write_bytes(b'keep existing library version')
        new_download = self.inbox / 'new-download.wav'
        commit = importing.commit_copy
        def new_file_arrives(*args):
            commit(*args)
            make_track(new_download)
        with mock.patch.object(importing, 'commit_copy', side_effect=new_file_arrives):
            report = self.run_import(remove_sources=True)
        self.assertEqual(report.removed, 1)
        self.assertEqual(report.counts['skipped'], 1)
        self.assertTrue(row.source.exists())
        self.assertTrue(new_download.exists())
        self.assertEqual(row.destination.read_bytes(), b'keep existing library version')
        self.assertTrue((self.inbox / 'notes.txt').exists())

    def test_cleanup_can_be_cancelled_between_originals(self):
        op = Operation()
        def cancel_during_cleanup(event):
            if event.phase == 'Removing verified originals' and event.completed == 1:
                op.cancelled.set()
        op.report = cancel_during_cleanup
        report = self.run_import(op=op, remove_sources=True)
        self.assertTrue(report.cancelled)
        self.assertEqual(report.counts['imported'], 2)
        self.assertEqual(report.removed, 1)
        self.assertEqual(len(list(self.inbox.rglob('*.wav'))), 1)

    def test_cleanup_keeps_embedded_artwork_source_needed_by_skipped_track(self):
        import io
        from mutagen.id3 import APIC
        source = self.session.albums[0].tracks[0].path
        image = io.BytesIO()
        Image.new('RGB', (64, 64), 'red').save(image, 'JPEG')
        audio = WAVE(source)
        audio.tags.add(APIC(mime='image/jpeg', type=3, data=image.getvalue()))
        audio.save()
        self.session = scan_inbox(self.inbox, self.library, correction_cache=self.root / 'none.json')
        tracks = self.session.albums[0].tracks
        tracks[1].selected_art = tracks[0].selected_art
        tracks[1].skip = True
        report = self.run_import(remove_sources=True)
        self.assertEqual(report.counts['imported'], 1)
        self.assertEqual(report.removed, 0)
        self.assertTrue(source.exists())
        self.assertIn('embedded artwork', report.files[-1].cleanup_error)

    @unittest.skipUnless(shutil.which('ffmpeg'), 'ffmpeg is used only to generate multi-format fixtures')
    def test_real_flac_mp3_mp4_ogg_opus_and_aiff_metadata_and_artwork(self):
        from hiby_music_tools.core.scan import read_track
        for suffix in ('flac', 'mp3', 'm4a', 'ogg', 'opus', 'aiff'):
            with self.subTest(format=suffix):
                source = self.root / suffix
                source.mkdir()
                track_path = source / ('track.' + suffix)
                result = subprocess.run(['ffmpeg', '-loglevel', 'error', '-i',
                                         str(self.inbox / 'Album/one.wav'), str(track_path)],
                                        capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)
                before = track_path.read_bytes()
                Image.new('RGB', (900, 900), 'green').save(source / 'cover.jpg')
                library = self.root / ('library-' + suffix)
                session = scan_inbox(source, library, correction_cache=self.root / 'none.json')
                edit_album(session.albums[0], 'New Artist', 'New Album', '2001')
                track = session.albums[0].tracks[0]
                track.track_number = '07/10'
                track.disc_number = '1/2'
                report = execute_import(session, build_plan(session), staging_parent=self.root / 'staging')
                self.assertEqual(report.counts['imported'], 1, report)
                imported = read_track(report.files[0].destination)
                self.assertEqual(imported.original.artist, 'New Artist')
                self.assertEqual(imported.original.album, 'New Album')
                self.assertEqual(imported.original.year, '2001')
                self.assertEqual(imported.disc_number, '1/2')
                self.assertTrue(imported.artwork)
                self.assertEqual(imported.artwork[0].width, 600)
                self.assertEqual(track_path.read_bytes(), before)
