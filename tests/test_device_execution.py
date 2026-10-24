"""Measured sync execution against disposable filesystem and local-GIO fixtures."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from test_device import DeviceFixture
from hiby_music_tools.device.execution import execute
from hiby_music_tools.device.events import SyncOperation, SyncProgress
from hiby_music_tools.device.transports import FilesystemTransport, GioTransport


class SyncExecutionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='hiby-sync-execution-')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.f = DeviceFixture(self.base)
        self.events = []
        self.op = SyncOperation(self.events.append)

    def run_sync(self, plan=None, **kwargs):
        return execute(plan or self.f.preview(True), self.f.devices, operation=self.op,
                       recovery_root=self.base / 'recovery', **kwargs)

    def populate(self):
        f = self.f
        f.file(f.source, 'Artist/Album/New 歌.flac', b'N' * (2 * 1024 * 1024 + 17))
        f.file(f.source, 'Artist/Album/update.mp3', b'new tags/artwork')
        f.file(f.music, 'Artist/Album/update.mp3', b'old tags/artwork')
        f.file(f.music, 'obsolete.flac', b'obsolete')
        f.file(f.music, 'device.db', b'nonaudio')
        f.file(f.mount, 'Podcasts/keep.mp3', b'outside Music')

    def test_add_update_remove_unicode_and_measured_chunk_progress(self):
        self.populate()
        source = {p:p.read_bytes() for p in self.f.source.rglob('*') if p.is_file()}
        plan = self.f.preview(True)
        report = self.run_sync(plan, confirmed_removals=True)
        self.assertEqual(report.state, 'complete', report.errors)
        self.assertEqual([r['status'] for r in report.files], ['Completed'] * 3)
        self.assertEqual(report.bytes_transferred, plan.transfer_bytes)
        for local in source:
            self.assertEqual(local.read_bytes(), source[local])
            self.assertEqual((self.f.music / local.relative_to(self.f.source)).read_bytes(), source[local])
        self.assertFalse((self.f.music / 'obsolete.flac').exists())
        self.assertEqual((self.f.music / 'device.db').read_bytes(), b'nonaudio')
        self.assertEqual((self.f.mount / 'Podcasts/keep.mp3').read_bytes(), b'outside Music')
        progress = [e for e in self.events if isinstance(e, SyncProgress) and e.relpath.endswith('New 歌.flac') and e.state == 'Copying']
        self.assertGreater(len({e.file_bytes for e in progress}), 3)
        self.assertTrue(any(0 < e.file_bytes < e.file_total for e in progress))
        self.assertEqual([e.bytes_transferred for e in progress], sorted(e.bytes_transferred for e in progress))
        self.assertEqual(self.events[-1].state, 'Complete')
        self.assertTrue(report.final_plan.complete)
        self.assertEqual(report.final_plan.changes, 0)
        self.assertTrue(Path(report.recovery).is_file())
        self.assertIn(b'old tags/artwork', [p.read_bytes() for p in Path(report.recovery).parent.glob('original-*')])

    def test_stale_review_and_missing_removal_confirmation_do_not_write(self):
        self.populate()
        plan = self.f.preview(True)
        report = self.run_sync(plan)
        self.assertIn('confirmation', report.errors[0])
        self.assertTrue((self.f.music / 'obsolete.flac').exists())
        self.f.file(self.f.source, 'new arrival.mp3', b'new')
        before = {p:p.read_bytes() for p in self.f.music.rglob('*') if p.is_file()}
        report = self.run_sync(plan, confirmed_removals=True)
        self.assertEqual(report.state, 'stale')
        self.assertEqual(before, {p:p.read_bytes() for p in self.f.music.rglob('*') if p.is_file()})
        self.assertFalse((self.base / 'recovery').exists())

    def test_case_only_rename_with_other_changes_and_later_update(self):
        f = self.f
        f.file(f.source, 'Album/track.flac', b'same audio')
        f.file(f.music, 'Album/Track.flac', b'same audio')
        f.file(f.source, 'Album/new.mp3', b'new song')
        f.file(f.music, 'obsolete.mp3', b'old song')
        report = self.run_sync(confirmed_removals=True)
        self.assertEqual(report.state, 'complete', report.errors)
        self.assertEqual(report.final_plan.synced, 2)
        self.assertFalse((f.music / 'Album/track.flac').exists())
        self.assertEqual((f.music / 'Album/Track.flac').read_bytes(), b'same audio')
        f.file(f.source, 'Album/track.flac', b'new tags!!')
        plan = f.preview(True)
        self.assertEqual(len(plan.groups['updated']), 1)
        self.assertEqual(plan.groups['updated'][0]['destination'], 'Album/Track.flac')
        report = self.run_sync(plan)
        self.assertEqual(report.state, 'complete', report.errors)
        self.assertEqual((f.music / 'Album/Track.flac').read_bytes(), b'new tags!!')
        self.assertFalse((f.music / 'Album/track.flac').exists())
        self.assertIn(b'same audio', [p.read_bytes() for p in Path(report.recovery).parent.glob('original-*')])

    def test_fast_sync_skips_unchanged_audio_and_detects_subsequent_same_size_edits(self):
        f = self.f
        f.file(f.source, 'track.flac', b'unchanged')
        f.file(f.music, 'Track.flac', b'unchanged')
        f.file(f.source, 'new.mp3', b'new song')
        f.file(f.music, 'old.mp3', b'obsolete')
        from hiby_music_tools.device.transports import FilesystemTransport
        original_digest = FilesystemTransport.digest
        reads = []
        def digest(transport, rel, *args):
            reads.append(rel)
            self.assertNotEqual(rel, 'Track.flac', 'Fast sync must not read unchanged device audio')
            return original_digest(transport, rel, *args)
        with mock.patch.object(FilesystemTransport, 'digest', digest), mock.patch(
                'hiby_music_tools.device.preview.sha256_file', side_effect=AssertionError('No full-library hashing')):
            plan = f.preview()
            self.assertTrue(plan.complete)
            self.assertEqual(len(plan.groups['uncertain']), 1)
            report = self.run_sync(plan, confirmed_removals=True)
        self.assertEqual(report.state, 'complete', report.errors)
        self.assertEqual(f.preview().changes, 0)
        f.file(f.source, 'track.flac', b'new tags!')  # same size; snapshot detects it
        changed = f.preview()
        self.assertEqual(len(changed.groups['updated']), 1)
        self.assertEqual(changed.groups['updated'][0]['destination'], 'Track.flac')
        report = self.run_sync(changed)
        self.assertEqual(report.state, 'complete', report.errors)
        self.assertEqual((f.music / 'Track.flac').read_bytes(), b'new tags!')

    def test_fast_sync_stale_source_still_blocks_writes(self):
        self.populate()
        plan = self.f.preview()
        self.f.file(self.f.source, 'late.mp3', b'late arrival')
        report = self.run_sync(plan, confirmed_removals=True)
        self.assertEqual(report.state, 'stale', report.errors)
        self.assertTrue((self.f.music / 'obsolete.flac').exists())
        self.assertFalse((self.base / 'recovery').exists())

    def test_insufficient_storage_and_write_failure_keep_existing_and_skip_removals(self):
        self.populate()
        with mock.patch.object(FilesystemTransport, 'available', return_value=0):
            report = self.run_sync(confirmed_removals=True)
        self.assertIn('Insufficient device', report.errors[0])
        self.assertFalse((self.base / 'recovery').exists())
        with mock.patch.object(FilesystemTransport, 'put', side_effect=OSError('Device write denied')):
            report = self.run_sync(confirmed_removals=True)
        self.assertEqual(report.state, 'error')
        self.assertTrue(any(r['status'] == 'Failed' for r in report.files))
        self.assertEqual((self.f.music / 'Artist/Album/update.mp3').read_bytes(), b'old tags/artwork')
        self.assertTrue((self.f.music / 'obsolete.flac').exists())
        from hiby_music_tools.core.streaming import copy_stream
        def interrupted(source, destination, *, progress, **kwargs):
            def written(count):
                progress(count)
                raise OSError('Interrupted after a real device write')
            return copy_stream(source,destination,progress=written,**kwargs)
        with mock.patch('hiby_music_tools.device.transports.copy_stream',side_effect=interrupted):
            report = self.run_sync(confirmed_removals=True)
        self.assertEqual(report.state,'error')
        self.assertGreater(report.bytes_transferred,0)
        self.assertFalse((self.f.music/'Artist/Album/New 歌.flac').exists())
        self.assertEqual((self.f.music/'Artist/Album/update.mp3').read_bytes(),b'old tags/artwork')
        self.assertTrue((self.f.music/'obsolete.flac').exists())

    def test_cancel_large_transfer_retains_original_and_next_sync_retries(self):
        self.populate()
        def cancel(event):
            self.events.append(event)
            if isinstance(event, SyncProgress) and event.state == 'Copying' and (event.file_bytes or 0) >= 512 * 1024:
                self.op.cancel()
        self.op.report = cancel
        report = self.run_sync(confirmed_removals=True)
        self.assertEqual(report.state, 'cancelled')
        self.assertFalse((self.f.music / 'Artist/Album/New 歌.flac').exists())
        self.assertTrue((self.f.music / 'obsolete.flac').exists())
        self.assertFalse(list(self.f.music.rglob('*.part')))
        self.op = SyncOperation(self.events.append)
        report = self.run_sync(confirmed_removals=True)
        self.assertEqual(report.state, 'complete', report.errors)

    def test_disconnect_does_not_cleanup_missing_mount_and_reconnect_skips_completed(self):
        self.populate()
        text = self.f.mountinfo.read_text()
        completed = []
        def unplug(event):
            self.events.append(event)
            if isinstance(event, SyncProgress) and event.state == 'Completed' and event.operation != 'remove':
                completed.append(event.relpath)
                self.f.mountinfo.write_text('')
        self.op.report = unplug
        report = self.run_sync(confirmed_removals=True)
        self.assertEqual(report.state, 'disconnected')
        self.assertEqual(len(completed),1)
        self.assertTrue((self.f.music / 'obsolete.flac').exists())
        self.f.mountinfo.write_text(text)
        plan = self.f.preview(True)
        self.assertNotIn(completed[0], [r['relpath'] for r in plan.groups['new'] + plan.groups['updated']])
        self.op = SyncOperation(self.events.append)
        report = self.run_sync(plan, confirmed_removals=True)
        self.assertEqual(report.state, 'complete', report.errors)

    def test_corrupt_stage_and_source_changes_block_publication_and_removal(self):
        self.populate()
        original = FilesystemTransport.digest
        def bad(self, rel, progress=lambda count: None):
            if rel.endswith('.part'): return 'corrupt'
            return original(self, rel, progress)
        with mock.patch.object(FilesystemTransport, 'digest', bad):
            report = self.run_sync(confirmed_removals=True)
        self.assertEqual(report.state, 'error')
        self.assertFalse((self.f.music / 'Artist/Album/New 歌.flac').exists())
        self.assertTrue((self.f.music / 'obsolete.flac').exists())
        self.assertEqual((self.f.music / 'Artist/Album/update.mp3').read_bytes(), b'old tags/artwork')

    def test_source_or_device_changes_before_removal_gate_block_all_deletions(self):
        self.populate()
        changed = []
        def arrival(event):
            if isinstance(event, SyncProgress) and event.state == 'Completed' and not changed:
                changed.append(True)
                self.f.file(self.f.source,'late source.flac',b'arrived during sync')
        self.op.report = arrival
        report = self.run_sync(confirmed_removals=True)
        self.assertEqual(report.state,'error')
        self.assertTrue((self.f.music/'obsolete.flac').exists())
        self.assertIn('changed', report.errors[0])

    def test_non_atomic_failed_publish_restores_original_and_cancel_finishes_publication(self):
        self.f.file(self.f.source,'update.flac',b'new')
        self.f.file(self.f.music,'update.flac',b'old')
        class RenameTransport(FilesystemTransport):
            atomic_replace = False
            def move(self, old, new, **kwargs):
                if old.endswith('.part'): raise OSError('Native publish unavailable')
                return super().move(old,new,**kwargs)
        report = self.run_sync(transport_factory=RenameTransport)
        self.assertEqual(report.state,'error')
        self.assertEqual((self.f.music/'update.flac').read_bytes(),b'old')
        op = self.op
        class CancelDuringPublish(FilesystemTransport):
            atomic_replace = False
            def move(self, old, new, **kwargs):
                result = super().move(old,new,**kwargs)
                if new.endswith('.backup'): op.cancel()
                return result
        report = self.run_sync(transport_factory=CancelDuringPublish)
        self.assertEqual(report.state,'cancelled')
        self.assertEqual(report.files[0]['status'],'Completed')
        self.assertEqual((self.f.music/'update.flac').read_bytes(),b'new')

    def test_destination_collision_and_unsupported_moves_do_not_overwrite_or_delete(self):
        self.f.file(self.f.source,'new.flac',b'authoritative')
        original = FilesystemTransport.move
        def race(transport, old, new, **kwargs):
            if old.endswith('.part'):
                self.f.file(self.f.music,new,b'external arrival')
            return original(transport,old,new,**kwargs)
        with mock.patch.object(FilesystemTransport,'move',race):
            report = self.run_sync()
        self.assertEqual(report.state,'error')
        self.assertEqual((self.f.music/'new.flac').read_bytes(),b'external arrival')

    def test_long_names_do_not_make_staging_names_exceed_filesystem_limit(self):
        name = 'a' * 240 + '.flac'
        self.f.file(self.f.source,name,b'music')
        report = self.run_sync()
        self.assertEqual(report.state,'complete',report.errors)
        self.assertEqual((self.f.music/name).read_bytes(),b'music')

    @unittest.skipUnless(importlib.util.find_spec('gi'), 'Install python-gobject for local GIO API tests')
    def test_native_gio_local_copy_callbacks_and_non_atomic_publication(self):
        # This exercises GIO itself over file://, NOT actual MTP hardware.
        import gi
        gi.require_version('Gio','2.0')
        from gi.repository import Gio
        self.populate()
        def factory(target, devices, source, op):
            return GioTransport(target, devices, source, op, gio_root=Gio.File.new_for_path(target.music))
        report = self.run_sync(confirmed_removals=True, transport_factory=factory)
        self.assertEqual(report.state, 'complete', report.errors)
        self.assertTrue(any(isinstance(e,SyncProgress) and e.state == 'Copying' and (e.file_bytes or 0) > 0 for e in self.events))
        self.f.file(self.f.source,'cancel-native.flac',b'C'*(2*1024*1024))
        def cancel(event):
            if isinstance(event,SyncProgress) and event.state == 'Copying' and (event.file_bytes or 0) > 0:
                self.op.cancel()
        self.op = SyncOperation(cancel)
        report = self.run_sync(transport_factory=factory)
        self.assertEqual(report.state,'cancelled')
        self.assertFalse((self.f.music/'cancel-native.flac').exists())
