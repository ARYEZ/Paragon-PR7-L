"""The Convert dialogs (Tag - Filename, Filename - Tag, Text file - Tag, Tag - Tag) and the Auto-numbering
Wizard: a format string with its history, and a preview of every selected file before OK."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                               QGridLayout, QHBoxLayout, QHeaderView, QLabel, QPlainTextEdit, QPushButton, QSpinBox,
                               QTreeView, QVBoxLayout)

from . import convert, script, settings, theme
from .tags import SEP
from .widgets import Header

KINDS = {  # kind: (title, header, default format strings, Mp3tag's examples)
    "tag2file": ("Tag - Filename", "TAG - FILENAME", ["%track% - %title%", "$num(%track%,2) %title%",
                                                      "%artist% - %title%", "%artist%\\%album%\\$num(%track%,2) %title%"]),
    "file2tag": ("Filename - Tag", "FILENAME - TAG", ["%track% - %title%", "%track%. %title%", "%artist% - %title%",
                                                      "%track% - %artist% - %title%", "%artist%\\%album%\\%track% %title%"]),
    "text2tag": ("Text file - Tag", "TEXT FILE - TAG", ["%title%", "%track%. %title%", "%track% %title%",
                                                        "%title% %dummy%"]),
    "tag2tag": ("Tag - Tag", "TAG - TAG", ["%title%", "$caps(%title%)", "$num(%track%,2)", "%artist% - %title%"]),
}
HELP = {
    "tag2file": "Placeholders %title% %artist% %track% ... and functions: $num(%track%,2) $caps(x) $left(x,n) "
                "$replace(x,a,b) $if(c,a,b) ...  A \\ makes folders. Illegal characters become '-'.",
    "file2tag": "Write the file name with placeholders where the fields are: %track% - %title%. "
                "%dummy% skips a part. A \\ also reads folder names: %artist%\\%album%\\%track% %title%",
    "text2tag": "One line per file, in the list's order. Write each line with placeholders: %track%. %title%",
    "tag2tag": "The field gets the format string's result, per file: $caps(%title%), %artist% - %title% ...",
}
FIELDS = ["TITLE", "ARTIST", "ALBUM", "ALBUMARTIST", "TRACK", "DISCNUMBER", "YEAR", "GENRE", "COMMENT", "COMPOSER"]


class Preview(QAbstractTableModel):
    def __init__(self, columns):
        super().__init__()
        self.columns, self.rows = columns, []   # rows: (old, new, is_error)

    def set_rows(self, rows):
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else 2

    def headerData(self, s, o, role=Qt.DisplayRole):
        return self.columns[s].upper() if o == Qt.Horizontal and role == Qt.DisplayRole else None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        old, new, bad = self.rows[index.row()]
        if role in (Qt.DisplayRole, Qt.ToolTipRole):
            return old if index.column() == 0 else new
        if role == Qt.ForegroundRole and index.column() == 1:
            return QColor(theme.METER_RED) if bad else QColor(theme.LED_ORANGE)
        return None


def _field_label(text: str) -> QLabel:
    lab = QLabel(text.upper())
    lab.setProperty("role", "field")
    return lab


def _history(kind: str) -> list[str]:
    saved = [s for s in settings.get_list(f"format_{kind}") if isinstance(s, str)]
    return list(dict.fromkeys(saved + KINDS[kind][2]))


def remember(kind: str, fmt: str) -> None:
    """The format string goes to the top of the converter's history (10 kept), as in Mp3tag."""
    if fmt:
        settings.set(f"format_{kind}", list(dict.fromkeys([fmt] + settings.get_list(f"format_{kind}")))[:10])


