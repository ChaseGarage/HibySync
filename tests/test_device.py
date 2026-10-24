"""Device identity/comparison tests use an injected Linux inventory and temp files."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from test_baseline import make_track
from hiby_music_tools.core.interaction import Cancelled, Operation
from hiby_music_tools.device.detection import LinuxDevices
from hiby_music_tools.device.preview import compare, scan
from hiby_music_tools.library.indexer import refresh
from hiby_music_tools.sync import needs_copy


class DeviceFixture:
    def __init__(self, base, *, mtp=False):
        self.base = base
        self.source = base / 'library'
        self.source.mkdir()
        self.usb_root = base / 'sys-usb'
        self.usb = self.usb_root / '1-5'
        self.usb.mkdir(parents=True)
        for key, value in dict(product='SONIX-PLAYER', manufacturer='HiBy', serial='TEST-R1',
                               idVendor='1234', idProduct='5678', busnum='1', devnum='5').items():
            (self.usb / key).write_text(value)
        self.gvfs = base / 'gvfs'
        self.mount = self.gvfs if mtp else base / 'mounted R1'
        self.mount.mkdir()
        self.endpoint = self.gvfs / 'mtp:host=HiBy_R1_TEST-R1' if mtp else None
        self.music = (self.endpoint / 'SD card' if mtp else self.mount) / 'Music'
        self.music.mkdir(parents=True)
        dev = self.music.stat().st_dev
        self.dev = f'{os.major(dev)}:{os.minor(dev)}'
        self.block = base / 'sys-block'
        self.block.mkdir()
        node = self.usb / 'storage/block/disk/partition'
        node.mkdir(parents=True)
        (self.block / self.dev).symlink_to(node)
        self.mountinfo = base / 'mountinfo'
        fs = 'fuse.gvfsd-fuse' if mtp else 'vfat'
        path = str(self.mount).replace(' ', r'\040')
        self.mountinfo.write_text(f'41 1 {self.dev} / {path} rw - {fs} /dev/fixture rw\n')
        self.devices = LinuxDevices(mountinfo=self.mountinfo, usb_root=self.usb_root,
                                    block_root=self.block, gvfs_root=self.gvfs)
        self.database = base / 'catalog.sqlite3'

    def target(self):
        return self.devices.detect().targets[0]

    def file(self, root, rel, contents):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
        return path

    def preview(self, verify=False, op=None):
        return compare(self.source, self.target(), self.devices, verify=verify,
                       database=self.database, operation=op)


class DeviceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='hiby-device-')
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.f = DeviceFixture(self.base)

    def test_mounted_usb_and_mtp_are_tied_to_live_identity(self):
        f = self.f
        target = f.target()
        self.assertEqual(target.music, str(f.music))
        self.assertEqual(f.devices.status(target), 'Connected')
        self.assertEqual(f.devices.validate(target, f.source), f.music)
        self.assertGreater(f.devices.storage(target)['total'], 0)
        mtp_base = self.base / 'mtp-fixture'
        mtp_base.mkdir()
        mtp = DeviceFixture(mtp_base, mtp=True)
        target = mtp.target()
        self.assertEqual(target.transport, 'MTP via GVFS/FUSE')
        self.assertEqual(mtp.devices.validate(target, mtp.source), mtp.music)
        self.assertIsNone(mtp.devices.storage(target))
        # Both GVFS's encoded bus/address and udev serial naming are supported.
        mtp.endpoint.rename(mtp.endpoint.with_name('mtp:host=%5Busb%3A001%2C005%5D'))
        self.assertEqual(mtp.devices.detect().status, 'Connected')
        self.assertIn('%5Busb', mtp.devices.detect().targets[0].music)

    def test_ordinary_music_folder_or_label_cannot_impersonate_a_device(self):
        f = self.f
        plain = self.base / 'HiBy R1/Music'
        plain.mkdir(parents=True)
        self.assertIsNone(f.devices.select(f.devices.detect(), plain))
        (f.usb / 'product').write_text('Generic USB storage')
        (f.usb / 'manufacturer').write_text('Unrelated manufacturer')
        self.assertEqual(f.devices.detect().status, 'Disconnected')
        # A folder with a perfect name without mount evidence is still refused.
        (f.usb / 'product').write_text('HiBy R1')
        f.mountinfo.write_text('')
        self.assertEqual(f.devices.detect().status, 'Unavailable')
        self.assertTrue(plain.is_dir())

    def test_unmounted_missing_symlink_and_stale_targets_are_refused_without_creation(self):
        f, target = self.f, self.f.target()
        f.music.rmdir()
        self.assertEqual(f.devices.detect().status, 'Unavailable')
        self.assertFalse(f.music.exists())
        with self.assertRaises(ValueError): f.devices.validate(target, f.source)
        self.assertFalse(f.music.exists())
        f.music.symlink_to(f.source)
        self.assertEqual(f.devices.detect().status, 'Unavailable')
        with self.assertRaises(ValueError): f.devices.validate(target, f.source)
        f.music.unlink()
        f.music.mkdir()
        f.mountinfo.write_text(f.mountinfo.read_text().replace('41 1', '42 1'))
        with self.assertRaises(ValueError): f.devices.validate(target, f.source)

    def test_usb_disconnect_and_unmount_have_distinct_status(self):
        f, target = self.f, self.f.target()
        f.mountinfo.write_text('')
        self.assertEqual(f.devices.status(target), 'Unavailable')
        (f.usb / 'idVendor').unlink()
        self.assertEqual(f.devices.status(target), 'Disconnected')
        self.assertFalse(f.devices.alive(target))

    def test_mtp_registry_removal_is_seen_without_scanning_music(self):
        base = self.base / 'mtp'
        base.mkdir()
        f = DeviceFixture(base, mtp=True)
        target = f.target()
        f.endpoint.rename(f.endpoint.with_name('not-an-mtp-mount'))
        self.assertEqual(f.devices.status(target), 'Unavailable')

    def test_fast_comparison_does_not_claim_unknown_same_sized_files_are_synced(self):
        f = self.f
        f.file(f.source, 'new.flac', b'new')
        f.file(f.source, 'changed.flac', b'new size')
        f.file(f.music, 'changed.flac', b'old')
        f.file(f.source, 'equal.mp3', b'equal')
        f.file(f.music, 'equal.mp3', b'equal')
        f.file(f.music, 'remove.wav', b'obsolete')
        with mock.patch('hiby_music_tools.device.preview.sha256_file', side_effect=AssertionError('Fast mode must not hash MTP audio')):
            plan = f.preview()
        self.assertEqual(plan.synced, 0)
        self.assertEqual(plan.changes, 3)
        self.assertEqual(plan.transfer_bytes, 11)
        self.assertEqual(len(plan.groups['uncertain']), 1)
        self.assertTrue(plan.complete)

    def test_hash_verification_detects_same_size_tag_art_audio_changes_and_preserves_everything(self):
        f = self.f
        f.file(f.source, 'same.mp3', b'match')
        f.file(f.music, 'same.mp3', b'match')
        f.file(f.source, 'metadata.flac', b'new metadata')
        f.file(f.music, 'metadata.flac', b'old metadata')
        f.file(f.music, 'obsolete.wav', b'remove')
        f.file(f.music, 'device.db', b'keep nonaudio')
        f.file(f.mount, 'Podcasts/podcast.mp3', b'outside Music')
        before = {p: p.read_bytes() for p in self.base.rglob('*') if p.is_file()}
        with mock.patch('hiby_music_tools.sync.init_db', side_effect=AssertionError('Preview must not initialize sync state')):
            plan = f.preview(True)
        self.assertEqual(plan.synced, 1)
        self.assertEqual(len(plan.groups['updated']), 1)
        self.assertEqual(len(plan.groups['remove']), 1)
        self.assertTrue(plan.complete)
        self.assertEqual(before, {p: p.read_bytes() for p in self.base.rglob('*') if p.is_file()})

    def test_fast_history_is_scoped_to_the_source_library(self):
        from hiby_music_tools.device.state import save
        f = self.f
        f.file(f.source, 'song.mp3', b'original')
        f.file(f.music, 'song.mp3', b'original')
        plan = f.preview(True)
        save(plan)
        f.file(f.source, 'song.mp3', b'new tags')
        self.assertEqual(len(f.preview().groups['updated']), 1)
        other = self.base / 'different-library'
        f.file(other, 'song.mp3', b'original')
        comparison = compare(other, f.target(), f.devices, state_path=plan.state_path)
        self.assertFalse(comparison.groups['updated'])
        self.assertEqual(len(comparison.groups['uncertain']), 1)

    def test_empty_source_guard_and_empty_device(self):
        f = self.f
        plan = f.preview()
        self.assertTrue(plan.complete)
        self.assertEqual(plan.changes, 0)
        f.file(f.music, 'keep.flac', b'keep')
        plan = f.preview()
        self.assertIn('Empty local library', plan.blocked)
        self.assertFalse(plan.complete)
        self.assertTrue((f.music / 'keep.flac').is_file())

    def test_unique_filename_case_and_unicode_aliases_are_verified_not_removed(self):
        f = self.f
        f.file(f.source, 'Artist/Album/track.flac', b'same audio')
        f.file(f.music, 'Artist/Album/Track.flac', b'same audio')
        f.file(f.source, 'Artist/Album/Caf\u00e9.mp3', b'unicode')
        f.file(f.music, 'Artist/Album/Cafe\u0301.mp3', b'unicode')
        quick = f.preview()
        self.assertFalse(quick.groups['conflicts'])
        self.assertEqual(len(quick.groups['uncertain']), 2)
        plan = f.preview(True)
        self.assertTrue(plan.complete)
        self.assertEqual(plan.synced, 2)
        self.assertEqual(plan.changes, 0)
        self.assertIn('Artist/Album/Track.flac', plan.remote_digests)
        f.file(f.source, 'Artist/Album/TRACK.flac', b'duplicate alias')
        self.assertTrue(f.preview(True).groups['conflicts'])

    def test_symlinks_case_aliases_and_file_directory_conflicts_block_preview(self):
        f = self.f
        f.file(f.source, 'Album/Song.flac', b'a')
        f.file(f.music, 'album/song.flac', b'a')
        f.file(f.source, 'directory.flac', b'a')
        (f.music / 'directory.flac').mkdir()
        outside = f.file(self.base, 'outside.mp3', b'untouched')
        (f.music / 'link.mp3').symlink_to(outside)
        plan = f.preview(True)
        self.assertGreaterEqual(len(plan.groups['conflicts']), 4)
        self.assertFalse(plan.complete)
        self.assertEqual(outside.read_bytes(), b'untouched')
        self.assertEqual(plan.changes, 0)

    def test_scan_errors_cancellation_and_device_loss_never_produce_a_ready_plan(self):
        f = self.f
        f.file(f.source, 'song.wav', b'a')
        f.file(f.music, 'song.wav', b'a')
        op = Operation()
        op.cancelled.set()
        with self.assertRaises(Cancelled): f.preview(True, op)
        original = os.scandir
        def denied(path):
            if Path(path) == f.music: raise PermissionError('Device read denied')
            return original(path)
        with mock.patch('hiby_music_tools.device.preview.os.scandir', side_effect=denied):
            plan = f.preview()
        self.assertFalse(plan.complete)
        self.assertTrue(plan.groups['conflicts'])
        with mock.patch.object(f.devices, 'alive', side_effect=[True, False]):
            with self.assertRaises(ValueError): f.preview(True)

    def test_real_catalog_labels_and_all_cli_supported_formats_are_reused(self):
        f = self.f
        make_track(f.source / 'Artist/Album/track.wav')
        refresh(f.source, f.database)
        for ext in ('.flac','.mp3','.m4a','.ogg','.aac','.alac','.aif','.wma','.ape','.wv','.opus','.mp4'):
            f.file(f.source, 'track' + ext, b'fixture')
        plan = f.preview()
        self.assertEqual(len(plan.groups['new']), 13)
        row = next(r for r in plan.groups['new'] if r['relpath'].endswith('.wav'))
        self.assertIn('Track Artist', row['detail'])
        self.assertTrue(plan.complete)

    def test_shared_cli_decision_preserves_legacy_fast_and_verified_rules(self):
        self.assertTrue(needs_copy(4, None, 'local'))
        self.assertTrue(needs_copy(4, 3, 'local'))
        self.assertFalse(needs_copy(4, 4, 'local'))
        self.assertTrue(needs_copy(4, 4, 'local', 'previous'))
        self.assertFalse(needs_copy(4, 4, 'local', 'local'))
        self.assertTrue(needs_copy(4, 4, 'local', verify=True, remote_digest='other'))
        self.assertFalse(needs_copy(4, 4, 'local', verify=True, remote_digest='local'))
