"""Confirmed one-way mirror execution with staged writes and durable recovery.

All removals follow successful verified transfers and a fresh, complete source
and device comparison. A stale review never silently authorizes a new operation.
"""
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import shutil
import time
import uuid

from hiby_music_tools.core.files import signature
from hiby_music_tools.core.interaction import Cancelled
from hiby_music_tools.paths import metadata_dir
from hiby_music_tools.sync import AUDIO_EXTENSIONS, sha256_file
from .events import Disconnected, SyncOperation, SyncProgress
from .preview import compare, scan, _fold
from .transports import make_transport, relative
from . import state


@dataclass
class SyncReport:
    state: str = 'error'
    files: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    recovery: str = ''
    final_plan: object = None
    bytes_transferred: int = 0


class Journal:
    def __init__(self, root, plan):
        self.directory = Path(root) / ('run-' + uuid.uuid4().hex)
        self.directory.mkdir(parents=True, mode=0o700)
        self.path = self.directory / 'journal.jsonl'
        self.write(dict(state='prepared', source=plan.source, music=plan.target.music,
                        device=plan.target.usb.key, target=plan.target.key,
                        changes=[r for kind in ('new','updated','remove') for r in plan.groups[kind]]))

    def write(self, value):
        with self.path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(value, ensure_ascii=False) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(fd)
        finally: os.close(fd)


def same_review(a, b):
    return (a.source == b.source and a.target == b.target and a.complete and b.complete and
            a.verified == b.verified and a.local_signatures == b.local_signatures and
            a.remote_signatures == b.remote_signatures and a.local_digests == b.local_digests and
            a.remote_digests == b.remote_digests)


