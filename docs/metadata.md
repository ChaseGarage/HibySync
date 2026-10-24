# Library metadata management

## Launch and entry points

Install the existing GUI dependencies plus FFmpeg/ffprobe:

```sh
sudo pacman -S mpv ffmpeg pyside6 python-pillow python-mutagen python-setuptools python-pip
./install.sh --gui
hibysync
```

`./hibysync` runs directly from the checkout. These commands work in Fish.
Library indexing and playback work without the metadata verification tools;
saves require both `ffmpeg` and `ffprobe`. The installer reports missing external
dependencies without running a package manager.

Use the song context menu for **Edit song**, **Change artwork**, or **Reorganize
file**. The album header's menu offers the corresponding album operations.
Open an artist's albums and choose **Edit artist** for corrections across their
catalog. The normal browser contains no editing forms. The old `--widgets`
frontend remains Import-only; metadata management uses QML.

## Pending changes and selection

Opening an editor rereads the audio files, using the shared metadata/artwork
helpers rather than treating SQLite as authoritative. Original values are kept
separate from editable proposals. The editor supports title, track artist, album
artist, album, four-digit release year, track/disc numbers (including number/total),
genre, and cover artwork. Changed fields show their original values; the preview
lists complete original → proposed changes. Unrelated tags are not intentionally
changed. Mutagen can normalize tag-container representations, including ID3
versions; exact preservation of every vendor-specific tag representation is not
guaranteed.

Album and artist editors provide per-file selection and individual track edits.
The selection toolbar selects all, clears selection, or selects the current
track's indexed album in the artist editor. **Apply album fields** copies album
artist, album title, year, and genre to selected files, preserving individual
track artists, titles, and numbers. A field edit alone affects the current track.

