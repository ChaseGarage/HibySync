"""Guarded filesystem IO and native GIO MTP transfers, never shell commands."""
from contextlib import contextmanager
import ctypes
import hashlib
import os
from pathlib import Path, PurePosixPath
import stat
import time
from urllib.parse import quote, unquote

from hiby_music_tools.core.streaming import copy_stream, CHUNK
from .events import Disconnected


def relative(value):
    path = PurePosixPath(value)
    if not value or path.is_absolute() or '..' in path.parts or '.' == value or '\x00' in value:
        raise ValueError('Unsafe device-relative path')
    return path


class Transport:
    atomic_replace = False
    initial_bytes = None

    def __init__(self, target, devices, source, operation):
        self.target, self.devices, self.source, self.op = target, devices, Path(source), operation
        self.root = devices.validate(target, source)
        self.deadline = 0
        self.created = set()

    def guard(self, force=False):
        self.op.checkpoint()
        if force or time.monotonic() >= self.deadline:
            self.deadline = time.monotonic() + .5
            try:
                self.devices.validate(self.target, self.source)
            except (OSError, ValueError) as exc:
                raise Disconnected(str(exc)) from exc

    def available(self):
        self.guard(True)
        storage = self.devices.storage(self.target)
        return storage['free'] if storage else None


class FilesystemTransport(Transport):
    atomic_replace = True
    initial_bytes = 0

    @contextmanager
    def parent(self, rel, create=False):
        path = relative(rel)
        self.guard(True)
        fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        expected = os.makedev(*map(int, self.target.mount.device.split(':')))
        try:
            if os.fstat(fd).st_dev != expected:
                raise Disconnected('The device mount changed')
            for part in path.parts[:-1]:
                self.guard(True)
                if create:
                    try: os.mkdir(part, dir_fd=fd)
                    except FileExistsError: pass
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = child
                if os.fstat(fd).st_dev != expected:
                    raise ValueError('Nested device mounts are not writable sync destinations')
            yield fd, path.name
        finally:
            os.close(fd)

    @contextmanager
    def read(self, rel):
        with self.parent(rel) as (parent, name):
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
            with os.fdopen(fd, 'rb') as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise ValueError('Expected a regular device file')
                yield stream

    def exists(self, rel):
        try:
            with self.parent(rel) as (parent, name):
                info = os.stat(name, dir_fd=parent, follow_symlinks=False)
                if not stat.S_ISREG(info.st_mode):
                    raise ValueError('Device path is not a regular file')
                return True
        except FileNotFoundError:
            return False

    def put(self, local, rel, progress):
        with self.parent(rel, create=True) as (parent, name):
            fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644, dir_fd=parent)
            self.created.add(rel)
            with os.fdopen(fd, 'wb', buffering=0) as output, open(local, 'rb') as source:
                copy_stream(source, output, progress=progress, checkpoint=self.guard)
            os.fsync(parent)

    def download(self, rel, local, progress=lambda count: None):
        with self.read(rel) as source, open(local, 'xb', buffering=0) as output:
            copy_stream(source, output, progress=progress, checkpoint=self.guard)

    def digest(self, rel, progress=lambda count: None):
        digest, count = hashlib.sha256(), 0
        with self.read(rel) as stream:
            while True:
                self.guard()
                data = stream.read(CHUNK)
                if not data: break
                digest.update(data)
                count += len(data)
                progress(count)
        return digest.hexdigest()

    def move(self, old, new, *, overwrite=False):
        with self.parent(old) as (a, source), self.parent(new, create=True) as (b, destination):
            self.guard(True)
            if overwrite:
                os.replace(source, destination, src_dir_fd=a, dst_dir_fd=b)
            else:
                libc = ctypes.CDLL(None, use_errno=True)
                rename = getattr(libc, 'renameat2', None)
                if rename is None:
                    raise OSError('Safe no-replace rename is unavailable')
                rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
                rename.restype = ctypes.c_int
                if rename(a, os.fsencode(source), b, os.fsencode(destination), 1):
                    number = ctypes.get_errno()
                    raise OSError(number, os.strerror(number))
            os.fsync(b)

    def remove(self, rel):
        with self.parent(rel) as (parent, name):
            self.guard(True)
            info = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode):
                raise ValueError('Only regular device files can be removed')
            os.unlink(name, dir_fd=parent)
            os.fsync(parent)


