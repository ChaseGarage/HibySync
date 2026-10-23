"""Apple catalog integration with mocked HTTP and real cached image decoding."""

import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import urllib.error

from PIL import Image
from test_baseline import ROOT
from hiby_music_tools import online_art
from hiby_music_tools.core.apple_art import search_apple
from hiby_music_tools.core.interaction import Cancelled, Operation


class AppleArtTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='hiby-apple-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.document = {'results': [dict(artistName='Artist', collectionName='Album',
                                         releaseDate='2024-01-01',
                                         artworkUrl100='https://is1-ssl.mzstatic.com/image/100x100bb.jpg')]}

    def image(self, size):
        output = io.BytesIO()
        Image.new('RGB', size, 'blue').save(output, 'JPEG')
        return output.getvalue()

    def test_high_resolution_results_are_cached_without_auto_selection(self):
        def request(url, **options):
            return json.dumps(self.document).encode() if '/search?' in url else self.image((1200, 900))
        with mock.patch.object(online_art, 'request_bytes', side_effect=request) as network:
            results = search_apple('Artist', 'Album', cache_dir=self.root)
            self.assertEqual((results[0].width, results[0].height), (1200, 900))
            self.assertEqual(results[0].origin, 'apple')
            self.assertTrue(any('1200x1200' in call.args[0] for call in network.call_args_list))
        with mock.patch.object(online_art, 'request_bytes', side_effect=AssertionError('cache miss')):
            self.assertEqual(search_apple('Artist', 'Album', cache_dir=self.root), results)

    def test_fallback_reports_real_resolution_and_empty_results(self):
        def request(url, **options):
            if '/search?' in url:
                return json.dumps(self.document).encode()
            if '1200x1200' in url:
                raise urllib.error.HTTPError(url, 404, 'not found', {}, None)
            return self.image((600, 600))
        with mock.patch.object(online_art, 'request_bytes', side_effect=request):
            self.assertEqual(search_apple('Artist', 'Album', cache_dir=self.root)[0].width, 600)
        with mock.patch.object(online_art, 'request_bytes', return_value=b'{"results": []}'):
            self.assertEqual(search_apple('Other', 'Missing', cache_dir=self.root), [])

    def test_cancellation_and_network_failures_are_reported(self):
        op = Operation()
        op.cancelled.set()
        with self.assertRaises(Cancelled):
            search_apple('Artist', 'Album', op, self.root)
        with mock.patch.object(online_art, 'request_bytes', side_effect=OSError('offline')):
            with self.assertRaisesRegex(OSError, 'offline'):
                search_apple('Artist', 'Album', cache_dir=self.root)

    def test_cancellable_retry_wait(self):
        op = Operation()
        def unavailable(*args, **kwargs):
            op.cancelled.set()
            raise urllib.error.HTTPError(args[0].full_url, 503, 'unavailable', {}, None)
        with mock.patch.object(online_art.urllib.request, 'urlopen', side_effect=unavailable):
            with self.assertRaises(Cancelled):
                online_art.request_bytes('https://itunes.apple.com/search', operation=op)
