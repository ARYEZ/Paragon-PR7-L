"""Export (Ctrl+E): pick a configuration, where to write it, OK. Configurations are templates (export.py),
kept in the `export_configs` setting and edited here with a live preview. Create Playlist (Ctrl+L)."""

from __future__ import annotations

import os

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QGridLayout,
                               QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QMessageBox, QPlainTextEdit,
                               QPushButton, QVBoxLayout)

from . import export, script, settings
from .widgets import Header


def load_configs() -> dict[str, str]:
    raw = settings.get("export_configs", "")
    if not raw:
        return dict(export.DEFAULT_CONFIGS)
    try:
        import json
        d = json.loads(raw)
        return {str(k): str(v) for k, v in d.items()} if isinstance(d, dict) else dict(export.DEFAULT_CONFIGS)
    except ValueError:
        return dict(export.DEFAULT_CONFIGS)


def save_configs(configs: dict[str, str]) -> None:
    settings.set("export_configs", configs)


def _shell(dlg, header):
    root = QVBoxLayout(dlg)
    root.setContentsMargins(0, 0, 0, 16)
    root.addWidget(Header(header))
    body = QVBoxLayout()
    body.setContentsMargins(20, 12, 20, 0)
    root.addLayout(body, 1)
    return body


def _label(text):
    lab = QLabel(text.upper())
    lab.setProperty("role", "field")
    return lab


def _mono(w):
    f = QFont("Consolas")
    f.setStyleHint(QFont.Monospace)
    f.setPointSizeF(9.5)
    w.setFont(f)
    return w


def _ok_cancel(dlg):
    b = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    b.accepted.connect(dlg.accept)
    b.rejected.connect(dlg.reject)
    return b


class ConfigEditor(QDialog):
    """One export configuration: its name and template, with the output it gives for the selected files."""

    def __init__(self, name: str, template: str, files, parent=None):
        super().__init__(parent)
        self.files = list(files)[:20]  # the preview uses the first files: quick on any selection
        self.setWindowTitle("Edit export configuration")
        self.resize(980, 720)
        body = _shell(self, "EXPORT CONFIGURATION")
        row = QHBoxLayout()
        row.addWidget(_label("Name"))
        self.name = QLineEdit(name)
        row.addWidget(self.name, 1)
        body.addLayout(row)
        hint = QLabel("$filename(csv,utf-8) first; $loop(%album%) ... $loopend() repeats per file (a loop in a loop: "
                      "per group); %title% $num(%track%,2) $csv(x) $html(x); %_total_files% %_date% outside loops.")
        hint.setProperty("role", "dim")
        hint.setWordWrap(True)
        body.addWidget(hint)
        self.template = _mono(QPlainTextEdit(template))
        self.template.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.template.textChanged.connect(lambda: self._timer.start())
        body.addWidget(self.template, 3)
        body.addWidget(_label("Preview (the first files)"))
        self.preview = _mono(QPlainTextEdit())
        self.preview.setReadOnly(True)
        self.preview.setLineWrapMode(QPlainTextEdit.NoWrap)
        body.addWidget(self.preview, 2)
        body.addWidget(_ok_cancel(self))
        self._timer = QTimer(self, singleShot=True, interval=200)
        self._timer.timeout.connect(self.refresh)
        self.refresh()

    def refresh(self):
        try:
            text, name, enc = export.render(self.template.toPlainText(), self.files)
            self.preview.setPlainText(text[:20000])
        except (export.ExportError, script.ScriptError) as e:
            self.preview.setPlainText(f"Error: {e}")

    def value(self) -> tuple[str, str]:
        return self.name.text().strip() or "New export", self.template.toPlainText()


