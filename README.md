# HiBy music tools

Python command-line tools developed on CachyOS Linux for preparing a local
music library and synchronizing it to a HiBy R1.

The implementations now live in `src/hiby_music_tools/`. The four root
executables remain source-checkout launchers, and packaging provides the same
command names. Shared naming rules, review, and verified-copy services also power the
optional HibySync GUI. See [the migration plan](docs/migration.md).

## HibySync desktop application

HibySync uses Qt Quick/QML for a minimalist dark interface, backed by Python
and PySide6. It supports scanning, metadata review, Apple artwork search, and
verified imports, an indexed local Library browser, metadata management, local
playlists, and mpv-backed playback with audio settings and Linux media controls. Existing CLI commands
retain their behavior.

On CachyOS/Arch, install Qt bindings along with the existing dependencies:

```sh
sudo pacman -S mpv ffmpeg pyside6 python-dbus-next python-pillow python-mutagen python-setuptools python-pip
./install.sh --gui
hibysync
```

Alternatively, `./install.sh --gui` can download PySide6 and dbus-next into its environment.
Use `./install.sh --offline --gui` when the dependencies are already installed.
Use `--gui` again when updating an existing GUI installation. CLI-only installs
do not replace a previously installed GUI launcher.

From this checkout, this command works in **Fish** as well as Bash:

```sh
./hibysync
```

To use test folders, without touching your incoming downloads:

```sh
./hibysync --inbox /path/to/test-inbox --library /path/to/test-library
```

The application uses a consistent near-black palette and Inter when available,
with proportional sans-serif fallbacks. On Hyprland, if Qt does not select
Wayland automatically, Fish supports:

```sh
env QT_QPA_PLATFORM=wayland ./hibysync
```

The previous functional Widgets interface remains available:

```sh
./hibysync --widgets
```

Import defaults to **`~/Music/Nicotine` → `~/Music/Library`**, not the entire
`~/Music` tree. Scan reads tags and artwork in the background and shows album
rows with thumbnails and review statuses. Filter to problematic albums, or open
any album for a dedicated review. Album metadata fields appear on Edit; select a
track to open its focused editor and original tags. Apply changes to keep them
pending in memory. Album edits preserve individual track artists. Artwork
selection shows embedded/folder candidates and their original resolutions.
Selecting the **Apple artwork** tab automatically searches using the artist and
album fields. Edit either field and select **Refresh** to search again.
Results prefer 1200px images and
show the dimensions actually downloaded; choosing a result never changes tags
until import is confirmed. Existing covers are not replaced automatically.
Preview lists destinations, conflicts, skipped files, and expandable change
details. Use the folder control or the top-right settings icon to change paths.

Select **Preview import**, inspect paths and changes, then **Import files**.
Existing-file conflicts default to keeping the library copy. A conflict's
button can explicitly select replacement, with verified backups retained.
The final confirmation names the destination and replacement count. Import
stages edited copies, verifies tags/artwork, and checks SHA-256 before and after
publishing each track. The completion page reports imports, replacements,
duplicates, skips, failures, and any unprocessed files after cancellation.

**GUI imports remove successfully imported and verified duplicate audio files
from the incoming folder.** Cleanup runs after copying, rechecks each source
and library file, verifies the library bytes again, and flushes the library
file/directory entries before removing the original. Skipped, failed, changed,
and unprocessed files stay. Folder artwork, other non-audio files, new downloads,
and empty folders are left alone. An embedded-art source needed by a pending
track is also kept. The completion page reports removed/retained counts and
cleanup errors separately from copy results. Cancellation during copying skips
cleanup; cancellation during cleanup stops between originals.

The CLI's existing inbox-cleanup behavior is unchanged. GUI edits remain in memory until
applied to imported copies; they are not written back to incoming tags or
saved as a new correction-cache entry. Scanning remains read-only and offline;
Apple searches explicitly write to the existing artwork cache. MusicBrainz
suggestions and manually browsing for artwork remain planned. Device remains a
placeholder. The `--widgets` fallback remains the earlier review-only
interface. See [GUI architecture and limits](docs/gui.md).

