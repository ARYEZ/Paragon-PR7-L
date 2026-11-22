"""The window, laid out like Mp3tag: tag panel and cover on the left, the file grid on the right."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QBuffer, QByteArray, QIODevice, QModelIndex, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QAction, QColor, QGuiApplication, QImage, QKeySequence, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QFileDialog, QGridLayout, QGroupBox,
                               QHeaderView, QInputDialog, QLabel, QMainWindow, QMenu, QMessageBox, QScrollArea,
                               QSplitter, QStatusBar, QTreeView, QVBoxLayout, QWidget)

from . import __version__, settings, tags, theme
from .musicbrainz import fmt_length
from .tags import SEP, TagFile
from .widgets import Header, Toolbar, file_icon

KEEP = "< keep >"
BLANK = "< blank >"
# The panel's fields, in Mp3tag's order: (label, field).
PANEL_FIELDS = [("Title", "TITLE"), ("Artist", "ARTIST"), ("Album", "ALBUM"), ("Year", "YEAR"), ("Track", "TRACK"),
                ("Genre", "GENRE"), ("Comment", "COMMENT"), ("Album Artist", "ALBUMARTIST"),
                ("Composer", "COMPOSER"), ("Disc", "DISCNUMBER")]


def _num(text: str):
    head = text.split("/")[0].strip()
    return (0, int(head), text) if head.isdigit() else (1, 0, text.lower())


def _kbps(t: TagFile) -> str:
    return f"{round(t.info.bitrate / 1000)} kbps" if t.info.bitrate else ""


# Grid columns: (title, text, sort key)
COLUMNS = [
    ("Filename", lambda t: t.filename, lambda t: t.filename.lower()),
    ("Title", lambda t: t.get("TITLE"), None), ("Artist", lambda t: t.get("ARTIST"), None),
    ("Album", lambda t: t.get("ALBUM"), None), ("Track", lambda t: t.get("TRACK"), lambda t: _num(t.get("TRACK"))),
    ("Year", lambda t: t.get("YEAR"), None), ("Genre", lambda t: t.get("GENRE"), None),
    ("Length", lambda t: fmt_length(t.info.length), lambda t: t.info.length),
    ("Bitrate", _kbps, lambda t: t.info.bitrate), ("Codec", lambda t: t.info.codec, None),
    ("Tag", lambda t: t.tag_label, None), ("Path", lambda t: os.path.dirname(t.path), lambda t: t.path.lower()),
]


class FileModel(QAbstractTableModel):
    """The grid's rows as a plain Python list of TagFiles (Qt asks for each cell)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: list[TagFile] = []
        self.icon = file_icon("audio")

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return COLUMNS[section][0].upper()
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        t = self.rows[index.row()]
        if role in (Qt.DisplayRole, Qt.ToolTipRole):
            return COLUMNS[index.column()][1](t)
        if role == Qt.DecorationRole and index.column() == 0:
            return self.icon
        if role == Qt.TextAlignmentRole and COLUMNS[index.column()][0] in ("Track", "Length", "Bitrate"):
            return int(Qt.AlignRight | Qt.AlignVCenter)
        return None

    def set_rows(self, rows: list[TagFile]):
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def add_rows(self, rows: list[TagFile]):
        if rows:
            self.beginInsertRows(QModelIndex(), len(self.rows), len(self.rows) + len(rows) - 1)
            self.rows.extend(rows)
            self.endInsertRows()

    def replace(self, row: int, t: TagFile):
        self.rows[row] = t
        self.dataChanged.emit(self.index(row, 0), self.index(row, len(COLUMNS) - 1))

    def sort(self, column, order=Qt.AscendingOrder):
        _, text, key = COLUMNS[column]
        self.layoutAboutToBeChanged.emit()
        self.rows.sort(key=key or (lambda t: text(t).lower()), reverse=order == Qt.DescendingOrder)
        self.layoutChanged.emit()


class FileView(QTreeView):
    """The grid; a selected row gets one family-gradient band across its width (as PR7-Z's list).
    Folders and audio files dropped on it are added."""

    dropped = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DropOnly)

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

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            e.acceptProposedAction()
            self.dropped.emit(paths)


