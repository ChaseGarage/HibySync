"""Reviewed Library maintenance using the existing tag writer and copy services.

Plans are snapshots. Execution commits one verified file at a time and retains
originals plus a durable journal outside the library for recovery.
"""

from dataclasses import dataclass, field, replace
import copy
import io
import json
import os
from pathlib import Path
import tempfile
import uuid

from mutagen import File as MutagenFile
from PIL import Image

from hiby_music_tools import importer, online_art, sanitize
from hiby_music_tools.core.artwork import embedded_blobs, folder_previews
from hiby_music_tools.core.files import signature, optional_signature
from hiby_music_tools.core.importing import commit_copy, safe_destination
from hiby_music_tools.core.interaction import Cancelled, Operation
from hiby_music_tools.core.naming import build_destination
from hiby_music_tools.core.scan import read_track
from hiby_music_tools.core.tagging import apply_metadata, read_genre
from .integrity import audio_fingerprint
from .metadata import album_folder
from .playback import tracks as indexed_tracks
from .indexer import refresh


FIELDS = ('title', 'track_artist', 'album_artist', 'album', 'year', 'track_number', 'disc_number', 'genre')
ALBUM_FIELDS = ('album_artist', 'album', 'year', 'genre')
WRITABLE = {'.mp3', '.flac', '.wav', '.wave', '.m4a', '.mp4', '.ogg', '.oga', '.opus', '.aif', '.aiff'}


@dataclass
class Draft:
    identifier: str
    track: object
    original: dict
    values: dict
    included: bool = True
    artwork: object = None
    optimize: bool = False
    error: str = ''
    album_id: str = ''


@dataclass
class EditSession:
    root: Path
    database: Path
    scope: str
    drafts: list[Draft]
    artwork: list = field(default_factory=list)
    artist: str = ''


@dataclass
class EditPlan:
    session: EditSession
    rows: list[dict]
    reorganize: bool


@dataclass
class EditReport:
    files: list = field(default_factory=list)
    updates: dict = field(default_factory=dict)
    cancelled: bool = False
    recovery: str = ''
    index_error: str = ''


def values(track):
    result = {key: getattr(track.original, key) or '' for key in FIELDS[:5]}
    result.update(track_number=track.track_number, disc_number=track.disc_number)
    result['genre'] = read_genre(track.path) if not track.error else ''
    return result


def load_session(root, database, scope, identifier, operation=None):
    op = operation or Operation()
    root = Path(root).expanduser().resolve()
    if scope not in ('track', 'album', 'artist'):
        raise ValueError('Invalid edit selection')
    rows = indexed_tracks(root, database, mode=scope, identifier=identifier, operation=op)
    if not rows:
        raise ValueError('No indexed files in this selection. Refresh the Library first.')
    drafts, artwork, seen = [], [], set()
    for index, row in enumerate(rows):
        op.progress('Reading original tags', index, len(rows), row['path'])
        path = Path(row['path'])
        safe_destination(path, root)
        track = read_track(path)
        original = values(track)
        error = track.error or ('' if path.suffix.lower() in WRITABLE else 'Tag editing is unsupported for this format')
        drafts.append(Draft(row['id'], track, original, dict(original), error=error, album_id=row['album_id']))
        candidates = list(track.artwork)
        for folder in dict.fromkeys((path.parent, album_folder(path, root))):
            if folder not in seen and folder.is_dir():
                candidates.extend(folder_previews(folder)[0])
                seen.add(folder)
        artwork.extend(candidates)
    artist = ''
    if scope == 'artist':
        from .database import connect
        with connect(database) as con:
            row = con.execute('SELECT name FROM artists WHERE id=?', (identifier,)).fetchone()
            artist = row['name'] if row else ''
    return EditSession(root, database, scope, drafts, artwork, artist)


def validate_values(data):
    if data['year'] and not sanitize.YEAR_RE.fullmatch(data['year']):
        raise ValueError('Release year must contain four digits or be empty')
    for key in ('track_number', 'disc_number'):
        if data[key]:
            parts = data[key].split('/')
            if len(parts) not in (1, 2) or not all(p.isdecimal() and len(p) <= 6 and int(p) > 0 for p in parts):
                raise ValueError(f'Invalid {key}: {data[key]}')
    if any('\x00' in text for text in data.values()):
        raise ValueError('Tags cannot contain NUL characters')


def proposed(draft):
    track = copy.deepcopy(draft.track)
    data = draft.values
    track.proposed = replace(track.original, **{key: data[key] or None for key in FIELDS[:5]},
                             artist=data['album_artist'] or data['track_artist'] or None)
    track.track_number, track.disc_number = data['track_number'], data['disc_number']
    return track


