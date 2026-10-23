"""Disposable, versioned SQLite catalog. Audio files remain authoritative."""

from contextlib import contextmanager
from pathlib import Path
import sqlite3
import unicodedata

from hiby_music_tools.core.interaction import Operation
from hiby_music_tools.paths import metadata_dir


def index_path():
    return metadata_dir() / 'library' / 'index.sqlite3'


def folded(value):
    return ' '.join(unicodedata.normalize('NFKC', value or '').casefold().split())


SCHEMA = '''
CREATE TABLE roots (
    id TEXT PRIMARY KEY, path TEXT NOT NULL UNIQUE, scanned_at REAL,
    last_errors INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE tracks (
    id TEXT PRIMARY KEY, root_id TEXT NOT NULL REFERENCES roots(id),
    relpath TEXT NOT NULL, dev INTEGER, inode INTEGER, size INTEGER,
    mtime_ns INTEGER, ctime_ns INTEGER, folder_stamp TEXT,
    title TEXT, artist TEXT, album_artist TEXT, album TEXT, year TEXT,
    track_number TEXT, disc_number TEXT, track_sort INTEGER, disc_sort INTEGER,
    duration REAL, format TEXT, codec TEXT, bitrate INTEGER, sample_rate INTEGER,
    bit_depth INTEGER, compilation INTEGER, art_key TEXT, art_origin TEXT,
    error TEXT, album_id TEXT, title_sort TEXT, artist_sort TEXT, album_sort TEXT,
    search_text TEXT, UNIQUE(root_id, relpath)
);
CREATE TABLE artists (
    id TEXT PRIMARY KEY, root_id TEXT NOT NULL REFERENCES roots(id),
    name TEXT NOT NULL, name_sort TEXT NOT NULL
);
CREATE TABLE albums (
    id TEXT PRIMARY KEY, root_id TEXT NOT NULL REFERENCES roots(id),
    artist_id TEXT NOT NULL, artist TEXT NOT NULL, title TEXT NOT NULL, year TEXT,
    title_sort TEXT, artist_sort TEXT, art_key TEXT, track_count INTEGER,
    duration REAL, disc_count INTEGER, max_disc INTEGER
);
CREATE TABLE artist_albums (
    artist_id TEXT NOT NULL, album_id TEXT NOT NULL,
    PRIMARY KEY(artist_id, album_id)
);
CREATE INDEX tracks_album ON tracks(root_id, album_id, disc_sort, track_sort, title_sort, id);
CREATE INDEX tracks_title ON tracks(root_id, title_sort, id);
CREATE INDEX tracks_artist ON tracks(root_id, artist_sort, id);
CREATE INDEX tracks_album_sort ON tracks(root_id, album_sort, id);
CREATE INDEX tracks_year ON tracks(root_id, year, id);
CREATE INDEX tracks_duration ON tracks(root_id, duration, id);
CREATE INDEX albums_order ON albums(root_id, artist_sort, title_sort, id);
CREATE INDEX artists_order ON artists(root_id, name_sort, id);
CREATE INDEX artist_albums_album ON artist_albums(album_id, artist_id);
PRAGMA user_version=1;
'''


@contextmanager
def connect(path: Path, *, write=False, operation: Operation | None = None):
    if write:
        path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(path, timeout=10)
    else:
        con = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        version = con.execute('PRAGMA user_version').fetchone()[0]
        if version not in ((0, 1) if write else (1,)):
            raise ValueError(f'Unsupported library index version: {version}')
        if write:
            con.execute('PRAGMA journal_mode=WAL')
            con.execute('PRAGMA foreign_keys=ON')
            if version == 0:
                con.executescript('BEGIN IMMEDIATE;\n' + SCHEMA + '\nCOMMIT;')
        if operation:
            con.set_progress_handler(lambda: int(operation.cancelled.is_set()), 2000)
        yield con
    except sqlite3.OperationalError:
        if operation:
            operation.checkpoint()
        raise
    finally:
        con.close()
