"""HibySync navigation and read-only scan/review workflow."""

from pathlib import Path

from PySide6.QtCore import QSize, QSortFilterProxyModel, Qt
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListView,
                               QListWidget, QMainWindow, QMessageBox, QProgressBar,
                               QPushButton, QScrollArea, QSplitter, QStackedWidget,
                               QTableView, QVBoxLayout, QWidget)

from hiby_music_tools.core.review import build_plan
from hiby_music_tools.core.scan import scan_inbox
from hiby_music_tools.paths import library_dir
from .details import AlbumDetails
from .models import AlbumModel, PreviewModel
from .workers import Task


class MainWindow(QMainWindow):
    def __init__(self, inbox=None, library=None):
        super().__init__()
        self.setWindowTitle('HibySync')
        self.resize(1180, 850)
        self.session = None
        self.task = None
        self.closing = False
        self.preview_dialog = None
        central = QWidget()
        layout = QHBoxLayout(central)
        self.setCentralWidget(central)
        nav = QListWidget()
        nav.addItems(['Import', 'Library', 'Device Sync'])
        nav.setFixedWidth(150)
        nav.setSpacing(8)
        self.pages = QStackedWidget()
        nav.currentRowChanged.connect(self.pages.setCurrentIndex)
        layout.addWidget(nav)
        layout.addWidget(self.pages, 1)

        page = QWidget()
        page_layout = QVBoxLayout(page)
        heading = QLabel('Import music')
        heading.setStyleSheet('font-size: 26px; font-weight: 600;')
        page_layout.addWidget(heading)
        page_layout.addWidget(QLabel('Scan → Review albums → Preview. All changes stay in memory.'))
        self.path_controls = QWidget()
        paths = QVBoxLayout(self.path_controls)
        paths.setContentsMargins(0, 0, 0, 0)
        self.inbox = QLineEdit(str(inbox or Path.home() / 'Music/Nicotine'))
        self.library = QLineEdit(str(library or library_dir()))
        self.inbox.textChanged.connect(self.paths_changed)
        self.library.textChanged.connect(self.paths_changed)
        for label, field in (('Incoming', self.inbox), ('Library', self.library)):
            row = QHBoxLayout()
            row.addWidget(QLabel(label))
            row.addWidget(field, 1)
            browse = QPushButton('Browse…')
            browse.clicked.connect(lambda checked=False, target=field: self.browse(target))
            row.addWidget(browse)
            paths.addLayout(row)
        page_layout.addWidget(self.path_controls)
        buttons = QHBoxLayout()
        self.scan_button = QPushButton('Scan incoming folder')
        self.scan_button.clicked.connect(self.start_scan)
        self.cancel_button = QPushButton('Cancel')
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel)
        self.filter = QComboBox()
        self.filter.addItems(['All albums', 'Needs Review', 'Error', 'Ready'])
        self.filter.currentIndexChanged.connect(self.filter_albums)
        buttons.addWidget(self.scan_button)
        buttons.addWidget(self.cancel_button)
        buttons.addStretch()
        buttons.addWidget(self.filter)
        page_layout.addLayout(buttons)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        page_layout.addWidget(self.progress)
        self.message = QLabel('Choose the incoming folder, then scan. No files will be changed.')
        self.message.setWordWrap(True)
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        page_layout.addWidget(self.message)
        splitter = QSplitter()
        self.albums = QListView()
        self.albums.setIconSize(QSize(56, 56))
        self.albums.setMinimumWidth(290)
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setFilterRole(Qt.ItemDataRole.UserRole)
        self.albums.setModel(self.proxy)
        self.albums.selectionModel().currentChanged.connect(self.select_album)
        self.details = AlbumDetails()
        self.details.changed.connect(self.review_changed)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.details)
        splitter.addWidget(self.albums)
        splitter.addWidget(scroll)
        splitter.setStretchFactor(1, 2)
        page_layout.addWidget(splitter, 1)
        footer = QHBoxLayout()
        self.preview_button = QPushButton('Preview import plan…')
        self.preview_button.setEnabled(False)
        self.preview_button.clicked.connect(self.start_preview)
        import_button = QPushButton('Import (pending)')
        import_button.setToolTip('Import execution is planned for milestone 3.')
        import_button.setEnabled(False)
        footer.addStretch()
        footer.addWidget(self.preview_button)
        footer.addWidget(import_button)
        page_layout.addLayout(footer)
        self.pages.addWidget(page)
        for title, explanation in (
            ('Library', 'Library management is planned. Use the existing sanitizer CLI for now.'),
            ('Device Sync', 'Device integration is planned. The existing musicsync CLI remains available.')):
            placeholder = QWidget()
            box = QVBoxLayout(placeholder)
            box.addWidget(QLabel(f'{title} — pending implementation'))
            box.addWidget(QLabel(explanation))
            box.addStretch()
            self.pages.addWidget(placeholder)
        nav.setCurrentRow(0)

    def browse(self, field):
        folder = QFileDialog.getExistingDirectory(self, 'Choose directory', field.text())
        if folder:
            field.setText(folder)

    def set_busy(self, busy):
        self.scan_button.setEnabled(not busy)
        self.cancel_button.setEnabled(busy)
        self.path_controls.setEnabled(not busy)
        self.filter.setEnabled(not busy)
        self.albums.setEnabled(not busy)
        self.details.setEnabled(not busy and self.details.album is not None)
        self.preview_button.setEnabled(not busy and self.paths_match())

    def paths_match(self):
        return self.session is not None and (
            Path(self.inbox.text()).expanduser().absolute() == self.session.source and
            Path(self.library.text()).expanduser().absolute() == self.session.library)

    def paths_changed(self):
        if self.session:
            self.preview_button.setEnabled(self.task is None and self.paths_match())
            if not self.paths_match():
                self.message.setText('Paths changed. Scan again to update the review and preview.')

    def start_task(self, function, kind):
        self.kind = kind
        self.set_busy(True)
        self.task = Task(function, self)
        self.task.progress.connect(self.show_progress)
        self.task.result.connect(self.task_result)
        self.task.failed.connect(self.task_error)
        self.task.cancelled.connect(self.task_cancelled)
        self.task.finished.connect(self.task_finished)
        self.task.start()

    def start_scan(self):
        if self.task:
            return
        if self.session:
            answer = QMessageBox.question(self, 'Replace current review?',
                                          'Scanning again discards pending edits. Continue?',
                                          defaultButton=QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
        source, library = Path(self.inbox.text()), Path(self.library.text())
        self.start_task(lambda op: scan_inbox(source, library, op), 'scan')

    def start_preview(self):
        if self.paths_match() and not self.task:
            self.start_task(lambda op: build_plan(self.session, op), 'preview')

    def show_progress(self, event):
        self.progress.setRange(0, 0 if event.total is None else max(1, event.total))
        self.progress.setValue(event.completed)
        self.message.setText(f'{event.phase}: {event.current}')

    def task_result(self, value):
        if self.closing:
            return
        if self.kind == 'scan':
            self.session = value
            self.inbox.setText(str(value.source))
            self.library.setText(str(value.library))
            old_model = self.proxy.sourceModel()
            self.album_model = AlbumModel(value.albums, self)
            self.proxy.setSourceModel(self.album_model)
            if old_model:
                old_model.deleteLater()
            self.details.set_album(None)
            self.message.setText(
                f'{len(value.albums)} albums · {sum(len(a.tracks) for a in value.albums)} tracks. '
                'No files changed. Audio duplicate comparison and online suggestions are pending. ' + '\n'.join(value.warnings))
            if self.proxy.rowCount():
                self.albums.setCurrentIndex(self.proxy.index(0, 0))
        else:
            self.show_preview(value)

    def task_error(self, message):
        self.message.setText(f'Error: {message}')
        self.progress.setRange(0, 1)
        self.progress.setValue(0)

    def task_cancelled(self):
        self.message.setText('Cancelled. No files were changed; the previous review is retained.')
        self.progress.setRange(0, 1)
        self.progress.setValue(0)

    def task_finished(self):
        task = self.task
        self.task = None
        task.deleteLater()
        self.set_busy(False)
        if self.closing:
            self.close()

    def select_album(self, index, previous=None):
        source = self.proxy.mapToSource(index)
        album = self.session.albums[source.row()] if source.isValid() and self.session else None
        self.details.set_album(album)

    def filter_albums(self):
        status = self.filter.currentText()
        self.proxy.setFilterFixedString('' if status == 'All albums' else status)

    def review_changed(self):
        self.album_model.refresh()
        self.message.setText('Pending edits updated. Preview the plan to inspect destinations and changes.')

    def show_preview(self, rows):
        dialog = QDialog(self)
        self.preview_dialog = dialog
        dialog.setWindowTitle('Import preview — no files will be written')
        dialog.resize(1100, 600)
        layout = QVBoxLayout(dialog)
        label = QLabel(f'{len(rows)} tracks · {sum(row.action == "Skip" for row in rows)} skipped. '
                       'Preview only; metadata/artwork edits are not saved on exit.\n'
                       f'Incoming: {self.session.source}\nLibrary: {self.session.library}')
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        layout.addWidget(label)
        table = QTableView()
        table.setModel(PreviewModel(rows, table))
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setWordWrap(False)
        for column, width in enumerate((120, 240, 300, 300, 240, 300)):
            table.setColumnWidth(column, width)
        layout.addWidget(table)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.close)
        layout.addWidget(buttons)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.show()

    def cancel(self):
        if self.task:
            self.task.cancel()
            self.cancel_button.setEnabled(False)
            self.message.setText('Cancelling after the current file…')

    def closeEvent(self, event):
        if self.task:
            self.closing = True
            self.cancel()
            event.ignore()
        else:
            event.accept()
