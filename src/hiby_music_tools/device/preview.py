"""Read-only mirror planning. No copy, unlink, mkdir, or sync-cache writes.

Reuse the CLI's managed extensions, size/hash decision and SHA-256 implementation.
Its legacy cache is deliberately not proof of equality: it has no device identity.
"""
from dataclasses import dataclass, field
import os
from pathlib import Path
import stat
import sqlite3
import time
import unicodedata

from hiby_music_tools.core.files import signature
from hiby_music_tools.core.interaction import Operation
from hiby_music_tools.sync import AUDIO_EXTENSIONS, human_bytes, needs_copy, sha256_file
from hiby_music_tools.library.database import connect
from hiby_music_tools.paths import metadata_dir
from . import state


@dataclass
class Manifest:
    files: dict = field(default_factory=dict)
    directories: set = field(default_factory=set)
    errors: list = field(default_factory=list)


@dataclass
class Plan:
    target: object
    source: str
    groups: dict
    synced: int = 0
    local_count: int = 0
    remote_count: int = 0
    verified: bool = False
    blocked: str = ''
    storage: dict | None = None
    local_signatures: dict = field(default_factory=dict)
    remote_signatures: dict = field(default_factory=dict)
    local_digests: dict = field(default_factory=dict)
    remote_digests: dict = field(default_factory=dict)
    state_path: str = ''

    @property
    def complete(self):
        return not self.groups['conflicts'] and not self.blocked

    @property
    def changes(self):
        return sum(len(self.groups[k]) for k in ('new', 'updated', 'remove'))

    @property
    def transfer_bytes(self):
        return sum(row['size'] for k in ('new', 'updated') for row in self.groups[k])


def _row(kind, rel, size=0, reason='', metadata=None):
    metadata = metadata or {}
    details = ' · '.join(str(metadata.get(k) or '') for k in ('artist', 'album') if metadata.get(k))
    return dict(kind=kind, relpath=rel, title=metadata.get('title') or Path(rel).name,
                detail=details or str(Path(rel).parent), size=size, sizeText=human_bytes(size), reason=reason)


def scan(root, operation=None, *, label='Music', guard=lambda: None):
    op, result = operation or Operation(), Manifest()
    if root.is_symlink() or not root.is_dir():
        raise ValueError(f'{label} is not an accessible regular directory: {root}')
    pending = [root]
    while pending:
        directory = pending.pop()
        guard()
        op.progress('Scanning ' + label, len(result.files), None, str(directory))
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    op.checkpoint()
                    guard()
                    path = Path(entry.path)
                    rel = path.relative_to(root).as_posix()
                    try:
                        info = entry.stat(follow_symlinks=False)
                        if stat.S_ISLNK(info.st_mode):
                            result.errors.append(_row('conflicts', rel, reason=f'{label}: symlink retained; not followed'))
                        elif stat.S_ISDIR(info.st_mode):
                            result.directories.add(rel)
                            pending.append(path)
                        elif path.suffix.lower() in AUDIO_EXTENSIONS:
                            if not stat.S_ISREG(info.st_mode):
                                raise ValueError('Not a regular audio file')
                            result.files[rel] = (path, (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns))
                    except (OSError, ValueError) as exc:
                        result.errors.append(_row('conflicts', rel, reason=f'{label}: {exc}'))
        except OSError as exc:
            result.errors.append(_row('conflicts', directory.relative_to(root).as_posix(), reason=f'{label}: {exc}'))
    return result


def _fold(path):
    return unicodedata.normalize('NFC', path).casefold()


def _file_aliases(local, remote):
    """Pair unique filename aliases; directory aliases still require review.

    Keep the device spelling rather than issuing an unsafe Add + Remove on FAT.
    Equality still requires hashing, and updates use the existing device path.
    """
    sides = []
    for manifest in (local, remote):
        folded = {}
        for path in manifest.files:
            folded.setdefault(_fold(path), []).append(path)
        sides.append(folded)
    directories = {_fold(p) for p in local.directories | remote.directories}
    pairs = {}
    for key in sides[0].keys() & sides[1].keys():
        left, right = sides[0][key], sides[1][key]
        if len(left) == len(right) == 1 and key not in directories:
            a, b = left[0], right[0]
            if a != b and Path(a).parent == Path(b).parent:
                pairs[a] = b
    return pairs


def _collisions(local, remote, aliases=None):
    """FAT/exFAT aliases must not become an Add + Remove pair."""
    seen, bad = {}, set()
    allowed = {_fold(p) for p in (aliases or {})}
    all_paths = set(local.files) | set(remote.files) | local.directories | remote.directories
    for path in sorted(all_paths):
        key = _fold(path)
        if key in seen and seen[key] != path and key not in allowed:
            bad.update((seen[key], path))
        seen[key] = path
    # A file/directory occupying the same path is also unsafe to overwrite.
    bad.update(set(local.files) & remote.directories)
    bad.update(set(remote.files) & local.directories)
    return {rel for rel in set(local.files) | set(remote.files)
            if any('/'.join(rel.split('/')[:i]) in bad for i in range(1, len(rel.split('/')) + 1))}


