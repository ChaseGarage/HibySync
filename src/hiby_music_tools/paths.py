"""Default user paths shared by all commands; CLI overrides take precedence."""

from pathlib import Path


def library_dir() -> Path:
    return Path.home() / "Music" / "Library"


def metadata_dir() -> Path:
    return Path.home() / ".cache" / "hiby-music-tools"
