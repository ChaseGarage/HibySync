# HibySync presentation and review foundation

## QML presentation

The default frontend is Qt Quick/QML, using a standard decorated application
window. It has no embedded terminal or Widgets forms. Launch with `./hibysync`,
or install using `./install.sh --gui`. `./hibysync --widgets` retains the original
functional Widgets frontend for comparison and fallback. The default launcher
uses QGuiApplication and does not load Qt Widgets.

`gui/qml/Theme.qml` owns the palette, typography, spacing, and sizing tokens.
Reusable components cover text, flat buttons, navigation, inputs, artwork,
status dots, dividers, album rows, empty states, scrollbars, modals, and the
track-editing sheet. Basic Qt Quick control primitives have explicit content
and backgrounds; no native widget style or dark stylesheet drives the design.
Inter is preferred, followed by Adwaita Sans, Noto Sans, DejaVu Sans, and
Liberation Sans. QML pins the chosen family because some platform theme plugins
reset the application font after startup, including to monospace.

The compact header navigates Import, Library, and Device. The Import page shows
an empty state until scanned, then virtualized album rows and compact status
filters. Opening an album navigates to its review page. Album fields appear only
on Edit; individual track fields live in a side sheet. Artwork choices open a
separate modal; import operations have a preview, confirmation, and result page. Settings
holds folder paths instead of displaying path forms on the main screen.

Library has an independent SQLite backend, paged Qt model, asynchronous thumbnail
provider, and worker controller. Its album grid, artist browser, song list, and
album details reuse the existing design tokens. Device remains a placeholder.
See [Library indexing](library.md) for storage and refresh guarantees.

A persistent player bar and queue drawer use a separate playback controller and
asynchronous mpv JSON IPC service. Library selections are queried in workers,
independent of the currently materialized view rows. No playback policy or IPC
commands live in QML. See [playback](playback.md) for quality defaults and tests.

`gui/controller.py` adapts the existing core services and Task workers to Qt
properties, slots, and signals. It owns the pending session and delegates writes
only to explicit artwork-search/import workers. `gui/quick_models.py` provides role-based list models and an
image provider restricted to in-memory backend thumbnails. QML never reads audio
files or implements naming, metadata processing, or sync behavior. All QML
components and the singleton manifest ship as package data, verified by the
temporary installation test.

## Existing backend and conservative extraction

`importer.py` orchestrates sanitizer and artwork subprocesses, stages output,
resolves conflicts, verifies per-file copies, and normally clears the inbox.
`sanitize.py` mixes reusable metadata/artwork functions with interactive
MusicBrainz review and CLI orchestration. `online_art.py` contains both callable
candidate lookup/embedding helpers and terminal review. `sync.py` independently
mirrors supported audio, with copy-before-delete ordering and optional hashing.

The GUI does not invoke those command entry points. They can prompt, write
caches even in dry-run mode, overwrite destinations, or clear source files.
The GUI uses their read-only helpers plus the existing verified-copy, artwork
conversion, and embedding functions. Three naming
functions and the metadata value object were extracted without changing their
bodies into `core/naming.py` and `core/metadata.py`; the sanitizer reexports
them for compatibility. Both CLI and GUI use the same naming implementation.
Synchronization and importer behavior are unchanged.

## Module boundaries

- `core/interaction.py`: structured progress events, cooperative cancellation,
  and a cancellation exception. No terminal prompts or Qt types.
- `core/scan.py`: read-only discovery, native tag display, approved-cache
  proposals, grouping, and review checks.
- `core/artwork.py`: read-only embedded/folder previews, with bounded thumbnails
  and explicit image-size limits.
- `core/review.py`: original/proposed metadata, artwork references, album edits,
  skip decisions, and a read-only destination plan.
- `core/apple_art.py`: explicit Apple catalog search, using existing artwork
  lookup/download/cache helpers. Results are never automatically selected.
- `core/files.py`: regular-file signatures for stale source/artwork/destination checks.
- `core/tagging.py`: reviewed tag writes on staged copies, with read-back checks;
  native ID3/MP4 handling and reuse of the sanitizer's other easy-tag writers.
- `core/importing.py`: confirmed-plan execution, verified staging and publishing,
  conflict policies, replacement backups, selective verified source cleanup,
  and partial/cancelled results.
