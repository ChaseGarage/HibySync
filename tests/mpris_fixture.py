"""Isolated real session-bus integration; launched only by test_audio_polish."""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['QT_QUICK_BACKEND'] = 'software'
import subprocess
import tempfile
from pathlib import Path
from test_baseline import make_track  # Bootstrap src for a standalone subprocess.
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest
from hiby_music_tools.gui.quick import create_engine
from hiby_music_tools.library.indexer import refresh
from hiby_music_tools.library.playback import tracks
from hiby_music_tools.playback.mpris import Mpris, NAME, PATH
from test_player_gui import FakeAudio

app = QGuiApplication.instance() or QGuiApplication([])

def wait(condition):
    for _ in range(600):
        if condition(): return
        QTest.qWait(10)
    raise AssertionError('Timed out')

def call(method, *arguments):
    process = subprocess.Popen(['gdbus', 'call', '--session', '--dest', NAME, '--object-path', PATH,
                                '--method', method, *arguments], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    wait(lambda: process.poll() is not None)
    out, err = process.communicate()
    assert process.returncode == 0, err
    return out

with tempfile.TemporaryDirectory(prefix='hiby-mpris-test-') as temp:
    base = Path(temp)
    root, database = base / 'music', base / 'index.sqlite3'
    for i in range(2): make_track(root / f'{i}.wav')
    from PIL import Image
    Image.new('RGB',(48,48),'green').save(root / 'cover.png')
    refresh(root, database)
    audio = FakeAudio()
    engine, importer = create_engine(base / 'inbox', root, library_database=database, playback_service=audio,
                                     player_state=base / 'player.json', enable_mpris=True)
    p = engine.player_controller
    duplicate = None
    try:
        wait(lambda: p.mediaStatus == 'MPRIS connected')
        wait(lambda: not p.busy)
        rows = tracks(root, database)
        p.playRows(rows)
        wait(lambda: p.state == 'playing')
        QTest.qWait(120)
        out = call('org.freedesktop.DBus.Properties.Get', 'org.mpris.MediaPlayer2.Player', 'Metadata')
        assert 'int64' in out and 'objectpath' in out and rows[0]['title'] in out, out
        assert 'mpris:artUrl' in out and 'file://' in out, out
        qid = p.currentQueueId
        call('org.mpris.MediaPlayer2.Player.SetPosition', '/org/mpris/MediaPlayer2/track/' + qid, '2000000')
        wait(lambda: p.position == 2)
        call('org.mpris.MediaPlayer2.Player.Seek', '1000000')
        wait(lambda: p.position == 3)
        assert 'int64' in call('org.freedesktop.DBus.Properties.Get', 'org.mpris.MediaPlayer2.Player', 'Position')
        assert 'Playing' in call('org.freedesktop.DBus.Properties.Get', 'org.mpris.MediaPlayer2.Player', 'PlaybackStatus')
        call('org.mpris.MediaPlayer2.Player.Pause')
        wait(lambda: p.state == 'paused')
        call('org.mpris.MediaPlayer2.Player.Play')
        wait(lambda: p.state == 'playing')
        call('org.mpris.MediaPlayer2.Player.Next')
        wait(lambda: p.currentTrackId == rows[1]['id'])
        call('org.freedesktop.DBus.Properties.Set', 'org.mpris.MediaPlayer2.Player', 'Volume', '<0.42>')
        wait(lambda: p.volume == 42)
        call('org.mpris.MediaPlayer2.Player.Stop')
        wait(lambda: p.state == 'stopped')
        call('org.mpris.MediaPlayer2.Player.Previous')
        wait(lambda: p.currentTrackId == rows[0]['id'])
        assert p.state == 'stopped'
        duplicate = Mpris(p, engine.rootObjects()[0], database.parent / 'artwork')
        wait(lambda: 'Another HibySync' in p.mediaStatus)
        assert 'HibySync' in call('org.freedesktop.DBus.Properties.Get', 'org.mpris.MediaPlayer2', 'Identity')
        assert engine.load_errors == [], engine.load_errors
    finally:
        if duplicate: duplicate.shutdown()
        engine.mpris.shutdown()
        for obj in (engine.playlist_controller, engine.deletion_controller, engine.metadata_controller,
                    p, engine.library_controller, importer): obj.shutdown()
print('MPRIS real bus controls, typed metadata and duplicate protection verified')