def execute(plan, devices, *, confirmed_removals=False, operation=None, recovery_root=None,
            transport_factory=make_transport):
    op = operation or SyncOperation()
    report = SyncReport()
    rows = [dict(row) for kind in ('new', 'updated', 'remove') for row in plan.groups[kind]]
    report.files = [dict(row, status='Skipped', error='Not started') for row in rows]
    completed, transferred, last_file_bytes = 0, 0, 0
    current = {}
    started = time.monotonic()
    journal = transport = None

    def event(state, *, count=None, total=None, error=''):
        speed = last_file_bytes / (time.monotonic() - started) if last_file_bytes and time.monotonic() - started >= .2 and state in ('Copying','Updating') else None
        op.report(SyncProgress(current.get('relpath',''), current.get('kind',''), state, count, total,
                               completed, len(rows), transferred, plan.transfer_bytes, error, speed))

    def copying(count):
        nonlocal transferred, last_file_bytes
        if count < last_file_bytes or count > current['size']:
            raise ValueError('Transport returned inconsistent byte progress')
        transferred += count - last_file_bytes
        last_file_bytes = count
        event('Updating' if current['kind'] == 'updated' else 'Copying', count=count, total=current['size'])

    def verifying(count):
        event('Verifying', count=count, total=current['size'])

    def source_unchanged():
        manifest = scan(Path(plan.source), op, label='local library', guard=transport.guard)
        if manifest.errors or {rel: item[1] for rel,item in manifest.files.items()} != plan.local_signatures:
            raise ValueError('Local library changed. Removals are blocked; refresh and review again.')

    def cleanup(rel):
        # Never issue cleanup against a disappeared mount/ordinary replacement path.
        if rel in transport.created and devices.alive(plan.target):
            with op.publication(recover=True):
                if transport.exists(rel): transport.remove(rel)

    try:
        if not plan.complete:
            raise ValueError('Sync requires a complete review without conflicts.')
        if plan.groups['remove'] and not confirmed_removals:
            raise ValueError('Explicit confirmation of the listed removals is required.')
        event('Revalidating')
        fresh = compare(plan.source, plan.target, devices, verify=plan.verified, operation=op, state_path=plan.state_path)
        if not same_review(plan, fresh):
            report.state, report.final_plan = 'stale', fresh
            raise ValueError('The libraries changed after review. No files were written; review the new comparison.')
        transport = transport_factory(plan.target, devices, plan.source, op)
        # Normal sync hashes only files it will actually write/delete. A full
        # library hash is reserved for the explicit Verify contents workflow.
        if not plan.verified:
            for row in rows:
                op.checkpoint()
                source_rel = row['relpath']
                rel = row.get('destination', source_rel)
                if row['kind'] != 'remove':
                    path = Path(plan.source) / source_rel
                    plan.local_digests[source_rel] = sha256_file(path, op)
                    if signature(path) != plan.local_signatures[source_rel]:
                        raise ValueError('Source changed after review; refresh before retrying')
                if row['kind'] != 'new':
                    plan.remote_digests[rel] = transport.digest(rel)
                    if signature(Path(plan.target.music) / rel) != plan.remote_signatures[rel]:
                        raise ValueError('Device file changed after review; refresh before retrying')
            source_unchanged()
        recovery = Path(recovery_root or metadata_dir() / 'device-sync').expanduser().resolve()
        for root in (Path(plan.source), Path(plan.target.music)):
            if recovery == root or recovery.is_relative_to(root) or root.is_relative_to(recovery):
                raise ValueError('Recovery storage must be separate from the library and device Music root.')
        free = transport.available()
        used, peak = 0, 0
        for row in rows:
            if row['kind'] == 'remove': continue
            peak = max(peak, used + row['size'])
            used += row['size'] - (plan.remote_signatures[row.get('destination', row['relpath'])][2] if row['kind'] == 'updated' else 0)
        if free is not None and free < peak:
            raise OSError('Insufficient device storage for verified staged transfers; nothing was written.')
        backup_bytes = sum(plan.remote_signatures[r.get('destination', r['relpath'])][2] for r in plan.groups['updated'])
        ancestor = recovery
        while not ancestor.exists(): ancestor = ancestor.parent
        if shutil.disk_usage(ancestor).free < backup_bytes + 65536:
            raise OSError('Insufficient local recovery storage; nothing was written.')
        journal = Journal(recovery, plan)
        report.recovery = str(journal.path)
        token = journal.directory.name
        transfers_failed = False
        removal_gate, source_checked = False, 0
        for index, row in enumerate(rows):
            current, last_file_bytes = row, 0
            op.checkpoint()
            transport.guard(True)
            source_rel = str(relative(row['relpath']))
            rel = str(relative(row.get('destination', source_rel)))
            # Only comparison-approved filename aliases may use a different
            # destination. Never accept arbitrary paths in a reviewed row.
            if rel != source_rel:
                if row['kind'] != 'updated' or _fold(rel) != _fold(source_rel) or Path(rel).parent != Path(source_rel).parent:
                    raise ValueError('Invalid device filename alias')
            if Path(rel).suffix.lower() not in AUDIO_EXTENSIONS:
                raise ValueError('Only managed audio files can be synchronized')
            result = report.files[index]
            if row['kind'] == 'remove':
                if transfers_failed:
                    result['error'] = 'Removals blocked because a transfer failed'
                    continue
                # The entire removal set must still be exactly the reviewed set.
                if not removal_gate:
                    event('Checking removals')
                    source_unchanged()
                    check = compare(plan.source, plan.target, devices, verify=plan.verified, operation=op,
                                    state_path=plan.state_path, history={})
                    if (not check.complete or check.groups['new'] or check.groups['updated'] or
                            {r['relpath'] for r in check.groups['remove']} != {r['relpath'] for r in plan.groups['remove']} or
                            (plan.verified and check.local_digests != plan.local_digests)):
                        raise ValueError('Final transfer/source verification failed or the device changed. No removal pass was performed.')
                    removal_gate, source_checked = True, time.monotonic()
                # No quadratic whole-library scan for every removed song.
                # The first source fingerprint catches loss/replacement/emptying
                # immediately; a complete source scan runs at bounded intervals.
                first = next(iter(plan.local_signatures))
                if signature(Path(plan.source) / first) != plan.local_signatures[first]:
                    raise ValueError('Local library changed during removals; remaining files retained')
                if time.monotonic() - source_checked >= .5:
                    source_unchanged()
                    source_checked = time.monotonic()
                if (Path(plan.source) / rel).exists() or (Path(plan.source) / rel).is_symlink():
                    raise ValueError('A removal now exists locally; retained')
                event('Verifying removal', count=None, total=None)
                if transport.digest(rel) != plan.remote_digests[rel]:
                    raise ValueError('Device removal changed after review; retained')
                journal.write(dict(relpath=rel, operation='remove', state='confirmed-removal'))
                event('Removing', count=None, total=None)
                transport.remove(rel)
                result.update(status='Completed', error='')
                completed += 1
                event('Completed', count=None, total=None)
                journal.write(dict(relpath=rel, operation='remove', state='completed'))
                continue
            stage = str(relative(rel).with_name(f'.hibysync-{token}-{index}.part'))
            old = str(relative(rel).with_name(f'.hibysync-{token}-{index}.backup'))
            backup = journal.directory / ('original-' + str(index) + '.audio')
            published = False
            old_moved = False
            try:
                local = Path(plan.source) / source_rel
                if signature(local) != plan.local_signatures[source_rel] or sha256_file(local, op) != plan.local_digests[source_rel]:
                    raise ValueError('Source changed since review; refresh before retrying')
                if row['kind'] == 'new' and transport.exists(rel):
                    raise ValueError('Destination appeared after review; it was not overwritten')
                if row['kind'] == 'updated' and transport.digest(rel) != plan.remote_digests[rel]:
                    raise ValueError('Destination changed since review; it was not overwritten')
                journal.write(dict(relpath=rel, operation=row['kind'], state='copying', stage=stage, old=old, backup=str(backup)))
                started = time.monotonic()
                event('Updating' if row['kind'] == 'updated' else 'Copying', count=transport.initial_bytes, total=row['size'])
                transport.put(local, stage, copying)
                event('Verifying', count=0, total=row['size'])
                if transport.digest(stage, verifying) != plan.local_digests[source_rel]:
                    raise OSError('Staged SHA-256 verification failed')
                # A silent backend with no intermediate callback is only credited
                # once its complete stored bytes have actually been read/verified.
                if last_file_bytes < row['size']: copying(row['size'])
                if signature(local) != plan.local_signatures[source_rel]:
                    raise ValueError('Source changed during transfer; staged copy was not published')
                if row['kind'] == 'updated':
                    event('Backing up', count=None, total=None)
                    transport.download(rel, backup)
                    if sha256_file(backup, op) != plan.remote_digests[rel]:
                        raise OSError('Original recovery backup verification failed')
                    if transport.digest(rel) != plan.remote_digests[rel]:
                        raise ValueError('Destination changed while preparing the replacement')
                op.checkpoint()
                with op.publication():
                    transport.guard(True)
                    if signature(local) != plan.local_signatures[source_rel]:
                        raise ValueError('Source changed before publication; retained original')
                    event('Publishing', count=None, total=None)
                    journal.write(dict(relpath=rel, operation=row['kind'], state='publishing', stage=stage, old=old, backup=str(backup)))
                    if row['kind'] == 'updated' and not transport.atomic_replace:
                        transport.move(rel, old)
                        old_moved = True
                    transport.move(stage, rel, overwrite=row['kind'] == 'updated' and transport.atomic_replace)
                    published = True
                    event('Verifying', count=0, total=row['size'])
                    if transport.digest(rel, verifying) != plan.local_digests[source_rel]:
                        raise OSError('Published SHA-256 verification failed')
                    if old_moved: transport.remove(old)
                    result.update(status='Completed', error='')
                    completed += 1
                    journal.write(dict(relpath=rel, operation=row['kind'], state='completed', backup=str(backup) if backup.exists() else ''))
                    event('Completed', count=row['size'], total=row['size'])
            except Exception as exc:
                # Restore only our own just-published data while still connected.
                # The recovery copy is kept even when rollback cannot be proved safe.
                if devices.alive(plan.target):
                    try:
                        with op.publication(recover=True):
                            if old_moved and not published and not transport.exists(rel):
                                transport.move(old, rel)
                            elif published and row['kind'] == 'updated' and backup.exists():
                                # A corrupt new destination is not overwritten blindly.
                                # Keep both the local original and any remote backup for recovery.
                                result['recoveryRequired'] = str(backup)
                    except Exception as recovery_error:
                        report.errors.append('Recovery needed: ' + str(recovery_error))
                if isinstance(exc, (Cancelled, Disconnected)):
                    result.update(status='Skipped' if isinstance(exc, Cancelled) else 'Failed',
                                  error='Cancelled during transfer' if isinstance(exc, Cancelled) else str(exc))
                    raise
                result.update(status='Failed', error=str(exc) + (f' · Original retained at {backup}' if backup.exists() else ''))
                transfers_failed = True
                journal.write(dict(relpath=rel, operation=row['kind'], state='failed', error=str(exc)))
                event('Failed', error=str(exc))
            finally:
                if not published:
                    try: cleanup(stage)
                    except Exception: pass  # Journal owns any retained .part object.
        current = {}
        if transfers_failed:
            raise OSError('One or more transfers failed. Device removals were not performed.')
        event('Final verification', count=None, total=None)
        source_unchanged()
        final = compare(plan.source, plan.target, devices, verify=plan.verified, operation=op,
                        state_path=plan.state_path, history={})
        report.final_plan = final
        if not final.complete or final.changes or (plan.verified and final.local_digests != plan.local_digests):
            raise OSError('Final library comparison did not match; refresh before retrying.')
        verified_paths = {r['relpath'] for r in report.files if r['kind'] != 'remove' and r['status'] == 'Completed'}
        final.synced += sum(r['relpath'] in verified_paths for r in final.groups['uncertain'])
        final.groups['uncertain'] = [r for r in final.groups['uncertain'] if r['relpath'] not in verified_paths]
        state.save(final)
        report.state = 'complete'
        journal.write(dict(state='complete', files=report.files))
        event('Complete', count=None, total=None)
    except Cancelled:
        report.state = 'cancelled'
        report.errors.append('Sync cancelled. Verified completed transfers were preserved; remaining work was not started.')
        event('Cancelled', error=report.errors[-1])
    except Exception as exc:
        try:
            connected = devices.alive(plan.target)
        except (OSError, ValueError):
            connected = False
        if isinstance(exc, Disconnected) or not connected:
            report.state = 'disconnected'
        if current:
            for result in report.files:
                if result['relpath'] == current['relpath'] and result['status'] == 'Skipped':
                    result.update(status='Failed', error=str(exc))
        report.errors.append(str(exc))
        event('Failed', error=str(exc))
    report.bytes_transferred = transferred
    if journal:
        try:
            journal.write(dict(state=report.state, errors=report.errors, files=report.files))
        except OSError as exc:
            report.errors.append('Could not finalize recovery log: ' + str(exc))
            if report.state == 'complete': report.state = 'error'
    return report