- `gui/workers.py`: adapts backend operations to Qt signals using a worker
  thread. Reports are throttled to avoid flooding the UI event queue.
- `gui/controller.py`: QML properties, session decisions, and worker lifecycle.
- `gui/quick_models.py`: lazy QML list models and in-memory image provider.
- `gui/quick.py`: font choice and QML engine setup.
- `library/`: Qt-independent SQLite storage, metadata/artwork extraction,
  incremental indexing, album grouping, and paged search queries.
- `gui/library_controller.py`: background indexing/query lifecycle and navigation.
- `gui/library_models.py`: paged list model and bounded thumbnail provider.
- `playback/queue.py`: independent queue entries, order, shuffle, and repeat policy.
- `playback/service.py`, `mpv.py`: replaceable service boundary and asynchronous
  QProcess/QLocalSocket implementation with native mpv playlist reconciliation.
- `playback/state.py`: atomic state persistence, called from workers.
- `library/playback.py`: complete ordered playback contexts from SQLite snapshots.
- `gui/player_controller.py`: Qt state, queue actions, audio preferences and shutdown lifecycle.
- `playback/audio.py`, `mpris.py`: conservative audio diagnostics and one threaded
  MPRIS session forwarding commands to the shared player.
- `library/playlists.py`, `gui/playlist_controller.py`: transactional persistent
  playlists, stable catalog references and background presentation tasks.
- `library/maintenance.py`, `integrity.py`: reviewed tag/path plans, shared tag
  writing, encoded/decoded audio verification, backups/journaling, and index repair.
- `gui/metadata_controller.py`, `editor_artwork.py`: focused metadata editing,
  background save/artwork tasks, and full-resolution image previews.
- `gui/qml/`: design tokens, reusable controls, and dedicated pages.
- `gui/models.py`, `details.py`, `window.py`: preserved Widgets frontend.
- `gui/app.py`: default QML / `--widgets` launcher and application lifecycle.