def preview_session(session, reorganize=False, operation=None):
    op = operation or Operation()
    snapshot = copy.deepcopy(session)
    rows, destinations = [], {}
    from .database import connect, folded
    with connect(snapshot.database) as con:
        existing_artists = {r[0] for r in con.execute('''SELECT ar.name_sort FROM artists ar
            JOIN roots r ON r.id=ar.root_id WHERE r.path=?''', (str(snapshot.root),))}
    for index, draft in enumerate(snapshot.drafts):
        path = draft.track.path
        op.progress('Preparing save preview', index, len(snapshot.drafts), str(path))
        error, destination = draft.error, path
        changes = [f'{key}: {draft.original[key] or "∅"} → {draft.values[key] or "∅"}'
                   for key in FIELDS if draft.original[key] != draft.values[key]]
        try:
            validate_values(draft.values)
            safe_destination(path, snapshot.root)
            if draft.track.signature is None or signature(path) != draft.track.signature:
                raise ValueError('File changed since opening the editor. Reopen it before saving.')
            if reorganize:
                metadata = proposed(draft).proposed
                context = path
                relative = path.relative_to(snapshot.root)
                if not metadata.artist and relative.parts[0] == 'missing-author' and len(relative.parts) > 1:
                    context = snapshot.root.joinpath(*relative.parts[1:])
                destination, _ = build_destination(context, snapshot.root, snapshot.root, metadata, set())
                safe_destination(destination, snapshot.root)
                if destination != path and optional_signature(destination) is not None:
                    raise ValueError('Destination exists; it will not be overwritten')
        except (OSError, ValueError) as exc:
            error = str(exc)
        art = ''
        if draft.artwork:
            art = f'{draft.artwork.label} · ' + ('HiBy JPEG ≤600px, quality 88' if draft.optimize else 'Preserve original JPEG/PNG bytes and resolution')
        action = 'skip' if not draft.included else 'blocked' if error else 'save' if changes or art or destination != path else 'unchanged'
        warning = ''
        for key in ('track_artist', 'album_artist'):
            if folded(draft.values[key]) != folded(draft.original[key]) and folded(draft.values[key]) in existing_artists:
                warning = 'This artist name already exists. Saving will group the selected files under that name.'
        row = dict(id=draft.identifier, source=str(path), destination=str(destination),
                   changes='\n'.join(changes), artwork=art, error=error, warning=warning, action=action)
        rows.append(row)
        if draft.included and destination != path:
            if destination in destinations:
                other = destinations[destination]
                for conflict in (other, row):
                    conflict['action'], conflict['error'] = 'blocked', 'Multiple selected files have the same destination'
            destinations[destination] = row
    return EditPlan(snapshot, rows, reorganize)


def artwork_bytes(art):
    if art.signature is None or signature(art.path) != art.signature:
        raise ValueError('Artwork source changed. Select it again before saving.')
    data = embedded_blobs(MutagenFile(art.path))[art.index] if art.origin == 'embedded' else art.path.read_bytes()
    if len(data) > 32 * 1024 * 1024:
        raise ValueError('Artwork exceeds 32 MiB')
    return data


def prepare_artwork(art, optimize):
    data = artwork_bytes(art)
    if optimize:
        data, size = online_art.prepare_jpeg(io.BytesIO(data), 600, 88)
        return data, size, 'image/jpeg'
    with Image.open(io.BytesIO(data)) as image:
        image.load()
        if image.format not in ('JPEG', 'PNG'):
            raise ValueError('Preserving artwork requires JPEG or PNG; choose HiBy optimization for other formats')
        return data, image.size, 'image/jpeg' if image.format == 'JPEG' else 'image/png'