Artist correction explicitly selects track artist and/or album artist. It changes
only selected files whose original value matches the chosen artist (using the
index's Unicode case folding). It does not guess similarly named artists. If the
proposed name already exists, the preview warns that the selected tracks will be
grouped under that name. Saving this reviewed proposal is the confirmation; no
unselected artist files are rewritten.

**Preview changes** reads and validates files but performs no music writes. It
shows the number that will change, source/destination paths, tag/artwork changes,
unchanged/skipped files, and blocking errors. Only **Save N files** publishes
changes. Discard/Close leaves pending edits unapplied. A valid subset can save
while blocked files remain unchanged and are reported as failures.

## Artwork

The Artwork tab lists embedded images and local JPEG/PNG folder images, including
common parent album folders for multi-disc releases. It also supports a manual
image chooser and the existing Apple search/download/cache service. Online results
are never selected automatically. Candidates show original dimensions and origin.
Preview opens the full image with Fit/Actual size viewing; thumbnails remain small.

Selecting a cover remains pending until Save. **Use for track** affects the current
track; **Use for selected files** applies to the chosen album/artist subset.
By default JPEG/PNG data and resolution are preserved exactly, with no automatic
downscaling/recompression. **Optimize for HiBy** explicitly uses the existing
600px JPEG, quality-88 conversion. This can also be requested for an embedded cover.
Original external images are never changed.
An empty Apple search (including matches whose covers could not be downloaded)
shows **No matches found** in red next to Apple artwork for 3.5 seconds, then
clears automatically. Existing cover choices stay intact. Search progress stays
inline so it does not resize the editor.

Replacement updates front/unspecified covers and preserves typed back/booklet
pictures where the format supports them; MP4 retains additional `covr` pictures.
Ordinary metadata edits do not run the Import artwork sanitizer. Artwork sources
are signature-checked and frozen before a batch, so selecting a cover embedded
in the first edited track does not invalidate subsequent album writes. Full-size
previews have the same 32 MiB source-byte limit as the shared preview utilities.

## File organization and playback

Metadata edits keep existing filenames and directories by default.
**Reorganize** is an explicit separate action/checkbox and uses the sanitizer's
shared naming rules, including album-artist preference, missing-author fallback,
missing-album naming, and omitted unknown years. The preview shows old/new paths.
Existing destinations and duplicate proposed paths block a move; unrelated files
are never replaced. Conflicting titles can be corrected or excluded before saving.
Already-organized missing-author paths do not gain repeated prefix folders.
As with Import, publishing a new path requires filesystem hard-link support
(available on typical local Linux filesystems). Unsupported targets fail safely
and retain their source files.

Only selected audio files move. Folder artwork, other source files, and empty
folders remain; choose to embed a folder cover if it should travel with a song.
Moves publish a verified copy before removing an unchanged original. Successful
moves retain the track ID in SQLite and update every matching queue instance.
Metadata changes update the browser and cached queue labels/artwork. Logical album
or artist IDs can change when identifying metadata changes, as with a normal scan.

Save releases mpv before changing a file that could be referenced by its native
playlist, waiting for the process to exit. The queue stays intact and Play resumes
explicitly afterward; saving never starts playback. When the native queue is
settled and all source/destination paths are outside it, unrelated edits leave
playback running. Transport/queue changes are held during maintenance.
Other applications' playback/file handles are not controlled by HibySync.

## Verification, cancellation, and recovery

For each selected file, execution:

1. Rechecks the original signature and managed path (rejecting symlinks/redirects).
2. Creates a verified working copy outside the music library.
3. Uses the existing shared Mutagen tag writer and artwork embedding utility.
4. Verifies tag/artwork read-back, encoded audio packet hashes, decoded float64
   sample hashes, and codec/rate/channel/bit-depth parameters against the original.
   Verification decodes to hashes, never to a rewritten music file. Vorbis comment
   headers are excluded from the codec-extra hash because they contain changed tags;
   decoded sample verification still covers the resulting audio.
5. Makes a durable original backup and writes a journal intent.
6. Publishes through the existing sibling-temporary/atomic copy service, verifies
   the final bytes, and flushes the published file/directory before completing a move.
7. Reconciles the index and repairs queue references for successful files.

No file is re-encoded to save tags. MP3, FLAC, WAV, M4A/AAC, ALAC, Ogg Vorbis,
Opus, and AIFF are exercised with fixtures. Other indexed formats, including raw
AAC without supported writable tags, remain explicitly blocked for metadata writes.

Cancellation is cooperative during staging and verification. Publication/removal
completes for the current file, then later files remain unprocessed. The final
index reconciliation still completes after cancellation so successful changes are
visible. The result lists saved, failed, skipped/unchanged, and unprocessed files.
A batch is not an all-or-nothing transaction; verified earlier saves remain.

Recovery runs live at the configured metadata cache's
`library/maintenance/run-<uuid>/`, normally
`~/.cache/hiby-music-tools/library/maintenance/run-<uuid>/`. They contain full
original files and `journal.jsonl` with original/new paths and prepared/published/
committed/failed phases. The result screen shows each original backup path and
the run directory. Staging copies are removed; recovery originals/journals are
retained until manually removed. They consume disk space and should be kept until
the changes have been reviewed.

For recovery, stop playback and inspect the journal and original backup. Preserve
any newer external edits separately before restoring a backup to its recorded old
path. For a completed move, verify the old backup first and keep the new file until
restoration is confirmed. Then refresh the Library. There is no automatic batch
Undo or recovery-on-launch operation in this milestone; retained originals and
the journal support deliberate manual recovery after a crash. If a crash happened
after publication but before removing the source, both copies can remain.

Failures before publication leave the original unchanged. Publication failures
attempt rollback only while the published file still matches HibySync's signature;
externally changed output is not overwritten by rollback. If index refresh fails
after successful writes, results retain those successes, show the index error,
and repair queue paths from the save report; Refresh can rebuild the catalog.
Filesystem changes by another process in the final check/publication interval
cannot be made globally transactional; source/destination checks, verification,
per-file atomic publication, backups, and journaling limit that risk.

## Permanent deletion

**Delete song…** and **Delete album…** are available in their context menus.
These operations have a separate confirmation showing the exact indexed audio
paths and file count. Cancel makes no changes. Confirming bypasses Trash and
does not make a recovery copy; this differs deliberately from metadata saves.
Previously retained maintenance backups are not removed by deletion.

HibySync releases mpv first, rechecks indexed and previewed file signatures,
and removes only the confirmed audio files. Changed/recreated files, symlinks,
or access failures are retained and reported. The index and all matching queue
instances are updated for completed removals. Folder images, other files, and
directories are left alone. Cancellation stops between files; completed permanent
deletions are not rolled back. If a catalog update fails, results identify the
failure and Refresh can reconcile the remaining index.

## Tests

```sh
python -m unittest discover -s tests -p test_maintenance.py -v
python -m unittest discover -s tests -p test_metadata_gui.py -v
python -m unittest discover -s tests -p test_deletion.py -v
python -m unittest discover -s tests -p test_library_actions_gui.py -v
python -m unittest discover -s tests -v
```

Tests use temporary music libraries only. They cover real formats, audio hashes,
unrelated tags, missing tags, genre clearing, album changes, artist selection,
artwork quality/optimization, stale files/images, collisions, cancellation,
backups, index failures, stable IDs after moves, queue repair, and GUI Save gating.
Deletion tests cover confirmation/cancellation, stale or inaccessible files,
missing files, album/index cleanup, and removal of repeated queue entries.
Real-mpv/null-output integration verifies file release before saves/moves and
deletion, and playback from the repaired queue afterward. Online artwork tests use explicit
fixtures; no test needs to write the actual library or HiBy device.
