"""Actions (Alt+6): the action groups, tick and run; New / Edit open the group editor, whose actions each have
their own small form. Actions (Quick) (Alt+7): one action, run once, not saved. Groups are kept in the
`action_groups` setting (JSON)."""

from __future__ import annotations

import copy

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QGridLayout,
                               QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMessageBox, QPushButton, QVBoxLayout)

from . import actions, settings
from .widgets import Header

FIELDS = ["TITLE", "ARTIST", "ALBUM", "ALBUMARTIST", "TRACK", "DISCNUMBER", "YEAR", "GENRE", "COMMENT", "COMPOSER",
          "_ALL", "_FILENAME", "TITLE;ARTIST;ALBUM;ALBUMARTIST"]


def load_groups() -> list[dict]:
    saved = settings.get("action_groups", "")
    if not saved:
        return copy.deepcopy(actions.DEFAULT_GROUPS)
    groups = settings.get_list("action_groups")
    return [g for g in groups if isinstance(g, dict) and isinstance(g.get("actions"), list)]


def save_groups(groups: list[dict]) -> None:
    settings.set("action_groups", groups)


def _shell(dlg: QDialog, header: str) -> QVBoxLayout:
    root = QVBoxLayout(dlg)
    root.setContentsMargins(0, 0, 0, 16)
    root.addWidget(Header(header))
    body = QVBoxLayout()
    body.setContentsMargins(20, 12, 20, 0)
    root.addLayout(body, 1)
    return body


def _ok_cancel(dlg: QDialog) -> QDialogButtonBox:
    b = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    b.accepted.connect(dlg.accept)
    b.rejected.connect(dlg.reject)
    return b


def _buttons(specs, layout=None) -> QVBoxLayout:
    col = layout or QVBoxLayout()
    for text, fn in specs:
        b = QPushButton(text)
        b.clicked.connect(fn)
        col.addWidget(b)
    col.addStretch(1)
    return col


class ActionEditor(QDialog):
    """The form of one action type (Mp3tag's 'Action: Replace' ... windows)."""

    def __init__(self, action: dict, parent=None):
        super().__init__(parent)
        self.action = dict(action)
        title, form = actions.TYPES[action["type"]]
        self.setWindowTitle(title)
        self.resize(640, 120 + 56 * len(form))
        body = _shell(self, title.upper())
        g = QGridLayout()
        self.widgets = {}
        for r, (key, label, kind, default) in enumerate(form):
            value = self.action.get(key, default)
            if kind == "check":
                w = QCheckBox(label)
                w.setChecked(bool(value))
                g.addWidget(w, r, 0, 1, 2)
            else:
                lab = QLabel(label.upper())
                lab.setProperty("role", "field")
                g.addWidget(lab, r, 0)
                if kind == "field":
                    w = QComboBox()
                    w.setEditable(True)
                    w.addItems(FIELDS)
                    w.setCurrentText(str(value))
                elif kind == "mode":
                    w = QComboBox()
                    for k, text in actions.MODES.items():
                        w.addItem(text, k)
                    w.setCurrentIndex(max(0, list(actions.MODES).index(value) if value in actions.MODES else 3))
                else:
                    w = QLineEdit(str(value))
                g.addWidget(w, r, 1)
            self.widgets[key] = (kind, w)
        g.setColumnStretch(1, 1)
        body.addLayout(g)
        body.addStretch(1)
        body.addWidget(_ok_cancel(self))

    def value(self) -> dict:
        out = {"type": self.action["type"]}
        for key, (kind, w) in self.widgets.items():
            if kind == "check":
                out[key] = w.isChecked()
            elif kind == "field":
                out[key] = w.currentText().strip().upper()
            elif kind == "mode":
                out[key] = w.currentData()
            else:
                out[key] = w.text()
        return out


def choose_type(parent) -> str | None:
    names = [t[0] for t in actions.TYPES.values()]
    name, ok = QInputDialog.getItem(parent, "New action", "Action type:", names, 0, False)
    return list(actions.TYPES)[names.index(name)] if ok else None