def _labels(root, database):
    if database is None or not Path(database).is_file():
        return {}
    try:
        with connect(Path(database)) as con:
            rows = con.execute('''SELECT t.relpath,t.title,t.artist,t.album FROM tracks t
              JOIN roots r ON r.id=t.root_id WHERE r.path=?''', (str(root),))
            return {r['relpath']: dict(r) for r in rows}
    except (OSError, ValueError, sqlite3.DatabaseError):
        return {}  # Labels are optional; the catalog is not synchronization truth.


def _digest(path, expected, op):
    if signature(path) != expected:
        raise ValueError('File changed during comparison; refresh before using this preview')
    result = sha256_file(path, op)
    if signature(path) != expected:
        raise ValueError('File changed while being hashed; refresh to compare again')
    return result


def compare(source, target, devices, *, verify=False, database=None, operation=None, state_path=None, history=None):
    op = operation or Operation()
    source = Path(source).expanduser().resolve()
    music = devices.validate(target, source)
    deadline = 0
    def guard():
        nonlocal deadline
        op.checkpoint()
        if time.monotonic() >= deadline:
            deadline = time.monotonic() + .5
            if not devices.alive(target):
                raise ValueError('The R1 was disconnected or its mount changed. Refresh to reconnect.')
    local = scan(source, op, label='local library', guard=guard)
    devices.validate(target, source)
    remote = scan(music, op, label='HiBy /Music', guard=guard)
    groups = {kind: [] for kind in ('new', 'updated', 'remove', 'uncertain', 'conflicts')}
    groups['conflicts'].extend(local.errors + remote.errors)
    plan = Plan(target, str(source), groups, local_count=len(local.files), remote_count=len(remote.files), verified=verify)
    plan.state_path = str(Path(state_path or (Path(database).parent if database else metadata_dir()) / 'device-sync-state.sqlite3').resolve())
    if history is None:
        history = state.load(plan.state_path, source, target) if not verify else {}
    plan.local_signatures = {rel: item[1] for rel, item in local.files.items()}
    plan.remote_signatures = {rel: item[1] for rel, item in remote.files.items()}
    if not local.files and remote.files:
        plan.blocked = 'Empty local library protection: removing all device music is blocked. No files will be changed.'
    aliases = _file_aliases(local, remote)
    labels, conflicts = _labels(source, database), _collisions(local, remote, aliases)
    aliases = {a: b for a, b in aliases.items() if a not in conflicts and b not in conflicts}
    paths = sorted((set(local.files) | set(remote.files)) - set(aliases.values()))
    for i, rel in enumerate(paths):
        op.progress('Comparing music', i, len(paths), rel)
        guard()
        item = local.files.get(rel)
        remote_rel = aliases.get(rel, rel)
        other = remote.files.get(remote_rel)
        size = (item or other)[1][2]
        if rel in conflicts:
            groups['conflicts'].append(_row('conflicts', rel, size, 'Case/Unicode alias or file/directory collision; manual review required', labels.get(rel)))
            continue
        kind, reason = '', ''
        try:
            if item and signature(item[0]) != item[1] or other and signature(other[0]) != other[1]:
                raise ValueError('File changed during comparison')
            if verify:
                op.progress('Hashing local and device contents', i, len(paths), rel)
                if item:
                    plan.local_digests[rel] = _digest(item[0], item[1], op)
                if other:
                    plan.remote_digests[remote_rel] = _digest(other[0], other[1], op)
            if item is None:
                kind = 'remove'
                reason = 'Device-only managed audio; removal requires explicit confirmation'
            elif other is None:
                kind = 'new'
            elif needs_copy(item[1][2], other[1][2], None):
                kind, reason = 'updated', 'File sizes differ'
            elif verify:
                digest = plan.local_digests[rel]
                remote_digest = plan.remote_digests[remote_rel]
                if needs_copy(item[1][2], other[1][2], digest, verify=True, remote_digest=remote_digest):
                    kind, reason = 'updated', 'SHA-256 differs (audio, tags, or artwork changed)'
                else:
                    plan.synced += 1
            else:
                previous = history.get(_fold(rel))
                if isinstance(previous, dict) and (previous.get('local') != list(item[1]) or previous.get('remote') != list(other[1][2:4])):
                    kind, reason = 'updated', 'File fingerprint changed since the last successful sync'
                else:
                    kind, reason = 'uncertain', 'Size matches; skipped by fast comparison. Verify contents is optional for detecting same-size changes without sync history.'
            if kind:
                row = _row(kind, rel, size, reason, labels.get(rel))
                if remote_rel != rel:
                    row['destination'] = remote_rel
                    row['reason'] += (' · ' if reason else '') + 'Device filename spelling retained: ' + remote_rel
                groups[kind].append(row)
        except (OSError, ValueError) as exc:
            groups['conflicts'].append(_row('conflicts', rel, size, str(exc), labels.get(rel)))
    devices.validate(target, source)
    if local.errors or remote.errors:
        plan.blocked = 'Some folders or files could not be scanned safely. This comparison is incomplete; no removal plan can be applied.'
    try:
        plan.storage = devices.storage(target)
    except OSError:
        pass
    op.progress('Comparison complete', len(local.files) + len(remote.files), len(local.files) + len(remote.files))
    return plan
