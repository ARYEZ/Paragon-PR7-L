"""Extended Tags (Alt+T) and Options, in the family look."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QGridLayout,
                               QGroupBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QPushButton, QSpinBox,
                               QTableWidget, QTableWidgetItem, QVBoxLayout)

from . import settings
from .tags import SEP
from .widgets import Header

KEEP = "< keep >"


def _buttons(dlg: QDialog) -> QDialogButtonBox:
    b = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    b.accepted.connect(dlg.accept)
    b.rejected.connect(dlg.reject)
    return b


class ExtendedTagsDialog(QDialog):
    """Every field of the selected files (Mp3tag's Extended Tags): edit a value, add or remove a field.
    Several files: a field they don't share shows '< keep >' and is left alone unless changed."""

    def __init__(self, files, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Extended Tags")
        self.resize(760, 620)
        self.files = files
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 16)
        root.addWidget(Header("EXTENDED TAGS"))
        body = QVBoxLayout()
        body.setContentsMargins(20, 12, 20, 0)
        hint = QLabel(files[0].filename if len(files) == 1 else f"{len(files)} files")
        hint.setProperty("role", "dim")
        body.addWidget(hint)
        names = sorted({k for f in files for k in f.fields})
        self.original: dict[str, str] = {}
        for n in names:
            values = {f.get(n) for f in files}
            self.original[n] = values.pop() if len(values) == 1 else KEEP
        self.table = QTableWidget(len(names), 2)
        self.table.setHorizontalHeaderLabels(["FIELD", "VALUE"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        for r, n in enumerate(names):
            it = QTableWidgetItem(n)
            it.setFlags(it.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(r, 0, it)
            self.table.setItem(r, 1, QTableWidgetItem(self.original[n]))
        body.addWidget(self.table, 1)
        row = QHBoxLayout()
        add = QPushButton("Add Field")
        add.clicked.connect(self.add_field)
        rem = QPushButton("Remove Field")
        rem.clicked.connect(self.remove_field)
        row.addWidget(add)
        row.addWidget(rem)
        row.addStretch(1)
        body.addLayout(row)
        body.addWidget(_buttons(self))
        root.addLayout(body, 1)
        self.removed: set[str] = set()

    def add_field(self, name: str | None = None, value: str = ""):
        if not name:
            name, ok = QInputDialog.getText(self, "Add field", "Field name:")
            if not ok or not name.strip():
                return
        name = name.strip().upper()
        self.removed.discard(name)
        r = self.table.rowCount()
        self.table.insertRow(r)
        it = QTableWidgetItem(name)
        it.setFlags(it.flags() & ~Qt.ItemIsEditable)
        self.table.setItem(r, 0, it)
        self.table.setItem(r, 1, QTableWidgetItem(value))
        self.table.setCurrentCell(r, 1)

    def remove_field(self):
        for r in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            self.removed.add(self.table.item(r, 0).text())
            self.table.removeRow(r)

    def changes(self) -> dict[str, list[str] | None]:
        out: dict[str, list[str] | None] = {n: None for n in self.removed}
        for r in range(self.table.rowCount()):
            name, text = self.table.item(r, 0).text(), self.table.item(r, 1).text()
            if text == KEEP or text == self.original.get(name):
                continue  # unchanged
            out[name] = text.split(SEP) if text else None
        return out


class OptionsDialog(QDialog):
    """Options (Ctrl+O): how tags are written, the directory list, covers, the finish."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Options")
        self.resize(640, 680)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 16)
        root.addWidget(Header("OPTIONS"))
        body = QVBoxLayout()
        body.setContentsMargins(20, 6, 20, 0)
        mp3 = QGroupBox("TAGS: MPEG (MP3, WAV, AIFF, TTA)")
        g = QGridLayout(mp3)
        lab = QLabel("ID3V2 VERSION")
        lab.setProperty("role", "field")
        self.id3v2 = QComboBox()
        self.id3v2.addItems(["ID3v2.3 UTF-16", "ID3v2.4 UTF-8"])
        self.id3v2.setCurrentIndex(1 if settings.get_int("id3v2_version", 3) == 4 else 0)
        g.addWidget(lab, 0, 0)
        g.addWidget(self.id3v2, 0, 1)
        self.id3v1 = QCheckBox("Also write ID3v1 (MP3 and TTA)")
        self.id3v1.setChecked(settings.get_bool("id3v1", True))
        g.addWidget(self.id3v1, 1, 0, 1, 2)
        self.mtime = QCheckBox("Preserve file modification time")
        self.mtime.setChecked(settings.get_bool("preserve_mtime", False))
        g.addWidget(self.mtime, 2, 0, 1, 2)
        body.addWidget(mp3)
        d = QGroupBox("DIRECTORY")
        dl = QVBoxLayout(d)
        self.subdirs = QCheckBox("Include subdirectories")
        self.subdirs.setChecked(settings.get_bool("subdirectories", True))
        dl.addWidget(self.subdirs)
        body.addWidget(d)
        c = QGroupBox("COVERS")
        cg = QGridLayout(c)
        lab = QLabel("SHRINK ADDED COVERS TO")
        lab.setProperty("role", "field")
        self.max_side = QSpinBox()
        self.max_side.setRange(0, 10000)
        self.max_side.setSingleStep(100)
        self.max_side.setSpecialValueText("Keep their size")
        self.max_side.setSuffix(" px")
        self.max_side.setValue(settings.get_int("cover_max_side", 0))
        cg.addWidget(lab, 0, 0)
        cg.addWidget(self.max_side, 0, 1)
        body.addWidget(c)
        cache = QGroupBox("FILE CACHE")
        cl = QGridLayout(cache)
        self.use_cache = QCheckBox("Remember files between runs (only new or changed files are read again)")
        self.use_cache.setChecked(settings.get_bool("use_cache", True))
        cl.addWidget(self.use_cache, 0, 0, 1, 2)
        lib = getattr(parent, "library", None)
        self.cache_info = QLabel(f"{lib.count()} file(s) cached" if lib else "Not in use")
        self.cache_info.setProperty("role", "dim")
        clear = QPushButton("Clear Cache")
        clear.setEnabled(lib is not None)
        clear.clicked.connect(lambda: (lib.clear(), self.cache_info.setText("0 file(s) cached")))
        cl.addWidget(self.cache_info, 1, 0)
        cl.addWidget(clear, 1, 1)
        body.addWidget(cache)
        f = QGroupBox("FINISH")
        fl = QHBoxLayout(f)
        self.finish = QComboBox()
        self.finish.addItems(["OBSIDIAN", "AURORA"])
        self.finish.setCurrentText(settings.get("finish", "obsidian").upper())
        fl.addWidget(self.finish)
        fl.addStretch(1)
        body.addWidget(f)
        body.addStretch(1)
        body.addWidget(_buttons(self))
        root.addLayout(body, 1)

    def apply(self):
        settings.set("id3v2_version", 4 if self.id3v2.currentIndex() == 1 else 3)
        settings.set("id3v1", self.id3v1.isChecked())
        settings.set("preserve_mtime", self.mtime.isChecked())
        settings.set("subdirectories", self.subdirs.isChecked())
        settings.set("cover_max_side", self.max_side.value())
        settings.set("finish", self.finish.currentText().lower())
        settings.set("use_cache", self.use_cache.isChecked())
