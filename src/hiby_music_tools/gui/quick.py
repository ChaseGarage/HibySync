"""QML engine setup, font selection, and explicit presentation lifecycle."""

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QFont, QFontDatabase, QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from .controller import ReviewController
from .library_controller import LibraryController
from .player_controller import PlayerController


def set_interface_font():
    available = set(QFontDatabase.families())
    family = next((name for name in ('Inter', 'Adwaita Sans', 'Noto Sans', 'DejaVu Sans',
                                     'Liberation Sans') if name in available), 'sans-serif')
    font = QFont(family)
    font.setStyleHint(QFont.StyleHint.SansSerif)
    font.setPixelSize(14)
    QGuiApplication.instance().setFont(font)
    return family


def create_engine(inbox=None, library=None, *, library_database=None, player_state=None, playback_service=None):
    family = set_interface_font()
    # Keep native wheel acceleration and pixel-based touchpad gestures, while
    # making mouse-wheel notches cover a useful distance in long music lists.
    hints = QGuiApplication.styleHints()
    hints.setWheelScrollLines(max(9, hints.wheelScrollLines()))
    engine = QQmlApplicationEngine()
    engine.load_errors = []
    engine.warnings.connect(lambda warnings: engine.load_errors.extend(error.toString() for error in warnings))
    controller = ReviewController(inbox, library)
    library_controller = LibraryController(controller, library_database)
    player = PlayerController(library_controller, service=playback_service,
                              state_file=player_state, persist=player_state is not None)
    # Keep both Python wrappers alive for the entire engine lifetime. Qt owns
    # the provider after registration; the controller only registers thumbnails.
    engine.review_controller = controller
    engine.library_controller = library_controller
    engine.player_controller = player
    engine.addImageProvider('artwork', controller.provider)
    engine.addImageProvider('library', library_controller.provider)
    engine.rootContext().setContextProperty('reviewController', controller)
    engine.rootContext().setContextProperty('libraryBrowser', library_controller)
    engine.rootContext().setContextProperty('playback', player)
    controller.changed.connect(library_controller.syncRoot)
    controller.libraryChanged.connect(library_controller.markChanged)
    library_controller.navigationRequested.connect(lambda: controller.navigate('library'))
    engine.rootContext().setContextProperty('interfaceFontFamily', family)
    controller.navigate('library')
    engine.load(QUrl.fromLocalFile(str(Path(__file__).parent / 'qml/Main.qml')))
    return engine, controller
