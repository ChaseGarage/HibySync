"""Linux identity validation for the existing mounted-filesystem sync transport.

GVFS MTP is usable only through its real FUSE mount. A path/volume label alone
never establishes device identity. No mount commands or directory creation occur.
"""
from dataclasses import dataclass, field
import hashlib
import os
from pathlib import Path
import re
import shutil
from urllib.parse import unquote

from hiby_music_tools.core.interaction import Operation


@dataclass(frozen=True)
class UsbDevice:
    path: str
    product: str
    manufacturer: str
    serial: str
    vendor: str
    model: str
    bus: int
    address: int

    @property
    def key(self):
        return f'{self.vendor}:{self.model}:{self.serial or self.path}:{self.bus}:{self.address}'

    @property
    def is_r1(self):
        text = f'{self.manufacturer} {self.product}'.casefold().replace('_', ' ')
        return bool((re.search(r'\bhiby\b', text) and re.search(r'\br1\b', text)) or
                    re.search(r'\bsonix[ -]?player\b', text))


@dataclass(frozen=True)
class Mount:
    identifier: str
    device: str
    path: str
    filesystem: str
    source: str


@dataclass(frozen=True)
class Target:
    key: str
    name: str
    music: str
    mount: Mount
    usb: UsbDevice
    transport: str
    endpoint: str = ''

    @property
    def identity(self):
        return f'{self.usb.product} · USB {self.usb.vendor}:{self.usb.model}' + (f' · {self.usb.serial}' if self.usb.serial else '')


@dataclass
class Detection:
    status: str
    message: str
    targets: list = field(default_factory=list)
    usb: list = field(default_factory=list)


def _unescape(value):
    return re.sub(r'\\([0-7]{3})', lambda m: chr(int(m[1], 8)), value)


def read_mounts(path=Path('/proc/self/mountinfo')):
    result = []
    for line in path.read_text().splitlines():
        left, right = line.split(' - ', 1)
        fields, tail = left.split(), right.split()
        result.append(Mount(fields[0], fields[2], _unescape(fields[4]), tail[0], _unescape(tail[1])))
    return result


def read_usb(root=Path('/sys/bus/usb/devices')):
    result = []
    if not root.is_dir():
        return result
    for entry in root.iterdir():
        if ':' in entry.name:
            continue
        def value(name):
            try:
                return (entry / name).read_text().strip()
            except OSError:
                return ''
        try:
            vendor, model = value('idVendor'), value('idProduct')
            if vendor and model:
                result.append(UsbDevice(str(entry.resolve()), value('product'), value('manufacturer'),
                                        value('serial'), vendor, model, int(value('busnum')), int(value('devnum'))))
        except (OSError, ValueError):
            continue  # Hot-unplug while enumerating sysfs.
    return result


def _mtp_matches(host, usb):
    host = unquote(host).casefold().strip('[]')
    address = re.fullmatch(r'usb:(\d+),(\d+)', host)
    if address:
        return (int(address[1]), int(address[2])) == (usb.bus, usb.address)
    # GVFS also uses udev's vendor_model_serial form. Require a real serial
    # boundary, not a substring of a volume label or a different device ID.
    if usb.serial:
        return bool(re.search(r'(?:^|[_ -])' + re.escape(usb.serial.casefold()) + r'(?:$|[_ -])', host))
    return False


def _plain_directory(path):
    return not path.is_symlink() and path.is_dir()


