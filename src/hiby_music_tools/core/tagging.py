"""Apply reviewed tag changes to a staged copy and verify the saved values."""

from mutagen import File as MutagenFile
from mutagen.id3 import TALB, TCON, TDRC, TIT2, TPE1, TPE2, TPOS, TRCK

from hiby_music_tools import sanitize
from .scan import read_track
from hiby_music_tools.online_art import tag_text


FIELDS = {'track_artist': 'artist', 'album_artist': 'albumartist', 'title': 'title',
          'album': 'album', 'year': 'date'}


def read_genre(path):
    audio = MutagenFile(path)
    if audio is None:
        raise ValueError('Cannot read audio tags')
    return tag_text(audio.tags or {}, ('genre', 'TCON', '\xa9gen')) or ''


def apply_metadata(path, track, *, genre=None):
    updates = {tag: getattr(track.proposed, field) or '' for field, tag in FIELDS.items()
               if getattr(track.proposed, field) != getattr(track.original, field)}
    for field, tag in (('track_number', 'tracknumber'), ('disc_number', 'discnumber')):
        if getattr(track, field) != getattr(track, 'original_' + field):
            updates[tag] = getattr(track, field)
    if genre is not None and genre != read_genre(path):
        updates['genre'] = genre
    if not updates:
        return
    if updates.get('date') and not sanitize.YEAR_RE.fullmatch(updates['date']):
        raise ValueError('Release year must contain four digits.')
    for key in ('tracknumber', 'discnumber'):
        if updates.get(key):
            parts = updates[key].split('/')
            if len(parts) not in (1, 2) or not all(p.isdecimal() and len(p) <= 6 and int(p) > 0 for p in parts):
                raise ValueError(f'Invalid {key}: {updates[key]}')
    audio = MutagenFile(path)
    if audio is None:
        raise ValueError(f'Cannot read staged audio: {path.name}')
    suffix = path.suffix.lower()
    if suffix in {'.mp3', '.wav', '.wave', '.aif', '.aiff'}:
        if audio.tags is None:
            audio.add_tags()
        frames = dict(artist=TPE1, albumartist=TPE2, title=TIT2, album=TALB,
                      date=TDRC, tracknumber=TRCK, discnumber=TPOS, genre=TCON)
        for key, value in updates.items():
            frame = frames[key]
            audio.tags.delall(frame.__name__)
            if value:
                audio.tags.add(frame(encoding=3, text=[value]))
        audio.save()
    elif suffix in {'.m4a', '.mp4'}:
        if audio.tags is None:
            audio.add_tags()
        keys = dict(artist='\xa9ART', albumartist='aART', title='\xa9nam', album='\xa9alb',
                    date='\xa9day', tracknumber='trkn', discnumber='disk', genre='\xa9gen')
        for key, value in updates.items():
            audio.tags.pop(keys[key], None)
            if value:
                if key in {'tracknumber', 'discnumber'}:
                    parts = value.split('/')
                    if len(parts) not in (1, 2) or not all(p.isdecimal() and len(p) <= 6 for p in parts):
                        raise ValueError(f'Invalid {key}: {value}')
                    audio.tags[keys[key]] = [(int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)]
                else:
                    audio.tags[keys[key]] = [value]
        audio.save()
    else:
        # Reuse the sanitizer's easy-tag writer for its supported formats.
        warnings = sanitize.write_metadata_updates(path, updates)
        if warnings:
            raise ValueError('; '.join(warnings))
        if any(not value for value in updates.values()):
            easy = MutagenFile(path, easy=True)
            for key, value in updates.items():
                if not value:
                    easy.pop(key, None)
            easy.save()
    check = read_track(path)
    if check.error:
        raise ValueError(f'Tag verification failed: {check.error}')
    for field, tag in FIELDS.items():
        if tag in updates and (getattr(check.original, field) or '') != updates[tag]:
            raise ValueError(f'Tag verification failed for {tag} in {path.name}')
    for field, tag in (('track_number', 'tracknumber'), ('disc_number', 'discnumber')):
        if tag in updates:
            actual, expected = getattr(check, field), updates[tag]
            # MP4 stores numeric tuples, so leading zeroes are not retained.
            if suffix in {'.m4a', '.mp4'} and actual and expected:
                def pair(text):
                    parts = [int(part) for part in text.split('/')]
                    return tuple(parts + [0]) if len(parts) == 1 else tuple(parts)
                equal = pair(actual) == pair(expected)
            else:
                equal = actual == expected
            if not equal:
                raise ValueError(f'Tag verification failed for {tag} in {path.name}')
    if 'genre' in updates and read_genre(path) != updates['genre']:
        raise ValueError(f'Tag verification failed for genre in {path.name}')