class ConvertDialog(QDialog):
    def __init__(self, kind: str, files, parent=None):
        super().__init__(parent)
        self.kind, self.files = kind, list(files)
        title, header, _ = KINDS[kind]
        self.setWindowTitle(title)
        self.resize(980, 640)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 16)
        root.addWidget(Header(header))
        body = QVBoxLayout()
        body.setContentsMargins(20, 12, 20, 0)
        grid = QGridLayout()
        row = 0
        self.field = None
        if kind == "tag2tag":
            self.field = QComboBox()
            self.field.setEditable(True)
            self.field.addItems(FIELDS)
            self.field.setCurrentText(settings.get("tag2tag_field", "TITLE"))
            self.field.editTextChanged.connect(self._later)
            grid.addWidget(_field_label("Field"), row, 0)
            grid.addWidget(self.field, row, 1)
            row += 1
        self.format = QComboBox()
        self.format.setEditable(True)
        self.format.setInsertPolicy(QComboBox.NoInsert)
        self.format.addItems(_history(kind))
        self.format.editTextChanged.connect(self._later)
        grid.addWidget(_field_label("Format string"), row, 0)
        grid.addWidget(self.format, row, 1)
        grid.setColumnStretch(1, 1)
        body.addLayout(grid)
        hint = QLabel(HELP[kind])
        hint.setProperty("role", "dim")
        hint.setWordWrap(True)
        body.addWidget(hint)
        self.text = None
        if kind == "text2tag":
            buttons = QHBoxLayout()
            load = QPushButton("Load Text File...")
            load.clicked.connect(self.load_text)
            paste = QPushButton("Paste")
            paste.clicked.connect(lambda: self.text.setPlainText(QGuiApplication.clipboard().text()))
            buttons.addWidget(load)
            buttons.addWidget(paste)
            buttons.addStretch(1)
            body.addLayout(buttons)
            self.text = QPlainTextEdit()
            self.text.setPlaceholderText("One line per file, e.g. a track list copied from a web page")
            self.text.setMaximumHeight(170)
            self.text.textChanged.connect(self._later)
            body.addWidget(self.text)
        self.message = QLabel("")
        self.message.setProperty("role", "dim")
        body.addWidget(self.message)
        self.preview = Preview(["File", "New name" if kind == "tag2file" else "New fields"])
        view = QTreeView()
        view.setRootIsDecorated(False)
        view.setAlternatingRowColors(True)
        view.setSelectionMode(QAbstractItemView.NoSelection)
        view.setModel(self.preview)
        view.header().setSectionResizeMode(QHeaderView.Interactive)
        view.header().resizeSection(0, 380)
        view.header().setStretchLastSection(True)
        body.addWidget(view, 1)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        body.addWidget(self.buttons)
        root.addLayout(body, 1)
        self._timer = QTimer(self, singleShot=True, interval=120)
        self._timer.timeout.connect(self.refresh)
        self.planned: list[convert.Planned] = []
        self.refresh()

    def _later(self, *_):
        self._timer.start()

    def load_text(self):
        start = os.path.dirname(self.files[0].path) if self.files else ""
        path, _ = QFileDialog.getOpenFileName(self, "Text file", start, "Text (*.txt *.m3u *.cue *.*)")
        if path:
            data = Path(path).read_bytes()
            for enc in ("utf-8-sig", "cp1252"):
                try:
                    self.text.setPlainText(data.decode(enc))
                    break
                except UnicodeDecodeError:
                    continue

    def plan(self) -> list[convert.Planned]:
        fmt = self.format.currentText()
        if self.kind == "tag2file":
            return convert.tag_to_filename(self.files, fmt)
        if self.kind == "file2tag":
            return convert.filename_to_tag(self.files, fmt)
        if self.kind == "text2tag":
            return convert.text_to_tag(self.files, self.text.toPlainText(), fmt)
        return convert.tag_to_tag(self.files, self.field.currentText() or "TITLE", fmt)

    def refresh(self):
        self._timer.stop()
        try:
            self.planned = self.plan()
        except script.ScriptError as e:
            self.planned = []
            self.message.setText(str(e))
            self.preview.set_rows([])
            self.buttons.button(QDialogButtonBox.Ok).setEnabled(False)
            return
        rows = []
        for p in self.planned:
            if p.error:
                rows.append((p.tf.filename, p.error, True))
            elif self.kind == "tag2file":
                new = p.new
                base = os.path.dirname(p.tf.path)
                shown = os.path.relpath(new, base) if os.path.splitdrive(new)[0] == os.path.splitdrive(base)[0] else new
                rows.append((p.tf.filename, shown, False))
            else:
                text = "   ".join(f"{k}: {SEP.join(v) if v else '(removed)'}" for k, v in (p.changes or {}).items())
                rows.append((p.tf.filename, text or "(nothing)", False))
        self.preview.set_rows(rows)
        bad = sum(1 for p in self.planned if p.error)
        good = len(self.planned) - bad
        self.message.setText(f"{good} of {len(self.planned)} file(s) will change" + (
            f"; {bad} left as they are" if bad else "") + ".")
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(good > 0)

    def accept(self):
        self.refresh()
        remember(self.kind, self.format.currentText())
        if self.field is not None:
            settings.set("tag2tag_field", self.field.currentText().upper())
        super().accept()


