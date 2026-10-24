"""Explicit, reviewed permanent removal of indexed audio files only."""

from dataclasses import dataclass, field
import os
from pathlib import Path

from hiby_music_tools.core.files import optional_signature
from hiby_music_tools.core.importing import safe_destination
from hiby_music_tools.core.interaction import Cancelled, Operation
from hiby_music_tools.sanitize import AUDIO_EXTENSIONS
from .database import connect
from .grouping import regroup


@dataclass
class DeletePlan:
    root: Path
    database: Path
    scope: str
    label: str
    files: list


@dataclass
class DeleteReport:
    files: list = field(default_factory=list)
    removed: set = field(default_factory=set)
    missing_albums: set = field(default_factory=set)
    index_error: str = ''
    cancelled: bool = False


def prepare(root, database, scope, identifier, operation=None):
    op = operation or Operation()
    if scope not in ('track', 'album'):
        raise ValueError('Only individual songs or albums can be deleted')
    root = Path(root).expanduser().resolve()
    key = 't.id' if scope == 'track' else 't.album_id'
    with connect(database, operation=op) as con:
        rows = con.execute(f'''SELECT t.* FROM tracks t JOIN roots r ON r.id=t.root_id
            WHERE r.path=? AND {key}=? ORDER BY t.disc_sort,t.track_sort,t.relpath,t.id''',
            (str(root), identifier)).fetchall()
    if not rows:
        raise ValueError('This selection is no longer indexed. Refresh the Library.')
    files = []
    for index, row in enumerate(rows):
        path = root / row['relpath']
        op.progress('Checking files for deletion', index, len(rows), str(path))
        expected, error = None, ''
        try:
            safe_destination(path, root)
            if path.suffix.lower() not in AUDIO_EXTENSIONS:
                raise ValueError('Only indexed audio files can be deleted')
            expected = optional_signature(path)
            indexed = tuple(row[key] for key in ('dev', 'inode', 'size', 'mtime_ns', 'ctime_ns'))
            if expected is not None and expected != indexed:
                raise ValueError('File changed since indexing. Refresh before deleting.')
        except (OSError, ValueError) as exc:
            error = str(exc)
        files.append(dict(id=row['id'], album_id=row['album_id'], path=str(path),
                          signature=expected, error=error, status='missing' if expected is None else 'pending'))
    label = (rows[0]['title'] or Path(rows[0]['relpath']).stem) if scope == 'track' else (rows[0]['album'] or 'Unknown Album')
    return DeletePlan(root, database, scope, label, files)


def execute(plan, operation=None, *, protected_paths=()):
    """No trash, backup, recursive directory removal, or unrelated-file cleanup."""
    op = operation or Operation()
    report = DeleteReport()
    if not plan.files or any(row['error'] for row in plan.files):
        raise ValueError('Deletion preview has conflicts. Refresh and review again.')
    protected = {Path(path) for path in protected_paths}
    albums = {row['album_id'] for row in plan.files}
    for index, target in enumerate(plan.files):
        try:
            op.progress('Permanently deleting audio files', index, len(plan.files), target['path'])
        except Cancelled:
            report.cancelled = True
            break
        row = {**target, 'status': 'failed', 'warning': ''}
        path = Path(target['path'])
        try:
            safe_destination(path, plan.root)
            if path in protected:
                raise ValueError('File is open for playback; retained')
            current = optional_signature(path)
            if current != target['signature']:
                raise ValueError('File changed after confirmation was opened; retained')
            if current is not None:
                path.unlink()
                row['status'] = 'deleted'
                # The unlink has happened even if a directory flush fails.
                try:
                    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
                    try:
                        os.fsync(descriptor)
                    finally:
                        os.close(descriptor)
                except OSError as exc:
                    row['warning'] = 'Deleted; directory flush failed: ' + str(exc)
            else:
                row['status'] = 'missing'
            report.removed.add(target['id'])
        except (OSError, ValueError) as exc:
            row['error'] = str(exc)
        report.files.append(row)
    if report.removed:
        try:
            # Reconcile completed removals even if the operation was cancelled.
            # Grouping uses stored tags; it does not scan or modify music.
            with connect(plan.database, write=True) as con:
                con.execute('BEGIN IMMEDIATE')
                root = con.execute('SELECT id FROM roots WHERE path=?', (str(plan.root),)).fetchone()
                if root is None:
                    raise ValueError('Library root is no longer indexed')
                for identifier in report.removed:
                    con.execute('DELETE FROM tracks WHERE id=? AND root_id=?', (identifier, root['id']))
                regroup(con, root['id'], plan.root, Operation(op.report))
                con.execute("UPDATE roots SET last_errors=(SELECT COUNT(*) FROM tracks WHERE root_id=? AND error!='') WHERE id=?",
                            (root['id'], root['id']))
                for album in albums:
                    if not con.execute('SELECT 1 FROM albums WHERE id=? AND root_id=?', (album, root['id'])).fetchone():
                        report.missing_albums.add(album)
                con.commit()
        except Exception as exc:
            report.index_error = str(exc)
    report.cancelled = report.cancelled or op.cancelled.is_set()
    return report