class LinuxDevices:
    """Injectable OS inventory; production always reads Linux mount/USB evidence."""
    def __init__(self, *, mountinfo=Path('/proc/self/mountinfo'), usb_root=Path('/sys/bus/usb/devices'),
                 block_root=Path('/sys/dev/block'), gvfs_root=None):
        self.mountinfo, self.usb_root, self.block_root = mountinfo, usb_root, block_root
        self.gvfs_root = gvfs_root or Path(os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')) / 'gvfs'

    def inventory(self):
        return read_mounts(self.mountinfo), [usb for usb in read_usb(self.usb_root) if usb.is_r1]

    def _block_usb(self, mount, devices):
        node = self.block_root / mount.device
        if not node.exists():
            return None
        path = node.resolve()
        return next((usb for usb in devices if path.is_relative_to(Path(usb.path))), None)

    def detect(self, operation=None):
        op = operation or Operation()
        mounts, devices = self.inventory()
        if not devices:
            return Detection('Disconnected', 'Connect the HiBy R1 in USB file-transfer mode.', usb=devices)
        targets, errors = [], []
        for mount in mounts:
            op.progress('Finding mounted HiBy Music folders', 0, None)
            root = Path(mount.path)
            if mount.filesystem == 'fuse.gvfsd-fuse' and root == self.gvfs_root:
                try:
                    if not _plain_directory(root):
                        continue
                    for endpoint in root.iterdir():
                        if not endpoint.name.startswith('mtp:host=') or endpoint.is_symlink():
                            continue
                        matches = [usb for usb in devices if _mtp_matches(endpoint.name[len('mtp:host='):], usb)]
                        if len(matches) != 1:
                            continue
                        usb = matches[0]
                        # MTP exposes one level of storage roots. Do not recurse
                        # into podcasts, firmware, or arbitrary user folders.
                        roots = [endpoint]
                        roots.extend(p for p in endpoint.iterdir() if _plain_directory(p) and p.name != 'Music')
                        for storage in roots:
                            op.checkpoint()
                            music = storage / 'Music'
                            if _plain_directory(music):
                                targets.append(self._target(mount, usb, music, 'MTP via GVFS/FUSE', str(endpoint)))
                except OSError as exc:
                    errors.append(str(exc))
            elif mount.filesystem not in ('tmpfs', 'overlay', 'proc', 'sysfs', 'fuse.gvfsd-fuse'):
                usb = self._block_usb(mount, devices)
                if usb:
                    try:
                        music = root / 'Music'
                        if _plain_directory(root) and _plain_directory(music):
                            targets.append(self._target(mount, usb, music, 'USB mounted filesystem'))
                    except OSError as exc:
                        errors.append(str(exc))
        targets = list({target.key: target for target in targets}.values())
        if targets:
            return Detection('Connected', '' if len(targets) == 1 else 'Choose the R1 storage to compare.', targets, devices)
        text = ('R1 detected, but no validated mounted /Music folder is accessible. '
                'Open the R1 in your file manager with GVFS MTP/FUSE, then Refresh. '
                'No mount or folder will be created automatically.')
        if errors:
            text += ' ' + errors[0]
        return Detection('Unavailable', text, usb=devices)

    @staticmethod
    def _target(mount, usb, music, transport, endpoint=''):
        token = f'{usb.key}|{mount.identifier}|{mount.device}|{music}'
        return Target(hashlib.sha256(token.encode()).hexdigest(), 'HiBy R1', str(music), mount, usb, transport, endpoint)

    def alive(self, target):
        """Cheap liveness: mount table, USB identity, GVFS mount registry only."""
        mounts, devices = self.inventory()
        if target.mount not in mounts or target.usb not in devices:
            return False
        if target.endpoint:
            # Listing GVFS's mount registry does not traverse the MTP storage.
            return Path(target.endpoint).name in {p.name for p in self.gvfs_root.iterdir()}
        return self._block_usb(target.mount, devices) == target.usb

    def validate(self, target, source):
        if not self.alive(target):
            raise ValueError('The R1 was disconnected or its mount changed. Refresh to reconnect.')
        source, music = Path(source).expanduser().resolve(), Path(target.music)
        if target.endpoint:
            endpoint = Path(target.endpoint)
            if (target.mount.filesystem != 'fuse.gvfsd-fuse' or Path(target.mount.path) != self.gvfs_root
                    or endpoint.parent != self.gvfs_root or not endpoint.name.startswith('mtp:host=')
                    or not _mtp_matches(endpoint.name[len('mtp:host='):], target.usb)
                    or not music.is_relative_to(endpoint) or len(music.relative_to(endpoint).parts) not in (1, 2)):
                raise ValueError('The chosen folder is not a validated R1 MTP music root.')
        elif music != Path(target.mount.path) / 'Music':
            raise ValueError('Choose /Music at the root of the identified device mount.')
        if not source.is_dir() or source.is_symlink():
            raise ValueError('The configured local library is not an accessible directory.')
        if not _plain_directory(music) or music.name != 'Music':
            raise ValueError('The device /Music folder is unavailable. No replacement directory was created.')
        if music.resolve() != music.absolute():
            raise ValueError('The device path contains a symlink; choose the real mounted /Music folder.')
        if source == music or source.is_relative_to(music) or music.is_relative_to(source):
            raise ValueError('The local library and device Music folders must be separate.')
        if os.stat(music).st_dev != os.makedev(*map(int, target.mount.device.split(':'))):
            raise ValueError('The Music folder is no longer on the identified device filesystem.')
        return music

    def select(self, detection, path):
        chosen = Path(path).expanduser().absolute()
        return next((target for target in detection.targets if Path(target.music) == chosen), None)

    def status(self, target):
        if self.alive(target):
            return 'Connected'
        _, devices = self.inventory()
        return 'Unavailable' if target.usb in devices else 'Disconnected'

    def storage(self, target):
        if target.endpoint:
            return None  # statvfs on aggregate GVFS may describe the host, not MTP storage.
        usage = shutil.disk_usage(target.music)
        return dict(total=usage.total, free=usage.free)