def durable(path):
    with open(path, 'rb') as stream:
        os.fsync(stream.fileno())
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def execute(plan, *, operation=None, protected_paths=()):
    op = operation or Operation()
    session = plan.session
    report = EditReport()
    root = session.root
    recovery = session.database.parent / 'maintenance' / ('run-' + uuid.uuid4().hex)
    if recovery.resolve().is_relative_to(root):
        raise ValueError('Recovery backups must be outside the music library')
    recovery.mkdir(parents=True)
    report.recovery = str(recovery)
    protected = {Path(path) for path in protected_paths}
    moves = []
    # Freeze all selected artwork before any source can be replaced, including
    # an embedded cover taken from another track in this same batch.
    assets = {}
    def art_key(draft):
        art = draft.artwork
        return (art.path, art.index, art.origin, art.signature, draft.optimize)
    try:
        for draft, row in zip(session.drafts, plan.rows):
            op.checkpoint()
            if row['action'] == 'save' and draft.artwork and art_key(draft) not in assets:
                try:
                    assets[art_key(draft)] = prepare_artwork(draft.artwork, draft.optimize)
                except Exception as exc:
                    assets[art_key(draft)] = exc
    except Cancelled:
        report.cancelled = True
        return report
    journal = recovery / 'journal.jsonl'
    def record(data):
        with journal.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(data, ensure_ascii=False) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        durable(journal)
    for index, (draft, row) in enumerate(zip(session.drafts, plan.rows)):
        try:
            op.progress('Saving Library files', index, len(plan.rows), row['source'])
        except Cancelled:
            report.cancelled = True
            break
        result = {**row, 'status': 'skipped', 'backup': ''}
        source, destination = Path(row['source']), Path(row['destination'])
        published = None
        try:
            if row['action'] == 'blocked':
                raise ValueError(row['error'])
            if row['action'] != 'save':
                report.files.append(result)
                continue
            if source in protected:
                result['error'] = 'File is open for playback; stop playback before saving'
                report.files.append(result)
                continue
            safe_destination(source, root)
            safe_destination(destination, root)
            if signature(source) != draft.track.signature:
                raise ValueError('File changed after preview; original retained')
            original_fingerprint = audio_fingerprint(source, op)
            with tempfile.TemporaryDirectory(prefix='work-', dir=recovery) as temporary:
                working = Path(temporary) / ('track' + source.suffix)
                importer.atomic_verified_copy(source, working)
                if signature(source) != draft.track.signature:
                    raise ValueError('Source changed while staging')
                apply_metadata(working, proposed(draft), genre=draft.values['genre'])
                if draft.artwork:
                    asset = assets[art_key(draft)]
                    if isinstance(asset, Exception):
                        raise ValueError(str(asset))
                    data, size, mime = asset
                    art_result = sanitize.embed_folder_art(working, data, size, mime=mime, preserve_other=True)
                    if art_result.error:
                        raise ValueError(art_result.error)
                    if data not in embedded_blobs(MutagenFile(working)):
                        raise ValueError('Artwork read-back verification failed')
                if audio_fingerprint(working, op) != original_fingerprint:
                    raise ValueError('Encoded audio changed; original retained')
                op.checkpoint()
                backup = recovery / (f'{index:06d}-' + uuid.uuid4().hex + source.suffix)
                importer.atomic_verified_copy(source, backup)
                durable(backup)
                result['backup'] = str(backup)
                if signature(source) != draft.track.signature or not importer.files_identical(source, backup):
                    raise ValueError('Source changed before publication')
                record({**result, 'phase': 'prepared', 'source_signature': draft.track.signature})
                # No cancellation inside publication/removal: finish this safe
                # file transaction, then honour cancellation before the next.
                expected = draft.track.signature if source == destination else None
                commit_copy(working, destination, expected, recovery / ('publish-' + backup.name), library=root)
                published = signature(destination)
                durable(destination)
                record({**result, 'phase': 'published', 'published_signature': published})
                if destination != source:
                    if signature(source) != draft.track.signature or not importer.files_identical(source, backup):
                        raise ValueError('Source changed before move completion')
                    source.unlink()
                    moves.append(dict(id=draft.identifier, source=str(source.relative_to(root)),
                                      destination=str(destination.relative_to(root)), signature=signature(destination)))
                    try:
                        descriptor = os.open(source.parent, os.O_RDONLY | os.O_DIRECTORY)
                        try:
                            os.fsync(descriptor)
                        finally:
                            os.close(descriptor)
                    except OSError as exc:
                        result['warning'] = 'Move completed, but source-directory flush failed: ' + str(exc)
                result['status'], result['error'] = 'saved', ''
                report.updates[draft.identifier] = dict(id=draft.identifier, path=str(destination),
                    title=draft.values['title'] or destination.stem,
                    artist=draft.values['track_artist'] or 'Unknown artist', album_title=draft.values['album'])
                try:
                    record({**result, 'phase': 'committed'})
                except OSError as exc:
                    result['warning'] = 'File saved; journal completion could not be flushed: ' + str(exc)
        except Cancelled:
            report.cancelled = True
            break
        except Exception as exc:
            result['status'], result['error'] = 'failed', str(exc)
            # If a move could not finish, remove only our verified published
            # copy while the intact source is still present. Never clobber it.
            if destination != source and published is not None and source.exists():
                try:
                    if signature(destination) == published:
                        destination.unlink()
                except OSError:
                    result['error'] += '; published copy remains at ' + str(destination)
            elif destination == source and published is not None:
                try:
                    if signature(source) == published:
                        importer.atomic_verified_copy(Path(result['backup']), source)
                except OSError:
                    result['error'] += '; restore the retained backup manually'
            try:
                record({**result, 'phase': 'failed'})
            except OSError as journal_error:
                result['error'] += '; journal unavailable: ' + str(journal_error)
                report.files.append(result)
                break
        report.files.append(result)
    # Reconcile successful writes even after cancellation. This never edits
    # music; the cancellation token from the save must not discard the catalog.
    if report.updates:
        try:
            refresh(root, session.database, relocations=moves, operation=Operation(op.report))
            for identifier in list(report.updates):
                found = indexed_tracks(root, session.database, mode='track', identifier=identifier)
                if found:
                    report.updates[identifier] = found[0]
        except Exception as exc:
            report.index_error = str(exc)
    report.cancelled = report.cancelled or op.cancelled.is_set()
    return report
