"""HibySync graphical launcher; parse --help without requiring Qt."""

import argparse
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description='HibySync native music review application')
    parser.add_argument('--inbox', type=Path, help='incoming folder (default: ~/Music/Nicotine)')
    parser.add_argument('--library', type=Path, help='library folder (default: ~/Music/Library)')
    parser.add_argument('--widgets', action='store_true', help='launch the previous Qt Widgets interface')
    args = parser.parse_args()
    try:
        from PySide6.QtGui import QGuiApplication
    except ImportError:
        parser.exit(2, 'Install GUI dependencies: pip install "hiby-music-tools[gui]"\n'
                       'On CachyOS/Arch: sudo pacman -S pyside6\n')
    from PySide6.QtCore import QCoreApplication, QEvent
    if args.widgets:
        from PySide6.QtWidgets import QApplication
        app = QApplication([sys.argv[0]])
    else:
        app = QGuiApplication([sys.argv[0]])
    app.setApplicationName('HibySync')
    app.setOrganizationName('HibySync')
    if args.widgets:
        from .window import MainWindow
        window = MainWindow(args.inbox, args.library)
        window.show()
        result = app.exec()
        if window.task:
            window.task.cancel()
            window.task.wait()
        window.deleteLater()
    else:
        from .quick import create_engine
        from hiby_music_tools.playback.state import state_path
        engine, controller = create_engine(args.inbox, args.library, player_state=state_path())
        if not engine.rootObjects():
            controller.shutdown()
            engine.library_controller.shutdown()
            engine.player_controller.shutdown()
            print('\n'.join(engine.load_errors) or 'Unable to load the HibySync QML interface.', file=sys.stderr)
            return 2
        result = app.exec()
        controller.shutdown()
        engine.library_controller.shutdown()
        engine.player_controller.shutdown()
        engine.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        engine.library_controller.deleteLater()
        engine.player_controller.deleteLater()
        controller.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    return result