# ---------------------------------------------------------------------------------------------- cover box
def shrink_image(data: bytes, max_side: int, quality: int = 90) -> bytes:
    """The picture scaled down so its longer side is `max_side` (never up), as JPEG (PNG stays PNG)."""
    img = QImage.fromData(data)
    if img.isNull() or max(img.width(), img.height()) <= max_side:
        return data
    img = img.scaled(max_side, max_side, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    png = tags.image_mime(data) == "image/png"
    img.save(buf, "PNG" if png else "JPEG", -1 if png else quality)
    return bytes(buf.data())


class CoverBox(QLabel):
    """The panel's cover: shows the selection's front cover; right-click for Add / Extract / Remove ...;
    an image file dropped on it replaces the cover (saved with the tag, as Mp3tag does)."""

    def __init__(self, panel: "TagPanel"):
        super().__init__()
        self.panel = panel
        self.setFixedSize(QSize(240, 240))
        self.setAlignment(Qt.AlignCenter)
        self.setAcceptDrops(True)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(lambda pos: self.panel.cover_menu(self.mapToGlobal(pos)))
        self.restyle()

    def restyle(self):
        self.setStyleSheet(f"background: {theme.WIDGET}; border: 1px solid {theme.PANEL_EDGE}; border-radius: 6px;"
                           f" color: {theme.TEXT_DIM};")

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() or e.mimeData().hasImage():
            e.acceptProposedAction()

    def dropEvent(self, e):
        md = e.mimeData()
        for u in md.urls():
            if u.isLocalFile():
                try:
                    self.panel.set_pending_cover(Path(u.toLocalFile()).read_bytes())
                except OSError:
                    pass
                return
        if md.hasImage():
            self.panel.set_pending_cover(_qimage_bytes(md.imageData()))


def _qimage_bytes(img) -> bytes:
    img = QImage(img)
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "JPEG", 92)
    return bytes(buf.data())


# ---------------------------------------------------------------------------------------------- the panel
class TagPanel(QScrollArea):
    """Mp3tag's tag panel: one box per field; '< keep >' when the selected files differ. Edits wait for
    Save (Ctrl+S); a changed box is marked with the accent border."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setMinimumWidth(320)
        self.setMaximumWidth(400)
        inner = QWidget()
        col = QVBoxLayout(inner)
        col.setContentsMargins(14, 8, 10, 10)
        col.setSpacing(4)
        box = QGroupBox("TAG PANEL")
        g = QGridLayout(box)
        g.setVerticalSpacing(5)
        self.fields: dict[str, QComboBox] = {}
        self.dirty: set[str] = set()
        self._filling = False
        for r, (label, name) in enumerate(PANEL_FIELDS):
            lab = QLabel(label.upper())
            lab.setProperty("role", "field")
            c = QComboBox()
            c.setEditable(True)
            c.setInsertPolicy(QComboBox.NoInsert)
            c.setObjectName(name)
            c.editTextChanged.connect(lambda _t, n=name: self._edited(n))
            self.fields[name] = c
            g.addWidget(lab, r, 0)
            g.addWidget(c, r, 1)
        g.setColumnStretch(1, 1)
        col.addWidget(box)
        cover = QGroupBox("COVER")
        cl = QVBoxLayout(cover)
        self.cover = CoverBox(self)
        cl.addWidget(self.cover, 0, Qt.AlignHCenter)
        self.cover_info = QLabel("")
        self.cover_info.setProperty("role", "dim")
        self.cover_info.setAlignment(Qt.AlignCenter)
        self.cover_info.setWordWrap(True)
        cl.addWidget(self.cover_info)
        col.addWidget(cover)
        col.addStretch(1)
        self.setWidget(inner)
        self.files: list[TagFile] = []
        self.pending_pictures: list[tags.Picture] | None = None  # None: leave the files' pictures alone
        self.shown_picture: tags.Picture | None = None
        self.max_cover = 0  # Options: shrink added covers to this many pixels (0 = as they are)
        self.show_files([])

    # ---------------------------------------------------------------------------------------- fields
    def _edited(self, name: str):
        if self._filling:
            return
        self.dirty.add(name)
        self.fields[name].setStyleSheet(f"QComboBox {{ border: 1px solid {theme.ACCENT}; }}")
        self.changed.emit()

    @property
    def has_changes(self) -> bool:
        return bool(self.dirty) or self.pending_pictures is not None

    def show_files(self, files: list[TagFile]):
        """Fill the boxes from the selection: the common value, or '< keep >' where they differ."""
        self._filling = True
        self.files = files
        self.dirty.clear()
        self.pending_pictures = None
        for _, name in PANEL_FIELDS:
            c = self.fields[name]
            c.setStyleSheet("")
            c.clear()
            c.setEnabled(bool(files))
            values = list(dict.fromkeys(f.get(name) for f in files))
            c.addItems([KEEP, BLANK] + [v for v in values if v])
            if not files:
                c.setEditText("")
            elif len(values) == 1:
                c.setEditText(values[0])
            else:
                c.setEditText(KEEP)
        self._filling = False
        self._show_cover()

    def changes(self) -> dict[str, list[str] | None]:
        """The edited fields: a value, None to remove (empty or '< blank >'); '< keep >' changes nothing."""
        out = {}
        for name in self.dirty:
            text = self.fields[name].currentText()
            if text == KEEP:
                continue
            out[name] = None if text in ("", BLANK) else text.split(SEP)
        return out

    # ---------------------------------------------------------------------------------------- cover
    def _show_cover(self):
        pics = self.pending_pictures
        if pics is not None:
            pic = pics[0] if pics else None
            self._paint_cover(pic, "No cover (on save)" if not pic else None)
            return
        # Compared by their fingerprints: only the one cover shown is read from its file.
        keys = {(m.sha1 if m else None) for m in (f.front_meta() for f in self.files)}
        if not self.files:
            self._paint_cover(None, "")
        elif len(keys) > 1:
            self._paint_cover(None, KEEP)
        else:
            pics = self.files[0].load_pictures()
            front = next((p for p in pics if p.type == tags.FRONT), pics[0] if pics else None)
            self._paint_cover(front, "No cover")

    def _paint_cover(self, pic: tags.Picture | None, text: str | None):
        self.shown_picture = pic
        if pic is None:
            self.cover.setPixmap(QPixmap())
            self.cover.setText(text or "")
            self.cover_info.setText("")
            return
        pm = QPixmap()
        pm.loadFromData(pic.data)
        if pm.isNull():
            self.cover.setPixmap(QPixmap())
            self.cover.setText("Unreadable picture")
        else:
            self.cover.setPixmap(pm.scaled(234, 234, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        info = tags.picture_info(pic)
        if self.pending_pictures is not None:
            info += "  (on save)"
        self.cover_info.setText(info)

    def set_pending_cover(self, data: bytes | None):
        """Replace the selection's cover with this picture (None: remove all pictures), on Save."""
        if not self.files:
            return
        if data is not None and self.max_cover:
            data = shrink_image(data, self.max_cover)
        self.pending_pictures = [tags.Picture(data, type=tags.FRONT)] if data else []
        self._show_cover()
        self.changed.emit()

    def cover_menu(self, at):
        m = QMenu(self)
        have = self.shown_picture is not None
        m.addAction("Add cover...", self.add_cover).setEnabled(bool(self.files))
        m.addAction("Extract cover...", self.extract_cover).setEnabled(have)
        m.addAction("Resize cover...", self.resize_cover).setEnabled(have)
        m.addAction("Remove cover", lambda: self.set_pending_cover(None)).setEnabled(bool(self.files))
        m.addSeparator()
        m.addAction("Copy cover", self.copy_cover).setEnabled(have)
        m.addAction("Paste cover", self.paste_cover).setEnabled(
            bool(self.files) and QGuiApplication.clipboard().mimeData().hasImage())
        m.exec(at)

    def add_cover(self):
        start = os.path.dirname(self.files[0].path) if self.files else ""
        path, _ = QFileDialog.getOpenFileName(self, "Add cover", start, "Images (*.jpg *.jpeg *.png *.gif *.bmp *.webp)")
        if path:
            self.set_pending_cover(Path(path).read_bytes())

    def extract_cover(self):
        pic = self.shown_picture
        if not pic:
            return
        ext = {"image/png": ".png", "image/gif": ".gif", "image/bmp": ".bmp", "image/webp": ".webp"}.get(pic.mime, ".jpg")
        start = os.path.join(os.path.dirname(self.files[0].path), "folder" + ext) if self.files else "folder" + ext
        path, _ = QFileDialog.getSaveFileName(self, "Extract cover", start, f"Image (*{ext})")
        if path:
            Path(path).write_bytes(pic.data)

    def resize_cover(self):
        pic = self.shown_picture
        if not pic:
            return
        w, h = tags.image_size(pic.data)
        side, ok = QInputDialog.getInt(self, "Resize cover", f"Longer side in pixels (now {max(w, h)}):",
                                       min(max(w, h), 1000) if w else 600, 50, 10000, 50)
        if ok:
            self.pending_pictures = [tags.Picture(shrink_image(pic.data, side), type=pic.type, desc=pic.desc)]
            self._show_cover()
            self.changed.emit()

    def copy_cover(self):
        if self.shown_picture:
            QGuiApplication.clipboard().setImage(QImage.fromData(self.shown_picture.data))

    def paste_cover(self):
        img = QGuiApplication.clipboard().image()
        if not img.isNull():
            self.set_pending_cover(_qimage_bytes(img))

    def restyle(self):
        self.cover.restyle()
        for name in self.dirty:
            self.fields[name].setStyleSheet(f"QComboBox {{ border: 1px solid {theme.ACCENT}; }}")


