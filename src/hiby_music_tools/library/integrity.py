"""Verify encoded packets and decoded samples without rewriting audio files."""

import json
import shutil
import subprocess

from hiby_music_tools.core.interaction import Operation


def run(argv, operation):
    with subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as process:
        try:
            while True:
                operation.checkpoint()
                try:
                    output, error = process.communicate(timeout=.1)
                    break
                except subprocess.TimeoutExpired:
                    continue
            if process.returncode:
                raise ValueError(error.decode('utf-8', 'replace').strip() or 'Audio verification failed')
            return output
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()


def audio_fingerprint(path, operation=None):
    op = operation or Operation()
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        raise ValueError('Library saves require ffmpeg/ffprobe for audio verification: sudo pacman -S ffmpeg')
    packets = run(['ffmpeg', '-v', 'error', '-nostdin', '-i', str(path), '-map', '0:a',
                   '-c', 'copy', '-f', 'streamhash', '-hash', 'sha256', '-'], op)
    samples = run(['ffmpeg', '-v', 'error', '-nostdin', '-threads', '1', '-i', str(path),
                   '-map', '0:a', '-c:a', 'pcm_f64le', '-f', 'streamhash', '-hash', 'sha256', '-'], op)
    streams = json.loads(run(['ffprobe', '-v', 'error', '-select_streams', 'a', '-show_streams',
                              '-show_data_hash', 'sha256', '-of', 'json', str(path)], op))['streams']
    if not streams or not packets.strip():
        raise ValueError('No verifiable audio stream')
    fields = ('codec_name', 'sample_rate', 'channels', 'channel_layout', 'bits_per_sample',
              'bits_per_raw_sample', 'extradata_hash')
    return packets, samples, [{key: stream.get(key) for key in fields
                      if key != 'extradata_hash' or stream.get('codec_name') != 'vorbis'} for stream in streams]
