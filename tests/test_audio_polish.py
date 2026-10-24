"""Confirmed backend facts and native gapless output; no speaker assumptions."""
import importlib.util
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import wave

from test_playback import tone
from hiby_music_tools.playback.audio import source_info, output_info


class AudioPolishTests(unittest.TestCase):
    def test_diagnostics_do_not_claim_unknown_output_or_source_depth(self):
        self.assertEqual(output_info({}), 'No active audio output')
        text = source_info(dict(codec='flac', sample_rate=96000, bit_depth=24))
        self.assertIn('Lossless', text)
        self.assertIn('96 kHz', text)
        self.assertIn('Lossy', source_info(dict(codec='aac', bitrate=256000)))
        self.assertNotIn('bit', source_info(dict(codec='alac')))
        self.assertIn('float', output_info({'current-ao': 'pipewire', 'audio-out-params': {'format': 'float', 'samplerate': 48000}}))

    @unittest.skipUnless(shutil.which('mpv') and shutil.which('ffmpeg'), 'Install mpv and FFmpeg')
    def test_native_gapless_flac_and_mp3_encoder_padding_produce_exact_pcm_lengths(self):
        # File-output driver verifies decoder/playlist continuity, not speakers or
        # PipeWire timing. Distinct, continuous halves make a missing boundary
        # sample or inserted silence observable in the FLAC byte comparison.
        with tempfile.TemporaryDirectory(prefix='hiby-gapless-') as temp:
            root = Path(temp)
            wav = root / 'whole.wav'
            tone(wav, .8)
            with wave.open(str(wav), 'rb') as stream:
                pcm = stream.readframes(stream.getnframes())
            halves = [pcm[:len(pcm)//2], pcm[len(pcm)//2:]]
            for codec in ('flac', 'mp3'):
                paths = []
                for i, data in enumerate(halves):
                    source = root / f'{i}.wav'
                    with wave.open(str(source), 'wb') as stream:
                        stream.setparams((1, 2, 44100, 0, 'NONE', 'not compressed'))
                        stream.writeframes(data)
                    target = root / f'{i}.{codec}'
                    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(source), str(target)], check=True, capture_output=True)
                    paths.append(str(target))
                output = root / (codec + '.pcm')
                process = subprocess.run(['mpv', '--no-config', '--load-scripts=no', '--video=no', '--terminal=no',
                    '--ao=pcm', '--ao-pcm-file=' + str(output), '--ao-pcm-waveheader=no', '--audio-format=s16',
                    '--gapless-audio=weak', '--replaygain=no', '--af=', '--', *paths], capture_output=True, timeout=20)
                self.assertEqual(process.returncode, 0, process.stderr)
                result = output.read_bytes()
                self.assertEqual(len(result), len(pcm), f'{codec} encoder delay/padding or boundary length changed')
                if codec == 'flac': self.assertEqual(result, pcm)
                self.assertTrue(any(struct.unpack('<' + 'h' * (len(result)//2), result)))

    @unittest.skipUnless(shutil.which('dbus-run-session') and shutil.which('gdbus') and importlib.util.find_spec('dbus_next'), 'Install dbus-next and D-Bus tools')
    def test_real_isolated_mpris_session(self):
        result = subprocess.run(['dbus-run-session', '--', sys.executable, str(Path(__file__).with_name('mpris_fixture.py'))],
                                capture_output=True, text=True, timeout=25, env=dict(os.environ))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('verified', result.stdout)
