"""Persistent user data, separate from the rebuildable library catalog.

Entries reference root + stable track ID, never a tag/title match. Unavailable
entries stay visible and can reconnect after an index refresh or file move.
"""
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import uuid

from hiby_music_tools.playback.state import state_path
from .database import connect as catalog
from .queries import decorated


def playlist_path():
    return state_path().parent / 'playlists.sqlite3'


@contextmanager
def connect(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        con.execute('PRAGMA journal_mode=WAL')
        con.execute('PRAGMA foreign_keys=ON')
        con.executescript('''CREATE TABLE IF NOT EXISTS playlists(id TEXT PRIMARY KEY, name TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS entries(id TEXT PRIMARY KEY, playlist_id TEXT NOT NULL
          REFERENCES playlists(id) ON DELETE CASCADE, root TEXT NOT NULL, track_id TEXT NOT NULL,
          ordinal INTEGER NOT NULL, snapshot TEXT NOT NULL);
          CREATE INDEX IF NOT EXISTS entry_order ON entries(playlist_id,ordinal);''')
        with con:
            yield con
    finally:
        con.close()


def name(value):
    value = value.strip()
    if not value or len(value) > 200:
        raise ValueError('Playlist names must contain 1–200 characters.')
    return value


def create(path, title):
    identifier = uuid.uuid4().hex
    with connect(path) as con:
        con.execute('INSERT INTO playlists VALUES(?,?)', (identifier, name(title)))
    return identifier


def rename(path, identifier, title):
    with connect(path) as con:
        if not con.execute('UPDATE playlists SET name=? WHERE id=?', (name(title), identifier)).rowcount:
            raise ValueError('Playlist no longer exists.')


def listing(path):
    with connect(path) as con:
        return [dict(r) for r in con.execute('''SELECT p.id,p.name,COUNT(e.id) AS count
          FROM playlists p LEFT JOIN entries e ON e.playlist_id=p.id GROUP BY p.id ORDER BY p.name COLLATE NOCASE,p.id''')]


def add(path, identifier, root, rows):
    root = str(Path(root).expanduser().resolve())
    with connect(path) as con:
        if not con.execute('SELECT 1 FROM playlists WHERE id=?', (identifier,)).fetchone():
            raise ValueError('Playlist no longer exists.')
        at = con.execute('SELECT COALESCE(MAX(ordinal),-1)+1 FROM entries WHERE playlist_id=?', (identifier,)).fetchone()[0]
        con.executemany('INSERT INTO entries VALUES(?,?,?,?,?,?)',
                        [(uuid.uuid4().hex, identifier, root, row['id'], at + i,
                          json.dumps(row, ensure_ascii=False)) for i, row in enumerate(rows)])


def remove(path, identifier, entry):
    with connect(path) as con:
        con.execute('DELETE FROM entries WHERE playlist_id=? AND id=?', (identifier, entry))


def move(path, identifier, entry, target):
    with connect(path) as con:
        entries = [r[0] for r in con.execute('SELECT id FROM entries WHERE playlist_id=? ORDER BY ordinal,id', (identifier,))]
        if entry not in entries:
            return
        entries.remove(entry)
        entries.insert(max(0, min(len(entries), target)), entry)
        con.executemany('UPDATE entries SET ordinal=? WHERE id=? AND playlist_id=?',
                        [(i, key, identifier) for i, key in enumerate(entries)])


def detail(path, identifier, database, operation=None):
    with connect(path) as con:
        title = con.execute('SELECT name FROM playlists WHERE id=?', (identifier,)).fetchone()
        entries = list(con.execute('SELECT * FROM entries WHERE playlist_id=? ORDER BY ordinal,id', (identifier,)))
    if not title:
        return dict(id='', name='', rows=[])
    found = {}
    if Path(database).is_file():
        with catalog(Path(database), operation=operation) as con:
            con.execute('BEGIN')
            for start in range(0, len(entries), 500):
                if operation:
                    operation.checkpoint()
                keys = [e['track_id'] for e in entries[start:start + 500]]
                marks = ','.join('?' for _ in keys)
                for row in con.execute(f'''SELECT t.*,a.title AS album_title,r.path AS root
                    FROM tracks t JOIN roots r ON r.id=t.root_id JOIN albums a ON a.id=t.album_id
                    WHERE t.id IN ({marks})''', keys):
                    found[(row['root'], row['id'])] = decorated(row, Path(row['root']))
    rows = []
    for entry in entries:
        current = found.get((entry['root'], entry['track_id']))
        row = current or json.loads(entry['snapshot'])
        rows.append(dict(row, entryId=entry['id'], missing=current is None,
                         error='Not in the library index; refresh or remove this entry.' if current is None else row.get('error', '')))
    return dict(id=identifier, name=title['name'], rows=rows)
