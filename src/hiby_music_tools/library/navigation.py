"""Resolve navigation from stable track IDs using the index, without music IO."""

from pathlib import Path

from .database import connect, index_path


def track_target(root, database=None, *, identifier, target, operation=None):
    if target not in ('artist', 'album'):
        raise ValueError('Unknown navigation target')
    database = database or index_path()
    if not database.is_file():
        return {}
    root = str(Path(root).expanduser().resolve())
    with connect(database, operation=operation) as con:
        row = con.execute('''SELECT t.album_id, ar.id AS artist_id, ar.name AS artist
            FROM tracks t JOIN roots r ON r.id=t.root_id
            LEFT JOIN artists ar ON ar.root_id=t.root_id AND ar.name_sort=t.artist_sort
            WHERE r.path=? AND t.id=?''', (root, identifier)).fetchone()
        if not row:
            return {}
        if target == 'album':
            return dict(target='album', id=row['album_id'])
        return dict(target='artist', id=row['artist_id'], name=row['artist']) if row['artist_id'] else {}