Long-running discovery, metadata/artwork reads, and destination existence checks
run in workers. Presentation models are updated on the UI thread. Cancellation
is checked between directories/files and preview rows. Closing during a scan
requests cancellation and waits for the current file; it never terminates a
thread while reading. Artwork download/retry cancellation is cooperative;
an active HTTP open/read may take up to the existing 25-second timeout to return.
Import cancellation completes the current safe file operation and reports
already published copies instead of hiding the partial result. The implementation follows Qt's
[thread and signal model](https://doc.qt.io/qtforpython-6/PySide6/QtCore/QThread.html).

## Read-only guarantees and review rules

Import scanning creates no directories, databases, cache entries, or edited music.
Library indexing writes only its SQLite index and thumbnail cache outside the
music library; it never writes audio files.
Source and library roots must not overlap in either direction. File/directory
symlinks are not followed. Files that cannot be read become Error entries;
directory/cache errors appear in the scan summary. Invalid artwork is reported
for review. A corrupt file does not abort the rest of the scan.

Original tags remain separate from proposals. Approved JSON corrections can
populate proposals, clearly labeled with their provenance; new online matches
are never silently applied. The CLI's easy-tag reader does not expose some
WAV/AIFF ID3 tags; the review reader also reads native frames for display and
editing, without changing the CLI reader's behavior.

Tracks group by source folder and original album name. Separate folders do not
merge just because they share an album title. Multi-disc folders currently
appear as separate groups. Metadata disagreements within a group require
review. Track totals, when present, flag missing files or duplicate numbers;
without totals, completeness is unknown. Offline checks can identify missing
or suspicious placeholder/domain artists, not reliably detect misspellings.

Ready means metadata passes existing local review checks and decodable artwork
is selected; it is not a guarantee of an online catalog match. Existing
decodable embedded artwork is preferred, even when folder artwork is available.
If no embedded cover is usable, the CLI's unambiguous folder-art selector supplies
a default. Artwork alternatives show their original resolution. Selecting art
changes only the pending reference, not the audio file. The plan retains the
existing 600-pixel/JPEG quality-88 policy during execution.

The preview uses the CLI's exact path rules, including missing-author paths,
unknown albums, absent years, and deterministic collision suffixes. Existing
destinations are flagged as conflicts, defaulting to keeping the library copy.
Users can explicitly choose replacement per source file. The preview is
invalidated on edits, skips, or path changes. Execution revalidates file
signatures, roots, and paths against the preview before copying.

## Apple artwork and confirmed imports

Apple searches use the existing `itunes_candidates`, `download_candidate`, and
`Cache` helpers. They request 1200px artwork with the existing 600/100px fallback,
display the downloaded dimensions, and share the artwork cache under
`~/.cache/hiby-music-tools/artwork`. SQLite connections are worker-local and
closed after searching. Network failures, no results, and cancellation leave
the current selected cover intact. Clicking the Apple artwork tab searches
automatically; the Refresh button repeats the lookup with the current fields.
The catalog endpoint is documented in Apple's
[Search API](https://performance-partners.apple.com/search-api).

Import requires a current preview and one final confirmation. The executor:

1. Rejects changed sources/artwork/destinations and redirected/symlink paths.
2. Prepares selected tracks under the hidden `import-staging` directory using
   the existing hash-verified copy helper. Writes reviewed metadata only to
   those copies, verifies saved tags, and applies/resizes selected artwork.
3. Compares prepared bytes to existing destinations. Identical outputs count
   as duplicates; differing existing outputs are skipped unless replacement
   was explicitly selected.
4. Hash-verifies a sibling temporary copy, publishes it, then verifies the final
   library file. New files use atomic hard-link publication without clobbering
   an unexpected destination. Unsupported filesystems fail without deleting
   source downloads. Replacements keep verified backups; a failed final check
   attempts restoration and reports the backup location.
5. Re-verifies each successful/duplicate output against the prepared bytes,
   flushes its file and parent directory entries, confirms its original has not
   changed, and removes only that incoming audio file.
6. Reports imported/replaced/duplicate/skipped/failed, unprocessed, and original
   removed/retained counts, including cleanup errors for successful copies.

The QML frontend enables `remove_sources=True`; backend callers retain the
previous copy-only behavior unless they opt in. The executor never calls
`empty_directory`. Skipped, failed, changed, and unprocessed tracks, folder
images, unrelated/new inbox files, and empty folders are retained. A source
providing embedded artwork to a pending track is kept too. Cleanup runs after
all preparation/copy work so shared embedded-art sources are available while
preparing other tracks. Individual prepared-file failures do not prevent other
valid tracks from importing. This is a per-file operation, not an atomic batch
transaction: completed copies remain after a later failure or cancellation.
Cancellation during preparation/copy skips source cleanup entirely. Once
cleanup starts, cancellation stops between originals; prior verified removals
remain removed. Cleanup failures retain originals and are reported separately.
Normal staging outputs are removed. Backups from
replacement runs remain under `import-staging/gui-*/backups` for manual recovery.
GUI manual edits are applied to library copies but not saved as new correction
cache entries. The CLI retains its original behavior, including its own source
cleanup option/default. The Widgets fallback still provides review only.

## Subsequent milestones

Remaining review work: structured MusicBrainz suggestions and approval,
manual artwork browsing, better grouping, audio duplicate analysis, and bulk
review. Existing terminal review functions must be separated from lookup and
choice handling before they can become shared workflows. Do not monkeypatch
`input()`/`print()` or run interactive CLI scripts in a hidden terminal.

Reviewed-plan execution and selective source cleanup are connected. Never
invoke the importer's whole-inbox cleanup from the GUI executor.

The test suite covers source preservation, cached proposals, missing/suspicious
tags, missing years, incomplete albums, corrupt/unreadable files, local artwork,
path conflicts, empty folders, overlapping roots, symlinks, worker cancellation,
event-loop responsiveness, metadata editing, filtering, preview, and shutdown.
Qt tests run offscreen with the QML software renderer. They exercise actual QML
controls for scanning, album/track editing, artwork selection, and skipping;
assert that hidden forms stay hidden; verify proportional text and the palette;
and check QML loading without binding errors. The existing Widgets tests also
run. Apple HTTP responses are mocked for deterministic tests; actual catalog
availability depends on the service and network. Import tests generate temporary
WAV files and, when ffmpeg is available, FLAC/MP3/M4A/Ogg/Opus/AIFF fixtures.
FFmpeg is optional for Import/indexing and required for Library-save audio verification.
A real Hyprland session is still needed to assess compositor-specific
scaling, graphics-driver behavior, and native folder pickers.
