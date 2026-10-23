"""Read artwork and prepare small previews without saving or altering images."""

import base64
import io
from pathlib import Path

from mutagen.flac import Picture
from PIL import Image, ImageOps

from .review import Artwork
from .files import signature


def preview(data: bytes, label: str, origin: str, path: Path, index=0) -> Artwork:
    if len(data) > 32 * 1024 * 1024:
        raise ValueError('Artwork exceeds 32 MiB preview limit')
    with Image.open(io.BytesIO(data)) as image:
        image.load()
        width, height = image.size
        image = ImageOps.exif_transpose(image)
        image.thumbnail((240, 240), Image.Resampling.LANCZOS)
        output = io.BytesIO()
        image.convert('RGB').save(output, 'PNG')
    return Artwork(label, output.getvalue(), width, height, origin, path, index, signature(path))


def folder_previews(folder: Path):
    results, warnings = [], []
    for path in sorted(folder.iterdir()):
        if path.is_symlink() or not path.is_file() or path.suffix.lower() not in {'.jpg', '.jpeg', '.png'}:
            continue
        try:
            if path.stat().st_size > 32 * 1024 * 1024:
                raise ValueError('Artwork exceeds 32 MiB preview limit')
            results.append(preview(path.read_bytes(), path.name, 'folder', path))
        except (OSError, ValueError, Image.DecompressionBombError) as exc:
            warnings.append(f'{path.name}: {exc}')
    return results, warnings


def embedded_blobs(audio):
    tags = audio.tags or {}
    blobs = [picture.data for picture in getattr(audio, 'pictures', [])]
    if hasattr(tags, 'getall'):
        blobs.extend(frame.data for frame in tags.getall('APIC'))
    blobs.extend(bytes(value) for value in tags.get('covr', []))
    for value in tags.get('metadata_block_picture', []):
        blobs.append(Picture(base64.b64decode(value)).data)
    for value in tags.get('coverart', []):
        blobs.append(base64.b64decode(value))
    return blobs


def embedded_previews(audio, path: Path):
    blobs = embedded_blobs(audio)
    results, warnings = [], []
    for index, data in enumerate(blobs):
        try:
            results.append(preview(data, f'Embedded cover {index + 1}', 'embedded', path, index))
        except (OSError, ValueError, Image.DecompressionBombError) as exc:
            warnings.append(f'Embedded cover {index + 1}: {exc}')
    return results, warnings
