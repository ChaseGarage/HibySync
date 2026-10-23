"""Execute a confirmed review plan, with optional verified source cleanup."""

from dataclasses import dataclass, field
import io
import os
from pathlib import Path
import shutil
import tempfile
import uuid

from mutagen import File as MutagenFile

from hiby_music_tools import importer, online_art, sanitize
from hiby_music_tools.paths import metadata_dir
from .artwork import embedded_blobs
from .files import optional_signature, signature
from .interaction import Cancelled, Operation, Progress
from .review import build_plan
from .scan import validate_roots
from .tagging import apply_metadata


@dataclass
class FileResult:
    source: Path
    destination: Path
    action: str
    error: str = ''
    source_removed: bool = False
    cleanup_error: str = ''


@dataclass
class ImportReport:
    total: int
    files: list[FileResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    cancelled: bool = False
    recovery: str = ''
    cleanup_requested: bool = False

    @property
    def removed(self):
        return sum(item.source_removed for item in self.files)

    @property
    def counts(self):
        return {action: sum(item.action == action for item in self.files)
                for action in ('imported', 'replaced', 'duplicate', 'skipped', 'failed')}


def safe_destination(destination, library):
    """Refuse redirected roots or symlinks in managed destination paths."""
    if library.resolve() != library:
        raise ValueError('Library path changed; scan and preview again.')
    try:
        relative = destination.relative_to(library)
    except ValueError:
        raise ValueError(f'Destination is outside the library: {destination}')
    current = library
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f'Refusing a destination symlink: {current}')
    if destination.resolve() != destination:
        raise ValueError(f'Destination path was redirected: {destination}')


def validate_source(track, source):
    if track.path.resolve() != track.path or source not in track.path.parents:
        raise ValueError(f'Source path changed: {track.path}')
    if track.signature is None or signature(track.path) != track.signature:
        raise ValueError(f'Source changed since scanning; scan again: {track.path.name}')
    art = track.selected_art
    if art and (art.signature is None or signature(art.path) != art.signature):
        raise ValueError(f'Selected artwork changed; select it again: {art.label}')


def stage_track(track, working, operation):
    operation.checkpoint()
    importer.atomic_verified_copy(track.path, working)
    operation.checkpoint()
    apply_metadata(working, track)
    operation.checkpoint()
    art = track.selected_art
    original = art and art.origin == 'embedded' and art.path == track.path and art.index == 0 and not track.artwork_approved
    if art and not original:
        if art.origin == 'embedded':
            blobs = embedded_blobs(MutagenFile(art.path))
            data = io.BytesIO(blobs[art.index])
        else:
            data = art.path
        jpeg, dimensions = online_art.prepare_jpeg(data, 600, 88)
        result = sanitize.embed_folder_art(working, jpeg, dimensions)
        if result.error:
            raise ValueError(result.error)
        if jpeg not in embedded_blobs(MutagenFile(working)):
            raise ValueError(f'Artwork verification failed: {track.path.name}')
    else:
        result = sanitize.sanitize_artwork(working, 600, 88)
        if result.error:
            raise ValueError(result.error)
    if MutagenFile(working) is None:
        raise ValueError(f'Cannot read prepared track: {track.path.name}')


def commit_copy(working, destination, expected, backup, library=None):
    """Verify a sibling temporary copy, then publish without unexpected overwrite."""
    if library is not None:
        safe_destination(destination, library)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if library is not None:
        safe_destination(destination, library)
    temporary = destination.with_name(f'.{destination.name}.hibysync-{uuid.uuid4().hex}')
    published = None
    try:
        importer.atomic_verified_copy(working, temporary)
        if library is not None:
            safe_destination(destination, library)
        if optional_signature(destination) != expected:
            raise ValueError(f'Destination changed since preview: {destination}')
        if expected is not None:
            importer.atomic_verified_copy(destination, backup)
            if signature(destination) != expected:
                raise ValueError(f'Destination changed while backing up: {destination}')
            os.replace(temporary, destination)
        else:
            # Hard-linking is an atomic no-clobber publish on local Linux
            # filesystems. If unsupported, fail safely rather than overwrite.
            os.link(temporary, destination)
        published = signature(destination)
        if not importer.files_identical(working, destination):
            raise OSError(f'Final SHA-256 verification failed: {destination}')
    except Exception:
        if published is not None and optional_signature(destination) == published:
            if expected is not None and backup.is_file():
                importer.atomic_verified_copy(backup, destination)
            elif expected is None:
                destination.unlink()
        raise
    finally:
        temporary.unlink(missing_ok=True)


def remove_verified_source(track, working, destination, source, library):
    """Delete one unchanged source only after re-verifying its durable destination."""
    if source.resolve() != source or track.path.resolve() != track.path or source not in track.path.parents:
        raise ValueError('Source path changed; original kept. Scan again.')
    if signature(track.path) != track.signature:
        raise ValueError('Source changed since scanning; original kept. Scan again.')
    safe_destination(destination, library)
    destination_before = signature(destination)
    if not importer.files_identical(working, destination):
        raise ValueError('Library verification failed; original kept.')
    # Persist both the verified file and its directory entry before removing
    # the incoming copy. A failed flush retains the original.
    with destination.open('rb') as output:
        os.fsync(output.fileno())
    for parent in (destination.parent, *destination.parent.parents):
        directory = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        if parent == library.parent:
            break
    safe_destination(destination, library)
    if signature(destination) != destination_before:
        raise ValueError('Library file changed during verification; original kept.')
    if track.path.resolve() != track.path or signature(track.path) != track.signature:
        raise ValueError('Source changed during verification; original kept. Scan again.')
    # Deliberately do not revalidate selected embedded-art references here:
    # all tracks have already been prepared before any originals are removed.
    track.path.unlink()


