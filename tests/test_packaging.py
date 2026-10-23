"""Offline installation and real subprocess tests, confined to a temp home."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import venv

from test_baseline import ROOT, make_track


class PackagingTests(unittest.TestCase):
    def test_installer_backs_up_commands_and_can_reinstall(self):
        with tempfile.TemporaryDirectory(prefix='hiby-installer-') as temporary:
            home = Path(temporary)
            bin_dir = home / '.local/bin'
            bin_dir.mkdir(parents=True)
            old_command = bin_dir / 'musicimport'
            old_command.write_text('#!/bin/sh\necho old-importer\n')
            old_command.chmod(0o755)
            old_bytes = old_command.read_bytes()
            env = os.environ.copy()
            env['HOME'] = str(home)
            env.pop('PYTHONPATH', None)
            for attempt in range(2):
                result = subprocess.run([str(ROOT / 'install.sh'), '--offline'],
                                        cwd=home, env=env, capture_output=True,
                                        text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                for command in ('hiby-music-sanitize', 'hiby-online-art', 'musicimport', 'musicsync'):
                    installed = bin_dir / command
                    self.assertTrue(installed.is_symlink())
                    check = subprocess.run([str(installed), '--help'], cwd=home,
                                           env=env, capture_output=True, text=True, timeout=10)
                    self.assertEqual(check.returncode, 0, check.stderr)
            root = home / '.local/share/hiby-music-tools'
            backups = list((root / 'backups').iterdir())
            self.assertEqual(len(backups), 2)
            self.assertTrue(any(not (p / 'musicimport').is_symlink()
                                and (p / 'musicimport').read_bytes() == old_bytes
                                for p in backups))
            self.assertFalse((home / 'Music').exists())
            self.assertFalse((home / '.cache/hiby-music-tools').exists())

    def test_installed_commands_and_import_helpers(self):
        with tempfile.TemporaryDirectory(prefix='hiby-install-') as temporary:
            root = Path(temporary)
            home = root / 'home'
            home.mkdir()
            environment = os.environ.copy()
            environment['HOME'] = str(home)
            environment.pop('PYTHONPATH', None)
            # Reuse available runtime/build dependencies, without network access
            # or changes to system/user Python packages.
            venv.create(root / 'venv', with_pip=True, system_site_packages=True)
            bin_dir = root / 'venv/bin'

            def run(*args):
                result = subprocess.run(list(map(str, args)), cwd=root,
                                        env=environment, capture_output=True,
                                        text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result

            run(bin_dir / 'python', '-m', 'pip', 'install', '--no-index',
                '--no-deps', '--no-build-isolation', ROOT)
            for command in ('hiby-music-sanitize', 'hiby-online-art', 'musicimport', 'musicsync'):
                self.assertIn('usage:', run(bin_dir / command, '--help').stdout)

            inbox = home / 'Music/Nicotine'
            track = inbox / 'song.wav'
            make_track(track)
            before = track.read_bytes()
            # Give the track a cover so the real artwork subprocess needs no
            # online requests. Neither installed helper exists at ~/.local/bin.
            from PIL import Image
            Image.new('RGB', (64, 64), 'red').save(inbox / 'cover.png')
            result = run(bin_dir / 'musicimport', '--no-online-review', '--keep-inbox')
            self.assertIn('Online album art: 0 album(s)', result.stdout)
            self.assertEqual(track.read_bytes(), before)
            library = home / 'Music/Library'
            self.assertTrue((library / 'missing-author/song.wav').is_file())
            metadata = home / '.cache/hiby-music-tools'
            self.assertTrue((metadata / 'musicbrainz.sqlite3').is_file())
            self.assertTrue((metadata / 'artwork/online-art.sqlite3').is_file())
            self.assertTrue((metadata / 'import-staging').is_dir())
            self.assertFalse((home / 'HiBy-Music').exists())
            self.assertFalse((home / 'Music/metadata-cache').exists())
            self.assertFalse((home / 'Music/.hiby-metadata-cache.json').exists())
            self.assertFalse((inbox / '.hiby-metadata-cache.json').exists())
            device = root / 'fake-device'
            device.mkdir()
            run(bin_dir / 'musicsync', '--device-music', device, '--verify', '--yes')
            self.assertEqual((library / 'missing-author/song.wav').read_bytes(),
                             (device / 'missing-author/song.wav').read_bytes())
            self.assertTrue((metadata / 'musicsync.sqlite3').is_file())


if __name__ == '__main__':
    unittest.main()
