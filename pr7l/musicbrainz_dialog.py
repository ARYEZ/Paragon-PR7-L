"""MusicBrainz tag source: search, pick a release, line its tracks up with the files, write.

Network calls run on Qt's thread pool so the window never freezes; their answers come back to the dialog
through queued signals (the GUI thread). A search result picked loads that release and its front cover
from the Cover Art Archive.
"""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, QRunnable, QSize, Qt, QThreadPool, Signal
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QGridLayout, QGroupBox,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton, QSplitter,
                               QTreeView, QVBoxLayout, QWidget)

from . import musicbrainz as mb, tags, theme
from .widgets import Header

RELEASE_FIELDS = [("Album", "ALBUM"), ("Album artist", "ALBUMARTIST"), ("Year", "YEAR"), ("Genre", "GENRE"),
                  ("Label", "LABEL"), ("Catalog #", "CATALOGNUMBER"), ("Type", "RELEASETYPE")]


class Table(QAbstractTableModel):
    def __init__(self, columns, rows=None, mark=None, parent=None):
        super().__init__(parent)
        self.columns, self.rows, self.mark = columns, rows or [], mark or (lambda r, c: None)

    def set_rows(self, rows):
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.columns)

    def headerData(self, s, o, role=Qt.DisplayRole):
        return self.columns[s].upper() if o == Qt.Horizontal and role == Qt.DisplayRole else None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        if role in (Qt.DisplayRole, Qt.ToolTipRole):
            return self.rows[index.row()][index.column()]
        if role == Qt.ForegroundRole:
            return self.mark(index.row(), index.column())
        if role == Qt.TextAlignmentRole and self.columns[index.column()] in ("#", "Score", "Length", "File length",
                                                                              "Tracks"):
            return int(Qt.AlignRight | Qt.AlignVCenter)
        return None


class _Signals(QObject):
    done = Signal(object, object)
    failed = Signal(object, str)


class _Job(QRunnable):
    def __init__(self, fn, signals, token):
        super().__init__()
        self.fn, self.signals, self.token = fn, signals, token

    def run(self):
        try:
            result = self.fn()
        except mb.LookupFailed as e:
            self.signals.failed.emit(self.token, str(e))
        except Exception as e:  # noqa: BLE001 - anything else is shown, not lost in a thread
            self.signals.failed.emit(self.token, f"{type(e).__name__}: {e}")
        else:
            self.signals.done.emit(self.token, result)


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


def _common(files, name) -> str:
    values = {f.get(name) for f in files} - {""}
    return values.pop() if len(values) == 1 else ""


