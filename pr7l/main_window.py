"""The window, laid out like Mp3tag: tag panel and cover on the left, the file grid on the right. (Mock-up.)"""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QAction, QKeySequence, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
                               QMainWindow, QScrollArea, QSplitter, QStatusBar, QTreeView, QVBoxLayout, QWidget)

from . import theme
from .widgets import Header, Toolbar, file_icon

COLUMNS = ["Filename", "Title", "Artist", "Album", "Track", "Year", "Genre", "Length", "Bitrate", "Codec", "Tag", "Path"]
PANEL_FIELDS = ["Title", "Artist", "Album", "Year", "Track", "Genre", "Comment", "Album Artist", "Composer", "Disc"]

MENUS = {
    "&File": ["Change &Directory...\tCtrl+D", "&Add Directory...\tCtrl+Shift+D", "&Refresh\tF5", "-",
              "&Save Tag\tCtrl+S", "Remo&ve Tag\tCtrl+R", "&Undo\tCtrl+Z", "-", "&Export...\tCtrl+E",
              "Create &Playlist...\tCtrl+L", "-", "&Options...\tCtrl+O", "-", "E&xit\tAlt+F4"],
    "&Edit": ["Select &All\tCtrl+A", "&Invert Selection", "-", "&Copy Tag\tCtrl+C", "&Paste Tag\tCtrl+V", "-",
              "&Find\tCtrl+F"],
    "&View": ["&Tag Panel\tF6", "&Extended Tags...\tAlt+T", "-", "&Customize Columns...", "-", "&Filter\tF3"],
    "&Convert": ["&Tag - Filename\tAlt+1", "&Filename - Tag\tAlt+2", "Te&xt file - Tag\tAlt+3",
                 "Tag - T&ag\tAlt+5", "-", "Auto-&numbering Wizard...\tCtrl+K"],
    "&Actions": ["&Actions...\tAlt+6", "Actions (&Quick)...\tAlt+7", "-", "&Case Conversion...",
                 "&Replace...", "Replace with &Regular Expression...", "Re&move Fields..."],
    "Tag &Sources": ["&MusicBrainz...\tCtrl+I", "&Discogs...", "-", "&Cover Art Archive (cover only)..."],
    "E&xtras": ["Cover &Art...", "&Embed Cover from File...", "E&xtract Cover...", "-", "&Rename Folder..."],
    "&Help": ["&Contents\tF1", "-", "&About PR7-L..."],
}

SAMPLE = [  # (filename, title, artist, album, track, year, genre, length, bitrate, codec, tag)
    ("01 Portal.flac", "Portal", "Paragon", "ELSEWORLD", "1/9", "2026", "Progressive Metal", "4:12", "1024 kbps",
     "FLAC", "FLAC"),
    ("02 Ruins of Elsewhere.flac", "Ruins of Elsewhere", "Paragon", "ELSEWORLD", "2/9", "2026",
     "Progressive Metal", "5:47", "1078 kbps", "FLAC", "FLAC"),
    ("03 Static Bloom.flac", "Static Bloom", "Paragon", "ELSEWORLD", "3/9", "2026", "Progressive Metal", "4:31",
     "1051 kbps", "FLAC", "FLAC"),
    ("04 Signal Lost.mp3", "Signal Lost", "Paragon", "ELSEWORLD", "4/9", "2026", "Progressive Metal", "3:58",
     "320 kbps", "MPEG-1 Layer 3", "ID3v2.4"),
    ("05 Arc Light.mp3", "Arc Light", "Paragon", "ELSEWORLD", "5/9", "2026", "Progressive Metal", "6:20",
     "320 kbps", "MPEG-1 Layer 3", "ID3v2.4"),
    ("06 The Long Collapse.flac", "The Long Collapse", "Paragon", "ELSEWORLD", "6/9", "2026", "Djent", "7:03",
     "1092 kbps", "FLAC", "FLAC"),
    ("07 Afterimage.m4a", "Afterimage", "Paragon", "ELSEWORLD", "7/9", "2026", "Progressive Metal", "4:44",
     "256 kbps", "AAC", "MP4"),
    ("08 Neon Requiem.flac", "Neon Requiem", "Paragon", "ELSEWORLD", "8/9", "2026", "Progressive Metal", "5:16",
     "1066 kbps", "FLAC", "FLAC"),
    ("09 Elseworld.flac", "Elseworld", "Paragon", "ELSEWORLD", "9/9", "2026", "Progressive Metal", "8:52",
     "1101 kbps", "FLAC", "FLAC"),
]


class FileModel(QAbstractTableModel):
    """The grid's rows as a plain Python list (Qt asks for each cell)."""

    def __init__(self, rows, parent=None):
        super().__init__(parent)
        self.rows = rows
        self.icon = file_icon("audio")

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return COLUMNS[section].upper()
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        if role == Qt.DisplayRole:
            return row[index.column()] if index.column() < len(row) else r"D:\Music\Paragon\ELSEWORLD"
        if role == Qt.DecorationRole and index.column() == 0:
            return self.icon
        return None


