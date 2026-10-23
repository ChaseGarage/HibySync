"""Deterministic album/artist identities, including untagged compilations."""

from collections import Counter, defaultdict
import json
from pathlib import Path
import uuid

from .database import folded
from .metadata import album_folder


def regroup(con, root_id, root, operation):
    rows = [dict(row) for row in con.execute('SELECT * FROM tracks WHERE root_id=? ORDER BY relpath', (root_id,))]
    contexts = defaultdict(list)
    for row in rows:
        context = str(album_folder(root / row['relpath'], root).relative_to(root))
        row['_context'] = context
        contexts[(context, folded(row['album']))].append(row)
    namespace = uuid.UUID(root_id)
    albums = defaultdict(list)
    for tracks in contexts.values():
        explicit = {folded(t['album_artist']): t['album_artist'] for t in tracks if t['album_artist']}
        contributors = {folded(t['artist']): t['artist'] for t in tracks if t['artist']}
        compilation = any(t['compilation'] for t in tracks)
        inferred = (next(iter(explicit.values())) if len(explicit) == 1 else
                    'Various Artists' if compilation or len(contributors) > 1 else
                    next(iter(contributors.values()), 'Unknown artist'))
        years = Counter(t['year'] for t in tracks if t['year'])
        year = years.most_common(1)[0][0] if years else ''
        for track in tracks:
            artist = 'Various Artists' if compilation and not explicit else track['album_artist'] or inferred
            title = track['album'] or 'Unknown Album'
            key = (folded(artist), folded(title), year,
                   track['_context'] if not track['album'] or artist == 'Unknown artist' else '')
            album_id = str(uuid.uuid5(namespace, 'album:' + json.dumps(key, ensure_ascii=False)))
            track['_album_artist'] = artist
            track['_album_title'] = title
            track['_album_year'] = year
            albums[album_id].append(track)

    con.execute('DELETE FROM artist_albums WHERE album_id IN (SELECT id FROM albums WHERE root_id=?)', (root_id,))
    con.execute('DELETE FROM albums WHERE root_id=?', (root_id,))
    con.execute('DELETE FROM artists WHERE root_id=?', (root_id,))
    artists, relations, updates, album_records = {}, set(), [], []
    def artist_id(name):
        identifier = str(uuid.uuid5(namespace, 'artist:' + folded(name)))
        artists.setdefault(identifier, (identifier, root_id, name, folded(name)))
        return identifier
    for index, (identifier, tracks) in enumerate(albums.items()):
        operation.progress('Grouping albums', index, len(albums))
        first = tracks[0]
        artist = first['_album_artist']
        owner = artist_id(artist)
        relations.add((owner, identifier))
        discs = {t['disc_sort'] for t in tracks}
        durations = [t['duration'] for t in tracks if t['duration'] is not None]
        album_records.append((identifier, root_id, owner, artist, first['_album_title'], first['_album_year'],
                              folded(first['_album_title']), folded(artist),
                              next((t['art_key'] for t in tracks if t['art_key']), ''), len(tracks),
                              sum(durations) if durations else None, len(discs), max(discs)))
        for track in tracks:
            if track['artist']:
                relations.add((artist_id(track['artist']), identifier))
            search = folded(' '.join((track['title'] or Path(track['relpath']).stem,
                                      track['artist'], track['album_artist'], artist, track['_album_title'])))
            updates.append((identifier, folded(track['title'] or Path(track['relpath']).stem),
                            folded(track['artist']), folded(track['_album_title']), search, track['id']))
    con.executemany('INSERT INTO artists VALUES(?,?,?,?)', artists.values())
    con.executemany('INSERT INTO albums VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)', album_records)
    con.executemany('INSERT INTO artist_albums VALUES(?,?)', sorted(relations))
    con.executemany('UPDATE tracks SET album_id=?,title_sort=?,artist_sort=?,album_sort=?,search_text=? WHERE id=?', updates)
    return len(albums)
