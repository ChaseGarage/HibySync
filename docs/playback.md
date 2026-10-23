# Local playback

## Install and launch

On CachyOS/Arch:

```sh
sudo pacman -S mpv pyside6 python-pillow python-mutagen python-setuptools python-pip
./install.sh --gui
hibysync
```

Use `./hibysync` directly from the checkout. Both work in Fish. If needed on
Hyprland, use `env QT_QPA_PLATFORM=wayland ./hibysync`. mpv is an external runtime
dependency, not a Python binding. Import and CLI tools still work without it;
trying playback shows an installation message. The installer reports a missing
mpv dependency but does not run a package manager automatically.

Choose Library and index/refresh the configured library. The leading control in
each song row appears on hover, selection, or keyboard focus. Click it to replace
the queue with that song's complete filtered/sorted context and start there.
For the current track it pauses/resumes the live queue instead. Clicking elsewhere
selects a row without starting playback. Double-click is an optional shortcut.
The context comes from one SQLite snapshot, including rows not yet loaded
by the view. Album playback uses disc/track order; artist playback groups their
albums and preserves disc/track order. The artist browser includes contributors;
Play artist includes their album-artist releases and their individual contributing
tracks on other albums. Play uses the original context order; Shuffle explicitly
randomizes it, and the bar can toggle shuffle while listening.

Album pages offer Play, Shuffle, Add to queue, and Play next. Track action menus
offer Play, Play next, and Add to queue. Play next inserts immediately after the
current entry; it does not interrupt the current song. Adding to an idle queue
does not start playback. Queue entries have separate instance IDs, so repeated
copies of the same song can be moved or removed independently.

The bottom bar remains present across all sections. It has previous, play/pause,
next, stop, shuffle, repeat, seek, volume, artwork, and queue controls. Previous
restarts the song after three seconds, otherwise selects the previous entry.
Manual Next ignores repeat-one; completion repeats that song. Repeat cycles
off → all → one. Shuffle preserves the playing entry and history while shuffling
upcoming entries; disabling it restores the original context order. Queue panel
controls play an entry, remove it, or move it earlier/later. Double-clicking a
queue entry also selects it. Clear stops playback and empties the queue.

## Responsive Library and controls

Library uses a centered content area up to 1400px wide, with 20–32px outer margins.
The application starts on Library and reads its cached index without automatically
rescanning music or starting playback. Qt's app-local wheel-scroll setting is at
least nine lines per notch, retaining a higher platform value if configured.
This is applied before creating the views, preserving native acceleration and
pixel-based touchpad gestures without changing desktop preferences.
Songs and album tracks share column metrics and a 52px normal row height.
Song title, artist, leading play control, duration, and actions stay visible;
Album appears at 880px of available list width and Year at 1100px. The header's
sort menu retains all sort choices when columns are hidden. Artwork grids add
columns as available content width increases. Album headers and tracks share
one virtualized scrolling list, including disc headings. Narrow album headers
reduce cover size and place secondary queue actions in a menu.

The bottom bar has independent track/transport/utility regions. Wide transport
controls and timeline remain centered regardless of the track title. Below
1000px of available bar width, previous/play-pause/next and queue stay visible,
with the timeline on its own row. Shuffle, repeat, Stop, and volume are available
through Playback options; volume is also inline on wide displays.

Stable track IDs and actual playback state drive a restrained green indicator,
title, and background. Paused tracks remain identifiable; stopped/error tracks
return to normal styling. Playing bars are static rather than animated, avoiding
continuous rendering work for offscreen or instantiated rows. Selection belongs
to the view, independently of the current song. A single shared Python row action
handles play/pause so a current-track click does not reconstruct its queue.

Arrow keys navigate selected rows, Enter activates a focused row/control, and
Tab visits controls. Space toggles playback outside text editors, while focused
buttons retain their normal Space action. Menus dismiss with Escape. These are
window-local shortcuts; MPRIS/global media keys remain a follow-up.

Artist/album text links underline on hover or keyboard focus and activate with
a click or Enter. They are shared across song rows, album cards/headers, the
artist browser, player, and queue. Player/queue song titles open their album.
Track artists resolve to their indexed contributor entity, while album headers
link to the album artist. Navigation uses IDs and read-only background index
lookups, preserves the live queue, and clears stale search filters for artist
destinations. Old saved-queue entries that are no longer indexed in the configured
root show a navigation error; playback remains independent of this lookup.

Seek dragging holds its displayed position independently of incoming playback
updates. Release sends one seek, retaining the requested display briefly until
the backend acknowledges it (or a bounded timeout expires). A track change during
a drag cancels that seek. Left/Right seek five seconds; Home/End seek the bounds.
Only position/duration properties notify on progress ticks: current-track and
playback-state notifications are separate, with cached current-track metadata.
No Library query or model reset is caused by position updates.

