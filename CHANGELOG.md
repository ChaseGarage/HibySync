# Changelog

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

Library metadata editing, MPRIS/global media keys, and advanced audio-output
configuration remain future work. Device synchronization remains available
through the CLI; its GUI page is a placeholder.
