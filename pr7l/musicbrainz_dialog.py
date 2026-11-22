"""MusicBrainz tag source: search, pick a release, line its tracks up with the files, write. (Mock-up.)"""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSize, Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QPushButton, QSplitter, QTreeView, QVBoxLayout, QWidget)

from . import theme
from .widgets import Header


class Table(QAbstractTableModel):
    def __init__(self, columns, rows, mark=None, parent=None):
        super().__init__(parent)
        self.columns, self.rows, self.mark = columns, rows, mark or (lambda r, c: None)

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.columns)

    def headerData(self, s, o, role=Qt.DisplayRole):
        return self.columns[s].upper() if o == Qt.Horizontal and role == Qt.DisplayRole else None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        if role == Qt.DisplayRole:
            return self.rows[index.row()][index.column()]
        if role == Qt.ForegroundRole:
            return self.mark(self.rows[index.row()], index.column())
        if role == Qt.TextAlignmentRole and self.columns[index.column()] in ("#", "Score", "Length", "File length",
                                                                              "Tracks"):
            return int(Qt.AlignRight | Qt.AlignVCenter)
        return None


RESULTS = [
    ("100", "ELSEWORLD", "Paragon", "2026-11-20", "XW", "Paragon Productions", "Digital Media", "9"),
    ("88", "ELSEWORLD (Instrumentals)", "Paragon", "2026-12-04", "XW", "Paragon Productions", "Digital Media", "9"),
    ("61", "Elseworld", "Various Artists", "2019-03-08", "GB", "Nuclear Blast", "CD", "14"),
]

TRACKS = [  # (#, MusicBrainz title, length, file, file length)
    ("1", "Portal", "4:12", "01 Portal.flac", "4:12"),
    ("2", "Ruins of Elsewhere", "5:47", "02 Ruins of Elsewhere.flac", "5:47"),
    ("3", "Static Bloom", "4:31", "03 Static Bloom.flac", "4:31"),
    ("4", "Signal Lost", "3:58", "04 Signal Lost.mp3", "3:58"),
    ("5", "Arc Light", "6:20", "05 Arc Light.mp3", "6:20"),
    ("6", "The Long Collapse", "7:03", "06 The Long Collapse.flac", "7:03"),
    ("7", "Afterimage", "4:44", "07 Afterimage.m4a", "4:44"),
    ("8", "Neon Requiem", "5:16", "08 Neon Requiem.flac", "5:16"),
    ("9", "Elseworld", "8:52", "09 Elseworld.flac", "8:52"),
]


def _view(model) -> QTreeView:
    v = QTreeView()
    v.setRootIsDecorated(False)
    v.setAlternatingRowColors(True)
    v.setSelectionBehavior(QAbstractItemView.SelectRows)
    v.setUniformRowHeights(True)
    v.setModel(model)
    v.header().setStretchLastSection(True)
    v.header().setSectionResizeMode(QHeaderView.Interactive)
    return v


class MusicBrainzDialog(QDialog):
    def __init__(self, parent=None, cover_path: str | None = None):
        super().__init__(parent)
        self.setWindowTitle("MusicBrainz")
        self.resize(1320, 820)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 16)
        root.setSpacing(0)
        root.addWidget(Header("MUSICBRAINZ"))
        body = QVBoxLayout()
        body.setContentsMargins(20, 10, 20, 0)
        search = QHBoxLayout()
        for label, value in (("Artist", "Paragon"), ("Album", "ELSEWORLD")):
            lab = QLabel(label.upper())
            lab.setProperty("role", "field")
            search.addWidget(lab)
            e = QLineEdit(value)
            search.addWidget(e, 1)
        go = QPushButton("Search")
        search.addWidget(go)
        body.addLayout(search)
        results = Table(["Score", "Title", "Artist", "Date", "Country", "Label", "Format", "Tracks"], RESULTS)
        rv = _view(results)
        rv.setMinimumHeight(170)
        rv.setMaximumHeight(190)
        for i, w in enumerate([70, 280, 170, 110, 80, 200, 140]):
            rv.header().resizeSection(i, w)
        rv.setCurrentIndex(results.index(0, 0))
        body.addWidget(rv)

        split = QSplitter(Qt.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 8, 0)
        rel = QGroupBox("RELEASE")
        g = QGridLayout(rel)
        for r, (k, v) in enumerate((("Album", "ELSEWORLD"), ("Album artist", "Paragon"), ("Year", "2026"),
                                    ("Genre", "Progressive Metal"), ("Label", "Paragon Productions"),
                                    ("Catalog #", "PRGN-007"), ("Type", "Album"), ("Release ID",
                                                                                   "6f1c0d6e-...-a3e2"))):
            lab = QLabel(k.upper())
            lab.setProperty("role", "field")
            g.addWidget(lab, r, 0)
            g.addWidget(QLineEdit(v), r, 1)
        ll.addWidget(rel)
        cov = QGroupBox("COVER ART ARCHIVE")
        cl = QVBoxLayout(cov)
        img = QLabel()
        img.setFixedSize(QSize(200, 200))
        img.setAlignment(Qt.AlignCenter)
        img.setStyleSheet(f"background: {theme.WIDGET}; border: 1px solid {theme.PANEL_EDGE}; border-radius: 6px;")
        if cover_path:
            img.setPixmap(QPixmap(cover_path).scaled(196, 196, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        row = QHBoxLayout()
        row.addWidget(img)
        opts = QVBoxLayout()
        info = QLabel("Front  1200 x 1200  JPEG")
        info.setProperty("role", "dim")
        opts.addWidget(info)
        save = QCheckBox("Save cover in files")
        save.setChecked(True)
        opts.addWidget(save)
        opts.addWidget(QCheckBox("Also save as folder.jpg"))
        opts.addStretch(1)
        row.addLayout(opts, 1)
        cl.addLayout(row)
        ll.addWidget(cov)
        ll.addStretch(1)
        split.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(8, 0, 0, 0)
        hint = QLabel("Line the tracks up with your files (lengths should match), then OK writes the tags.")
        hint.setProperty("role", "dim")
        rl.addWidget(hint)
        match = Table(["#", "Title (MusicBrainz)", "Length", "File", "File length"], TRACKS,
                      lambda r, c: QColor(theme.LED_ORANGE) if c in (2, 4) and r[2] == r[4] else None)
        tv = _view(match)
        for i, w in enumerate([40, 240, 70, 280]):
            tv.header().resizeSection(i, w)
        rl.addWidget(tv, 1)
        mv = QHBoxLayout()
        for t in ("Move Up", "Move Down", "Remove File"):
            mv.addWidget(QPushButton(t))
        mv.addStretch(1)
        rl.addLayout(mv)
        split.addWidget(right)
        split.setStretchFactor(1, 1)
        body.addWidget(split, 1)
        root.addLayout(body, 1)
        buttons = QHBoxLayout()
        buttons.setContentsMargins(20, 14, 20, 0)
        buttons.addStretch(1)
        for t in ("OK", "Back", "Cancel"):
            b = QPushButton(t)
            b.setMinimumWidth(96)
            b.setDefault(t == "OK")
            buttons.addWidget(b)
        root.addLayout(buttons)
