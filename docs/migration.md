# Incremental migration

Preserve the original command names, CLI options, naming rules, cache schemas,
review decisions, exit statuses, and transfer order while restructuring.
Behavior changes should be separate, reviewed changes with regression tests.

1. **Complete:** Document the baseline and add temporary-library characterization tests.
   Extend coverage for cache compatibility, network failures, artwork formats,
   and interrupted transfers as those areas are extracted.
2. **Complete:** Add `pyproject.toml` and a `src/hiby_music_tools/` package with console entry
   points for all four commands. Initially move as little logic as possible.
   Keep the subprocess workflow, with helpers resolved to the same install.
   Console entry points and root source launchers are verified by baseline and
   temporary installation tests.
3. Extract path configuration and hashing first, then metadata, artwork,
   MusicBrainz, and cache helpers. Preserve per-command supported formats and
   distinct local-copy versus MTP-copy behavior until explicitly reconciled.
4. Consolidate caches under `~/Music/metadata-cache`, with explicit CLI overrides
   and compatibility for existing correction caches. Do not silently relocate
   or overwrite approved corrections.
5. Add isolated user installation, development setup, uninstall support, and CI
   that tests both source and installed commands. Installation and removal must
   leave libraries, downloads, caches, and devices alone.

## Follow-up behavior decisions

Keep these separate from mechanical extraction:

- Explicit source-cleanup consent and handling downloads arriving during import.
- Ancestor/descendant and symlink guards for source/destination paths.
- Case-insensitive FAT/exFAT name collisions.
- Whether dry runs should avoid even cache initialization.
- Sync state scoped to source/device identity and first-sync hash guarantees.
- Batch import recovery and MTP replacement failures. The current MTP fallback
  may unlink an existing destination before renaming its replacement.

## Baseline reference

The original scripts are recorded in commit `ebb760b` (Initial working HiBy
music tools). No history rewrite or script refactor is required for this stage.
