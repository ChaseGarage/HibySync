"""Offline installation and real subprocess tests, confined to a temp home."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import venv

from test_baseline import ROOT, make_track
import importlib.util


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
                gui = attempt == 1 and importlib.util.find_spec('PySide6') is not None
                command = [str(ROOT / 'install.sh'), '--offline'] + (['--gui'] if gui else [])
                result = subprocess.run(command,
                                        cwd=home, env=env, capture_output=True,
                                        text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                for command in ('hiby-music-sanitize', 'hiby-online-art', 'musicimport', 'musicsync'):
                    installed = bin_dir / command
                    self.assertTrue(installed.is_symlink())
                    check = subprocess.run([str(installed), '--help'], cwd=home,
                                           env=env, capture_output=True, text=True, timeout=10)
                    self.assertEqual(check.returncode, 0, check.stderr)
                if gui:
                    self.assertTrue((bin_dir / 'hibysync').is_symlink())
                    subprocess.run([str(bin_dir / 'hibysync'), '--help'], env=env,
                                   check=True, capture_output=True, timeout=10)
                    # A wheel must carry every QML component and the singleton
                    # manifest, not just the Python launcher. Test away from src.
                    quick_env = {**env, 'QT_QPA_PLATFORM': 'offscreen', 'QT_QUICK_BACKEND': 'software'}
                    script = '''
from PySide6.QtGui import QGuiApplication
from PySide6.QtCore import QCoreApplication, QEvent
from hiby_music_tools.gui.quick import create_engine
app = QGuiApplication([])
engine, controller = create_engine()
assert engine.rootObjects(), engine.load_errors
app.processEvents()
assert not engine.load_errors, engine.load_errors
controller.shutdown()
engine.library_controller.shutdown()
engine.player_controller.shutdown()
engine.rootObjects()[0].close()
engine.deleteLater()
QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
controller.deleteLater()
QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
'''
                    smoke = subprocess.run([str((bin_dir / 'hibysync').resolve().parent / 'python'),
                                            '-c', script], env=quick_env, cwd=home,
                                           capture_output=True, text=True, timeout=15)
                    self.assertEqual(smoke.returncode, 0, smoke.stdout + smoke.stderr)
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
            for command in ('hiby-music-sanitize', 'hiby-online-art', 'musicimport', 'musicsync', 'hibysync'):
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
