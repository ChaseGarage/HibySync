# HiBy music tools

Python command-line tools developed on CachyOS Linux for preparing a local
music library and synchronizing it to a HiBy R1.

The implementations now live in `src/hiby_music_tools/`. The four root
executables remain source-checkout launchers, and packaging provides the same
command names. Shared-module extraction and installation scripts are planned. See [the migration plan](docs/migration.md).

## Workflow

```text
~/Music/Nicotine
  -> musicimport
       -> hiby-music-sanitize -> temporary staging library
       -> hiby-online-art    -> missing covers in staging
       -> verified merge into ~/HiBy-Music

~/HiBy-Music -> musicsync -> mounted HiBy Music directory
```

`musicimport` enables interactive metadata and artwork review by default. It
calls the sanitizer and artwork modules using its own Python interpreter and
package location. Use `--sanitizer` and `--online-art-script` to explicitly
select external executables instead.

There is no separate artwork-repair executable in this checkout. The sanitizer
processes existing and folder artwork, while the online helper fills missing
embedded covers.

## Requirements and commands

Use Python 3.10 or later, Pillow, and Mutagen. On CachyOS/Arch the dependency
packages are `python-pillow` and `python-mutagen`. Optional `chafa` provides
terminal artwork previews. Network review uses MusicBrainz, Cover Art Archive,
and Apple's artwork services; the tests do not require these services.

Each executable supports `--help`. Commands can be run directly from this checkout, for example:

```sh
./hiby-music-sanitize --help
./hiby-online-art --help
./musicimport --help
./musicsync --help
```

## Package installation

For a local development environment (downloads dependencies if needed):

```sh
python -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/musicimport --help
```

For a regular installation into a chosen virtual environment, use `pip install .`
without `-e`. Do not copy the root launchers into `~/.local/bin`: they depend on
being beside this checkout's `src` directory. Installed console commands are
created by the package installer. Existing standalone installations are not
changed automatically.

## Paths and caches

| Purpose | Current default |
| --- | --- |
| Permanent library | `~/HiBy-Music` |
| Incoming downloads | `~/Music/Nicotine` |
| Import correction cache | `~/Music/.hiby-metadata-cache.json` |
| Standalone sanitizer correction cache | `SOURCE/.hiby-metadata-cache.json` |
| MusicBrainz response cache | `~/Music/metadata-cache/musicbrainz.sqlite3` |
| Artwork cache | `~/Music/metadata-cache/artwork/` |
| Import staging parent | `~/Music/metadata-cache/import-staging/` |
| Sync state | `~/Music/metadata-cache/musicsync.sqlite3` |

The intended cache root is `~/Music/metadata-cache`. The older correction-cache
defaults above are retained for now; migration must preserve approved fixes.

## Current behavior and recovery

- The sanitizer copies audio into `Artist/Year-Album/Title.ext` (without the
  year prefix when unknown). Album artist takes precedence over track artist.
  Missing artists go under `missing-author`. Name collisions get deterministic
  suffixes. It does not transcode audio.
- Selected folder covers take precedence over embedded covers. External covers
  become baseline JPEG, at most 600 pixels by default; large embedded covers
  are resized. Ambiguous or failed folder-cover processing fails the run.
  Some other metadata/artwork problems are warnings, so success does not mean
  every tag and cover was repaired.
- `--clean` deletes the sanitizer destination before rebuilding. Without it,
  existing output paths may be overwritten. The source audio is read, but the
  default correction cache can be written inside the source directory.
- A successful import **empties the entire inbox**, including non-audio files,
  unless `--keep-inbox` is supplied. Conflict choices are replace, keep existing
  and discard incoming, or abort. Keeping a differing existing file still
  permits inbox cleanup.
- Sanitizer/artwork failure, count mismatch, abort, or merge verification failure
  retains the inbox. Earlier successful library copies are not rolled back.
  Staging is temporary and removed on context exit. Inspect the library before
  retrying a partial import; conflict handling will apply again.
- Sync copies new/changed audio before deleting obsolete supported audio. A
  copy failure prevents the deletion phase. Non-audio files remain; empty
  directories are pruned. An empty source cannot clear a nonempty device unless
  `--allow-empty` is supplied. The apply prompt defaults to yes; `--yes` skips it.
- Normal sync uses sizes and cached local hashes. `--verify` hashes both sides
  and verifies transfers. Without verification, an unknown same-sized device
  difference can be treated as unchanged. Sync state is keyed by relative path,
  not device identity; separate device state files are advisable.
- Dry runs avoid library/device transfers but can create cache directories and
  SQLite databases. They are not completely free of filesystem writes.

Development and tests must use temporary libraries first. Changes to the real
library, deletion of real downloads, and device writes require explicit owner
permission.

## Baseline tests

From the repository root, with Pillow and Mutagen available:

```sh
python -m unittest discover -s tests -v
```

Baseline tests load the packaged implementations without running their entry points. They use
temporary homes, caches, inboxes, libraries, and fake device directories.
Network access is blocked during each baseline test. Audio fixtures are generated small
WAV files; no personal music or mounted device is needed. These are baseline
regressions, not certification of every format or actual MTP behavior.
Tagged path tests also use a simulated common-tag reader. The generated WAV's
ID3 tags are retained, but the current sanitizer reader does not expose them as
common tags and places that fixture under `missing-author`.

The packaging test builds and installs offline into a temporary virtual
environment using available system dependencies. It exercises all installed
help commands, both real import helpers on covered WAV audio, and verified sync
to a fake device. It needs `pip`, `setuptools>=61`, and working `venv` support.
