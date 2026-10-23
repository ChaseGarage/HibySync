"""Read tags/technical properties and cache bounded, content-addressed previews."""

import hashlib
import json
from pathlib import Path
import re
import uuid

from mutagen import File as MutagenFile

from hiby_music_tools import sanitize
from hiby_music_tools.core.artwork import embedded_blobs, preview
from hiby_music_tools.online_art import tag_text


DISC_FOLDER = re.compile(r'^(?:cd|disc|disk|volume)[ ._-]*\d+(?:[ ._-].*)?$', re.I)


def album_folder(path, root):
    folder = path.parent
    if folder != root and DISC_FOLDER.fullmatch(folder.name):
        folder = folder.parent
    return folder


def number(value, fallback):
    first = (value or '').split('/')[0].strip()
    return int(first) if first.isdecimal() and len(first) <= 6 else fallback


def folder_stamp(folder):
    entries = []
    for path in sorted(folder.iterdir()):
        if not path.is_symlink() and path.suffix.lower() in sanitize.FOLDER_ART_EXTS and path.is_file():
            info = path.stat()
            entries.append((path.name, info.st_size, info.st_mtime_ns, info.st_ctime_ns))
    return json.dumps(entries, ensure_ascii=False)


class ThumbnailCache:
    def __init__(self, directory, force=False):
        self.directory = directory
        self.force = force
        self.prepared = set()
        self.folder_art = {}

    def from_bytes(self, data, source, origin):
        key = hashlib.sha256(data).hexdigest()
        target = self.directory / (key + '.png')
        if not target.is_file() or (self.force and key not in self.prepared):
            art = preview(data, 'Library cover', origin, source)
            self.directory.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix('.' + uuid.uuid4().hex + '.tmp')
            try:
                temporary.write_bytes(art.thumbnail)
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
        self.prepared.add(key)
        return key

    def from_folder(self, folder, album):
        lookup = folder, album
        if lookup not in self.folder_art:
            result = ''
            selected, _ = sanitize.find_folder_art(folder, album)
            if selected and not selected.is_symlink() and selected.stat().st_size <= 32 * 1024 * 1024:
                try:
                    result = self.from_bytes(selected.read_bytes(), selected, 'folder')
                except (OSError, ValueError):
                    pass
            self.folder_art[lookup] = result
        return self.folder_art[lookup]


def read_metadata(path: Path, root: Path, thumbnails: ThumbnailCache):
    meta = sanitize.extract_metadata(path)
    result = dict(title=meta.title or '', artist=meta.track_artist or '',
                  album_artist=meta.album_artist or '', album=meta.album or '', year=meta.year or '',
                  track_number='', disc_number='', duration=None, format=path.suffix[1:].upper(),
                  codec='', bitrate=None, sample_rate=None, bit_depth=None, compilation=0,
                  art_key='', art_origin='', error='')
    try:
        audio = MutagenFile(path)
        if audio is None:
            raise ValueError('Unrecognized or damaged audio')
        tags = audio.tags or {}
        def value(*keys):
            return tag_text(tags, keys) or ''
        result.update(title=meta.title or value('title', 'TIT2', '\xa9nam'),
                      artist=meta.track_artist or value('artist', 'TPE1', '\xa9ART'),
                      album_artist=meta.album_artist or value('albumartist', 'album artist', 'album_artist', 'TPE2', 'aART'),
                      album=meta.album or value('album', 'TALB', '\xa9alb'),
                      track_number=value('tracknumber', 'TRCK'), disc_number=value('discnumber', 'TPOS'))
        year = sanitize.YEAR_RE.search(value('date', 'year', 'originaldate', 'TDRC', '\xa9day'))
        result['year'] = meta.year or (year.group(0) if year else '')
        for key, field in (('trkn', 'track_number'), ('disk', 'disc_number')):
            if tags.get(key):
                index, total = tags[key][0]
                result[field] = f'{index}/{total}' if total else str(index)
        result['compilation'] = int(value('compilation', 'TCMP', 'cpil').casefold() in ('1', 'true', 'yes'))
        info = audio.info
        for key, attribute in (('duration', 'length'), ('bitrate', 'bitrate'), ('sample_rate', 'sample_rate')):
            result[key] = getattr(info, attribute, None)
        result['codec'] = str(getattr(info, 'codec', '') or type(info).__name__.removesuffix('Info'))
        # Bit depth has meaning for PCM/lossless streams, not decoded lossy samples.
        if path.suffix.lower() in {'.wav', '.wave', '.aiff', '.aif', '.flac', '.wv', '.ape'} or 'alac' in result['codec'].lower():
            result['bit_depth'] = getattr(info, 'bits_per_sample', None)
        try:
            blobs = embedded_blobs(audio)
            for blob in blobs:
                try:
                    result['art_key'] = thumbnails.from_bytes(blob, path, 'embedded')
                    result['art_origin'] = 'embedded'
                    break
                except (OSError, ValueError):
                    continue
        except Exception:
            pass  # A bad cover must not hide otherwise readable music.
        if not result['art_key']:
            for folder in dict.fromkeys((path.parent, album_folder(path, root))):
                result['art_key'] = thumbnails.from_folder(folder, result['album'])
                if result['art_key']:
                    result['art_origin'] = 'folder'
                    break
    except Exception as exc:
        result['error'] = str(exc)
    result['track_sort'] = number(result['track_number'], 2**31 - 1)
    result['disc_sort'] = max(1, number(result['disc_number'], 1))
    return result
