# Changelog

## 0.3.0 — 2026-10-23

- Keep full content verification optional; normal device sync uses scoped file
  fingerprints and verifies transferred files without rereading unchanged audio.
- Handle unambiguous case/Unicode filename differences without unsafe Add/Remove
  pairs, retaining the device filename spelling.

- Connect Device sync through explicit refreshed-plan and removal confirmation.
- Add measured streaming/native-GIO transfers, per-file/overall progress, activity,
  cancellation, recovery logs, retry and SHA-256 verification of transfers.
- Stage and verify updates before publication, preserve recovery originals and block
  removals after failure, stale/incomplete scans or disconnection.
- Keep CLI behavior while sharing its measured streaming loop with the GUI backend.

- Add a read-only Device sync dashboard with live Linux USB/mount validation,
  manual storage selection, progress/cancellation and lightweight disconnect checks.
- Reuse CLI size/hash decisions while reporting unverified same-size matches,
  collisions, empty-source protection and explicit removal previews.
- Preserve CLI transfer behavior while adding guarded GUI execution.

- Add mouse Back/Forward UI history and compact green source-rate/depth in the player.
- Explain how to repair a missing MPRIS dependency in source-checkout launches.

- Add Audio Settings with backend device discovery, saved selection, fallback,
  and separate source/decoder/audio-API diagnostics.
- Add a single MPRIS media session and native gapless FLAC/MP3 continuity tests.
- Add persistent local playlists, song/album membership, ordering, Play and Shuffle.
- Preserve playback during metadata saves confirmed outside the native playlist.

- Anchor album menus to their button and keep Apple no-result errors inline and transient.
- Add confirmed permanent song/album deletion with playback release and index/queue cleanup.

- Add focused Library track/album/artist metadata editing and explicit save previews.
- Extend the shared tag writer for genre and artwork preservation/optimization.
- Add opt-in reorganization, collision checks, durable backups/journaling, and
  encoded/decoded audio verification through FFmpeg/ffprobe.
- Release playback files before saving and repair index/queue references afterward.

## 0.2.0 — 2026-10-23

- Add the native PySide6/QML desktop application and shared backend modules.
- Add background Import scanning, album/track review, Apple artwork search,
  import preview, verified importing, and selective verified source cleanup.
- Add the read-only SQLite Library index with incremental refresh/rebuild,
  artwork caching, album/artist/song browsing, search, and sorting.
- Add asynchronous mpv playback, an independent queue, shuffle/repeat,
  seeking, saved state without autoplay, and the persistent player bar.
- Refine responsive layouts, album scrolling, row selection/playback controls,
  active-track indicators, keyboard navigation, and artist/album links.
- Open Library by default and increase native mouse-wheel scrolling speed.
- Extend installation, documentation, and temporary-fixture regression tests.
- Preserve existing CLI and device synchronization behavior.

Exclusive-output configuration and playback history remain future work. Device synchronization remains available
through the CLI; the GUI provides validated comparison and confirmed synchronization.