Offscreen rendered checks and interaction tests cover 1600×900, 1200×800,
900×800, and 750×700, including resizing, column alignment, primary-control
bounds, exactly one row-control operation, duplicate titles with different IDs,
selection, keyboard/editable focus, seeking, scroll virtualization, and returning
to the playing album. A real-mpv/null-output test also checks playback continues
during navigation and resizing. Desktop-specific fractional scaling, accessibility
tools, and real Hyprland input behavior still need local desktop testing.

## Audio and IPC

`PlaybackService` is an interchangeable Python/Qt boundary. Its mpv implementation
launches a dedicated process lazily and uses a private, permission-restricted
temporary directory for a Unix socket. Commands are UTF-8 JSON arrays with
request IDs; replies and asynchronous property/file events drive state. Paths
are absolute local filenames, passed as JSON values. No shell commands, terminal
output parsing, or QML playback logic are involved. QProcess and QLocalSocket
perform nonblocking IO. Large queue planning yields to the event loop; context
queries and state-file IO run in workers. Closing cancels outstanding queries,
saves state, and asks mpv to quit, with bounded process termination as a fallback.

HibySync owns the queue and mirrors its order into mpv's native playlist. Native
completion handles track transitions without waiting for a Python EOF handler.
Moving/removing upcoming items preserves the current decoder and position.
Selecting another song or removing the current song intentionally changes it.
mpv uses `gapless-audio=weak`, retaining the output for compatible formats and
allowing it to reopen for changed parameters. Gapless transitions across different
sample rates/codecs or slow filesystems are not guaranteed.

The predictable process configuration disables personal configs, automatic
scripts, automatic external tracks, video, and network artwork helpers. Speed
is 1; audio filters, ReplayGain, normalization, EQ, and crossfade are off. Volume
defaults to 100% with no amplification above unity, and is user adjustable.
No output sample rate or sample format is imposed. PipeWire is preferred;
PulseAudio and ALSA are fallbacks. mpv/FFmpeg handles decoding the installed
engine's supported MP3, FLAC, WAV, AAC/M4A, ALAC, Ogg, and other audio formats.

This does **not** establish bit-perfect output. Software volume below 100%,
necessary channel/format conversion, PipeWire graph settings, mixing, hardware
volume, and DAC capabilities can alter samples. Exclusive output and advanced
rate/device configuration are not exposed in this milestone. See the official
[mpv audio options](https://mpv.io/manual/stable/#audio) and
[JSON IPC protocol](https://mpv.io/manual/stable/#json-ipc) for the engine contract.

Missing/unreadable tracks report a nonmodal error and mpv can advance to the next
entry. A run of failed entries is stopped to prevent infinite error loops under
repeat. Audio-output initialization errors stop playback; Play retries, and Next
can select another track. Temporary device availability depends on PipeWire's
rerouting and mpv's output handling; automatic device-recovery retry is not
implemented. mpv crashes/timeouts leave a retryable error and retain the queue.

## Saved state

Queue entries, selection, shuffle, repeat, volume, and recent position are saved
atomically to `$XDG_STATE_HOME/hibysync/player.json`, normally
`~/.local/state/hibysync/player.json`. Writes are debounced; position is checkpointed
every 15 seconds and at clean shutdown. Launch restores a stopped player and does
not start mpv or produce sound. Press Play to resume the saved selection/position.
Renamed/deleted files in a saved queue can be missing even after the Library is
refreshed: queues are snapshots, and currently do not resolve later filesystem
renames through the index. Rebuild that listening context from the Library.

MPRIS/global media keys remain a documented follow-up. Full library metadata
editing, crossfade/DSP controls, output-device preferences, and playback-history
management are outside this milestone. The preserved `--widgets` frontend is
still Import review only.

## Tests

```sh
python -m unittest discover -s tests -v
python -m unittest discover -s tests -p test_playback.py -v
```

The real-engine tests need mpv, PySide6, and local Unix-socket access. Optional
FFmpeg creates format fixtures (`sudo pacman -S ffmpeg`). They decode generated
tones in WAV, FLAC, MP3, AAC, AAC-in-M4A, ALAC, and Ogg to PCM files, checking
nonzero audio data; lossless WAV/FLAC/ALAC fixtures also compare decoded samples
with the source at the software PCM output. Timed null-output tests exercise real mpv decoding and IPC,
pause/resume, exact seeking, completion, repeat, missing files, rapid switching,
playlist edits, large-queue responsiveness, and shutdown. Null output alone is
not evidence of audible sound; PCM tests verify decoded output separately.
GUI tests explicitly use a fake service to verify presentation and queue actions.
All fixtures, database files, state files, and generated audio are temporary.

To explicitly exercise the real PipeWire output with a short low-volume tone:

```sh
env HIBYSYNC_TEST_PIPEWIRE=1 python -m unittest discover -s tests -p test_playback.py -k pipewire_output -v
```

This optional test checks the active output is PipeWire, negotiated output
parameters exist, and playback advances without errors. It does not record the
DAC's electrical output or prove bit-perfect delivery. It is skipped by default
so the normal suite never plays sound through your speakers. Qt GUI tests use
offscreen/software rendering and do not validate every Hyprland driver/scale.
