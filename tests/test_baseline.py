"""Characterize the original executables using disposable libraries only."""

import contextlib
import importlib.machinery
import importlib.util
import io
import os
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest import mock
import wave

from mutagen.id3 import TALB, TDRC, TIT2, TPE1, TPE2
from mutagen.wave import WAVE
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]


def load_script(filename):
    name = filename.replace('-', '_') + '_baseline'
    modules = {'hiby-music-sanitize': 'sanitize', 'hiby-online-art': 'online_art',
               'musicimport': 'importer', 'musicsync': 'sync'}
    path = ROOT / 'src/hiby_music_tools' / (modules[filename] + '.py')
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    loader.exec_module(module)
    return module


def make_track(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b'\0\0' * 80)
    audio = WAVE(path)
    audio.add_tags()
    for frame in (TPE1(text=['Track Artist']), TPE2(text=['Album Artist']),
                  TALB(text=['Album']), TIT2(text=['Song']), TDRC(text=['2020'])):
        audio.tags.add(frame)
    audio.save()


class BaselineTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='hiby-baseline-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.home = self.root / 'home'
        self.home.mkdir()
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.dict(os.environ, {'HOME': str(self.home)}))
        self.stack.enter_context(mock.patch('pathlib.Path.home', return_value=self.home))
        self.stack.enter_context(mock.patch('socket.create_connection',
                                           side_effect=AssertionError('Network forbidden in baseline tests')))
        self.stack.enter_context(mock.patch.object(socket.socket, 'connect',
                                           side_effect=AssertionError('Network forbidden in baseline tests')))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
        self.sanitizer = load_script('hiby-music-sanitize')
        self.art = load_script('hiby-online-art')
        self.importer = load_script('musicimport')
        self.sync = load_script('musicsync')
        # Original scripts retain SQLite connections in some main() paths.
        # Track and close them before removing the temporary directories.
        import sqlite3
        connect = sqlite3.connect
        self.connections = []

        def tracked_connect(*args, **kwargs):
            con = connect(*args, **kwargs)
            self.connections.append(con)
            return con

        self.stack.enter_context(mock.patch('sqlite3.connect', side_effect=tracked_connect))
        self.addCleanup(lambda: [con.close() for con in self.connections])

    def run_main(self, module, *args):
        with mock.patch.object(sys, 'argv', [module.__file__, *map(str, args)]):
            return module.main()

    def sanitize(self, source, destination, *extra):
        return self.run_main(self.sanitizer, source, destination,
                             '--metadata-cache', self.root / 'corrections.json',
                             '--lookup-cache', self.root / 'lookup.sqlite3', *extra)

    def test_sanitize_layout_artwork_and_source_preservation(self):
        source = self.root / 'inbox'
        track = source / 'original.wav'
        make_track(track)
        Image.new('RGB', (900, 300), 'red').save(source / 'cover.png')
        original = {p.name: p.read_bytes() for p in source.iterdir()}
        destination = self.root / 'library'
        self.assertEqual(self.sanitize(source, destination), 0)
        # Current easy-tag reader does not map WAV ID3 frames to common keys.
        copied = destination / 'missing-author/original.wav'
        audio = WAVE(copied)
        self.assertEqual(str(audio.tags['TIT2']), 'Song')
        covers = audio.tags.getall('APIC')
        self.assertEqual(len(covers), 1)
        with Image.open(io.BytesIO(covers[0].data)) as image:
            self.assertEqual(image.format, 'JPEG')
            self.assertEqual(image.size, (600, 200))
        self.assertEqual(original, {p.name: p.read_bytes() for p in source.iterdir()})

    def test_missing_artist_and_collision_paths(self):
        meta = self.sanitizer.TrackMetadata(None, None, None, 'Song', None, None)
        source = self.root / 'inbox'
        destination = self.root / 'out'
        reserved = set()
        first, missing = self.sanitizer.build_destination(
            source / 'disc/a.wav', source, destination, meta, reserved)
        second, _ = self.sanitizer.build_destination(
            source / 'disc/b.wav', source, destination, meta, reserved)
        self.assertTrue(missing)
        self.assertEqual(first, destination / 'missing-author/disc/Song.wav')
        self.assertNotEqual(first, second)
        repeated, _ = self.sanitizer.build_destination(
            source / 'disc/b.wav', source, destination, meta, {first})
        self.assertEqual(second, repeated)

    def test_tagged_layout_prefers_album_artist_and_omits_unknown_year(self):
        source = self.root / 'inbox'
        track = source / 'song.flac'
        tags = {'artist': ['Track Artist'], 'albumartist': ['Album Artist'],
                'title': ['Song'], 'album': ['Album'], 'date': ['2020-01-01']}
        with mock.patch.object(self.sanitizer, 'MutagenFile',
                               return_value=type('Audio', (), {'tags': tags})()):
            meta = self.sanitizer.extract_metadata(track)
        self.assertEqual(meta.artist, 'Album Artist')
        self.assertEqual(meta.track_artist, 'Track Artist')
        target, missing = self.sanitizer.build_destination(
            track, source, self.root / 'out', meta, set())
        self.assertFalse(missing)
        self.assertEqual(target.relative_to(self.root / 'out').as_posix(),
                         'Album Artist/2020-Album/Song.flac')
        meta.year = None
        target, _ = self.sanitizer.build_destination(
            track, source, self.root / 'out', meta, set())
        self.assertEqual(target.parent.name, 'Album')

    def test_ambiguous_folder_art_fails_without_changing_source(self):
        source = self.root / 'inbox'
        track = source / 'song.wav'
        make_track(track)
        before = track.read_bytes()
        for name in ('one.png', 'two.png'):
            Image.new('RGB', (64, 64)).save(source / name)
        self.assertEqual(self.sanitize(source, self.root / 'out'), 4)
        self.assertEqual(track.read_bytes(), before)

    def test_sanitizer_dry_run_creates_cache_but_no_output(self):
        source = self.root / 'inbox'
        make_track(source / 'song.wav')
        destination = self.root / 'out'
        self.assertEqual(self.sanitize(source, destination, '--dry-run'), 0)
        self.assertFalse(destination.exists())
        self.assertTrue((self.root / 'lookup.sqlite3').is_file())

    def test_online_art_preserves_existing_cover(self):
        track = self.root / 'song.wav'
        make_track(track)
        image = io.BytesIO()
        Image.new('RGB', (64, 64), 'red').save(image, format='JPEG')
        self.art.embed_one(track, image.getvalue(), (64, 64))
        before = track.read_bytes()
        self.art.embed_one(track, b'invalid replacement', (64, 64))
        self.assertEqual(track.read_bytes(), before)
        self.assertTrue(self.art.has_cover(WAVE(track), '.wav'))

    def import_with_fake_helper(self, *, keep=False, fail=False):
        inbox = self.root / 'inbox'
        make_track(inbox / 'song.wav')
        (inbox / 'notes.txt').write_text('non-audio source file')
        library = self.root / 'library'

        def helper(command, **kwargs):
            if fail:
                return type('Result', (), {'returncode': 4})()
            staging = Path(command[2])
            self.assertTrue(staging.is_relative_to(self.home))
            self.importer.atomic_verified_copy(inbox / 'song.wav', staging / 'song.wav')
            return type('Result', (), {'returncode': 0})()

        args = ['--inbox', inbox, '--library', library,
                '--sanitizer', ROOT / 'hiby-music-sanitize', '--no-online-review',
                '--no-online-art', '--metadata-cache', self.root / 'corrections.json',
                '--lookup-cache', self.root / 'lookup.sqlite3']
        if keep:
            args.append('--keep-inbox')
        with mock.patch.object(self.importer.subprocess, 'run', side_effect=helper):
            result = self.run_main(self.importer, *args)
        return result, inbox, library

    def test_import_keep_inbox_and_verified_merge(self):
        result, inbox, library = self.import_with_fake_helper(keep=True)
        self.assertEqual(result, 0)
        self.assertEqual((inbox / 'song.wav').read_bytes(), (library / 'song.wav').read_bytes())
        self.assertTrue((inbox / 'notes.txt').exists())

    def test_successful_import_clears_even_non_audio_inbox_files(self):
        result, inbox, library = self.import_with_fake_helper()
        self.assertEqual(result, 0)
        self.assertEqual(list(inbox.iterdir()), [])
        self.assertTrue((library / 'song.wav').is_file())

    def test_failed_sanitizer_retains_inbox(self):
        result, inbox, library = self.import_with_fake_helper(fail=True)
        self.assertEqual(result, 4)
        self.assertTrue((inbox / 'song.wav').exists())
        self.assertTrue((inbox / 'notes.txt').exists())
        self.assertEqual(list(library.iterdir()), [])

    def test_conflict_defaults_to_abort_and_skip_accepts_different_bytes(self):
        staging, library = self.root / 'staging', self.root / 'library'
        staging.mkdir()
        library.mkdir()
        track = staging / 'song.wav'
        track.write_bytes(b'incoming')
        (library / track.name).write_bytes(b'existing')
        with mock.patch('builtins.input', return_value=''):
            self.assertIsNone(self.importer.resolve_conflicts(staging, library, [track]))
        with mock.patch('builtins.input', return_value='s'):
            self.assertEqual(self.importer.resolve_conflicts(staging, library, [track]),
                             {track: 'duplicate'})

    def sync_directories(self):
        source, device = self.root / 'library', self.root / 'fake-device'
        source.mkdir()
        device.mkdir()
        return source, device

    def sync_run(self, source, device, *extra):
        return self.run_main(self.sync, '--source', source, '--device-music', device,
                             '--state-db', self.root / 'sync.sqlite3', *extra)

    def test_sync_verify_copies_changes_deletes_audio_preserves_other_files(self):
        source, device = self.sync_directories()
        (source / 'song.mp3').write_bytes(b'new')
        (device / 'song.mp3').write_bytes(b'old')
        (device / 'obsolete.mp3').write_bytes(b'obsolete')
        (device / 'device.db').write_bytes(b'keep')
        self.assertEqual(self.sync_run(source, device, '--verify', '--yes'), 0)
        self.assertEqual((device / 'song.mp3').read_bytes(), b'new')
        self.assertFalse((device / 'obsolete.mp3').exists())
        self.assertEqual((device / 'device.db').read_bytes(), b'keep')

    def test_sync_empty_source_guard(self):
        source, device = self.sync_directories()
        (device / 'song.mp3').write_bytes(b'keep')
        self.assertEqual(self.sync_run(source, device, '--yes'), 3)
        self.assertEqual((device / 'song.mp3').read_bytes(), b'keep')

    def test_sync_copy_failure_prevents_deletion(self):
        source, device = self.sync_directories()
        (source / 'new.mp3').write_bytes(b'new')
        (device / 'obsolete.mp3').write_bytes(b'keep')
        with mock.patch.object(self.sync, 'safe_copy', side_effect=OSError('transfer failed')):
            self.assertEqual(self.sync_run(source, device, '--yes'), 4)
        self.assertEqual((device / 'obsolete.mp3').read_bytes(), b'keep')

    def test_sync_dry_run_creates_state_without_transfers(self):
        source, device = self.sync_directories()
        (source / 'new.mp3').write_bytes(b'new')
        (device / 'obsolete.mp3').write_bytes(b'keep')
        self.assertEqual(self.sync_run(source, device, '--dry-run'), 0)
        self.assertEqual([p.name for p in device.iterdir()], ['obsolete.mp3'])
        self.assertTrue((self.root / 'sync.sqlite3').exists())


if __name__ == '__main__':
    unittest.main()
