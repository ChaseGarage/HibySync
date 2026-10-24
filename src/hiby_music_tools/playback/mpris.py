"""One MPRIS session; D-Bus IO lives on an asyncio thread, Qt owns playback.

No playback state is owned here. Immutable snapshots cross the boundary and
commands return to the single Qt player via a queued signal.
"""
import asyncio
from pathlib import Path
import threading

from PySide6.QtCore import QObject, Signal, QTimer

NAME = 'org.mpris.MediaPlayer2.HibySync'
PATH = '/org/mpris/MediaPlayer2'


def snapshot(player, art_directory):
    row = player.current
    track_path = '/org/mpris/MediaPlayer2/track/' + (player.currentQueueId or 'none')
    metadata = dict(track=track_path, title=row.get('title', ''), artist=row.get('artist', ''),
                    album=row.get('album_title', ''), length=int(player.duration * 1000000),
                    url=Path(row['path']).as_uri() if row.get('path') else '', art='')
    key = row.get('art_key', '')
    if key and all(c in '0123456789abcdef' for c in key):
        art = Path(art_directory) / (key + '.png')
        if art.is_file():
            metadata['art'] = art.as_uri()
    return dict(status='Playing' if player.state in ('playing', 'loading', 'buffering') else 'Paused' if player.state == 'paused' else 'Stopped',
                loop={'off': 'None', 'all': 'Playlist', 'one': 'Track'}[player.repeat],
                shuffle=player.shuffle, volume=player.volume / 100,
                position=int(player.position * 1000000), metadata=metadata,
                available=bool(player.count) and not player.maintenance,
                next=bool(player.queue.adjacent(1)) and not player.maintenance,
                previous=bool(player.queue.adjacent(-1)) and not player.maintenance)


def interfaces(owner):
    from dbus_next import Variant
    from dbus_next.service import ServiceInterface, method, dbus_property, signal
    from dbus_next.constants import PropertyAccess

    class Root(ServiceInterface):
        def __init__(self):
            super().__init__('org.mpris.MediaPlayer2')

        @method()
        def Raise(self):
            owner.command.emit('raise', None)

        @method()
        def Quit(self):
            owner.command.emit('quit', None)

        @dbus_property(access=PropertyAccess.READ)
        def CanQuit(self) -> 'b': return True
        @dbus_property(access=PropertyAccess.READ)
        def CanRaise(self) -> 'b': return True
        @dbus_property(access=PropertyAccess.READ)
        def HasTrackList(self) -> 'b': return False
        @dbus_property(access=PropertyAccess.READ)
        def Identity(self) -> 's': return 'HibySync'
        @dbus_property(access=PropertyAccess.READ)
        def DesktopEntry(self) -> 's': return 'hibysync'
        @dbus_property(access=PropertyAccess.READ)
        def SupportedUriSchemes(self) -> 'as': return []
        @dbus_property(access=PropertyAccess.READ)
        def SupportedMimeTypes(self) -> 'as': return []

    class Player(ServiceInterface):
        def __init__(self):
            super().__init__('org.mpris.MediaPlayer2.Player')

        @method()
        def PlayPause(self): owner.command.emit('toggle', None)
        @method()
        def Play(self): owner.command.emit('play', None)
        @method()
        def Pause(self): owner.command.emit('pause', None)
        @method()
        def Stop(self): owner.command.emit('stop', None)
        @method()
        def Next(self): owner.command.emit('next', None)
        @method()
        def Previous(self): owner.command.emit('previous', None)
        @method()
        def Seek(self, Offset: 'x'): owner.command.emit('seek', Offset)
        @method()
        def SetPosition(self, TrackId: 'o', Position: 'x'):
            owner.command.emit('position', (TrackId, Position))
        @method()
        def OpenUri(self, Uri: 's'):
            from dbus_next.errors import DBusError
            raise DBusError('org.mpris.MediaPlayer2.Player.Error.NotSupported', 'Use the local Library to select music.')

        @signal()
        def Seeked(self, position) -> 'x': return position

        @dbus_property(access=PropertyAccess.READ)
        def PlaybackStatus(self) -> 's': return owner.data['status']
        @dbus_property()
        def LoopStatus(self) -> 's': return owner.data['loop']
        @LoopStatus.setter
        def LoopStatus(self, value: 's'): owner.command.emit('repeat', value)
        @dbus_property()
        def Shuffle(self) -> 'b': return owner.data['shuffle']
        @Shuffle.setter
        def Shuffle(self, value: 'b'): owner.command.emit('shuffle', value)
        @dbus_property()
        def Volume(self) -> 'd': return owner.data['volume']
        @Volume.setter
        def Volume(self, value: 'd'): owner.command.emit('volume', value)
        @dbus_property()
        def Rate(self) -> 'd': return 1.0
        @Rate.setter
        def Rate(self, value: 'd'):
            if value != 1.0:
                from dbus_next.errors import DBusError
                raise DBusError('org.freedesktop.DBus.Error.NotSupported', 'Playback speed is fixed at 1.')
        @dbus_property(access=PropertyAccess.READ)
        def MinimumRate(self) -> 'd': return 1.0
        @dbus_property(access=PropertyAccess.READ)
        def MaximumRate(self) -> 'd': return 1.0
        @dbus_property(access=PropertyAccess.READ)
        def Position(self) -> 'x': return owner.data['position']
        @dbus_property(access=PropertyAccess.READ)
        def CanPlay(self) -> 'b': return owner.data['available']
        @dbus_property(access=PropertyAccess.READ)
        def CanPause(self) -> 'b': return owner.data['available']
        @dbus_property(access=PropertyAccess.READ)
        def CanSeek(self) -> 'b': return owner.data['available'] and owner.data['status'] != 'Stopped'
        @dbus_property(access=PropertyAccess.READ)
        def CanControl(self) -> 'b': return True
        @dbus_property(access=PropertyAccess.READ)
        def CanGoNext(self) -> 'b': return owner.data['next']
        @dbus_property(access=PropertyAccess.READ)
        def CanGoPrevious(self) -> 'b': return owner.data['previous']
        @dbus_property(access=PropertyAccess.READ)
        def Metadata(self) -> 'a{sv}':
            m = owner.data['metadata']
            if not m['title'] and m['track'].endswith('/none'):
                return {}
            values = {'mpris:trackid': Variant('o', m['track']), 'mpris:length': Variant('x', m['length']),
                      'xesam:title': Variant('s', m['title']), 'xesam:artist': Variant('as', [m['artist']]),
                      'xesam:album': Variant('s', m['album']), 'xesam:url': Variant('s', m['url'])}
            if m['art']:
                values['mpris:artUrl'] = Variant('s', m['art'])
            return values

    return Root(), Player()