class GroupEditor(QDialog):
    """One action group: its name and its actions, in the order they run."""

    def __init__(self, group: dict, parent=None):
        super().__init__(parent)
        self.group = copy.deepcopy(group)
        self.setWindowTitle("Edit action group")
        self.resize(760, 520)
        body = _shell(self, "ACTION GROUP")
        row = QHBoxLayout()
        lab = QLabel("NAME")
        lab.setProperty("role", "field")
        row.addWidget(lab)
        self.name = QLineEdit(self.group.get("name", ""))
        row.addWidget(self.name, 1)
        body.addLayout(row)
        mid = QHBoxLayout()
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda _i: self.edit())
        mid.addWidget(self.list, 1)
        mid.addLayout(_buttons([("New...", self.add), ("Edit...", self.edit), ("Delete", self.delete),
                                ("Move Up", lambda: self.move(-1)), ("Move Down", lambda: self.move(1))]))
        body.addLayout(mid, 1)
        body.addWidget(_ok_cancel(self))
        self._fill()

    def _fill(self, current: int = -1):
        while self.list.count():
            self.list.takeItem(0)
        for a in self.group["actions"]:
            self.list.addItem(actions.describe(a))
        if self.group["actions"]:
            self.list.setCurrentRow(max(0, min(current, len(self.group["actions"]) - 1)))

    def add(self, kind: str | None = None, edit: bool = True):
        kind = kind or choose_type(self)
        if not kind:
            return
        a = actions.new_action(kind)
        if edit:
            dlg = ActionEditor(a, self)
            if not dlg.exec():
                return
            a = dlg.value()
        self.group["actions"].append(a)
        self._fill(len(self.group["actions"]) - 1)

    def edit(self):
        i = self.list.currentRow()
        if 0 <= i < len(self.group["actions"]):
            dlg = ActionEditor(self.group["actions"][i], self)
            if dlg.exec():
                self.group["actions"][i] = dlg.value()
                self._fill(i)

    def delete(self):
        i = self.list.currentRow()
        if 0 <= i < len(self.group["actions"]):
            del self.group["actions"][i]
            self._fill(i)

    def move(self, step: int):
        i, a = self.list.currentRow(), self.group["actions"]
        if 0 <= i < len(a) and 0 <= i + step < len(a):
            a[i], a[i + step] = a[i + step], a[i]
            self._fill(i + step)

    def value(self) -> dict:
        self.group["name"] = self.name.text().strip() or "New action group"
        return self.group


class ActionsDialog(QDialog):
    """Tick the groups to run (in list order) on the selected files; OK runs them."""

    def __init__(self, count: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Actions")
        self.resize(760, 560)
        self.groups = load_groups()
        body = _shell(self, "ACTIONS")
        hint = QLabel(f"Tick the action groups to run on the {count} selected file(s). Double-click edits a group.")
        hint.setProperty("role", "dim")
        body.addWidget(hint)
        mid = QHBoxLayout()
        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list.itemDoubleClicked.connect(lambda _i: self.edit())
        mid.addWidget(self.list, 1)
        mid.addLayout(_buttons([("New...", self.new), ("Edit...", self.edit), ("Copy", self.copy),
                                ("Delete", self.delete), ("Move Up", lambda: self.move(-1)),
                                ("Move Down", lambda: self.move(1))]))
        body.addLayout(mid, 1)
        body.addWidget(_ok_cancel(self))
        self.checked = set(settings.get_list("action_checked"))
        self._fill()

    def _fill(self, current: int = 0):
        while self.list.count():
            self.list.takeItem(0)
        for g in self.groups:
            it = QListWidgetItem(g.get("name", ""))
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if g.get("name") in self.checked else Qt.Unchecked)
            it.setToolTip("\n".join(actions.describe(a) for a in g["actions"]))
            self.list.addItem(it)
        if self.groups:
            self.list.setCurrentRow(max(0, min(current, len(self.groups) - 1)))

    def _sync_checks(self):
        self.checked = {self.groups[i]["name"] for i in range(self.list.count())
                        if self.list.item(i).checkState() == Qt.Checked}

    def _changed(self, current: int):
        save_groups(self.groups)
        self._fill(current)

    def new(self):
        self._sync_checks()
        dlg = GroupEditor({"name": "", "actions": []}, self)
        if dlg.exec():
            self.groups.append(dlg.value())
            self._changed(len(self.groups) - 1)

    def edit(self):
        self._sync_checks()
        i = self.list.currentRow()
        if 0 <= i < len(self.groups):
            dlg = GroupEditor(self.groups[i], self)
            if dlg.exec():
                was = self.groups[i]["name"] in self.checked
                self.groups[i] = dlg.value()
                if was:
                    self.checked.add(self.groups[i]["name"])
                self._changed(i)

    def copy(self):
        self._sync_checks()
        i = self.list.currentRow()
        if 0 <= i < len(self.groups):
            g = copy.deepcopy(self.groups[i])
            g["name"] += " (copy)"
            self.groups.insert(i + 1, g)
            self._changed(i + 1)

    def delete(self):
        self._sync_checks()
        i = self.list.currentRow()
        if 0 <= i < len(self.groups) and QMessageBox.question(
                self, "Actions", f'Delete the action group "{self.groups[i]["name"]}"?',
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes:
            del self.groups[i]
            self._changed(i)

    def move(self, step: int):
        self._sync_checks()
        i, g = self.list.currentRow(), self.groups
        if 0 <= i < len(g) and 0 <= i + step < len(g):
            g[i], g[i + step] = g[i + step], g[i]
            self._changed(i + step)

    def chosen(self) -> list[dict]:
        """The actions of the ticked groups, in list order."""
        self._sync_checks()
        settings.set("action_checked", sorted(self.checked))
        return [a for g in self.groups if g["name"] in self.checked for a in g["actions"]]