# ---------------------------------------------------------------------------------------------- the window
# Menus: (text with shortcut after a tab, slot name or None for "not yet"); "-" is a separator.
MENUS = {
    "&File": [("Change &Directory...\tCtrl+D", "open_dir"), ("&Add Directory...\tCtrl+Shift+D", "add_dir"),
              ("&Refresh\tF5", "refresh"), "-", ("&Save Tag\tCtrl+S", "save"), ("Remo&ve Tag\tCtrl+R", "remove_tag"),
              ("&Undo\tCtrl+Z", "undo"), "-", ("&Export...\tCtrl+E", "export_files"), ("Create &Playlist...\tCtrl+L", "create_playlist"),
              "-", ("&Options...\tCtrl+O", "options"), "-", ("E&xit\tAlt+F4", "close")],
    "&Edit": [("Select &All\tCtrl+A", "select_all"), ("&Invert Selection", "invert_selection"), "-",
              ("&Copy Tag\tCtrl+C", "copy_tag"), ("&Paste Tag\tCtrl+V", "paste_tag"), "-",
              ("Remove from &List\tDel", "remove_from_list")],
    "&View": [("&Tag Panel\tF6", "toggle_panel"), ("&Extended Tags...\tAlt+T", "extended_tags"), "-",
              ("&Filter\tF3", None)],
    "&Convert": [("&Tag - Filename\tAlt+1", "tag_to_filename"), ("&Filename - Tag\tAlt+2", "filename_to_tag"),
                 ("Te&xt file - Tag\tAlt+3", "text_to_tag"), ("Tag - T&ag\tAlt+5", "tag_to_tag"), "-",
                 ("Auto-&numbering Wizard...\tCtrl+K", "auto_number")],
    "&Actions": [("&Actions...\tAlt+6", "run_actions"), ("Actions (&Quick)...\tAlt+7", "quick_action"), "-",
                 ("&Case Conversion...", "quick_case"), ("&Replace...", "quick_replace"),
                 ("Replace with Regular E&xpression...", "quick_regexp"), ("Re&move Fields...", "quick_remove")],
    "Tag &Sources": [("&MusicBrainz...\tCtrl+I", "musicbrainz"), ("&Discogs...", None), "-",
                     ("&Cover Art Archive (cover only)...", "cover_only")],
    "E&xtras": [("&Add Cover...", "add_cover"), ("E&xtract Cover...", "extract_cover"),
                ("&Resize Cover...", "resize_cover"), ("Re&move Cover", "remove_cover")],
    "&Help": [("&About PR7-L...", "about")],
}
TOOLBAR_SLOTS = {"opendir": "open_dir", "adddir": "add_dir", "save": "save", "removetag": "remove_tag",
                 "undo": "undo", "musicbrainz": "musicbrainz", "cover": "cover_only", "tag2file": "tag_to_filename",
                 "file2tag": "filename_to_tag", "text2tag": "text_to_tag", "tag2tag": "tag_to_tag",
                 "number": "auto_number", "actions": "run_actions"}


