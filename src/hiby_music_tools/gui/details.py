"""Album review form. All edits change only the in-memory session."""

from dataclasses import replace

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QPlainTextEdit, QVBoxLayout, QWidget)

from hiby_music_tools.core.review import edit_album


class AlbumDetails(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.album = None
        layout = QVBoxLayout(self)
        self.heading = QLabel('Select an album to review')
        self.heading.setTextFormat(Qt.TextFormat.PlainText)
        self.heading.setStyleSheet('font-size: 20px; font-weight: 600;')
        layout.addWidget(self.heading)
        self.summary = QLabel()
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.skip = QCheckBox('Skip this album in the import plan')
        self.skip.toggled.connect(self.skip_album)
        layout.addWidget(self.skip)

        album_box = QGroupBox('Album metadata — proposed values')
        form = QFormLayout(album_box)
        self.artist, self.title, self.year = QLineEdit(), QLineEdit(), QLineEdit()
        form.addRow('Album artist', self.artist)
        form.addRow('Album title', self.title)
        form.addRow('Release year', self.year)
        apply_album = QPushButton('Apply album fields to all tracks')
        apply_album.clicked.connect(self.apply_album)
        form.addRow(apply_album)
        layout.addWidget(album_box)

        track_box = QGroupBox('Track review')
        form = QFormLayout(track_box)
        self.tracks = QComboBox()
        self.tracks.currentIndexChanged.connect(self.select_track)
        form.addRow('Track', self.tracks)
        self.original = QPlainTextEdit()
        self.original.setReadOnly(True)
        self.original.setMaximumHeight(115)
        form.addRow('Original tags', self.original)
        self.provenance = QLabel()
        self.provenance.setTextFormat(Qt.TextFormat.PlainText)
        form.addRow('Proposal source', self.provenance)
        self.track_artist, self.track_title = QLineEdit(), QLineEdit()
        self.track_number, self.disc_number = QLineEdit(), QLineEdit()
        form.addRow('Track artist', self.track_artist)
        form.addRow('Track title', self.track_title)
        form.addRow('Track number', self.track_number)
        form.addRow('Disc number', self.disc_number)
        apply_track = QPushButton('Apply track fields')
        apply_track.clicked.connect(self.apply_track)
        form.addRow(apply_track)
        layout.addWidget(track_box)

        artwork_box = QGroupBox('Artwork — local preview')
        art_layout = QVBoxLayout(artwork_box)
        self.art = QComboBox()
        self.art.setMinimumContentsLength(16)
        self.art.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.art.currentIndexChanged.connect(self.show_art)
        art_layout.addWidget(self.art)
        self.image = QLabel('No artwork')
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setMinimumHeight(120)
        art_layout.addWidget(self.image)
        buttons = QHBoxLayout()
        choose = QPushButton('Use for track')
        choose.clicked.connect(lambda: self.apply_art(False))
        all_tracks = QPushButton('Use for album')
        all_tracks.clicked.connect(lambda: self.apply_art(True))
        buttons.addWidget(choose)
        buttons.addWidget(all_tracks)
        art_layout.addLayout(buttons)
        pending = QLabel('Online artwork and manual image selection: next milestone')
        pending.setWordWrap(True)
        art_layout.addWidget(pending)
        layout.removeWidget(album_box)
        top = QWidget()
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.addWidget(album_box, 1)
        top_layout.addWidget(artwork_box, 1)
        layout.insertWidget(3, top)
        layout.addStretch()
        self.setEnabled(False)

    def set_album(self, album):
        self.album = album
        self.setEnabled(album is not None)
        if not album:
            self.heading.setText('Select an album to review')
            self.summary.clear()
            self.original.clear()
            self.provenance.clear()
            for field in (self.artist, self.title, self.year, self.track_artist,
                          self.track_title, self.track_number, self.disc_number):
                field.clear()
            self.tracks.clear()
            self.art.clear()
            self.image.setText('No artwork')
            return
        self.refresh_summary()
        self.skip.blockSignals(True)
        self.skip.setChecked(album.skip)
        self.skip.blockSignals(False)
        first = album.tracks[0].proposed
        self.artist.setText(first.album_artist or first.artist or '')
        self.title.setText(first.album or '')
        self.year.setText(first.year or '')
        for widget, attribute in ((self.artist, 'album_artist'), (self.title, 'album'), (self.year, 'year')):
            if len({getattr(t.proposed, attribute) for t in album.tracks}) > 1:
                widget.setToolTip('Mixed values. Applying replaces this field for every track.')
            else:
                widget.setToolTip('Changes stay pending until Apply is clicked.')
        self.tracks.blockSignals(True)
        self.tracks.clear()
        self.tracks.addItems([t.path.name for t in album.tracks])
        self.tracks.blockSignals(False)
        self.select_track(0)

    def refresh_summary(self):
        album = self.album
        self.heading.setText(f'{album.artist} · {album.title}')
        reasons = sorted({reason for t in album.tracks for reason in ([t.error] if t.error else t.reasons)})
        self.summary.setText(f'{album.status} · {album.year} · {len(album.tracks)} tracks\n' +
                             '\n'.join(reasons))

    def current_track(self):
        index = self.tracks.currentIndex()
        return self.album.tracks[index] if self.album and index >= 0 else None

    def select_track(self, index):
        track = self.current_track()
        if track is None:
            return
        original = track.original
        self.original.setPlainText(
            f'Album artist: {original.album_artist or "∅"}\n'
            f'Album: {original.album or "∅"} · Year: {original.year or "∅"}\n'
            f'Artist: {original.track_artist or "∅"} · Title: {original.title or "∅"}\n'
            f'Track: {track.original_track_number or "∅"} · Disc: {track.original_disc_number or "∅"}')
        self.provenance.setText(track.provenance)
        self.track_artist.setText(track.proposed.track_artist or '')
        self.track_title.setText(track.proposed.title or '')
        self.track_number.setText(track.track_number)
        self.disc_number.setText(track.disc_number)
        self.art.blockSignals(True)
        self.art.clear()
        for candidate in track.artwork:
            self.art.addItem(f'{candidate.label} · {candidate.width}×{candidate.height} · {candidate.origin}', candidate)
        if track.selected_art:
            if track.selected_art not in track.artwork:
                self.art.addItem(track.selected_art.label, track.selected_art)
            for i in range(self.art.count()):
                if self.art.itemData(i) == track.selected_art:
                    self.art.setCurrentIndex(i)
                    break
        self.art.blockSignals(False)
        self.show_art()

    def show_art(self, *args):
        candidate = self.art.currentData()
        self.image.clear()
        if candidate:
            pixmap = QPixmap()
            pixmap.loadFromData(candidate.thumbnail)
            self.image.setPixmap(pixmap.scaled(160, 160, Qt.AspectRatioMode.KeepAspectRatio,
                                              Qt.TransformationMode.SmoothTransformation))
        else:
            self.image.setText('No artwork available')

    def apply_album(self):
        if self.album:
            edit_album(self.album, self.artist.text().strip(), self.title.text().strip(), self.year.text().strip())
            self.refresh_summary()
            self.select_track(self.tracks.currentIndex())
            self.changed.emit()

    def apply_track(self):
        track = self.current_track()
        if track:
            artist = self.track_artist.text().strip() or None
            track.proposed = replace(track.proposed, track_artist=artist,
                                     artist=track.proposed.album_artist or artist,
                                     title=self.track_title.text().strip() or None)
            track.track_number = self.track_number.text().strip()
            track.disc_number = self.disc_number.text().strip()
            track.provenance = 'Manual edit'
            self.refresh_summary()
            self.provenance.setText(track.provenance)
            self.changed.emit()

    def apply_art(self, entire_album):
        candidate = self.art.currentData()
        if candidate and self.album:
            targets = self.album.tracks if entire_album else [self.current_track()]
            for track in targets:
                track.selected_art = candidate
                track.artwork_approved = True
            self.refresh_summary()
            self.changed.emit()

    def skip_album(self, checked):
        if self.album:
            self.album.skip = checked
            self.changed.emit()
