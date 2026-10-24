# Device sync

## Install and launch

```sh
./install.sh --gui
hibysync
```

`./hibysync` runs the checkout directly. Both launch commands work from Fish.
On CachyOS/Arch, MTP execution additionally needs the system GIO bindings/backend:

```sh
sudo pacman -S python-gobject gvfs gvfs-mtp
```

[`python-gobject`](https://archlinux.org/packages/extra/x86_64/python-gobject/)
provides GIO's Python bindings. The installer reuses system packages and reports
missing optional GIO support; it does not run pacman, mount the player, change USB
modes or modify audio configuration. Filesystem sync does not require GIO.

## Review and explicit confirmation

The first Device visit detects the R1 and compares `/Music` with the application's
configured library, normally `~/Music/Library`. Refresh repeats a fast comparison.
Choose device selects among validated storage roots or validates a manually chosen
mounted Music folder. Ordinary folders and raw `mtp://` URIs are not accepted as
filesystem mounts. A recognized USB identity and current mount evidence are required.

The overview counts verified synced tracks, transfers (New + Updated), and
removals. Expand Changes to Sync categories to inspect names, paths, indexed
artist/album labels and byte totals. The index supplies optional labels, not
file-equality decisions. Non-audio/device-generated files are left unmanaged.

Normal comparison avoids reading unchanged MTP audio. Matching sizes are skipped
by the fast check and do not block Sync. Successful syncs save file fingerprints
in `device-sync-state.sqlite3` beside the library index, scoped to the source,
device identity and storage root. Subsequent fingerprint changes trigger updates,
including same-size tag/artwork edits. The legacy CLI cache is not reused.
**Verify contents** is optional: it reads SHA-256 on both sides to find same-size
differences without history or changes that preserved the observed fingerprints.
Fast matches are labeled as such; they are not proof of byte equality. An initial
same-size mismatch without history requires that optional full check.

Preview changes remains read-only. **Sync Device** prepares a fresh fast
plan, then opens a distinct confirmation listing every Add, Update and
Remove. When removals exist, a separate checkbox must explicitly consent to the
listed permanent device deletions. Merely opening Device, Preview or confirmation
never writes to the R1. Local files are never deleted, retagged or re-encoded.

After confirmation, a worker revalidates identity, mount, source and destination
file sets/signatures/hashes, and available storage where reported. A changed plan
is returned for review with **no writes**, rather than silently adding new work.
An empty source cannot clear a populated device. Unique filenames differing only
in case or Unicode normalization are paired within the same directory. Matching
SHA-256 contents count as synced; changed contents update the existing device
filename, retaining its spelling. Fast comparison can skip these aliases by size.
Multiple aliases on either side and differently spelled directory paths remain
conflicts, rather than risking duplicate folders or deleting a replacement.
Symlinks, file/directory conflicts, incomplete scans and unreadable/changed files
block sync.
Only the exact `/Music` destination is managed; no reverse import is performed.

## Transfer architecture

`device/execution.py` implements the transport-independent confirmed workflow.
`device/transports.py` owns all device IO. QML only presents state and sends
commands through `gui/device_sync.py` and `device_controller.py`.

`core/streaming.py` is the shared measured copy loop used by the existing CLI
`safe_copy` and GUI filesystem transport. The managed extensions, SHA-256 and
copy/update decision are also shared with `sync.py`. CLI flags, prompts, state
schema, transfer order and established transport behavior remain intact. The CLI
still uses its legacy POSIX/GVFS copy path and replacement fallback; the GUI uses
the guarded transports described below. No interactive terminal script is run
inside the GUI, and no filesystem logic lives in QML.

### Filesystem transport

A validated mounted R1 block filesystem uses unbuffered 512 KiB streaming writes.
Progress advances after successful writes and fsync; short writes are handled.
Directory descriptors and no-follow opens constrain writes to the mounted Music
root, including parent creation. A missing mount/root is never recreated locally.

Uploads go to unique, short sibling `.hibysync-…part` names, avoiding filename
length problems. A staged file is read back and SHA-256 checked before publishing.
New destinations use Linux no-replace rename; updates use atomic replacement
where the filesystem supports it. Existing updates first receive a verified,
flushed original backup in local recovery storage. No file is called Completed
until the published destination is read back and verified too. Unsupported safe
publication operations fail instead of falling back to unexpected overwrite.

### Native GIO MTP transport

Discovery/comparison still requires the existing GVFS/FUSE projection, but copying,
reading, renaming and deleting use **native MTP GFile operations**, derived from
the same validated GVFS host/storage identity. They do not copy to the FUSE path
with POSIX writes or assume `os.replace` works over MTP.

GIO copy uses its [native byte-progress callback](https://docs.gtk.org/gio/callback.FileProgressCallback.html)
and a thread-safe [Gio.Cancellable](https://docs.gtk.org/gio/method.Cancellable.cancel.html).
Only counts actually reported by GIO are displayed; until a callback provides
counts the current upload is indeterminate. If a backend reports only completion,
no intermediate percentages are synthesized. Read-back hashes, rather than a
successful copy call alone, determine completion. These are API-level byte counts,
not independent measurement of USB wire traffic or durable flash writes.

MTP does not promise atomic overwrite. After staging/read-back verification and
saving a verified local original, an update natively renames the old object to a
unique sibling backup, publishes the staged object, verifies the final path, then
removes the owned device backup. The old filename can briefly be absent. GIO
moves use [NO_FALLBACK_FOR_MOVE](https://docs.gtk.org/gio/flags.FileCopyFlags.html):
an unsupported native move cannot silently turn into copy-and-delete. Failed
publication attempts restore the old name while connected when safe. If the
transport cannot provide the required native rename, it reports an error and
leaves the original intact/recoverable; it does not switch to unsafe overwrite.
This capability and Sonix-player behavior need physical-device verification.

## Progress and completion

`SyncProgress` provides a stable path-derived identifier, relative path, operation,
state, per-file byte counts/total (or unknown), files completed/total, upload bytes
transferred/total, errors and measured throughput when available. The GUI worker
throttles intermediate updates to roughly 20 Hz; terminal transitions are delivered.
Source hashing, backups, verification and removals do not inflate upload byte counts.

The Device tab transitions to one integrated progress view: overall upload bar,
current-file bar, numeric counts, operation state and a virtualized activity list.
Navigation and playback remain independent. Unknown progress has no invented
percentage or elapsed-time animation. At 100% copied bytes, the screen explicitly
states that verification/removals still need to finish. Sync Complete is withheld
until final checks pass. Recent activity can be scrolled to inspect failures;
Latest resumes following new entries.

All transfers precede removals. A failed/interrupted transfer blocks the entire
removal phase. Before removals, a new complete comparison must show that all
transfers match and that the removal set is still exactly the confirmed set.
Source state is rechecked, and each removal's current bytes must match its approved
hash before deletion. A source/configuration change or unreadable scan cannot
silently authorize cleanup. Only confirmed managed audio is removed; GUI sync
leaves empty directories and non-audio files alone.

Final checks recheck source state, expected file sets and sizes. Every transferred
file receives staged and published SHA-256 verification; unchanged audio is not
hashed during normal sync. An explicitly verified plan retains full hashing.
Only completed checks produce Sync Complete; fast matches remain labeled as such.
Successful completion refreshes the dashboard from that comparison and saves
fingerprint history. Errors, cancellation, disconnects and changed reviews have distinct
summaries with completed/failed/skipped activity. Retry Failed **re-evaluates all
remaining work and asks for confirmation again**; it never blindly replays an
old deletion list. Already-correct completed transfers are hashed/matched and
not recopied. Refresh can re-evaluate after reconnection.

## Cancellation, recovery and limits

Cancel stops starting new work. Filesystem copies check cancellation between
chunks; native GIO operations receive cancellation directly. Once publication
starts, HibySync safely concludes or attempts to restore that replacement before
honoring cancellation. This can complete a fully verified current file after
Cancel was pressed; completed work remains listed. No pause/resume is offered.

A lost identity/mount stops writes and removals. No cleanup is issued against a
missing mount. Partial stages are removed only when owned by this run and still
connected; otherwise they remain for recovery. Cancellation does not erase
verified completed files. A new plan after reconnection decides what still needs
copying, so successful transfers are not needlessly repeated.

Recovery lives under `~/.cache/hiby-music-tools/device-sync/run-<id>/`. Each run has
a flushed `journal.jsonl` with device/source identity, approved operations,
stage/backup paths and outcomes. Verified originals for updates are retained as
`original-<n>.audio` beside it, outside both the source library and device. Copy log
path in the result view copies the exact journal path. Retain this directory until
satisfied with the sync; recovery backups are not pruned automatically.

If publication fails after a disconnect, preserve the journal, local original,
and any `.part`/`.backup` objects. Reconnect the same player and Refresh first.
For manual restoration, stop other writers, inspect the logged original relative
path and hashes, and restore only a confirmed backup; do not blindly overwrite a
newer device file. Obsolete-file removals are permanent and do not create a
recovery copy. They always require explicit GUI consent.

Storage preflight reserves the peak staged-upload space and local update-backup
space. Native MTP capacity is used only if GIO supplies a free-space attribute;
otherwise it remains unknown and backend errors are handled without a deletion
pass. Capacity can change after preflight. Hardware caches, power failure and
concurrent external writers cannot be made transactional across local and MTP
filesystems. Close other writers during sync; a refresh is a point-in-time
snapshot, not a global lock. A read/check/publish interval remains even with
signatures and hashes. Do not disconnect until completion and eject normally
using the desktop; HibySync never unmounts or changes USB modes itself.

Linux detection uses `/proc/self/mountinfo` and live `/sys/bus/usb/devices`
identity (HiBy R1/SONIX-PLAYER), plus sysfs block ancestry or a matching GVFS MTP
host. An ordinary folder/volume label is insufficient. Multiple storages require
selection. GVFS is normally at `$XDG_RUNTIME_DIR/gvfs`; raw MTP/GIO-only mounts,
unknown firmware identities, other MTP FUSE implementations and device-mapper
mounts are not silently accepted. Refresh/Choose device cannot bypass validation.
Storage statistics from aggregate FUSE statvfs are not presented as MTP capacity.

## Tests and safe manual MTP check

```sh
python -m unittest discover -s tests -p test_device_execution.py -v
python -m unittest discover -s tests -p test_device_sync_gui.py -v
python -m unittest discover -s tests -v
```

Automated tests use temporary source libraries and injected Linux inventories.
They exercise actual filesystem writes/read-back hashes, measured multi-chunk
progress, updates, Unicode/long names, permanent removals, insufficient space,
write interruption, corrupt stages, stale reviews, cancellation, disconnect and
retry, destination races and non-atomic publication/restore. GIO tests use native
**file:// local GFile APIs**, including copy callbacks and cancellation; they do
**not** exercise USB/MTP. UI tests use a fake audio service while running real
filesystem transfers, consent, live bars, navigation, resizing and retry. Existing
mpv tests separately exercise real playback. No test writes the real R1 or library.

For a physical MTP test, use a **spare empty card/storage** with an existing Music
root, not the normal populated card. Do not point a small test library at a Music
root containing personal music: this is an authoritative mirror and would propose
removing device-only tracks. No write test should proceed unless the destination
has been independently checked and the user explicitly consents.

1. Mount the spare R1 storage normally in the file manager. Start HibySync with
   `./hibysync --library /path/to/disposable-test-library` and choose that exact
   storage. Confirm its USB identity and Music path before continuing.
2. Use generated test audio only: a small track, a multi-megabyte track, and Unicode
   names. Verify contents and review a plan with **zero removals**, then confirm.
3. Check that the large file receives real intermediate byte callbacks. If the
   firmware supplies only end-of-copy progress, verify the indeterminate behavior.
   Compare destination SHA-256 with the unchanged local fixtures after completion.
4. Change only a fixture's tags/artwork, including a same-size update. Inspect the
   update confirmation, native rename support, final read-back and retained original
   recovery copy. Unsupported native moves must fail without unsafe replacement.
5. Cancel a fixture transfer, then retry after fresh comparison. On the spare card
   only, an explicit unplug test can inspect disconnect handling, retained journal
   and incomplete objects. Reconnect and verify no cleanup targets a missing mount.
6. Finally remove one fixture from the disposable source. Confirm that its exact
   Remove entry requires the separate checkbox and is applied only after transfers
   and verification. Check folders outside Music and non-audio files stayed intact.

Actual Sonix/R1 copy latency, rename support, USB progress granularity, permissions,
flash persistence and unplug timing remain unverified until that hardware procedure
is performed. Local GIO and filesystem success do not establish those guarantees.
