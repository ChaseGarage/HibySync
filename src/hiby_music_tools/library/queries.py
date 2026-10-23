"""Parameterized, paged SQL queries. No music files or full-size art are read."""

from pathlib import Path

from .database import connect, folded, index_path


PAGE_SIZE = 120
SORTS = {'title': 't.title_sort', 'artist': 't.artist_sort', 'album': 't.album_sort',
         'year': 't.year', 'duration': 't.duration'}


def duration_text(value):
    if value is None:
        return '—'
    seconds = max(0, int(value))
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f'{hours}:{minutes:02}:{seconds:02}' if hours else f'{minutes}:{seconds:02}'


def decorated(row, root):
    record = dict(row)
    record['image'] = 'image://library/' + record['art_key'] if record.get('art_key') else ''
    record['durationText'] = duration_text(record.get('duration'))
    if 'relpath' in record:
        record['path'] = str(root / record['relpath'])
        record['title'] = record['title'] or Path(record['relpath']).stem
        record['artist'] = record['artist'] or 'Unknown artist'
        record['number'] = (record['track_number'] or '').split('/')[0] or '—'
    return record


def browse(root, database=None, *, mode='albums', search='', sort='title', descending=False,
           artist_id='', album_id='', offset=0, limit=PAGE_SIZE, operation=None):
    """Return one page and aggregate counts from a consistent read snapshot."""
    root = Path(root).expanduser().resolve()
    database = database or index_path()
    empty = dict(rows=[], total=0, album={}, summary=dict(tracks=0, albums=0, artists=0, errors=0, scanned=False))
    if not database.is_file():
        return empty
    offset, limit = max(0, int(offset)), min(500, max(1, int(limit)))
    term = folded(search)
    with connect(database, operation=operation) as con:
        con.execute('BEGIN')
        library = con.execute('SELECT id,scanned_at,last_errors FROM roots WHERE path=?', (str(root),)).fetchone()
        if not library:
            return empty
        identifier = library['id']
        summary = dict(scanned=library['scanned_at'] is not None, errors=library['last_errors'])
        for table, key in (('tracks', 'tracks'), ('albums', 'albums'), ('artists', 'artists')):
            summary[key] = con.execute(f'SELECT COUNT(*) FROM {table} WHERE root_id=?', (identifier,)).fetchone()[0]
        params = [identifier]
        album = {}
        if mode == 'artists':
            base = 'FROM artists ar WHERE ar.root_id=?'
            if term:
                base += ''' AND (instr(ar.name_sort,?)>0 OR ar.id IN (
                    SELECT aa.artist_id FROM artist_albums aa JOIN tracks t ON t.album_id=aa.album_id
                    WHERE t.root_id=? AND instr(t.search_text,?)>0))'''
                params.extend((term, identifier, term))
            columns = '''ar.id,ar.name,
                (SELECT COUNT(*) FROM artist_albums aa WHERE aa.artist_id=ar.id) AS album_count,
                (SELECT a.art_key FROM artist_albums aa JOIN albums a ON a.id=aa.album_id
                 WHERE aa.artist_id=ar.id AND a.art_key!='' ORDER BY a.artist_sort,a.title_sort,a.id LIMIT 1) AS art_key'''
            order = 'ar.name_sort,ar.id'
        elif mode == 'albums':
            base = 'FROM albums a WHERE a.root_id=?'
            if artist_id:
                base += ' AND a.id IN (SELECT album_id FROM artist_albums WHERE artist_id=?)'
                params.append(artist_id)
            if term:
                base += ' AND a.id IN (SELECT album_id FROM tracks WHERE root_id=? AND instr(search_text,?)>0)'
                params.extend((identifier, term))
            columns, order = 'a.*', 'a.artist_sort,a.title_sort,a.year,a.id'
        elif mode in ('songs', 'album'):
            base = 'FROM tracks t JOIN albums a ON a.id=t.album_id WHERE t.root_id=?'
            if mode == 'album':
                base += ' AND t.album_id=?'
                params.append(album_id)
                row = con.execute('SELECT * FROM albums WHERE root_id=? AND id=?', (identifier, album_id)).fetchone()
                if row:
                    album = decorated(row, root)
                    album['multiDisc'] = row['disc_count'] > 1 or row['max_disc'] > 1
            if term:
                base += ' AND instr(t.search_text,?)>0'
                params.append(term)
            columns = 't.*,a.title AS album_title,a.artist AS display_album_artist'
            order = ('t.disc_sort,t.track_sort,t.title_sort,t.relpath,t.id' if mode == 'album' else
                     SORTS.get(sort, SORTS['title']) + (' DESC' if descending else ' ASC') + ',t.artist_sort,t.album_sort,t.relpath,t.id')
        else:
            raise ValueError(f'Unknown Library mode: {mode}')
        count = con.execute('SELECT COUNT(*) ' + base, params).fetchone()[0]
        previous_disc = None
        if mode == 'album' and offset:
            previous = con.execute('SELECT t.disc_sort ' + base + ' ORDER BY ' + order + ' LIMIT 1 OFFSET ?',
                                   [*params, offset - 1]).fetchone()
            previous_disc = previous[0] if previous else None
        rows = []
        for row in con.execute('SELECT ' + columns + ' ' + base + ' ORDER BY ' + order + ' LIMIT ? OFFSET ?',
                               [*params, limit, offset]):
            record = decorated(row, root)
            if mode == 'album':
                record['discHeader'] = bool(album.get('multiDisc')) and record['disc_sort'] != previous_disc
                previous_disc = record['disc_sort']
            rows.append(record)
        return dict(rows=rows, total=count, album=album, summary=summary)