class Mpris(QObject):
    command = Signal(str, object)
    status = Signal(str)

    def __init__(self, player, window, art_directory):
        super().__init__(player)
        self.player, self.window, self.art_directory = player, window, art_directory
        self.loop = self.bus = self.interface = None
        self.data = snapshot(player, art_directory)
        self._duration = player.duration
        self._closing = False
        self.command.connect(self._command)
        self.status.connect(player.setMediaStatus)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(80)
        self.timer.timeout.connect(self.update)
        for signal in (player.trackChanged, player.stateChanged, player.changed):
            signal.connect(self.schedule)
        player.positionChanged.connect(lambda: self.update(position_only=True))
        player.seeked.connect(self.seeked)
        self.thread = threading.Thread(target=self._run, name='HibySync-MPRIS', daemon=True)
        self.thread.start()

    def schedule(self):
        if not self.timer.isActive(): self.timer.start()

    def update(self, position_only=False):
        if position_only:
            # Position ticks do not query the catalog or stat artwork files.
            if self.player.duration != self._duration:
                self._duration = self.player.duration
                self.schedule()
            position = int(self.player.position * 1000000)
            if self.loop and not self._closing:
                try: self.loop.call_soon_threadsafe(lambda: self.data.update(position=position))
                except RuntimeError: pass
            return
        data = snapshot(self.player, self.art_directory)
        if self.loop and not self._closing:
            def publish():
                self.data = data
                if self.interface and not position_only:
                    self.interface.emit_properties_changed({key: getattr(self.interface, key) for key in
                        ('PlaybackStatus', 'LoopStatus', 'Shuffle', 'Volume', 'Metadata', 'CanPlay', 'CanPause', 'CanSeek', 'CanGoNext', 'CanGoPrevious')})
            try: self.loop.call_soon_threadsafe(publish)
            except RuntimeError: pass

    def seeked(self, seconds):
        if self.loop and self.interface and not self._closing:
            self.loop.call_soon_threadsafe(self.interface.Seeked, int(seconds * 1000000))

    def _run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        async def start():
            from dbus_next.aio import MessageBus
            from dbus_next.constants import NameFlag, RequestNameReply
            self.bus = await MessageBus().connect()
            reply = await self.bus.request_name(NAME, NameFlag.DO_NOT_QUEUE)
            if reply != RequestNameReply.PRIMARY_OWNER:
                self.status.emit('Another HibySync media session is already registered.')
                return False
            root, self.interface = interfaces(self)
            self.bus.export(PATH, root)
            self.bus.export(PATH, self.interface)
            self.status.emit('MPRIS connected')
            return True
        try:
            if self.loop.run_until_complete(start()) and not self._closing:
                self.loop.run_forever()
        except ModuleNotFoundError as exc:
            if exc.name == 'dbus_next':
                self.status.emit('MPRIS needs dbus-next. On Arch: sudo pacman -S python-dbus-next. Restart HibySync afterward, or update with ./install.sh --gui.')
            else:
                self.status.emit('MPRIS unavailable: ' + str(exc))
        except Exception as exc:
            self.status.emit('MPRIS unavailable: ' + str(exc))
        finally:
            if self.bus:
                self.bus.disconnect()
                # Drain disconnect callbacks before closing the event loop.
                self.loop.run_until_complete(asyncio.sleep(0))
            self.loop.close()

    def _command(self, name, value):
        p = self.player
        if self._closing:
            return
        if name == 'raise':
            self.window.show(); self.window.raise_(); self.window.requestActivate()
        elif name == 'quit': self.window.close()
        elif p.maintenance: return
        elif name == 'toggle': p.togglePause()
        elif name == 'play' and p.state not in ('playing', 'loading', 'buffering'): p.togglePause()
        elif name == 'pause' and p.state in ('playing', 'buffering'): p.togglePause()
        elif name == 'stop': p.stop()
        elif name in ('next', 'previous'): p.mediaAdjacent(1 if name == 'next' else -1)
        elif name == 'seek': p.seek(p.position + value / 1000000)
        elif name == 'position':
            if value[0] == '/org/mpris/MediaPlayer2/track/' + (p.currentQueueId or 'none') and 0 <= value[1] <= p.duration * 1000000:
                p.seek(value[1] / 1000000)
        elif name == 'volume': p.setVolume(value * 100)
        elif name == 'shuffle' and value != p.shuffle: p.toggleShuffle()
        elif name == 'repeat' and value in ('None', 'Playlist', 'Track'):
            target = {'None': 'off', 'Playlist': 'all', 'Track': 'one'}[value]
            while p.repeat != target: p.cycleRepeat()

    def shutdown(self):
        self._closing = True
        self.timer.stop()
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=2)
