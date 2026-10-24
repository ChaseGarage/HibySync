"""Device/source-scoped fast comparison history; never proof of byte equality."""
import hashlib
import json
from contextlib import closing
from pathlib import Path
import sqlite3


def scope(source, target):
    identity = [str(source), target.music, target.usb.vendor, target.usb.model,
                target.usb.serial or target.usb.path, target.mount.source]
    return hashlib.sha256(json.dumps(identity).encode()).hexdigest()


def load(path, source, target):
    if not Path(path).is_file():
        return {}
    try:
        with closing(sqlite3.connect(f'{Path(path).as_uri()}?mode=ro', uri=True)) as con:
            row = con.execute('SELECT snapshot FROM device_history WHERE scope=?',
                              (scope(source, target),)).fetchone()
        value = json.loads(row[0]) if row else {}
        return value if isinstance(value, dict) else {}
    except (OSError, sqlite3.Error, ValueError):
        return {}


def save(plan):
    """Called only after successful final checks, with current fingerprints."""
    from .preview import _fold
    remote = {_fold(p): sig for p, sig in plan.remote_signatures.items()}
    snapshot = {_fold(p): dict(local=list(sig), remote=list(remote[_fold(p)][2:4]))
                for p, sig in plan.local_signatures.items() if _fold(p) in remote}
    path = Path(plan.state_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as con:
        with con:
            con.execute('CREATE TABLE IF NOT EXISTS device_history (scope TEXT PRIMARY KEY, snapshot TEXT NOT NULL)')
            con.execute('INSERT OR REPLACE INTO device_history VALUES (?,?)',
                        (scope(plan.source, plan.target), json.dumps(snapshot)))
