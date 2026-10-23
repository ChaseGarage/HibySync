# Manual moves for the new defaults

Close running import, sanitizer, artwork, and sync commands before moving data.
These are instructions only; the project does not move or discover old data.
Use the updated source commands or reinstall the updated package afterward.

| Existing location | New location |
| --- | --- |
| `~/HiBy-Music` | `~/Music/Library` |
| `~/Music/metadata-cache` | `~/.cache/hiby-music-tools` |
| `~/Music/.hiby-metadata-cache.json` | `~/.cache/hiby-music-tools/corrections.json` |

Move the **contents** of an old directory into the new location if the new
directory already exists; do not accidentally nest `HiBy-Music` or
`metadata-cache` inside it. Inspect existing destination files before replacing
anything. The metadata-directory move carries these paths together:

- `musicbrainz.sqlite3` (and any SQLite sidecar files)
- `musicsync.sqlite3` (and any SQLite sidecar files)
- `artwork/`, including its lookup database and downloaded images
- `import-staging/`, if present (normally empty after a completed import)

Standalone sanitizer runs previously defaulted to
`SOURCE/.hiby-metadata-cache.json`. If you have such files, inspect them before
choosing the new shared `corrections.json`. Do not overwrite one correction
cache with another blindly: they can contain different approved decisions.
Keep separate files and select one using `--metadata-cache` if necessary;
this change does not merge JSON caches. Correction entries include source
relative path, size, and timestamp, so not every entry applies to every source.

`~/Music/Nicotine` stays in place. No device files need moving. Any scripts or
aliases with explicit old path arguments must be updated separately.

The baseline tag still describes the original path defaults. These new defaults
apply to the updated code; an older installed copy continues using its old paths
until reinstalled.
