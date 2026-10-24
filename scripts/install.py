#!/usr/bin/env python3
"""Install a snapshot of this checkout without touching music or metadata."""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import venv


COMMANDS = ('hiby-music-sanitize', 'hiby-online-art', 'musicimport', 'musicsync')
PROJECT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--offline', action='store_true',
                        help='forbid package index access; use installed dependencies')
    parser.add_argument('--gui', action='store_true',
                        help='install PySide6/dbus-next dependencies and GUI launcher')
    args = parser.parse_args()
    commands = (*COMMANDS, 'hibysync') if args.gui else COMMANDS
    home = Path.home()
    install_root = home / '.local/share/hiby-music-tools'
    bin_dir = home / '.local/bin'
    for name in commands:
        destination = bin_dir / name
        if destination.is_dir() and not destination.is_symlink():
            parser.error(f'Command path is a directory: {destination}')

    releases = install_root / 'releases'
    releases.mkdir(parents=True, exist_ok=True)
    # Virtual environments embed absolute paths: create at its final location.
    release = Path(tempfile.mkdtemp(prefix='install-', dir=releases))
    activated = False
    try:
        # CachyOS supplies Pillow/Mutagen via pacman. Reuse those packages when
        # available; pip installs missing requirements into this venv only.
        venv.create(release, with_pip=True, system_site_packages=True)
        python = release / 'bin/python'
        command = [str(python), '-m', 'pip', 'install', '--disable-pip-version-check',
                   '--no-build-isolation', '--no-cache-dir']
        if args.offline:
            command.append('--no-index')
        target = str(PROJECT) + ('[gui]' if args.gui else '')
        subprocess.run([*command, target], check=True)
        env = os.environ.copy()
        env.pop('PYTHONPATH', None)
        for name in commands:
            subprocess.run([str(release / 'bin' / name), '--help'],
                           check=True, stdout=subprocess.DEVNULL, env=env)

        bin_dir.mkdir(parents=True, exist_ok=True)
        backups = install_root / 'backups' / release.name
        existing = [name for name in commands if os.path.lexists(bin_dir / name)]
        if existing:
            backups.mkdir(parents=True)
            for name in existing:
                shutil.copy2(bin_dir / name, backups / name, follow_symlinks=False)

        # Save all previous commands before replacing any of them. Restore on
        # activation failure; never remove a release that a command still uses.
        changed = []
        try:
            for name in commands:
                destination = bin_dir / name
                temporary = bin_dir / f'.{name}-{release.name}'
                try:
                    temporary.symlink_to(release / 'bin' / name)
                    os.replace(temporary, destination)
                    changed.append(name)
                finally:
                    temporary.unlink(missing_ok=True)
        except BaseException:
            for name in reversed(changed):
                destination = bin_dir / name
                if name in existing:
                    os.replace(backups / name, destination)
                else:
                    destination.unlink()
            raise
        activated = True
        print(f'Installed into: {release}')
        print(f'Commands linked in: {bin_dir}')
        if existing:
            print(f'Previous commands saved in: {backups}')
        if str(bin_dir) not in os.environ.get('PATH', '').split(os.pathsep):
            print(f'Add {bin_dir} to PATH to run the commands by name.')
        print('No music, metadata, inbox, or device files were changed.')
        if args.gui and not shutil.which('mpv'):
            print('Library playback requires mpv: sudo pacman -S mpv')
        if args.gui and (not shutil.which('ffmpeg') or not shutil.which('ffprobe')):
            print('Library metadata saves require audio verification: sudo pacman -S ffmpeg')
        if args.gui:
            gio = subprocess.run([str(python), '-c', 'import gi; gi.require_version("Gio", "2.0"); from gi.repository import Gio'],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
            if gio.returncode:
                print('Optional native MTP sync requires GIO: sudo pacman -S python-gobject gvfs gvfs-mtp')
    finally:
        if not activated:
            shutil.rmtree(release)


if __name__ == '__main__':
    main()
