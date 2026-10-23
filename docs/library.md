# Library browser and index

Launch `./hibysync` from the checkout, or update the installed application with
`./install.sh --gui` and run `hibysync`. These commands work in Fish and Bash.
Dependencies and Wayland launch options are in the [README](../README.md).
The Library browser is part of the QML frontend; `--widgets` retains the earlier
Import review interface.

## Browsing

Library uses the same configured library path as Import (normally
`~/Music/Library`), including the Settings folder selection and `--library`
override. It never scans the incoming folder as the library automatically.
Select **Index library** initially, then **Refresh** for external changes.
Albums presents a virtualized artwork grid; Artists includes both album artists
and contributing track artists. Selecting an artist shows their albums.
Songs supports title, artist, album, year, and duration sorting. Search matches
song titles, artists, and albums using normalized Unicode case folding and
literal substring matching. It is debounced and runs against SQLite in a worker.
Album details show track numbers, disc groups, track count, and total duration.
Playback and the independent queue are documented in [playback.md](playback.md).
Library tag editing remains a future milestone.

## Storage and authority

The default database is
`~/.cache/hiby-music-tools/library/index.sqlite3`. It follows the existing
metadata-cache configuration; no second cache-path setting is introduced.
SQLite may also create adjacent `-wal` and `-shm` files. Content-addressed cover
thumbnails live in `library/artwork/` beside the database. They are PNGs bounded
to 240 pixels, with a bounded in-memory image cache. QML requests these thumbnails
rather than decoding full-resolution source covers. Unreferenced thumbnails
are currently retained; there is no cache garbage collector.

The index is disposable. Audio files and tags remain authoritative. Indexing
reads files and writes only the cache, never tags or source artwork. A database
inside the music root is rejected. Symlinks are not followed. Roots have separate
catalogs in the same database, so changing the library path does not mix them.

Stored track data includes path, original tags, track/disc numbers, duration,
format/codec, bitrate, sample rate, meaningful bit depth, artwork origin, file
size, nanosecond modification time, and scan errors. Missing technical values
remain null, displayed as a dash. Mutagen support varies by format: for example,
its Opus reader does not expose a sample rate. MP3, FLAC, WAV, M4A/ALAC/AAC,
Ogg Vorbis, Opus, and AIFF use existing supported extensions and metadata helpers.
No new runtime dependency beyond the existing GUI dependencies is required.

## Refresh and identity

Incremental refresh enumerates the root and compares filesystem identity,
size/timestamps, and folder-art signatures. Unchanged audio is not reopened.
Added/changed files are read, missing entries removed, and album/artist summaries
regrouped from stored metadata. Folder-art changes and missing thumbnails trigger
reprocessing. **Rebuild index** rereads all supported files and regenerates
thumbnails, retaining IDs where file identity still matches.

Each refresh commits atomically. SQLite WAL allows browsing the preceding
committed index while scanning. Cancellation and directory-enumeration failures
roll back the refresh, preventing accidental pruning after a partial scan.
Unreadable audio is recorded with an error rather than silently discarded.
Cancellation is cooperative between operations; a slow filesystem read must
return before cancellation completes. A cancelled run may leave harmless cached
thumbnails. The next refresh can reuse them.

Track UUIDs survive edits at the same path and unambiguous same-filesystem
renames identified by device/inode, size, and modification time. Cross-filesystem
copy-and-delete moves, ambiguous hard links, or simultaneous rename and retagging
can receive a new ID; vanished entries are still pruned, avoiding accumulation.
Album and artist IDs derive from their normalized logical identity within the
configured root. Changing identifying album metadata can change its album ID.

Grouping prefers album artist over individual track artists. Within an album
folder, a sole explicit album artist fills missing album-artist values; multiple
contributors or compilation tags can produce a **Various Artists** display
group. These are index display fallbacks, never tag corrections. Missing titles
and unknown artists retain folder context to avoid collapsing unrelated files.
Common CD/Disc/Disk/Volume subfolders collapse into their parent album and disc
numbers order the track list. Missing years use the folder group's known year
where available. Editions sharing album artist, title, and year can merge;
release-ID-based edition distinctions are not implemented. Ambiguous or unusual
folder layouts benefit from complete album-artist and disc tags.

There is no filesystem watcher. GUI imports invalidate the catalog and refresh
on the next Library visit. External tag edits or downloads require **Refresh**.
Search is not accent-insensitive or locale-specific and does not use full-text
tokenization. Queries return bounded pages (120 rows normally); Qt views recycle
delegates rather than constructing every cover or song row at once.

## Verification

Temporary-fixture tests cover metadata, compilations, multiple discs, missing
tags, corrupt files, artwork invalidation, unchanged scans, rebuilds, cancellation,
added/removed/renamed files, stable IDs, separate roots, Unicode search, sorting,
and bounded queries over 20,001 tracks. Optional FFmpeg generates real-format
fixtures for tests; it is not required by the index at runtime. Offscreen QML
tests exercise navigation, search, paging, worker responsiveness, cancellation,
and close handling. They do not modify the real library. Actual Hyprland display
scaling and graphics-driver behavior still depend on the local desktop.
