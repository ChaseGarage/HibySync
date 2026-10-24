#!/usr/bin/env python3
"""
musicsync - Mirror a sanitized local HiBy music library to the mounted HiBy /Music folder.

Default local library:
    ~/Music/Library

Behavior:
  * Preserves the local Artist/Year-Album/Title.ext structure exactly.
  * Copies new files.
  * Re-copies changed files.
  * Deletes audio files from the HiBy when they no longer exist locally.
  * Removes empty directories after deletions.
  * Leaves non-audio/device-generated files alone.
  * Keeps a small local SQLite state DB so same-size metadata edits are still detected.
  * Optional --verify reads and hashes device files and verifies newly copied files.
  * Refuses a destructive sync when the local library contains zero audio files unless
    --allow-empty is explicitly supplied.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sqlite3
import sys
import time
from pathlib import Path

from hiby_music_tools.paths import library_dir, metadata_dir
from hiby_music_tools.core.streaming import copy_stream

AUDIO_EXTENSIONS = {
    ".mp3", ".flac", ".m4a", ".mp4", ".aac", ".ogg", ".opus",
    ".wav", ".aif", ".aiff", ".wma", ".ape", ".wv", ".alac"
}

STATE_DB_DEFAULT = metadata_dir() / "musicsync.sqlite3"
SOURCE_DEFAULT = library_dir()
CHUNK = 512 * 1024


def human_bytes(n: int) -> str:
    value = float(n)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TiB"


def audio_files(root: Path) -> dict[str, Path]:
    found = {}
    if not root.exists():
        return found
    for p in root.rglob("*"):
        try:
            if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS:
                found[p.relative_to(root).as_posix()] = p
        except OSError:
            pass
    return found


def init_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute("""
        CREATE TABLE IF NOT EXISTS sync_state (
            relpath TEXT PRIMARY KEY,
            local_size INTEGER NOT NULL,
            local_mtime_ns INTEGER NOT NULL,
            local_sha256 TEXT NOT NULL,
            synced_sha256 TEXT NOT NULL,
            synced_at INTEGER NOT NULL
        )
    """)
    con.commit()
    return con


def sha256_file(path: Path, operation=None) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            if operation:
                operation.checkpoint()
            block = f.read(CHUNK)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def needs_copy(local_size, remote_size, digest, previous_digest=None, *, verify=False, remote_digest=None):
    """Shared CLI/preview decision, preserving the original fast-sync policy.

    False in fast mode means unchanged by these rules, not proven byte equality.
    Frontends must distinguish that from verified equality on a new device.
    """
    if remote_size is None or remote_size != local_size:
        return True
    if verify:
        return remote_digest != digest
    return previous_digest is not None and previous_digest != digest


def local_hash(con: sqlite3.Connection, rel: str, path: Path) -> str:
    st = path.stat()
    row = con.execute(
        "SELECT local_size, local_mtime_ns, local_sha256 FROM sync_state WHERE relpath=?",
        (rel,)
    ).fetchone()
    if row and row[0] == st.st_size and row[1] == st.st_mtime_ns:
        return row[2]
    return sha256_file(path)


def update_state(con: sqlite3.Connection, rel: str, path: Path, digest: str) -> None:
    st = path.stat()
    con.execute("""
        INSERT INTO sync_state
            (relpath, local_size, local_mtime_ns, local_sha256, synced_sha256, synced_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(relpath) DO UPDATE SET
            local_size=excluded.local_size,
            local_mtime_ns=excluded.local_mtime_ns,
            local_sha256=excluded.local_sha256,
            synced_sha256=excluded.synced_sha256,
            synced_at=excluded.synced_at
    """, (rel, st.st_size, st.st_mtime_ns, digest, digest, int(time.time())))


def remove_state_not_local(con: sqlite3.Connection, local_relpaths: set[str]) -> None:
    for (rel,) in con.execute("SELECT relpath FROM sync_state").fetchall():
        if rel not in local_relpaths:
            con.execute("DELETE FROM sync_state WHERE relpath=?", (rel,))


def candidate_music_dirs() -> list[Path]:
    uid = os.getuid()
    user = os.environ.get("USER", "")
    roots = [Path(f"/run/user/{uid}/gvfs")]
    if user:
        roots += [Path(f"/run/media/{user}"), Path(f"/media/{user}")]

    found = []
    for base in roots:
        if not base.exists():
            continue
        base_depth = len(base.parts)
        for current, dirs, _files in os.walk(base):
            cur = Path(current)
            if len(cur.parts) - base_depth > 5:
                dirs[:] = []
                continue
            if cur.name.lower() == "music":
                found.append(cur)
                dirs[:] = []
    return found


def candidate_score(path: Path) -> int:
    s = str(path).lower()
    score = 0
    if "hiby" in s:
        score += 100
    if "r1" in s:
        score += 50
    if "mtp" in s:
        score += 30
    if any(x in s for x in ("sd card", "sd_card", "sdcard")):
        score += 20
    return score


def autodetect_device_music() -> Path:
    candidates = candidate_music_dirs()
    if not candidates:
        raise RuntimeError(
            "Could not find a mounted HiBy /Music folder.\n"
            "Mount the R1 first, or pass --device-music '/path/to/device/Music'."
        )

    ranked = sorted(candidates, key=lambda p: (-candidate_score(p), len(str(p))))
    best_score = candidate_score(ranked[0])
    best = [p for p in ranked if candidate_score(p) == best_score]

    if len(best) == 1:
        return best[0]

    hibyish = [p for p in best if "hiby" in str(p).lower() or "r1" in str(p).lower()]
    if len(hibyish) == 1:
        return hibyish[0]

    choices = "\n".join(f"  {p}" for p in ranked)
    raise RuntimeError(
        "More than one mounted /Music folder was found, so I will not guess:\n"
        f"{choices}\n\n"
        "Run again with --device-music '/exact/path/to/HiBy/Music'."
    )


class ProgressBar:
    """Same dependency-free progress bar style used by podsync."""
    def __init__(self, total: int | None, width: int = 28, prefix: str = "            "):
        self.total = total
        self.width = width
        self.prefix = prefix
        self.current = 0
        self.started = time.monotonic()
        self.last_draw = 0.0

    def update(self, amount: int, force: bool = False) -> None:
        self.current += amount
        now = time.monotonic()

        # Avoid redrawing thousands of times on very fast local copies.
        if not force and now - self.last_draw < 0.08:
            return
        self.last_draw = now

        elapsed = max(now - self.started, 0.001)
        rate = self.current / elapsed

        if self.total and self.total > 0:
            fraction = min(self.current / self.total, 1.0)
            filled = min(int(self.width * fraction), self.width)
            bar = "█" * filled + "░" * (self.width - filled)
            line = (
                f"\r{self.prefix}[{bar}] {fraction * 100:5.1f}%  "
                f"{human_bytes(self.current)} / {human_bytes(self.total)}  "
                f"{human_bytes(rate)}/s"
            )
        else:
            # Same moving activity indicator podsync uses when size is unknown.
            pos = int((now - self.started) * 8) % self.width
            cells = ["░"] * self.width
            cells[pos] = "█"
            bar = "".join(cells)
            line = (
                f"\r{self.prefix}[{bar}]  "
                f"{human_bytes(self.current)}  {human_bytes(rate)}/s"
            )

        sys.stdout.write(line)
        sys.stdout.flush()

    def finish(self) -> None:
        if self.total is not None and self.current < self.total:
            self.update(self.total - self.current, force=True)
        print()


class CountProgressBar:
    """Podsync-style bar for deletion/count-only operations."""
    def __init__(self, total: int, width: int = 28, prefix: str = "            "):
        self.total = max(total, 1)
        self.width = width
        self.prefix = prefix
        self.current = 0

    def update(self, current: int) -> None:
        self.current = current
        fraction = min(self.current / self.total, 1.0)
        filled = min(int(self.width * fraction), self.width)
        bar = "█" * filled + "░" * (self.width - filled)
        sys.stdout.write(
            f"\r{self.prefix}[{bar}] {fraction * 100:5.1f}%  "
            f"{self.current} / {self.total} files"
        )
        sys.stdout.flush()

    def finish(self) -> None:
        self.update(self.total)
        print()


def safe_copy(src: Path, dst: Path, rel: str, number: int, total_files: int) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    temp = dst.with_name(dst.name + f".musicsync-part-{os.getpid()}")

    print(f"  [{number}/{total_files}] {rel}")
    progress = ProgressBar(src.stat().st_size)

    try:
        if temp.exists():
            temp.unlink()

        # MTP/GVFS can buffer writes very aggressively. If we only update the
        # bar after write(), the whole file can appear to copy instantly and
        # then stall on close/fsync. Flush each chunk before advancing the bar
        # so progress follows the actual device transfer much more closely.
        with src.open("rb") as rf, temp.open("wb", buffering=0) as wf:
            copy_stream(rf, wf, progress=lambda count: progress.update(count - progress.current, force=True),
                        tolerate_flush_errors=True)

        progress.finish()

        if temp.stat().st_size != src.stat().st_size:
            raise IOError(f"size verification failed for {rel}")

        try:
            os.replace(temp, dst)
        except OSError:
            if dst.exists():
                dst.unlink()
            temp.rename(dst)

    except Exception:
        # Ensure a partially drawn progress bar does not swallow the error line.
        if progress.current:
            print()
        try:
            if temp.exists():
                temp.unlink()
        except OSError:
            pass
        raise


def prune_empty_dirs(root: Path) -> int:
    removed = 0
    dirs = [p for p in root.rglob("*") if p.is_dir()]
    for d in sorted(dirs, key=lambda p: len(p.parts), reverse=True):
        try:
            if not any(d.iterdir()):
                d.rmdir()
                removed += 1
        except OSError:
            pass
    return removed


def confirm(prompt: str) -> bool:
    ans = input(prompt + " [Y/n]: ").strip().lower()
    return ans in ("", "y", "yes")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Mirror ~/Music/Library to the mounted HiBy /Music folder."
    )
    ap.add_argument("--source", type=Path, default=SOURCE_DEFAULT)
    ap.add_argument("--device-music", type=Path)
    ap.add_argument("--state-db", type=Path, default=STATE_DB_DEFAULT)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--verify", "--verify-hash", action="store_true",
        help=("compare SHA-256 hashes of local and device audio, including same-sized "
              "files; also verify copies after transfer (slower over MTP)")
    )
    ap.add_argument("--yes", action="store_true")
    ap.add_argument(
        "--allow-empty", action="store_true",
        help="allow an empty local library to remove all managed audio from the HiBy"
    )
    args = ap.parse_args()

    source = args.source.expanduser().resolve()
    state_db = args.state_db.expanduser()

    if not source.is_dir():
        print(f"ERROR: local library does not exist: {source}", file=sys.stderr)
        return 2

    try:
        device = (
            args.device_music.expanduser().resolve()
            if args.device_music
            else autodetect_device_music().resolve()
        )
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    if not device.is_dir():
        print(f"ERROR: device Music folder does not exist: {device}", file=sys.stderr)
        return 2

    if source == device:
        print("ERROR: source and device paths are the same.", file=sys.stderr)
        return 2

    print(f"Local library: {source}")
    print(f"HiBy Music:    {device}")
    print(f"State DB:      {state_db}")
    print(f"Compare mode:  {'SHA-256 both sides' if args.verify else 'size + local change cache'}\n")

    print("Scanning local library...")
    local = audio_files(source)
    print(f"  {len(local)} audio files")

    print("Scanning HiBy...")
    remote = audio_files(device)
    print(f"  {len(remote)} audio files\n")

    if not local and remote and not args.allow_empty:
        print(
            "REFUSING TO SYNC: the local library is empty while the HiBy is not.\n"
            "Use --allow-empty only if deleting all device music is intentional.",
            file=sys.stderr
        )
        return 3

    con = init_db(state_db)
    to_copy = []
    unchanged = []

    print("Comparing libraries...")
    # Full device hashing is opt-in: an MTP read can be far slower than a local stat.
    compare_progress = CountProgressBar(len(local), prefix="  Verifying  ") if args.verify and local else None
    try:
        for i, (rel, src) in enumerate(sorted(local.items()), start=1):
            dst = device / Path(rel)
            digest = local_hash(con, rel, src)
            state = con.execute(
                "SELECT synced_sha256 FROM sync_state WHERE relpath=?", (rel,)
            ).fetchone()
            previous_digest = state[0] if state else None

            remote_size = remote[rel].stat().st_size if rel in remote else None
            remote_digest = sha256_file(remote[rel]) if args.verify and remote_size == src.stat().st_size else None
            if needs_copy(src.stat().st_size, remote_size, digest, previous_digest,
                          verify=args.verify, remote_digest=remote_digest):
                to_copy.append((rel, src, dst, digest))
            else:
                unchanged.append(rel)
                if not args.dry_run:
                    update_state(con, rel, src, digest)

            if compare_progress:
                compare_progress.update(i)
            elif i % 250 == 0:
                print(f"  compared {i}/{len(local)}...")
    except (OSError, ValueError) as exc:
        if compare_progress:
            print()
        print(f"ERROR comparing libraries: {exc}", file=sys.stderr)
        print("Sync aborted; no device files were modified.", file=sys.stderr)
        con.close()
        return 6
    if compare_progress:
        compare_progress.finish()

    to_delete = sorted(set(remote) - set(local))
    copy_bytes = sum(src.stat().st_size for _, src, _, _ in to_copy)
    delete_bytes = sum(
        remote[rel].stat().st_size for rel in to_delete if remote[rel].exists()
    )

    print("\nSync plan")
    print("---------")
    print(f"Unchanged:   {len(unchanged)}")
    print(f"Copy/update: {len(to_copy)} files ({human_bytes(copy_bytes)})")
    print(f"Delete:      {len(to_delete)} files ({human_bytes(delete_bytes)})")

    if to_copy:
        print("\nFiles to copy/update:")
        for rel, *_ in to_copy[:15]:
            print(f"  + {rel}")
        if len(to_copy) > 15:
            print(f"  ... and {len(to_copy)-15} more")

    if to_delete:
        print("\nFiles to delete from HiBy:")
        for rel in to_delete[:15]:
            print(f"  - {rel}")
        if len(to_delete) > 15:
            print(f"  ... and {len(to_delete)-15} more")

    if not to_copy and not to_delete:
        if not args.dry_run:
            remove_state_not_local(con, set(local))
            con.commit()
        print("\nHiBy is already in sync.")
        return 0

    if args.dry_run:
        print("\nDry run only; no files changed.")
        return 0

    if not args.yes and not confirm("\nApply this sync?"):
        print("Cancelled. Nothing changed.")
        return 0

    # Copy everything first. A failed copy prevents the deletion phase.
    if to_copy:
        print("\nCopying new/changed music...")
        try:
            for number, (rel, src, dst, digest) in enumerate(to_copy, start=1):
                safe_copy(src, dst, rel, number, len(to_copy))
                if args.verify:
                    # Avoid updating the state database for incomplete/corrupt
                    # device transfers; deletions below must not run on failure.
                    if sha256_file(dst) != digest:
                        raise IOError(f"SHA-256 verification FAILED after copying {rel}")
                    print("            SHA-256 verified")
                update_state(con, rel, src, digest)
                con.commit()
        except KeyboardInterrupt:
            print("\nCancelled during copy. No deletion pass was performed.", file=sys.stderr)
            return 130
        except Exception as e:
            print(f"\nERROR during copy: {e}", file=sys.stderr)
            print("Deletion pass was NOT performed.", file=sys.stderr)
            return 4

    if to_delete:
        print(f"\nDeleting {len(to_delete)} obsolete audio files from HiBy...")
        progress = CountProgressBar(len(to_delete))
        for i, rel in enumerate(to_delete, start=1):
            try:
                remote[rel].unlink()
            except Exception as e:
                print(f"\nERROR deleting {remote[rel]}: {e}", file=sys.stderr)
                return 5
            progress.update(i)
        progress.finish()

    removed_dirs = prune_empty_dirs(device)
    remove_state_not_local(con, set(local))

    for rel in unchanged:
        src = local[rel]
        update_state(con, rel, src, local_hash(con, rel, src))

    con.commit()

    print("\nSync complete.")
    print(f"  Copied/updated: {len(to_copy)}")
    print(f"  Deleted:        {len(to_delete)}")
    print(f"  Empty folders:  {removed_dirs} removed")
    print(f"  Device tracks:  {len(local)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
