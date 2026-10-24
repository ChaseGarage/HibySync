"""Conservative audio descriptions: file tags and backend output stay separate."""


def stream_label(track):
    """Compact source information; never invent a depth for lossy/unknown data."""
    parts = []
    rate, depth = track.get('sample_rate'), track.get('bit_depth')
    if isinstance(rate, (int, float)) and rate > 0:
        parts.append(f'{rate / 1000:g}kHz')
    if isinstance(depth, int) and depth > 0:
        parts.append(f'{depth} bit')
    return ' '.join(parts)


def source_info(track):
    codec = str(track.get('codec') or track.get('format') or '').strip()
    lower = codec.lower()
    lossless = any(word in lower for word in ('flac', 'alac', 'pcm', 'wav', 'aiff', 'monkey'))
    lossy = any(word in lower for word in ('mp3', 'aac', 'mp4a', 'vorbis', 'opus', 'mpeg'))
    display = codec.upper()
    if 'wave' in lower or lower == 'wav':
        display = 'PCM (WAV)'
    elif 'aiff' in lower:
        display = 'PCM (AIFF)'
    elif 'flac' in lower:
        display = 'FLAC'
    elif 'alac' in lower:
        display = 'ALAC'
    elif 'mp4a' in lower or 'aac' in lower:
        display = 'AAC'
    elif 'mpeg' in lower or 'mp3' in lower:
        display = 'MP3'
    elif 'vorbis' in lower:
        display = 'Vorbis'
    elif 'opus' in lower:
        display = 'Opus'
    parts = [display] if display else []
    rate = track.get('sample_rate')
    if rate:
        parts.append(f'{rate / 1000:g} kHz')
    if track.get('bit_depth'):
        parts.append(f"{track['bit_depth']}-bit")
    if track.get('bitrate') and lossy:
        parts.append(f"{track['bitrate'] / 1000:g} kb/s")
    parts.append('Lossless' if lossless else 'Lossy' if lossy else 'Encoding unknown')
    return ' · '.join(parts)


def output_info(data):
    ao, params = data.get('current-ao'), data.get('audio-out-params')
    if not ao or not isinstance(params, dict):
        return 'No active audio output'
    parts = [str(ao)]
    if params.get('samplerate'):
        parts.append(f"{params['samplerate'] / 1000:g} kHz")
    if params.get('format'):
        parts.append(str(params['format']))
    if params.get('hr-channels') or params.get('channels'):
        parts.append(str(params.get('hr-channels') or params['channels']))
    return ' · '.join(parts)
