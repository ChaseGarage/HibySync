"""Apple artwork lookup using the existing catalog, download, and cache helpers."""

from hiby_music_tools import online_art
from hiby_music_tools.paths import metadata_dir
from .artwork import preview
from .interaction import Operation


def search_apple(artist: str, album: str, operation: Operation | None = None, cache_dir=None):
    op = operation or Operation()
    if not artist.strip() or not album.strip():
        raise ValueError('Enter an artist and album to search Apple artwork.')
    op.progress('Searching Apple artwork', 0)
    cache = online_art.Cache(cache_dir or metadata_dir() / 'artwork')
    cache.operation = op
    try:
        candidates = online_art.itunes_candidates(artist.strip(), album.strip(), cache)[:6]
        results, seen = [], set()
        for index, candidate in enumerate(candidates):
            op.progress('Downloading Apple artwork', index, len(candidates), candidate.album)
            if not online_art.download_candidate(candidate, cache):
                continue
            art = preview(candidate.image_path.read_bytes(),
                          f'{candidate.artist} — {candidate.album}' +
                          (f' ({candidate.label[:4]})' if candidate.label else ''),
                          'apple', candidate.image_path)
            if art.thumbnail not in seen:
                results.append(art)
                seen.add(art.thumbnail)
        op.progress('Apple artwork ready', len(candidates), len(candidates))
        if candidates and not results:
            raise ValueError('Apple returned matches, but no covers could be downloaded. Try again.')
        return results
    finally:
        cache.db.close()