HibySync opens in **Library**, loading the existing index without scanning music
or starting playback. Select **Index library** to scan the configured library.
Browse artwork in Albums, select an artist to see their albums, or search and
sort Songs by title, artist, album, year, and duration. Album details include
numbered tracks, disc groups, and total duration. Scanning only reads music;
it does not retag, move, or remove library files. Library writes are separate,
explicit actions through the metadata editor.

Use a song's **… → Edit song**, an album's **… → Edit album**, or **Edit artist**
on an artist page. Edit tags, select affected tracks/albums, and choose embedded,
folder, manual, or Apple artwork. Changes stay pending until **Preview changes →
Save**. Original tag values and proposed changes appear in the review. Artwork
keeps its original JPEG/PNG bytes unless HiBy optimization is explicitly selected.
**Reorganize files** is a separate opt-in with an old/new-path preview; metadata
edits alone do not rename anything. Referenced playback files are released safely
before saving; unrelated edits can preserve playback. The queue/index receive
successful metadata/path updates. After a release, press Play to resume.
FFmpeg/ffprobe verify encoded audio and decoded samples without rewriting audio.
Backups and a recovery journal remain alongside the index under
`~/.cache/hiby-music-tools/library/maintenance/`. See
[Library metadata management and recovery](docs/metadata.md).

Song and album context menus also offer **Delete…**. A separate confirmation
lists the audio files before permanent deletion. Confirmed deletion bypasses
Trash, creates no deletion backup, releases playback first, and removes successful
deletions from the Library index and every queued instance. Folder artwork and
other non-audio files stay in place.

Use a song row's leading play control to play its complete sorted/filtered
context; the same control pauses/resumes the current track without replacing
the queue. Clicking elsewhere selects the row, and double-click remains a
shortcut. The active track has a muted-green indicator. Use **Play**
and **Shuffle** on an album. Artist pages offer **Play artist**. Track menus and
album pages provide **Play next** and **Add to queue**. The persistent bottom bar
controls pause, previous/next, stop, precise seeking, volume, shuffle, repeat,
and the queue panel. Queue entries can be selected, removed, and moved earlier
or later. Music continues while browsing Import, Library, and Device.
Artist and album names underline on hover and open their Library pages when
clicked. These links also work in the player and queue; clicking the player's
song title opens its album without interrupting playback.
Library expands on wide displays and hides Album/Year columns at narrower
content widths; all sort options remain available in the header menu. Album
headers scroll naturally with their tracks. The player bar centers transport
controls on wide displays and uses a separate progress row on narrow displays.
Stop, shuffle/repeat, and volume remain accessible through its options menu.
Mouse-wheel scrolling uses a faster app-local setting (at least nine lines per
notch), while retaining native touchpad scrolling.

Playback uses a private mpv process over JSON IPC, with personal mpv settings
and scripts disabled, speed 1, and no EQ, normalization, ReplayGain, or crossfade.
No output sample rate or sample format is forced. PipeWire is preferred, with
PulseAudio/ALSA fallbacks. The system and DAC may still convert audio; HibySync
does not claim bit-perfect output. Preferences and queue state are saved at
`~/.local/state/hibysync/player.json` (following `XDG_STATE_HOME`) and restored
without autoplay. See [playback configuration, testing, and limits](docs/playback.md).

**Refresh** incrementally indexes added, changed, renamed, and removed files.
**Rebuild index** rereads all files. Both run in background workers and can be
cancelled while retaining the previous committed index. GUI imports mark the
Library for refresh on its next visit; external changes require Refresh.
The SQLite index is stored at
`~/.cache/hiby-music-tools/library/index.sqlite3`, with bounded artwork thumbnails
in the neighboring `artwork/` directory. Existing metadata-cache configuration
also controls this location. See [Library indexing and limitations](docs/library.md).