class MusicBrainzDialog(QDialog):
    def __init__(self, files, client: mb.Client, parent=None, cover_only: bool = False, options=None):
        super().__init__(parent)
        self.files = list(files)
        self.client = client
        self.cover_only = cover_only
        self.options = options
        self.sync = False             # tests: run the network calls inline
        self.release: mb.Release | None = None
        self.releases: dict[str, mb.Release] = {}
        self.cover: bytes | None = None
        self.order: list = []         # the files, lined up with release.tracks (None: no file for that track)
        self.snapshots: list = []
        self._signals = _Signals()
        self._signals.done.connect(self._done)
        self._signals.failed.connect(self._failed)
        self._handlers: dict[object, tuple] = {}
        self._token = 0
        self._pending = 0

        self.setWindowTitle("Cover Art Archive" if cover_only else "MusicBrainz")
        self.resize(1320, 820)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 16)
        root.setSpacing(0)
        root.addWidget(Header("COVER ART ARCHIVE" if cover_only else "MUSICBRAINZ"))
        body = QVBoxLayout()
        body.setContentsMargins(20, 10, 20, 0)
        search = QHBoxLayout()
        self.artist = QLineEdit(_common(self.files, "ALBUMARTIST") or _common(self.files, "ARTIST"))
        self.album = QLineEdit(_common(self.files, "ALBUM"))
        self.album.setPlaceholderText("Album, or a MusicBrainz release ID / link")
        for label, e in (("Artist", self.artist), ("Album", self.album)):
            lab = QLabel(label.upper())
            lab.setProperty("role", "field")
            search.addWidget(lab)
            search.addWidget(e, 1)
            e.returnPressed.connect(self.search)
        self.go = QPushButton("Search")
        self.go.clicked.connect(self.search)
        search.addWidget(self.go)
        body.addLayout(search)
        self.results = Table(["Score", "Title", "Artist", "Date", "Country", "Label", "Format", "Tracks"])
        self.rv = _view(self.results)
        self.rv.setMinimumHeight(170)
        self.rv.setMaximumHeight(190)
        for i, w in enumerate([70, 280, 170, 110, 80, 200, 140]):
            self.rv.header().resizeSection(i, w)
        self.rv.selectionModel().currentRowChanged.connect(lambda cur, _p: self.pick(cur.row()))
        body.addWidget(self.rv)
        self.message = QLabel("")
        self.message.setProperty("role", "dim")
        body.addWidget(self.message)

        split = QSplitter(Qt.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 8, 0)
        rel = QGroupBox("RELEASE")
        g = QGridLayout(rel)
        self.edits: dict[str, QLineEdit] = {}
        for r, (label, name) in enumerate(RELEASE_FIELDS + [("Release ID", "")]):
            lab = QLabel(label.upper())
            lab.setProperty("role", "field")
            g.addWidget(lab, r, 0)
            e = QLineEdit()
            if name:
                self.edits[name] = e
            else:
                e.setReadOnly(True)
                self.release_id = e
            g.addWidget(e, r, 1)
        ll.addWidget(rel)
        cov = QGroupBox("COVER ART ARCHIVE")
        cl = QVBoxLayout(cov)
        self.img = QLabel("")
        self.img.setFixedSize(QSize(200, 200))
        self.img.setAlignment(Qt.AlignCenter)
        self.img.setStyleSheet(f"background: {theme.WIDGET}; border: 1px solid {theme.PANEL_EDGE}; border-radius: 6px;"
                               f" color: {theme.TEXT_DIM};")
        row = QHBoxLayout()
        row.addWidget(self.img)
        opts = QVBoxLayout()
        self.cover_info = QLabel("")
        self.cover_info.setProperty("role", "dim")
        self.cover_info.setWordWrap(True)
        opts.addWidget(self.cover_info)
        size_row = QHBoxLayout()
        lab = QLabel("SIZE")
        lab.setProperty("role", "field")
        size_row.addWidget(lab)
        self.cover_size = QComboBox()
        self.cover_size.addItems(mb.COVER_SIZES)
        self.cover_size.setCurrentText("1200")
        self.cover_size.currentTextChanged.connect(lambda _t: self._load_cover())
        size_row.addWidget(self.cover_size)
        size_row.addStretch(1)
        opts.addLayout(size_row)
        self.save_cover = QCheckBox("Save cover in files")
        self.save_cover.setChecked(True)
        opts.addWidget(self.save_cover)
        self.folder_jpg = QCheckBox("Also save as folder.jpg")
        opts.addWidget(self.folder_jpg)
        opts.addStretch(1)
        row.addLayout(opts, 1)
        cl.addLayout(row)
        ll.addWidget(cov)
        ll.addStretch(1)
        split.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(8, 0, 0, 0)
        self.hint = QLabel("Line the tracks up with your files (lengths should match), then OK writes the tags.")
        self.hint.setProperty("role", "dim")
        self.hint.setWordWrap(True)
        rl.addWidget(self.hint)
        self.match = Table(["#", "Title (MusicBrainz)", "Length", "File", "File length"], mark=self._mark)
        self.tv = _view(self.match)
        for i, w in enumerate([50, 240, 70, 280]):
            self.tv.header().resizeSection(i, w)
        rl.addWidget(self.tv, 1)
        mv = QHBoxLayout()
        for t, fn in (("Move Up", lambda: self.move(-1)), ("Move Down", lambda: self.move(1)),
                      ("Remove File", self.remove_file)):
            b = QPushButton(t)
            b.clicked.connect(fn)
            mv.addWidget(b)
        mv.addStretch(1)
        rl.addLayout(mv)
        split.addWidget(right)
        split.setStretchFactor(1, 1)
        right.setVisible(not cover_only)
        if cover_only:
            self.save_cover.setChecked(True)
            self.save_cover.setEnabled(False)
        body.addWidget(split, 1)
        root.addLayout(body, 1)
        buttons = QHBoxLayout()
        buttons.setContentsMargins(20, 14, 20, 0)
        buttons.addStretch(1)
        self.ok = QPushButton("OK")
        self.ok.setDefault(True)
        self.ok.setEnabled(False)
        self.ok.clicked.connect(self.write)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        for b in (self.ok, cancel):
            b.setMinimumWidth(96)
            buttons.addWidget(b)
        root.addLayout(buttons)

    # ------------------------------------------------------------------------------------ jobs
    def run(self, fn, done, failed=None):
        self._token += 1
        token = self._token
        self._handlers[token] = (done, failed)
        self._pending += 1
        self._busy()
        if self.sync:
            _Job(fn, self._signals, token).run()
        else:
            QThreadPool.globalInstance().start(_Job(fn, self._signals, token))
        return token

    def _done(self, token, result):
        self._pending -= 1
        self._busy()
        done, _ = self._handlers.pop(token, (None, None))
        if done:
            done(result)

    def _failed(self, token, text):
        self._pending -= 1
        self._busy()
        _, failed = self._handlers.pop(token, (None, None))
        (failed or self._show_error)(text)

    def _show_error(self, text):
        self.message.setProperty("role", "error")
        self.message.setText(text)
        self.message.style().polish(self.message)

    def _say(self, text):
        self.message.setProperty("role", "dim")
        self.message.setText(text)
        self.message.style().polish(self.message)

    def _busy(self):
        self.go.setEnabled(self._pending == 0)
        self.ok.setEnabled(self._pending == 0 and self.release is not None)

    @property
    def busy(self) -> bool:
        return self._pending > 0

    # ------------------------------------------------------------------------------------ steps
    def search(self):
        artist, album = self.artist.text(), self.album.text()
        self._say("Searching MusicBrainz ...")
        self.run(lambda: self.client.search(artist, album), self._show_results)

    def _show_results(self, results: list[mb.ReleaseSummary]):
        self.summaries = results
        self.results.set_rows([(str(r.score), r.title + (f" ({r.disambiguation})" if r.disambiguation else ""),
                                r.artist, r.date, r.country, r.label, r.format, str(r.tracks)) for r in results])
        if not results:
            self._say("Nothing found. Try fewer words, or paste the release's MusicBrainz link.")
            return
        n = len(self.files)
        self._say(f"{len(results)} release(s). Pick one; {n} file(s) to tag.")
        best = next((i for i, r in enumerate(results) if r.tracks == n), 0)  # Mp3tag: the first that fits
        self.rv.setCurrentIndex(self.results.index(best, 0))

    def pick(self, row: int):
        if row < 0 or row >= len(getattr(self, "summaries", [])):
            return
        rid = self.summaries[row].id
        if rid in self.releases:
            self._show_release(self.releases[rid])
            return
        self._say("Loading the release ...")
        self.run(lambda: self.client.release(rid), self._show_release)

    def _show_release(self, release: mb.Release):
        self.releases[release.id] = release
        self.release = release
        first = release.album_tags
        for _, name in RELEASE_FIELDS:
            self.edits[name].setText(tags.SEP.join(first.get(name, [])))
        self.release_id.setText(release.id)
        self.release_id.setCursorPosition(0)
        self.order = mb.initial_order(self.files, release)
        self._refresh_match()
        n, t = len(self.files), len(release.tracks)
        self._say(f"{release.artist} - {release.title}: {t} track(s), {n} file(s)."
                  + ("" if n == t or self.cover_only else "  The counts differ: only lined-up pairs are written."))
        self._busy()
        self._load_cover()

    def _load_cover(self):
        if self.release is None:
            return
        self.cover = None
        self.img.setPixmap(QPixmap())
        self.img.setText("Loading ...")
        self.cover_info.setText("")
        rel, size = self.release, self.cover_size.currentText()
        self.run(lambda: self.client.front_cover(rel.id, rel.release_group, size),
                 lambda data, rid=rel.id: self._show_cover(rid, data),
                 lambda text: (self.img.setText("No cover"), self.cover_info.setText(text)))

    def _show_cover(self, rid, data):
        if self.release is None or rid != self.release.id:
            return  # an older release's cover arrived late
        self.cover = data
        if not data:
            self.img.setPixmap(QPixmap())
            self.img.setText("No cover")
            self.cover_info.setText("The Cover Art Archive has no front cover for this release.")
            return
        pm = QPixmap()
        if not pm.loadFromData(data):
            self.img.setText("Unreadable picture")
        else:
            self.img.setPixmap(pm.scaled(196, 196, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.cover_info.setText(tags.picture_info(tags.Picture(data)))

    # ------------------------------------------------------------------------------------ matching
    def _pairs_rows(self):
        tracks = self.release.tracks if self.release else []
        n = max(len(tracks), len(self.order))
        rows = []
        for i in range(n):
            t = tracks[i] if i < len(tracks) else None
            f = self.order[i] if i < len(self.order) else None
            num = (f"{t.disc}-{t.number}" if t.discs > 1 else str(t.number)) if t else ""
            rows.append((num, t.title if t else "", mb.fmt_length(t.length) if t else "",
                         f.filename if f else "", mb.fmt_length(f.info.length) if f else ""))
        return rows

    def _refresh_match(self, current: int | None = None):
        self.match.set_rows(self._pairs_rows())
        if current is not None:
            self.tv.setCurrentIndex(self.match.index(current, 3))

    def _mark(self, row, col):
        if col not in (2, 4) or not self.release:
            return None
        tracks = self.release.tracks
        if row < len(tracks) and row < len(self.order) and self.order[row] is not None:
            if mb.lengths_match(tracks[row].length, self.order[row].info.length):
                return QColor(theme.LED_ORANGE)
        return None

    def move(self, step: int):
        i = self.tv.currentIndex().row()
        j = i + step
        n = max(len(self.order), len(self.release.tracks) if self.release else 0)
        if i < 0 or not (0 <= j < n):
            return
        while len(self.order) < n:
            self.order.append(None)
        self.order[i], self.order[j] = self.order[j], self.order[i]
        while self.order and self.order[-1] is None:
            self.order.pop()
        self._refresh_match(j)

    def remove_file(self):
        i = self.tv.currentIndex().row()
        if 0 <= i < len(self.order):
            del self.order[i]
            self._refresh_match(min(i, max(0, len(self._pairs_rows()) - 1)))

    def pairs(self) -> list:
        tracks = self.release.tracks if self.release else []
        return [(f, t) for f, t in zip(self.order, tracks) if f is not None]

    # ------------------------------------------------------------------------------------ OK
    def write(self):
        if self.release is None or self.busy:
            return
        cover = self.cover if self.save_cover.isChecked() else None
        folder = self.folder_jpg.isChecked() and self.cover is not None
        try:
            if self.cover_only:
                if not self.cover:
                    QMessageBox.information(self, "Cover Art Archive", "This release has no front cover to save.")
                    return
                snaps = []
                for f in self.files:
                    snaps.append(tags.snapshot(f.path))
                    tags.save(f.path, {}, [tags.Picture(self.cover, type=tags.FRONT)], self.options)
                if folder:
                    self._folder_jpg()
                self.snapshots = snaps
            else:
                edits = {name: e.text() for name, e in self.edits.items()}
                self.snapshots = mb.write_release(self.pairs(), self.release, edits, cover, folder,
                                                  self.options)
                if folder and cover is None:
                    self._folder_jpg()
        except (OSError, tags.UnsupportedFile) as e:
            QMessageBox.warning(self, "MusicBrainz", f"Writing failed: {e}")
            return
        self.accept()

    def _folder_jpg(self):
        import os
        ext = "png" if tags.image_mime(self.cover) == "image/png" else "jpg"
        for folder in dict.fromkeys(os.path.dirname(f.path) for f in self.files):
            with open(os.path.join(folder, f"folder.{ext}"), "wb") as fh:
                fh.write(self.cover)