class MainWindow(QMainWindow):
    def __init__(self, paths: list[str] | None = None, client=None):
        super().__init__()
        self.client = client  # the MusicBrainz client (tests pass one with recorded answers)
        self._library = False  # the file cache: opened on first use
        self.folder = ""
        self.undo_stack: list[list] = []  # each step: tag snapshots and/or convert.Rename records
        self.copied: dict[str, list[str]] | None = None
        self.resize(1440, 860)
        self.actions_by_slot: dict[str, QAction] = {}
        bar = self.menuBar()
        for title, items in MENUS.items():
            m = bar.addMenu(title)
            for it in items:
                if it == "-":
                    m.addSeparator()
                    continue
                text, slot = it
                text, _, sc = text.partition("\t")
                a = QAction(text, self)
                if sc and sc != "Alt+F4":
                    a.setShortcut(QKeySequence(sc))
                if slot:
                    a.triggered.connect(getattr(self, slot))
                    self.actions_by_slot[slot] = a
                else:
                    a.setEnabled(False)
                    a.setToolTip("Coming in a later version")
                m.addAction(a)
        central = QWidget()
        col = QVBoxLayout(central)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        self.header = Header()
        col.addWidget(self.header)
        self.toolbar = Toolbar()
        for key, button in self.toolbar.keys.items():
            if key not in TOOLBAR_SLOTS:
                button.setEnabled(False)
                button.setToolTip(button.toolTip() + " (coming in a later version)")
        self.toolbar.triggered.connect(lambda n: getattr(self, TOOLBAR_SLOTS[n])() if n in TOOLBAR_SLOTS else None)
        col.addWidget(self.toolbar)
        self.split = QSplitter(Qt.Horizontal)
        self.panel = TagPanel()
        self.panel.max_cover = settings.get_int("cover_max_side", 0)
        self.panel.changed.connect(self._update_title)
        self.split.addWidget(self.panel)
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
        self.view.setSortingEnabled(True)
        self.model = FileModel()
        self.view.setModel(self.model)
        self.view.header().setSortIndicator(-1, Qt.AscendingOrder)
        widths = settings.get_list("column_widths") or [250, 190, 110, 120, 60, 60, 150, 70, 90, 120, 100]
        for i, w in enumerate(widths[:len(COLUMNS) - 1]):
            self.view.header().resizeSection(i, int(w))
        self.view.header().setSectionResizeMode(QHeaderView.Interactive)
        self.view.header().setStretchLastSection(True)
        self.view.selectionModel().selectionChanged.connect(self._selection_changed)
        self.view.dropped.connect(lambda paths: self.load(paths, add=True))
        self.view.doubleClicked.connect(lambda _i: self.panel.fields["TITLE"].setFocus())
        rl.addWidget(self.view)
        self.split.addWidget(right)
        self.split.setStretchFactor(1, 1)
        col.addWidget(self.split, 1)
        self.setCentralWidget(central)
        sb = QStatusBar()
        sb.setSizeGripEnabled(False)
        self.status = [QLabel(""), QLabel(""), QLabel(""), QLabel("")]
        for lab, stretch in zip(self.status, (0, 0, 0, 1)):
            sb.addWidget(lab, stretch)
        self.setStatusBar(sb)
        self._update_title()
        if paths:
            self.load(paths)
        else:  # what was open last time: the folder from Change Directory and every one added to it
            last = [p for p in settings.get_list("open_paths") if isinstance(p, str) and os.path.exists(p)]
            if not last and settings.get("last_dir") and os.path.isdir(settings.get("last_dir")):
                last = [settings.get("last_dir")]  # 0.1/0.2 kept only this
            if last:
                self.load(last)

    # ---------------------------------------------------------------------------------------- loading
    def _scan(self, paths: list[str]) -> list[str]:
        sub = settings.get_bool("subdirectories", True)
        out = []
        for p in paths:
            if os.path.isdir(p):
                if sub:
                    for root, dirs, files in os.walk(p):
                        dirs.sort(key=str.lower)
                        out.extend(os.path.join(root, f) for f in sorted(files, key=str.lower))
                else:
                    out.extend(os.path.join(p, f) for f in sorted(os.listdir(p), key=str.lower))
            else:
                out.append(p)
        return [p for p in out if Path(p).suffix.lower() in tags.AUDIO_EXTENSIONS and os.path.isfile(p)]

    def load(self, paths: list[str], add: bool = False):
        """Change Directory (replace the list) or Add Directory (add to it), as Mp3tag does."""
        if not self._confirm_discard():
            return
        files = self._scan(paths)
        have = {os.path.normcase(t.path) for t in self.model.rows} if add else set()
        rows, failed, fresh = [], 0, 0
        self.read_count = 0
        for i, p in enumerate(files):
            if os.path.normcase(p) in have:
                continue
            try:
                rows.append(self._read(p))
            except (tags.UnsupportedFile, OSError):
                failed += 1
            if i % 50 == 49:
                self.status[3].setText(f"Reading {i + 1} of {len(files)} ({self.read_count} new or changed) ...")
                QApplication.processEvents()
        if self.library:
            self.library.commit()
        if add:
            self.model.add_rows(rows)
        else:
            self.model.set_rows(rows)
            self.undo_stack.clear()
            folder = paths[0] if len(paths) == 1 and os.path.isdir(paths[0]) else os.path.dirname(paths[0]) if paths else ""
            self.folder = folder
            if folder:
                settings.set("last_dir", folder)
        sources = [os.path.abspath(p) for p in paths]
        if add:
            sources = settings.get_list("open_paths") + sources
        settings.set("open_paths", list(dict.fromkeys(sources)))
        self.status[3].setText(f"{failed} file(s) couldn't be read" if failed else
                               f"{len(rows)} file(s), {self.read_count} read from disk, the rest from the cache"
                               if self.library and rows else "")
        self._selection_changed()
        self._update_title()

    def open_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Change directory", self.folder or settings.get("last_dir", ""))
        if d:
            self.load([d])

    def add_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Add directory", self.folder or settings.get("last_dir", ""))
        if d:
            self.load([d], add=True)

    def refresh(self):
        if not self._confirm_discard():
            return
        rows = []
        for i, t in enumerate(self.model.rows):  # F5 reads every file again, cache or not (Mp3tag's Refresh)
            try:
                rows.append(self._read(t.path, use_cache=False))
            except (tags.UnsupportedFile, OSError):
                pass
            if i % 50 == 49:
                self.status[3].setText(f"Reading {i + 1} of {len(self.model.rows)} ...")
                QApplication.processEvents()
        if self.library:
            self.library.commit()
        self.model.set_rows(rows)
        self.status[3].setText("")
        self._selection_changed()

    # ---------------------------------------------------------------------------------------- the cache
    @property
    def library(self):
        """The file cache, opened on first use; None if it can't be (then every file is read from disk)."""
        if self._library is False:
            from .cache import Library
            try:
                self._library = Library() if settings.get_bool("use_cache", True) else None
            except Exception:  # noqa: BLE001 - a cache that won't open must never stop PR7-L
                self._library = None
        return self._library

    def _read(self, path: str, use_cache: bool = True) -> TagFile:
        """A file for the list: from the cache when it's unchanged on disk, else read (and cached), slim."""
        lib = self.library
        st = os.stat(path)
        if lib and use_cache:
            tf = lib.get(path, st)
            if tf is not None:
                return tf
        tf = tags.read(path)
        self.read_count = getattr(self, "read_count", 0) + 1
        if lib:
            lib.put(tf, st)
        return tf.slim()

    # ---------------------------------------------------------------------------------------- selection
    def selected_rows(self) -> list[int]:
        return sorted(i.row() for i in self.view.selectionModel().selectedRows())

    def selected(self) -> list[TagFile]:
        return [self.model.rows[r] for r in self.selected_rows()]

    def _selection_changed(self, *_):
        files = self.selected()
        if self.panel.has_changes and self.panel.files and self.panel.files != files:
            if self._ask_save(self.panel.files):
                self._write(self.panel.files, self.panel.changes(), self.panel.pending_pictures)
                files = self.selected()
        self.panel.show_files(files)
        shown = files or self.model.rows
        n = len(files)
        self.status[0].setText(f"{n} file(s) selected" if n else f"{len(self.model.rows)} file(s)")
        self.status[1].setText(fmt_length(sum(t.info.length for t in shown)) or "0:00")
        size = sum(t.size for t in shown)
        self.status[2].setText(f"{size / 1048576:.1f} MB" if size >= 1048576 else f"{size / 1024:.0f} KB")
        self._update_title()

    def _ask_save(self, files) -> bool:
        r = QMessageBox.question(self, "PR7-L", f"Save the changes to {len(files)} file(s)?",
                                 QMessageBox.Save | QMessageBox.Discard, QMessageBox.Save)
        return r == QMessageBox.Save

    def _confirm_discard(self) -> bool:
        if self.panel.has_changes and self.panel.files:
            if self._ask_save(self.panel.files):
                self._write(self.panel.files, self.panel.changes(), self.panel.pending_pictures)
            self.panel.show_files([])
        return True

    def _update_title(self):
        star = "*" if self.panel.has_changes else ""
        self.setWindowTitle(f"{star}{self.folder or 'PR7-L'} - PR7-L" if self.folder else f"{star}PR7-L")

    def select_all(self):
        self.view.selectAll()

    def invert_selection(self):
        sel = self.view.selectionModel()
        from PySide6.QtCore import QItemSelection, QItemSelectionModel
        all_rows = QItemSelection(self.model.index(0, 0), self.model.index(len(self.model.rows) - 1, len(COLUMNS) - 1))
        sel.select(all_rows, QItemSelectionModel.Toggle | QItemSelectionModel.Rows)

    def remove_from_list(self):
        rows = self.selected_rows()
        self.panel.show_files([])
        for r in reversed(rows):
            self.model.beginRemoveRows(QModelIndex(), r, r)
            del self.model.rows[r]
            self.model.endRemoveRows()
        self._selection_changed()

    # ---------------------------------------------------------------------------------------- writing
    def _options(self) -> tags.WriteOptions:
        return tags.WriteOptions(id3v2_version=settings.get_int("id3v2_version", 3),
                                 id3v1=settings.get_bool("id3v1", True),
                                 preserve_mtime=settings.get_bool("preserve_mtime", False))

    def _reload(self, files: list[TagFile]):
        index = {os.path.normcase(t.path): i for i, t in enumerate(self.model.rows)}
        for f in files:
            i = index.get(os.path.normcase(f.path))
            if i is None:
                continue
            try:
                self.model.replace(i, self._read(f.path, use_cache=False))
            except (tags.UnsupportedFile, OSError):
                pass
        if self.library:
            self.library.commit()

    def _write(self, files: list[TagFile], changes: dict, pictures) -> int:
        """Save `changes` (and pictures, unless None) to the files; one Undo step. Returns how many failed."""
        if not files or (not changes and pictures is None):
            return 0
        snaps, failed = [], []
        options = self._options()
        for f in files:
            try:
                snap = tags.snapshot(f.path)
                tags.save(f.path, changes, pictures, options)
                snaps.append(snap)
            except (tags.UnsupportedFile, OSError, Exception) as e:  # noqa: BLE001 - report every file's error
                failed.append(f"{f.filename}: {e}")
        if snaps:
            self.undo_stack.append(snaps)
        self._reload(files)
        self.panel.show_files(self.selected())
        if failed:
            QMessageBox.warning(self, "Save tag", "These files couldn't be saved:\n\n" + "\n".join(failed[:20]))
        self._update_title()
        return len(failed)

    def save(self):
        files = self.panel.files or self.selected()
        n = len(files)
        failed = self._write(files, self.panel.changes(), self.panel.pending_pictures)
        if files:
            self.status[3].setText(f"Saved {n - failed} file(s)")

    def remove_tag(self, confirm: bool = True):
        files = self.selected()
        if not files:
            return
        if confirm and QMessageBox.question(
                self, "Remove tag", f"Remove the tags (and covers) from {len(files)} file(s)?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        snaps = []
        for f in files:
            try:
                snaps.append(tags.snapshot(f.path))
                tags.remove_tags(f.path, self._options())
            except (tags.UnsupportedFile, OSError):
                pass
        self.undo_stack.append(snaps)
        self._reload(files)
        self.panel.show_files(self.selected())

    def undo(self):
        if not self.undo_stack:
            self.status[3].setText("Nothing to undo")
            return
        from .convert import Rename, undo_renames
        step = self.undo_stack.pop()
        renames = [r for r in step if isinstance(r, Rename)]
        snaps = [s for s in step if not isinstance(s, Rename)]
        errors = undo_renames(renames)
        self._renamed([(r.new, r.old) for r in renames])
        for s in snaps:
            try:
                tags.restore(s, self._options())
            except (tags.UnsupportedFile, OSError):
                pass
        self._reload([TagFile(path=s.path, kind="") for s in snaps])
        self.panel.show_files(self.selected())
        self.status[3].setText(f"Undone: {len(step)} file(s)")
        if errors:
            QMessageBox.warning(self, "Undo", "These files couldn't be renamed back:\n\n" + "\n".join(errors[:20]))

    # ---------------------------------------------------------------------------------------- converters
    def _renamed(self, moves: list[tuple[str, str]]):
        """Rows whose files were renamed: read them at their new paths."""
        index = {os.path.normcase(t.path): i for i, t in enumerate(self.model.rows)}
        for old, new in moves:
            i = index.get(os.path.normcase(old))
            if self.library:
                self.library.forget(old)
            if i is not None:
                try:
                    self.model.replace(i, self._read(new, use_cache=False))
                except (tags.UnsupportedFile, OSError):
                    pass

    def apply_plan(self, planned) -> int:
        """Apply each planned file's own changes: tags and pictures first (at the file's present name), covers
        exported, then renames; all one Undo step (exported images stay). Returns how many failed."""
        from .convert import apply_renames
        step, failed, exported = [], [], 0
        options = self._options()
        for p in planned:
            if p.error or (not p.changes and p.pictures is None):
                continue
            try:
                snap = tags.snapshot(p.tf.path)
                tags.save(p.tf.path, p.changes or {}, p.pictures, options)
                step.append(snap)
            except Exception as e:  # noqa: BLE001 - report every file's error
                failed.append(f"{p.tf.filename}: {e}")
        self._reload([p.tf for p in planned if not p.error and (p.changes or p.pictures is not None)])
        for p in planned:
            for path, data in p.exports if not p.error else []:
                try:
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    Path(path).write_bytes(data)
                    exported += 1
                except OSError as e:
                    failed.append(f"{os.path.basename(path)}: {e}")
        renames = [p for p in planned if p.new and not p.error]
        if renames:
            done, errors = apply_renames(renames)
            failed += errors
            step += done
            self._renamed([(r.old, r.new) for r in done])
        if step:
            self.undo_stack.append(step)
        self.panel.show_files(self.selected())
        files = len({os.path.normcase(getattr(x, "path", getattr(x, "old", ""))) for x in step})
        self.status[3].setText(f"{files} file(s) changed" + (f", {exported} cover(s) exported" if exported else "")
                               + (f", {len(failed)} failed" if failed else ""))
        if failed:
            QMessageBox.warning(self, "PR7-L", "These files couldn't be changed:\n\n" + "\n".join(failed[:20]))
        return len(failed)

    # ---------------------------------------------------------------------------------------- export, playlist
    def _list_files(self, title: str):
        """The selection, in the list's order, or every file when nothing is selected."""
        self._confirm_discard()
        files = self.selected() or list(self.model.rows)
        if not files:
            QMessageBox.information(self, title, "Open a folder first.")
        return files

    def export_files(self):
        from .export_dialog import ExportDialog
        files = self._list_files("Export")
        if not files:
            return
        dlg = ExportDialog(files, self)
        self._dialog = dlg  # tests drive the open dialog
        if dlg.exec():
            self.status[3].setText(f"Exported {len(files)} file(s) to {os.path.basename(dlg.written)}")

    def create_playlist(self):
        from .export_dialog import PlaylistDialog
        files = self._list_files("Create playlist")
        if not files:
            return
        dlg = PlaylistDialog(files, self)
        self._dialog = dlg
        if dlg.exec():
            self.status[3].setText(f"Playlist {os.path.basename(dlg.path)}: {len(files)} file(s)")

    # ---------------------------------------------------------------------------------------- actions
    def apply_actions(self, chosen: list[dict], files: list[TagFile] | None = None) -> int:
        from . import actions, script
        files = files if files is not None else self.selected()
        if not chosen or not files:
            return 0
        try:
            planned = actions.plan(chosen, files)
        except script.ScriptError as e:
            QMessageBox.warning(self, "Actions", str(e))
            return 1
        if not any(p.changes or p.pictures is not None or p.exports or p.new for p in planned if not p.error):
            self.status[3].setText("The actions changed nothing")
            return 0
        return self.apply_plan(planned)

    def run_actions(self):
        from .actions_dialog import ActionsDialog
        files = self._converter_files("Actions")
        if not files:
            return
        dlg = ActionsDialog(len(files), self)
        self._dialog = dlg  # tests drive the open dialog
        if dlg.exec():
            self.apply_actions(dlg.chosen(), files)

    def quick_action(self, kind: str | None = None):
        """Actions (Quick): one action, run once and not saved, as Mp3tag's Alt+7."""
        from . import actions
        from .actions_dialog import ActionEditor, choose_type
        files = self._converter_files("Actions (Quick)")
        if not files:
            return
        kind = kind or choose_type(self)
        if not kind:
            return
        key = f"quick_{kind}"
        saved = settings.get_list(key)
        dlg = ActionEditor(saved[0] if saved and isinstance(saved[0], dict) else actions.new_action(kind), self)
        self._dialog = dlg
        if dlg.exec():
            settings.set(key, [dlg.value()])  # the form comes back filled in next time
            self.apply_actions([dlg.value()], files)

    def quick_case(self):
        self.quick_action("case")

    def quick_replace(self):
        self.quick_action("replace")

    def quick_regexp(self):
        self.quick_action("regexp")

    def quick_remove(self):
        self.quick_action("remove")

    def _converter_files(self, title: str):
        self._confirm_discard()
        files = self.selected()
        if not files:
            QMessageBox.information(self, title, "Select the files first (Ctrl+A for all).")
        return files

    def _convert(self, kind: str):
        from .convert_dialog import KINDS, ConvertDialog
        files = self._converter_files(KINDS[kind][0])
        if not files:
            return
        dlg = ConvertDialog(kind, files, self)
        self._dialog = dlg  # tests drive the open dialog
        if dlg.exec():
            self.apply_plan(dlg.planned)

    def tag_to_filename(self):
        self._convert("tag2file")

    def filename_to_tag(self):
        self._convert("file2tag")

    def text_to_tag(self):
        self._convert("text2tag")

    def tag_to_tag(self):
        self._convert("tag2tag")

    def auto_number(self):
        from .convert_dialog import AutoNumberDialog
        files = self._converter_files("Auto-numbering Wizard")
        if not files:
            return
        dlg = AutoNumberDialog(files, self)
        self._dialog = dlg
        if dlg.exec():
            self.apply_plan(dlg.planned)

    def copy_tag(self):
        f = self.selected()
        if f:
            self.copied = {k: list(v) for k, v in f[0].fields.items()}
            self._copied_pictures = list(f[0].load_pictures())
            self.status[3].setText(f"Tag of {f[0].filename} copied")

    def paste_tag(self):
        files = self.selected()
        if self.copied is None or not files:
            return
        changes = {k: None for f in files for k in f.fields}  # Mp3tag's Paste Tag replaces the whole tag
        changes.update(self.copied)
        self._write(files, changes, list(self._copied_pictures))

    # ---------------------------------------------------------------------------------------- covers
    def add_cover(self):
        self.panel.add_cover()

    def extract_cover(self):
        self.panel.extract_cover()

    def resize_cover(self):
        self.panel.resize_cover()

    def remove_cover(self):
        self.panel.set_pending_cover(None)

    # ---------------------------------------------------------------------------------------- dialogs
    def _client(self):
        if self.client is None:
            from .musicbrainz import Client
            self.client = Client()
        return self.client

    def musicbrainz(self, cover_only: bool = False):
        from .musicbrainz_dialog import MusicBrainzDialog
        files = self.selected() or list(self.model.rows)
        if not files:
            QMessageBox.information(self, "MusicBrainz", "Open a folder and select the files of one album first.")
            return
        self._confirm_discard()
        files = [self.model.rows[i] for i in self.selected_rows()] or list(self.model.rows)
        dlg = MusicBrainzDialog(files, self._client(), self, cover_only=cover_only, options=self._options())
        dlg.cover_size.setCurrentText(settings.get("mb_cover_size", "1200"))
        dlg.save_cover.setChecked(settings.get_bool("mb_save_cover", True))
        dlg.folder_jpg.setChecked(settings.get_bool("mb_folder_jpg", False))
        self._mb_dialog = dlg  # tests drive the open dialog
        if dlg.exec() and dlg.snapshots:
            self.undo_stack.append(dlg.snapshots)
            self._reload(files)
            self.panel.show_files(self.selected())
            self.status[3].setText(f"MusicBrainz: {len(dlg.snapshots)} file(s) tagged")
        settings.set("mb_cover_size", dlg.cover_size.currentText())
        settings.set("mb_save_cover", dlg.save_cover.isChecked())
        settings.set("mb_folder_jpg", dlg.folder_jpg.isChecked())

    def cover_only(self):
        self.musicbrainz(cover_only=True)

    def extended_tags(self):
        from .dialogs import ExtendedTagsDialog
        files = self.selected()
        if not files:
            return
        self._confirm_discard()
        files = self.selected()
        dlg = ExtendedTagsDialog(files, self)
        if dlg.exec():
            self._write(files, dlg.changes(), None)

    def options(self):
        from .dialogs import OptionsDialog
        dlg = OptionsDialog(self)
        if dlg.exec():
            dlg.apply()
            if self._library and not settings.get_bool("use_cache", True):
                self._library.close()
            self._library = False  # opened again (or not) by the next read, as the option says
            self.panel.max_cover = settings.get_int("cover_max_side", 0)
            self.set_finish(settings.get("finish", "obsidian"))

    def set_finish(self, name: str):
        theme.set_finish(name)
        app = QApplication.instance()
        app.setPalette(theme.palette())
        app.setStyleSheet(theme.stylesheet())
        self.toolbar.setStyleSheet("")
        self.panel.restyle()
        self.header.update()
        for w in self.findChildren(QWidget):
            w.update()

    def toggle_panel(self):
        self.panel.setVisible(not self.panel.isVisible())

    def about(self):
        QMessageBox.about(self, "About PR7-L",
                          f"<b>Paragon PR7-L</b> {__version__}<br>A tag editor that works the way Mp3tag works.<br><br>"
                          "Tags: mutagen (GPL-2.0-or-later). Tag sources: MusicBrainz and the Cover Art Archive.")

    def closeEvent(self, e):
        self._confirm_discard()
        if self.library:
            self.library.close()
            self._library = False
        settings.set("column_widths", [self.view.header().sectionSize(i) for i in range(len(COLUMNS) - 1)])
        settings.set("geometry", bytes(self.saveGeometry().toHex()).decode())
        super().closeEvent(e)