GUI staging is under `~/.cache/hiby-music-tools/import-staging/gui-*`. Ordinary
temporary outputs are removed after execution. Replacements retain their old
library versions under the run's `backups/` directory; the result screen shows
the recovery location. A batch is not rolled back when a later track fails or
is cancelled. Successfully verified copies stay in the library. New-file
publication requires hard-link support (available on typical local Linux
filesystems such as ext4/Btrfs); unsupported filesystems fail safely and retain
sources. A changed source, artwork, or destination requires a fresh review.

Library **Playlists** supports create/rename, track removal/reordering, Play and
Shuffle. Song/album context menus offer **Add to playlist…**. Playlists are saved
separately from the index at `~/.local/state/hibysync/playlists.sqlite3` (honors
`XDG_STATE_HOME`) and follow stable indexed track IDs through HibySync moves.
Unavailable entries stay visible and are skipped during playback.

**Settings → Audio** lists backend devices and shows separate source, decoded,
and audio-API output information. The normal output prefers PipeWire; no global
audio configuration is changed. MPRIS exposes controls/metadata to desktop media
clients without registering multiple sessions. Read [audio behavior and limitations](docs/playback.md)
for gapless verification, device fallback, media keys, and why these diagnostics
do not establish bit-perfect output.

## Workflow

```text
~/Music/Nicotine
  -> musicimport
       -> hiby-music-sanitize -> temporary staging library
       -> hiby-online-art    -> missing covers in staging
       -> verified merge into ~/Music/Library

~/Music/Library -> musicsync -> mounted HiBy Music directory
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

Install or update the commands in `~/.local/bin`:

```sh
./install.sh
```

The installer creates a fresh environment under
`~/.local/share/hiby-music-tools/releases/`, installs a snapshot of this checkout,
checks all four help commands, then links them into `~/.local/bin`. Previous
commands are saved under `~/.local/share/hiby-music-tools/backups/`. Old
environments remain so backed-up links still work. Re-run after code changes.

On CachyOS the environment reuses available distro Python packages. Missing
runtime dependencies are installed into the environment by pip. Python's `venv`,
pip, and `setuptools>=61` must be available. Use `./install.sh --offline` to
forbid package index access when dependencies are already present. No `sudo`
is needed. The installer never moves music or metadata; perform the
[manual moves](docs/manual-moves.md) before importing or syncing.

For a local development environment (downloads dependencies if needed):

```sh
python -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/musicimport --help
```

For a regular installation into a chosen virtual environment, use `pip install .`
without `-e`. Do not copy the root launchers into `~/.local/bin`: they depend on
being beside this checkout's `src` directory. Installed console commands are
created by the package installer. Existing standalone installations are replaced
only when running `install.sh`.

## Paths and caches

| Purpose | Current default |
| --- | --- |
| Permanent library | `~/Music/Library` |
| Incoming downloads | `~/Music/Nicotine` |
| Import correction cache | `~/.cache/hiby-music-tools/corrections.json` |
| Standalone sanitizer correction cache | `~/.cache/hiby-music-tools/corrections.json` |
| MusicBrainz response cache | `~/.cache/hiby-music-tools/musicbrainz.sqlite3` |
| Artwork cache | `~/.cache/hiby-music-tools/artwork/` |
| Import staging parent | `~/.cache/hiby-music-tools/import-staging/` |
| Sync state | `~/.cache/hiby-music-tools/musicsync.sqlite3` |

All tools now default to `~/.cache/hiby-music-tools` for metadata and staging.
Existing data is not relocated automatically. See [manual moves](docs/manual-moves.md)
before using these defaults. CLI path overrides still take precedence.
The correction JSON contains approved decisions; keep it when clearing caches.

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
  correction cache is stored separately under the hidden metadata directory.
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

GUI tests use Qt's offscreen platform and temporary fixtures. QML tests use the
software renderer, exercise actual controls, check proportional typography and
progressive disclosure, and cover worker cancellation and packaged QML assets.
The previous Widgets frontend also retains its integration tests. Install the
GUI extra or distro `pyside6` to run them; otherwise they are reported as skipped.