def cleanup_imported_sources(session, prepared, report, operation):
    successful = {result.source: result for result in report.files
                  if result.action in ('imported', 'replaced', 'duplicate')}
    pending = {track.selected_art.path for album in session.albums for track in album.tracks
               if track.path not in successful and track.selected_art and track.selected_art.origin == 'embedded'}
    eligible = [(row, track, working) for _, row, track, working in prepared if row.source in successful]
    for index, (row, track, working) in enumerate(eligible):
        operation.progress('Removing verified originals', index, len(eligible), row.source.name)
        operation.checkpoint()
        result = successful[row.source]
        if row.source in pending:
            result.cleanup_error = 'Original kept: a pending track uses its embedded artwork.'
            continue
        try:
            remove_verified_source(track, working, row.destination, session.source, session.library)
            result.source_removed = True
        except (OSError, ValueError) as exc:
            result.cleanup_error = str(exc)


def execute_import(session, preview, replacements=None, operation=None, staging_parent=None, remove_sources=False):
    """Import reviewed copies and return partial/cancelled results.

    Existing non-identical files are skipped unless their source path appears in
    replacements. Optional cleanup removes only verified successes; it never
    empties the inbox or deletes skipped/unprocessed files or folder images.
    """
    op = operation or Operation()
    replacements = set(replacements or ())
    report = ImportReport(len(preview), cleanup_requested=remove_sources)
    run_dir = None
    try:
        op.checkpoint()
        source, library = validate_roots(session.source, session.library)
        if (source, library) != (session.source, session.library):
            raise ValueError('Folder paths changed; scan again.')
        fresh = build_plan(session, op)
        if fresh != preview:
            raise ValueError('The review or destinations changed. Preview the import again.')
        tracks = {t.path: t for album in session.albums for t in album.tracks}
        for row in preview:
            if row.action not in ('Skip', 'Blocked'):
                validate_source(tracks[row.source], source)
                safe_destination(row.destination, library)
        parent = staging_parent or metadata_dir() / 'import-staging'
        parent.mkdir(parents=True, exist_ok=True)
        run_dir = Path(tempfile.mkdtemp(prefix='gui-', dir=parent))
        prepared = []
        for index, row in enumerate(preview):
            op.progress('Preparing and verifying tracks', index, len(preview), row.source.name)
            if row.action == 'Skip':
                report.files.append(FileResult(row.source, row.destination, 'skipped'))
                continue
            if row.action == 'Blocked':
                report.files.append(FileResult(row.source, row.destination, 'failed', row.warning))
                continue
            track = tracks[row.source]
            working = run_dir / 'prepared' / f'{index}{track.path.suffix}'
            try:
                validate_source(track, source)
                stage_track(track, working, op)
                validate_source(track, source)
                prepared.append((index, row, track, working))
            except Cancelled:
                raise
            except Exception as exc:
                report.files.append(FileResult(row.source, row.destination, 'failed', str(exc)))
        # All edits occur on staged copies before the library is touched.
        for index, row, track, working in prepared:
            op.progress('Importing verified tracks', index, len(preview), row.source.name)
            try:
                validate_source(track, source)
                safe_destination(row.destination, library)
                if optional_signature(row.destination) != row.destination_signature:
                    raise ValueError('Destination changed since preview; preview again.')
                if row.exists and importer.files_identical(working, row.destination):
                    if optional_signature(row.destination) != row.destination_signature:
                        raise ValueError('Destination changed during duplicate verification; preview again.')
                    action = 'duplicate'
                elif row.exists and str(row.source) not in replacements:
                    action = 'skipped'
                else:
                    backup = run_dir / 'backups' / row.destination.relative_to(library)
                    commit_copy(working, row.destination, row.destination_signature, backup, library)
                    action = 'replaced' if row.exists else 'imported'
                report.files.append(FileResult(row.source, row.destination, action))
            except Exception as exc:
                report.files.append(FileResult(row.source, row.destination, 'failed', str(exc)))
        if remove_sources:
            cleanup_imported_sources(session, prepared, report, op)
        # Report completion without another checkpoint: a late cancel must not
        # hide copies which have already been safely committed.
        op.report(Progress('Import complete', len(preview), len(preview)))
    except Cancelled:
        report.cancelled = True
    except Exception as exc:
        report.errors.append(str(exc))
    finally:
        if run_dir:
            try:
                if (run_dir / 'backups').exists():
                    report.recovery = str(run_dir / 'backups')
                    shutil.rmtree(run_dir / 'prepared')
                else:
                    shutil.rmtree(run_dir)
            except OSError as exc:
                report.recovery = str(run_dir)
                report.errors.append(f'Temporary files could not be removed: {exc}')
    return report
