"""File identity checks used to detect stale reviews before library writes."""

from pathlib import Path
import stat


def signature(path: Path) -> tuple[int, ...]:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError(f'Expected a regular file, not a symlink or directory: {path}')
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def optional_signature(path: Path):
    try:
        return signature(path)
    except FileNotFoundError:
        return None
