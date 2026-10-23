"""Incremental, transactional library refresh. Never writes to music files."""

from collections import defaultdict
from dataclasses import dataclass
import json
import os
from pathlib import Path
import time
import uuid

from hiby_music_tools.sanitize import AUDIO_EXTENSIONS
from hiby_music_tools.core.files import signature
from hiby_music_tools.core.interaction import Operation
from .database import connect, index_path
from .grouping import regroup
from .metadata import ThumbnailCache, album_folder, folder_stamp, read_metadata


@dataclass(frozen=True)
class ScanResult:
    root: str
    tracks: int
    albums: int
    processed: int
    unchanged: int
    removed: int
    errors: int


def refresh(root: Path, database: Path | None = None, *, rebuild=False, operation=None):
    op = operation or Operation()
    root = root.expanduser().resolve()
    database = database or index_path()
    if not root.is_dir():
        raise ValueError(f'Music library does not exist: {root}')
    if database.resolve().is_relative_to(root):
        raise ValueError('The index and thumbnails must be stored outside the music library.')
    thumbnails = ThumbnailCache(database.parent / 'artwork', force=rebuild)
    files = []
    op.progress('Finding library tracks', 0)
    def walk_error(error):
        # Never prune an index from an incomplete directory enumeration.
        raise OSError(f'Could not scan library directory: {error}')
    for current, dirs, names in os.walk(root, followlinks=False, onerror=walk_error):
        op.checkpoint()
        dirs[:] = sorted(name for name in dirs if not (Path(current) / name).is_symlink())
        for name in sorted(names):
            path = Path(current) / name
            if path.suffix.lower() in AUDIO_EXTENSIONS and not path.is_symlink():
                try:
                    files.append((path, str(path.relative_to(root)), signature(path)))
                except FileNotFoundError:
                    continue
                except ValueError:
                    continue  # Ignore named pipes/sockets, never open them as audio.
        op.progress('Finding library tracks', len(files))
    current_paths = {relative for _, relative, _ in files}
    processed = unchanged = errors = 0
    folder_stamps = {}
    with connect(database, write=True, operation=op) as con:
        con.execute('BEGIN IMMEDIATE')
        row = con.execute('SELECT id FROM roots WHERE path=?', (str(root),)).fetchone()
        root_id = row['id'] if row else str(uuid.uuid4())
        con.execute('INSERT OR IGNORE INTO roots(id,path) VALUES(?,?)', (root_id, str(root)))
        old = {row['relpath']: dict(row) for row in con.execute('SELECT * FROM tracks WHERE root_id=?', (root_id,))}
        identities = defaultdict(list)
        for row in old.values():
            identities[(row['dev'], row['inode'], row['size'], row['mtime_ns'])].append(row)
        claimed = set()
        allowed = {r['name'] for r in con.execute('PRAGMA table_info(tracks)')}
        con.execute('CREATE TEMP TABLE seen(id TEXT PRIMARY KEY)')
        for index, (path, relative, initial) in enumerate(files):
            op.progress('Reading library metadata', index, len(files), relative)
            folders = dict.fromkeys((path.parent, album_folder(path, root)))
            for folder in folders:
                if folder not in folder_stamps:
                    folder_stamps[folder] = folder_stamp(folder)
            stamp = json.dumps([(str(folder), folder_stamps[folder]) for folder in folders])
            previous = old.get(relative)
            if previous is None:
                matches = [candidate for candidate in identities[initial[:4]]
                           if candidate['relpath'] not in current_paths and candidate['id'] not in claimed]
                if len(matches) == 1:
                    previous = matches[0]
            identifier = previous['id'] if previous else str(uuid.uuid4())
            claimed.add(identifier)
            same = previous and all(previous[key] == value for key, value in zip(
                ('dev', 'inode', 'size', 'mtime_ns', 'ctime_ns'), initial))
            cached_art = not previous or not previous['art_key'] or (thumbnails.directory / (previous['art_key'] + '.png')).is_file()
            if same and not rebuild and previous['folder_stamp'] == stamp and not previous['error'] and cached_art:
                record = previous
                unchanged += 1
            else:
                record = read_metadata(path, root, thumbnails)
                processed += 1
            try:
                final = signature(path)
            except FileNotFoundError:
                continue
            if final != initial:
                record['error'] = 'File changed during indexing; refresh again.'
            errors += bool(record.get('error'))
            record.update(id=identifier, root_id=root_id, relpath=relative, folder_stamp=stamp,
                          **dict(zip(('dev', 'inode', 'size', 'mtime_ns', 'ctime_ns'), final)))
            record = {key: value for key, value in record.items() if key in allowed}
            keys = list(record)
            updates = ','.join(f'{key}=excluded.{key}' for key in keys if key != 'id')
            con.execute(f'INSERT INTO tracks({",".join(keys)}) VALUES({",".join("?" for _ in keys)}) '
                        f'ON CONFLICT(id) DO UPDATE SET {updates}', [record[key] for key in keys])
            con.execute('INSERT INTO seen VALUES(?)', (identifier,))
        op.checkpoint()
        removed = con.execute('DELETE FROM tracks WHERE root_id=? AND id NOT IN (SELECT id FROM seen)', (root_id,)).rowcount
        albums = regroup(con, root_id, root, op)
        count = con.execute('SELECT COUNT(*) FROM tracks WHERE root_id=?', (root_id,)).fetchone()[0]
        con.execute('UPDATE roots SET scanned_at=?,last_errors=? WHERE id=?', (time.time(), errors, root_id))
        op.checkpoint()
        con.commit()
    op.progress('Library index updated', len(files), len(files))
    return ScanResult(str(root), count, albums, processed, unchanged, removed, errors)