class AutoNumberDialog(QDialog):
    """Mp3tag's Auto-numbering Wizard: numbers the selected files in the list's order."""

    def __init__(self, files, parent=None):
        super().__init__(parent)
        self.files = list(files)
        self.setWindowTitle("Auto-numbering Wizard")
        self.resize(820, 600)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 16)
        root.addWidget(Header("AUTO-NUMBERING"))
        body = QVBoxLayout()
        body.setContentsMargins(20, 12, 20, 0)
        g = QGridLayout()
        self.start = QSpinBox()
        self.start.setRange(0, 9999)
        self.start.setValue(settings.get_int("number_start", 1))
        g.addWidget(_field_label("Start at"), 0, 0)
        g.addWidget(self.start, 0, 1)
        g.setColumnStretch(2, 1)
        body.addLayout(g)
        self.zero = QCheckBox("Add leading zero (01, 02 ...)")
        self.zero.setChecked(settings.get_bool("number_zero", True))
        self.per_folder = QCheckBox("Reset counter for every directory")
        self.per_folder.setChecked(settings.get_bool("number_per_folder", True))
        self.total = QCheckBox("Add total number of tracks (01/12)")
        self.total.setChecked(settings.get_bool("number_total", False))
        self.discs = QCheckBox("Number discs by directory (DISCNUMBER 1/2, 2/2 ...)")
        self.discs.setChecked(settings.get_bool("number_discs", False))
        for c in (self.zero, self.per_folder, self.total, self.discs):
            c.toggled.connect(self.refresh)
            body.addWidget(c)
        self.start.valueChanged.connect(self.refresh)
        hint = QLabel("Files are numbered in the order of the list: sort it first (click a column title).")
        hint.setProperty("role", "dim")
        body.addWidget(hint)
        self.preview = Preview(["File", "New fields"])
        view = QTreeView()
        view.setRootIsDecorated(False)
        view.setAlternatingRowColors(True)
        view.setSelectionMode(QAbstractItemView.NoSelection)
        view.setModel(self.preview)
        view.header().resizeSection(0, 380)
        view.header().setStretchLastSection(True)
        body.addWidget(view, 1)
        b = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        b.accepted.connect(self.accept)
        b.rejected.connect(self.reject)
        body.addWidget(b)
        root.addLayout(body, 1)
        self.refresh()

    def plan(self) -> list[convert.Planned]:
        self.discs.setEnabled(self.per_folder.isChecked())
        return convert.auto_number(self.files, self.start.value(), self.zero.isChecked(),
                                   self.per_folder.isChecked(), self.total.isChecked(),
                                   self.discs.isChecked() and self.per_folder.isChecked())

    def refresh(self, *_):
        self.planned = self.plan()
        self.preview.set_rows([(p.tf.filename, "   ".join(f"{k}: {v[0]}" for k, v in p.changes.items()), False)
                               for p in self.planned])

    def accept(self):
        for k, w in (("number_zero", self.zero), ("number_per_folder", self.per_folder), ("number_total", self.total),
                     ("number_discs", self.discs)):
            settings.set(k, w.isChecked())
        settings.set("number_start", self.start.value())
        self.refresh()
        super().accept()
