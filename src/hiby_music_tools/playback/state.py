"""Atomic player-state persistence; called by workers, never during playback IO."""

import json
import os
from pathlib import Path
import tempfile


def state_path():
    return Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state'))) / 'hibysync/player.json'


def load(path):
    if not path.is_file():
        return {}
    if path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError('Saved playback state is too large')
    result = json.loads(path.read_text())
    if not isinstance(result, dict):
        raise ValueError('Invalid playback state')
    return result


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream, ensure_ascii=False, separators=(',', ':'))
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)
