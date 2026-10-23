#!/usr/bin/env python3
"""Import an inbox of music into the sanitized local HiBy library.

Default workflow:
    ~/Music/Nicotine
        -> hiby-music-sanitize (interactive MusicBrainz review)
        -> temporary staging tree
        -> ~/HiBy-Music
        -> empty ~/Music/Nicotine only after a successful verified import

The source inbox is never deleted if sanitizing, conflict resolution, copying, or
verification fails.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

AUDIO_EXTENSIONS = {
    ".mp3", ".flac", ".m4a", ".mp4", ".aac", ".ogg", ".oga", ".opus",
    ".wav", ".wave", ".aif", ".aiff", ".ape", ".wma", ".wv", ".dsf", ".dff",
}


def parse_args() -> argparse.Namespace:
    home = Path.home()
    p = argparse.ArgumentParser(
        description="Sanitize ~/Music/Nicotine, merge it into ~/HiBy-Music, then empty the inbox."
    )
    p.add_argument(
        "--inbox",
        type=Path,
        default=home / "Music" / "Nicotine",
        help="incoming music folder (default: ~/Music/Nicotine)",
    )
    p.add_argument(
        "--library",
        type=Path,
        default=home / "HiBy-Music",
        help="sanitized local library (default: ~/HiBy-Music)",
    )
    p.add_argument(
        "--sanitizer",
        type=Path,
        default=None,
        help="override the packaged sanitizer with an executable path",
    )
    p.add_argument(
        "--metadata-cache",
        type=Path,
        default=home / "Music" / ".hiby-metadata-cache.json",
        help="persistent sanitizer correction cache",
    )
    p.add_argument(
        "--lookup-cache",
        type=Path,
        default=home / "Music" / "metadata-cache" / "musicbrainz.sqlite3",
        help="persistent MusicBrainz lookup cache",
    )
    p.add_argument(
        "--no-online-review",
        action="store_true",
        help="run sanitizer without interactive MusicBrainz review",
    )
    p.add_argument(
        "--online-art-script",
        type=Path,
        default=None,
        help="override the packaged artwork helper with an executable path",
    )
    p.add_argument(
        "--no-online-art",
        action="store_true",
        help="skip online artwork searches for missing covers",
    )
    p.add_argument(
        "--keep-inbox",
        action="store_true",
        help="do not delete the inbox after a successful import",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="pass --verbose to the sanitizer and show individual imports",
    )
    return p.parse_args()


def audio_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(
        (p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS),
        key=lambda p: str(p).casefold(),
    )


def sha256(path: Path, chunk_size: int = 4 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


def files_identical(a: Path, b: Path) -> bool:
    try:
        if a.stat().st_size != b.stat().st_size:
            return False
    except OSError:
        return False
    return sha256(a) == sha256(b)


def resolve_conflicts(staging: Path, library: Path, staged_files: list[Path]) -> dict[Path, str] | None:
    """Return per-file action: copy, replace, or duplicate. None means abort."""
    actions: dict[Path, str] = {}
    conflicts: list[tuple[Path, Path]] = []

    for src in staged_files:
        rel = src.relative_to(staging)
        dst = library / rel
        if not dst.exists():
            actions[src] = "copy"
        elif files_identical(src, dst):
            actions[src] = "duplicate"
        else:
            conflicts.append((src, dst))

    if not conflicts:
        return actions

    print(f"\n{len(conflicts)} library path conflict(s) need a decision.")
    print("A conflict means the sanitized incoming track has the same library path")
    print("as an existing file, but the bytes are different.\n")

    for i, (src, dst) in enumerate(conflicts, start=1):
        rel = src.relative_to(staging)
        print(f"Conflict {i}/{len(conflicts)}: {rel}")
        print(f"  Existing: {dst}")
        print("  [r] replace the existing library file")
        print("  [s] keep the existing file and discard this incoming copy")
        print("  [a] abort the entire import and keep the Nicotine inbox")
        while True:
            answer = input("Choice [a]: ").strip().casefold()
            if answer in {"", "a", "abort"}:
                return None
            if answer in {"r", "replace"}:
                actions[src] = "replace"
                break
            if answer in {"s", "skip"}:
                actions[src] = "duplicate"
                break
            print("Please enter r, s, or a.")
        print()

    return actions


def atomic_verified_copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    # Put the temporary file beside the final file so os.replace() is atomic.
    tmp = dst.with_name(f".{dst.name}.musicimport-part-{os.getpid()}")
    try:
        shutil.copy2(src, tmp)
        if not files_identical(src, tmp):
            raise OSError(f"verification failed after copying {src} -> {dst}")
        os.replace(tmp, dst)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def empty_directory(root: Path) -> None:
    """Remove everything inside root, but keep root itself."""
    for child in root.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()


def main() -> int:
    args = parse_args()
    inbox = args.inbox.expanduser().resolve()
    library = args.library.expanduser().resolve(strict=False)
    sanitizer = args.sanitizer.expanduser().resolve(strict=False) if args.sanitizer else None
    metadata_cache = args.metadata_cache.expanduser().resolve(strict=False)
    lookup_cache = args.lookup_cache.expanduser().resolve(strict=False)
    online_art_script = args.online_art_script.expanduser().resolve(strict=False) if args.online_art_script else None

    if not inbox.is_dir():
        print(f"Inbox does not exist: {inbox}", file=sys.stderr)
        return 2
    if sanitizer is not None and not sanitizer.is_file():
        print(f"Sanitizer not found: {sanitizer}", file=sys.stderr)
        print("Install hiby-music-sanitize in ~/.local/bin first.", file=sys.stderr)
        return 2
    if not args.no_online_art and online_art_script is not None and not online_art_script.is_file():
        print(f"Online art helper missing: {online_art_script}", file=sys.stderr)
        print("Install hiby-online-art or use --no-online-art.", file=sys.stderr)
        return 2
    if inbox == library:
        print("Inbox and library cannot be the same directory.", file=sys.stderr)
        return 2

    incoming = audio_files(inbox)
    if not incoming:
        print(f"No supported audio files found in {inbox}")
        return 0

    metadata_cache.parent.mkdir(parents=True, exist_ok=True)
    lookup_cache.parent.mkdir(parents=True, exist_ok=True)
    library.mkdir(parents=True, exist_ok=True)

    staging_parent = Path.home() / "Music" / "metadata-cache" / "import-staging"
    staging_parent.mkdir(parents=True, exist_ok=True)

    print("HiBy music import")
    print("-----------------")
    print(f"Inbox:        {inbox}")
    print(f"Library:      {library}")
    print(f"Incoming:     {len(incoming)} track(s)")
    print(f"Corrections:  {metadata_cache}")
    print(f"Lookup cache: {lookup_cache}")
    print()

    with tempfile.TemporaryDirectory(prefix="import-", dir=staging_parent) as tmpdir:
        staging = Path(tmpdir) / "sanitized"

        sanitizer_cmd = ([str(sanitizer)] if sanitizer is not None else
                         [sys.executable, "-m", "hiby_music_tools.sanitize"])
        cmd = [
            *sanitizer_cmd,
            str(inbox),
            str(staging),
            "--metadata-cache", str(metadata_cache),
            "--lookup-cache", str(lookup_cache),
        ]
        if not args.no_online_review:
            cmd.append("--online-review")
        if args.verbose:
            cmd.append("--verbose")

        helper_env = os.environ.copy()
        package_root = str(Path(__file__).resolve().parent.parent)
        helper_env["PYTHONPATH"] = os.pathsep.join(
            filter(None, [package_root, helper_env.get("PYTHONPATH", "")])
        )

        print("Step 1/3: Sanitizing incoming music...\n")
        result = subprocess.run(cmd, env=helper_env)
        if result.returncode != 0:
            print("\nSanitizer did not finish successfully.", file=sys.stderr)
            print("Nothing was deleted from the Nicotine inbox.", file=sys.stderr)
            return result.returncode or 1

        if not args.no_online_art:
            print("\nStep 1b/3: Finding missing album artwork online...\n")
            art_cmd = ([str(online_art_script)] if online_art_script is not None else
                       [sys.executable, "-m", "hiby_music_tools.online_art"]) + [str(staging)]
            result = subprocess.run(art_cmd, env=helper_env)
            if result.returncode != 0:
                print("\nOnline artwork review did not finish successfully.", file=sys.stderr)
                print("Nothing was deleted from the Nicotine inbox.", file=sys.stderr)
                return result.returncode or 1

        staged = audio_files(staging)
        if len(staged) != len(incoming):
            print("\nSafety check failed: sanitizer input/output track counts differ.", file=sys.stderr)
            print(f"Incoming audio:  {len(incoming)}", file=sys.stderr)
            print(f"Sanitized audio: {len(staged)}", file=sys.stderr)
            print("Nothing was deleted from the Nicotine inbox.", file=sys.stderr)
            return 1

        print("\nStep 2/3: Checking and merging into the local library...")
        actions = resolve_conflicts(staging, library, staged)
        if actions is None:
            print("\nImport aborted. Nothing was deleted from the Nicotine inbox.")
            return 1

        copied = 0
        replaced = 0
        already_present = 0
        try:
            for index, src in enumerate(staged, start=1):
                rel = src.relative_to(staging)
                dst = library / rel
                action = actions[src]

                if action == "duplicate":
                    already_present += 1
                else:
                    atomic_verified_copy(src, dst)
                    if action == "replace":
                        replaced += 1
                    else:
                        copied += 1

                if args.verbose:
                    print(f"[{index}/{len(staged)}] {action:9} {rel}")
                elif index == 1 or index == len(staged) or index % 25 == 0:
                    print(f"\rMerging {index}/{len(staged)}...", end="", flush=True)
        except Exception as exc:
            print(f"\n\nLibrary merge failed: {exc}", file=sys.stderr)
            print("Nothing was deleted from the Nicotine inbox.", file=sys.stderr)
            return 1

        if not args.verbose:
            print()

        # Verify every staged destination that should now be represented in the library.
        print("Verifying library copies...")
        for src in staged:
            rel = src.relative_to(staging)
            dst = library / rel
            action = actions[src]
            if action == "duplicate":
                # For explicit skip, the existing file may intentionally differ.
                # Exact duplicates were also classified this way, so existence is the
                # required postcondition for both cases.
                if not dst.is_file():
                    print(f"Verification failed; missing library file: {dst}", file=sys.stderr)
                    print("Nothing was deleted from the Nicotine inbox.", file=sys.stderr)
                    return 1
            elif not files_identical(src, dst):
                print(f"Verification failed: {dst}", file=sys.stderr)
                print("Nothing was deleted from the Nicotine inbox.", file=sys.stderr)
                return 1

        print("\nStep 3/3: Finalizing import...")
        if args.keep_inbox:
            print("--keep-inbox was used; source files were left in place.")
        else:
            try:
                empty_directory(inbox)
            except Exception as exc:
                print(f"Library import succeeded, but the inbox could not be emptied: {exc}", file=sys.stderr)
                return 1
            print(f"Emptied: {inbox}")

        print("\nImport complete")
        print("---------------")
        print(f"New tracks:       {copied}")
        print(f"Replaced tracks:  {replaced}")
        print(f"Already present:  {already_present}")
        print(f"Library tracks:   {len(audio_files(library))}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
