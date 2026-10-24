"""Build complete playback contexts from one SQLite snapshot, not visible rows."""

from pathlib import Path

from .database import connect, folded, index_path
from .queries import decorated, SORTS


def tracks(root, database=None, *, mode='songs', identifier='', search='', sort='title', descending=False, operation=None):
    root = Path(root).expanduser().resolve()
    database = database or index_path()
    if not database.is_file():
        return []
    with connect(database, operation=operation) as con:
        con.execute('BEGIN')
        library = con.execute('SELECT id FROM roots WHERE path=?', (str(root),)).fetchone()
        if not library:
            return []
        base = ' FROM tracks t JOIN albums a ON a.id=t.album_id WHERE t.root_id=?'
        params = [library['id']]
        order = 'a.artist_sort,a.title_sort,a.year,a.id,t.disc_sort,t.track_sort,t.title_sort,t.relpath,t.id'
        if mode == 'track':
            base += ' AND t.id=?'
            params.append(identifier)
        elif mode == 'album':
            base += ' AND a.id=?'
            params.append(identifier)
        elif mode == 'artist':
            base += ''' AND (a.artist_id=? OR t.artist_sort=(
                SELECT name_sort FROM artists WHERE id=? AND root_id=?))'''
            params.extend((identifier, identifier, library['id']))
        elif mode == 'songs':
            order = SORTS.get(sort, SORTS['title']) + (' DESC' if descending else ' ASC') + ',t.artist_sort,t.album_sort,t.relpath,t.id'
        else:
            raise ValueError('Invalid playback context')
        if search and mode == 'songs':
            base += ' AND instr(t.search_text,?)>0'
            params.append(folded(search))
        rows = []
        columns = 't.id,t.album_id,t.relpath,t.title,t.artist,t.album_artist,t.track_number,t.disc_number,t.duration,t.art_key,t.year,t.format,t.codec,t.sample_rate,t.bit_depth,t.bitrate,a.title AS album_title'
        for row in con.execute('SELECT ' + columns + base + ' ORDER BY ' + order, params):
            if operation:
                operation.checkpoint()
            rows.append(decorated(row, root))
        return rows