class ExportDialog(QDialog):
    def __init__(self, files, parent=None):
        super().__init__(parent)
        self.files = list(files)
        self.setWindowTitle("Export")
        self.resize(820, 560)
        self.configs = load_configs()
        body = _shell(self, "EXPORT")
        hint = QLabel(f"Export the {len(self.files)} selected file(s) with a configuration.")
        hint.setProperty("role", "dim")
        body.addWidget(hint)
        mid = QHBoxLayout()
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._picked)
        self.list.itemDoubleClicked.connect(lambda _i: self.edit())
        mid.addWidget(self.list, 1)
        col = QVBoxLayout()
        for text, fn in (("New...", self.new), ("Edit...", self.edit), ("Copy", self.copy), ("Delete", self.delete),
                         ("Restore Defaults", self.defaults)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            col.addWidget(b)
        col.addStretch(1)
        mid.addLayout(col)
        body.addLayout(mid, 1)
        g = QGridLayout()
        g.addWidget(_label("Export file"), 0, 0)
        self.output = QLineEdit()
        g.addWidget(self.output, 0, 1)
        browse = QPushButton("Browse...")
        browse.clicked.connect(self.browse)
        g.addWidget(browse, 0, 2)
        g.setColumnStretch(1, 1)
        body.addLayout(g)
        self.append = QCheckBox("Append to the file if it's there")
        self.open_after = QCheckBox("Open the file afterwards")
        self.open_after.setChecked(settings.get_bool("export_open", True))
        body.addWidget(self.append)
        body.addWidget(self.open_after)
        body.addWidget(_ok_cancel(self))
        self._fill(settings.get("export_last", "CSV (Excel)"))

    def _fill(self, current: str = ""):
        while self.list.count():
            self.list.takeItem(0)
        names = list(self.configs)
        self.list.addItems(names)
        if names:
            self.list.setCurrentRow(names.index(current) if current in names else 0)

    def current(self) -> str:
        it = self.list.currentItem()
        return it.text() if it else ""

    def _picked(self, _row):
        name = self.current()
        if not name:
            return
        try:
            ext = export.parse(self.configs[name])[0]
        except export.ExportError:
            ext = "txt"
        self.output.setText(export.default_output(ext, name, self.files))

    def browse(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export file", self.output.text())
        if path:
            self.output.setText(path)

    def _changed(self, select: str):
        save_configs(self.configs)
        self._fill(select)

    def new(self):
        self._edit("New export", "$filename(txt,utf-8)$loop(%_path%)%artist% - %title%\n$loopend()", new=True)

    def edit(self):
        if self.current():
            self._edit(self.current(), self.configs[self.current()])

    def _edit(self, name, template, new=False):
        dlg = ConfigEditor(name, template, self.files, self)
        if dlg.exec():
            new_name, text = dlg.value()
            if not new and new_name != name:
                self.configs.pop(name, None)
            self.configs[new_name] = text
            self._changed(new_name)

    def copy(self):
        name = self.current()
        if name:
            self.configs[f"{name} (copy)"] = self.configs[name]
            self._changed(f"{name} (copy)")

    def delete(self):
        name = self.current()
        if name and QMessageBox.question(self, "Export", f'Delete the configuration "{name}"?',
                                         QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes:
            del self.configs[name]
            self._changed("")

    def defaults(self):
        self.configs.update(export.DEFAULT_CONFIGS)  # yours stay; the defaults come back as they were
        self._changed(self.current())

    def accept(self):
        name, path = self.current(), self.output.text().strip()
        if not name or not path:
            return
        try:
            text, _, enc = export.render(self.configs[name], self.files)
        except (export.ExportError, script.ScriptError) as e:
            QMessageBox.warning(self, "Export", str(e))
            return
        append = self.append.isChecked()
        if os.path.exists(path) and not append and QMessageBox.question(
                self, "Export", f"{os.path.basename(path)} is already there. Replace it?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            export.write(path, text, enc, append)
        except (OSError, UnicodeEncodeError) as e:
            QMessageBox.warning(self, "Export", f"Couldn't write {path}:\n{e}")
            return
        settings.set("export_last", name)
        settings.set("export_open", self.open_after.isChecked())
        self.written = path
        if self.open_after.isChecked():
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        super().accept()


class PlaylistDialog(QDialog):
    """Create Playlist: an M3U of the selected files, in the list's order, next to the first file."""

    def __init__(self, files, parent=None):
        super().__init__(parent)
        self.files = list(files)
        self.setWindowTitle("Create playlist")
        self.resize(820, 600)
        body = _shell(self, "CREATE PLAYLIST")
        g = QGridLayout()
        g.addWidget(_label("Playlist name"), 0, 0)
        self.name = QComboBox()
        self.name.setEditable(True)
        self.name.addItems(["%_directory%", "%album%", "$if2(%albumartist%,%artist%) - %album%", "playlist"])
        self.name.setCurrentText(settings.get("playlist_name", "%_directory%"))
        g.addWidget(self.name, 0, 1)
        g.setColumnStretch(1, 1)
        body.addLayout(g)
        self.extended = QCheckBox("Extended playlist (#EXTINF: length, artist - title)")
        self.extended.setChecked(settings.get_bool("playlist_extended", True))
        self.relative = QCheckBox("Relative paths (the playlist keeps working when the folder moves)")
        self.relative.setChecked(settings.get_bool("playlist_relative", True))
        self.utf8 = QCheckBox("UTF-8 (.m3u8); off: .m3u in Windows' ANSI, for old players")
        self.utf8.setChecked(settings.get_bool("playlist_utf8", True))
        for c in (self.extended, self.relative, self.utf8):
            body.addWidget(c)
            c.toggled.connect(self.refresh)
        self.name.editTextChanged.connect(self.refresh)
        self.where = QLabel("")
        self.where.setProperty("role", "dim")
        self.where.setWordWrap(True)
        body.addWidget(self.where)
        self.preview = _mono(QPlainTextEdit())
        self.preview.setReadOnly(True)
        self.preview.setLineWrapMode(QPlainTextEdit.NoWrap)
        body.addWidget(self.preview, 1)
        body.addWidget(_ok_cancel(self))
        self.refresh()

    def options(self) -> export.PlaylistOptions:
        return export.PlaylistOptions(self.name.currentText(), self.extended.isChecked(), self.relative.isChecked(),
                                      self.utf8.isChecked())

    def refresh(self, *_):
        try:
            self.path, self.text, self.encoding = export.playlist(self.files, self.options())
        except (export.ExportError, script.ScriptError) as e:
            self.path = ""
            self.where.setText(str(e))
            self.preview.setPlainText("")
            return
        self.where.setText(f"{len(self.files)} file(s) in {self.path}")
        self.preview.setPlainText(self.text)

    def accept(self):
        self.refresh()
        if not self.path:
            return
        if os.path.exists(self.path) and QMessageBox.question(
                self, "Create playlist", f"{os.path.basename(self.path)} is already there. Replace it?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            export.write(self.path, self.text, self.encoding)
        except UnicodeEncodeError:
            QMessageBox.warning(self, "Create playlist", "Some names have characters ANSI can't hold: tick UTF-8.")
            return
        except OSError as e:
            QMessageBox.warning(self, "Create playlist", f"Couldn't write {self.path}:\n{e}")
            return
        for k, v in (("playlist_name", self.name.currentText()), ("playlist_extended", self.extended.isChecked()),
                     ("playlist_relative", self.relative.isChecked()), ("playlist_utf8", self.utf8.isChecked())):
            settings.set(k, v)
        super().accept()