class GioTransport(Transport):
    """Native GFile operations. Copy/delete fallback for move is never allowed."""
    def __init__(self, target, devices, source, operation, *, gio_root=None):
        super().__init__(target, devices, source, operation)
        try:
            import gi
            gi.require_version('Gio', '2.0')
            from gi.repository import Gio, GLib
        except (ImportError, ValueError) as exc:
            raise RuntimeError('MTP sync needs python-gobject and gvfs-mtp. Install them and restart HibySync.') from exc
        self.Gio, self.GLib = Gio, GLib
        if gio_root is not None:
            self.file = gio_root  # Explicit local-GIO test injection, never used by the GUI.
        else:
            endpoint = Path(target.endpoint)
            host = unquote(endpoint.name.split('=', 1)[1])
            self.file = Gio.File.new_for_uri('mtp://' + quote(host, safe='[]:,') + '/')
            for part in Path(target.music).relative_to(endpoint).parts:
                self.file = self.file.get_child(part)

    def child(self, rel):
        file = self.file
        for part in relative(rel).parts:
            file = file.get_child(part)
        return file

    @contextmanager
    def cancellable(self):
        cancel = self.Gio.Cancellable()
        with self.op.bind(cancel.cancel):
            try:
                yield cancel
            except self.GLib.Error:
                self.op.checkpoint()  # Convert an explicit user cancellation to Cancelled.
                raise

    def _info(self, file, cancel):
        return file.query_info('standard::type,standard::is-symlink', self.Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS, cancel)

    def parents(self, rel):
        self.guard(True)
        with self.cancellable() as cancel:
            root_info = self._info(self.file, cancel)
            if root_info.get_file_type() != self.Gio.FileType.DIRECTORY or root_info.get_is_symlink():
                raise ValueError('Native MTP /Music root is missing or redirected')
            file = self.file
            for part in relative(rel).parts[:-1]:
                file = file.get_child(part)
                self.guard(True)
                try:
                    info = self._info(file, cancel)
                except self.GLib.Error as exc:
                    if not exc.matches(self.Gio.io_error_quark(), self.Gio.IOErrorEnum.NOT_FOUND): raise
                    file.make_directory(cancel)
                    info = self._info(file, cancel)
                if info.get_file_type() != self.Gio.FileType.DIRECTORY or info.get_is_symlink():
                    raise ValueError('Native MTP parent is not a regular directory')

    def exists(self, rel):
        self.guard()
        with self.cancellable() as cancel:
            try: info = self._info(self.child(rel), cancel)
            except self.GLib.Error as exc:
                if exc.matches(self.Gio.io_error_quark(), self.Gio.IOErrorEnum.NOT_FOUND): return False
                raise
            if info.get_is_symlink() or info.get_file_type() != self.Gio.FileType.REGULAR:
                raise ValueError('Native MTP path is not a regular file')
            return True

    def _copy(self, source, destination, progress, owned=None):
        self.guard(True)
        callback_error = []
        with self.cancellable() as cancel:
            def advanced(current, total, *_):
                try:
                    self.guard()
                    if owned and current > 0:
                        self.created.add(owned)
                    progress(int(current))
                except Exception as exc:
                    callback_error.append(exc)
                    cancel.cancel()
            try:
                source.copy(destination, self.Gio.FileCopyFlags.NOFOLLOW_SYMLINKS | self.Gio.FileCopyFlags.TARGET_DEFAULT_PERMS,
                            cancel, advanced, None)
            except self.GLib.Error:
                if callback_error: raise callback_error[0]
                raise
            if callback_error: raise callback_error[0]
            if owned: self.created.add(owned)

    def put(self, local, rel, progress):
        self.parents(rel)
        self._copy(self.Gio.File.new_for_path(str(local)), self.child(rel), progress, owned=rel)

    def download(self, rel, local, progress=lambda count: None):
        self._copy(self.child(rel), self.Gio.File.new_for_path(str(local)), progress)
        with open(local, 'rb') as stream:
            os.fsync(stream.fileno())

    def digest(self, rel, progress=lambda count: None):
        self.guard(True)
        digest, count = hashlib.sha256(), 0
        with self.cancellable() as cancel:
            stream = self.child(rel).read(cancel)
            try:
                while True:
                    self.guard()
                    block = stream.read_bytes(CHUNK, cancel).get_data()
                    if not block: break
                    digest.update(block)
                    count += len(block)
                    progress(count)
            finally:
                stream.close(None)
        return digest.hexdigest()

    def move(self, old, new, *, overwrite=False):
        if overwrite:
            raise ValueError('Atomic overwrite is not guaranteed by the MTP transport')
        self.guard(True)
        with self.cancellable() as cancel:
            self.child(old).move(self.child(new), self.Gio.FileCopyFlags.NOFOLLOW_SYMLINKS |
                                 self.Gio.FileCopyFlags.NO_FALLBACK_FOR_MOVE, cancel, None, None)

    def remove(self, rel):
        self.guard(True)
        self.exists(rel)
        with self.cancellable() as cancel:
            self.child(rel).delete(cancel)

    def available(self):
        self.guard(True)
        with self.cancellable() as cancel:
            try: info = self.file.query_filesystem_info('filesystem::free', cancel)
            except self.GLib.Error:
                self.op.checkpoint()
                return None
        return info.get_attribute_uint64('filesystem::free') if info.has_attribute('filesystem::free') else None


def make_transport(target, devices, source, operation):
    return (GioTransport if target.endpoint else FilesystemTransport)(target, devices, source, operation)