class FileView(QTreeView):
    """The grid; a selected row gets one family-gradient band across its width (as PR7-Z's list)."""

    def drawRow(self, painter: QPainter, option, index):
        super().drawRow(painter, option, index)
        if self.selectionModel().isRowSelected(index.row(), index.parent()):
            r = QRectF(option.rect)
            r.setLeft(0)
            r.setRight(self.viewport().width())
            painter.save()
            painter.fillRect(r, theme.family_gradient(r.left(), 0, r.right(), 0, theme.LIT, 0.22))
            painter.setPen(QPen(theme.family_gradient(r.left(), 0, r.right(), 0), 1))
            painter.drawLine(QPointF(r.left(), r.top() + 0.5), QPointF(r.right(), r.top() + 0.5))
            painter.drawLine(QPointF(r.left(), r.bottom() - 0.5), QPointF(r.right(), r.bottom() - 0.5))
            painter.restore()


class TagPanel(QScrollArea):
    """Mp3tag's tag panel: one box per field; '< keep >' when the selected files differ."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setMinimumWidth(320)
        self.setMaximumWidth(380)
        inner = QWidget()
        col = QVBoxLayout(inner)
        col.setContentsMargins(14, 8, 10, 10)
        col.setSpacing(4)
        box = QGroupBox("TAG PANEL")
        g = QGridLayout(box)
        g.setVerticalSpacing(5)
        self.fields: dict[str, QComboBox] = {}
        for r, name in enumerate(PANEL_FIELDS):
            lab = QLabel(name.upper())
            lab.setProperty("role", "field")
            c = QComboBox()
            c.setEditable(True)
            c.addItems(["< keep >", "< blank >"])
            self.fields[name] = c
            g.addWidget(lab, r, 0)
            g.addWidget(c, r, 1)
        g.setColumnStretch(1, 1)
        col.addWidget(box)
        cover = QGroupBox("COVER")
        cl = QVBoxLayout(cover)
        self.cover = QLabel()
        self.cover.setFixedSize(QSize(240, 240))
        self.cover.setAlignment(Qt.AlignCenter)
        self.cover.setStyleSheet(f"background: {theme.WIDGET}; border: 1px solid {theme.PANEL_EDGE}; border-radius: 6px;")
        cl.addWidget(self.cover, 0, Qt.AlignHCenter)
        self.cover_info = QLabel("")
        self.cover_info.setProperty("role", "dim")
        self.cover_info.setAlignment(Qt.AlignCenter)
        cl.addWidget(self.cover_info)
        col.addWidget(cover)
        col.addStretch(1)
        self.setWidget(inner)

    def set_cover(self, pixmap: QPixmap | None, info: str):
        if pixmap is None or pixmap.isNull():
            self.cover.setText("No cover")
        else:
            self.cover.setPixmap(pixmap.scaled(234, 234, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.cover_info.setText(info)


class MainWindow(QMainWindow):
    def __init__(self, cover_path: str | None = None):
        super().__init__()
        self.setWindowTitle(r"D:\Music\Paragon\ELSEWORLD - PR7-L")
        self.resize(1440, 860)
        bar = self.menuBar()
        for title, items in MENUS.items():
            m = bar.addMenu(title)
            for it in items:
                if it == "-":
                    m.addSeparator()
                    continue
                text, _, sc = it.partition("\t")
                a = QAction(text, self)
                if sc:
                    a.setShortcut(QKeySequence(sc))
                m.addAction(a)
        central = QWidget()
        col = QVBoxLayout(central)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        col.addWidget(Header())
        self.toolbar = Toolbar()
        col.addWidget(self.toolbar)
        split = QSplitter(Qt.Horizontal)
        self.panel = TagPanel()
        split.addWidget(self.panel)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(4, 8, 16, 12)
        self.view = FileView()
        self.view.setRootIsDecorated(False)
        self.view.setAlternatingRowColors(True)
        self.view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.view.setUniformRowHeights(True)
        self.view.setIconSize(QSize(18, 18))
        self.model = FileModel(SAMPLE)
        self.view.setModel(self.model)
        widths = [250, 190, 110, 120, 60, 60, 150, 70, 90, 120, 80]
        for i, w in enumerate(widths):
            self.view.header().resizeSection(i, w)
        self.view.header().setSectionResizeMode(QHeaderView.Interactive)
        self.view.header().setStretchLastSection(True)
        rl.addWidget(self.view)
        split.addWidget(right)
        split.setStretchFactor(1, 1)
        col.addWidget(split, 1)
        self.setCentralWidget(central)
        sb = QStatusBar()
        sb.setSizeGripEnabled(False)
        for text, stretch in (("9 file(s) selected", 0), ("0:50:43", 0), ("412.6 MB", 0), ("", 1)):
            sb.addWidget(QLabel(text), stretch)
        self.setStatusBar(sb)
        pm = QPixmap(cover_path) if cover_path else None
        self.panel.set_cover(pm, "5950 x 5950  JPEG  3.8 MB  Front" if pm else "")
        for name, value in (("Artist", "Paragon"), ("Album", "ELSEWORLD"), ("Year", "2026"),
                            ("Album Artist", "Paragon"), ("Genre", "< keep >"), ("Title", "< keep >"),
                            ("Track", "< keep >"), ("Comment", ""), ("Composer", ""), ("Disc", "1/1")):
            self.panel.fields[name].setEditText(value)
