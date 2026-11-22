"""Mp3tag's Convert menu and the Auto-numbering Wizard, as plans: each function returns what would happen
(for the dialog's preview) and the window applies it as one Undo step. (No Qt here.)

    Tag - Filename (Alt+1)      rename files from a format string; '\\' in it makes folders
    Filename - Tag (Alt+2)      read fields out of the file name (and folders, with '\\' in the pattern)
    Text file - Tag (Alt+3)     read fields out of a text, one line per file, in the list's order
    Tag - Tag (Alt+5)           set a field from a format string
    Auto-numbering (Ctrl+K)     TRACK (and DISCNUMBER) by the list's order
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from . import script
from .tags import SEP, TagFile

# Characters Windows doesn't allow in names, and what a tag value's become in a file name.
ILLEGAL = {"\\": "-", "/": "-", "|": "-", ":": " -", "*": "", "?": "", '"': "'", "<": "", ">": ""}


@dataclass
class Rename:
    """One file renamed (or moved): Undo renames it back."""
    old: str
    new: str


@dataclass
class Planned:
    tf: TagFile
    new: str = ""                                   # Tag - Filename: the new path
    changes: dict | None = None                     # the others: field -> values (None removes)
    error: str = ""                                 # why this file is left as it is
    pictures: list | None = None                    # actions: the file's new pictures (None: unchanged)
    exports: list = field(default_factory=list)     # actions: (path, image bytes) to write next to the file


def clean_component(text: str) -> str:
    for bad, good in ILLEGAL.items():
        text = text.replace(bad, good)
    text = re.sub(r"[\x00-\x1f]", "", text)
    text = re.sub(r" {2,}", " ", text)
    return text.strip().rstrip(".").strip()  # Windows drops trailing dots and spaces


class _FilenameContext(script.Context):
    """Placeholders in a file name: several values as 'A, B', and nothing that would split a folder."""

    def get(self, name):
        if name.startswith("_"):
            return super().get(name)
        return clean_component(", ".join(self.values(name)))


# ------------------------------------------------------------------------------------------ Tag - Filename
def tag_to_filename(files: list[TagFile], fmt: str) -> list[Planned]:
    nodes = script.parse(fmt)  # a syntax error is raised once, for the dialog to show
    out = []
    taken: dict[str, str] = {}
    for i, tf in enumerate(files, 1):
        p = Planned(tf)
        name = script._eval(nodes, _FilenameContext(tf, counter=i))
        parts = [clean_component(c) for c in re.split(r"[\\/]", name)]
        drive = ""
        if re.match(r"^[A-Za-z]:$", name.split("\\")[0].split("/")[0]):  # an absolute path: D:\Music\...
            drive = name[:2] + os.sep
            parts = parts[1:]
        parts = [c for c in parts if c]
        ext = os.path.splitext(tf.path)[1]
        if not parts:
            p.error = "The format string gives an empty name."
        else:
            base = drive if drive else os.path.dirname(tf.path)
            p.new = os.path.normpath(os.path.join(base, *parts)) + ext
            key = os.path.normcase(p.new)
            if key in taken:
                p.error = f"Same new name as {os.path.basename(taken[key])}."
                p.new = ""
            elif os.path.exists(p.new) and os.path.normcase(p.new) != os.path.normcase(tf.path):
                p.error = "A file with that name is already there."
                p.new = ""
            else:
                taken[key] = tf.path
        out.append(p)
    return out


def apply_renames(plan: list[Planned]) -> tuple[list[Rename], list[str]]:
    """Rename the planned files (making folders as needed). Returns what was renamed, and the errors."""
    done, errors = [], []
    for p in plan:
        if p.error or not p.new or p.new == p.tf.path:
            continue
        try:
            os.makedirs(os.path.dirname(p.new), exist_ok=True)
            if os.path.exists(p.new) and os.path.normcase(p.new) != os.path.normcase(p.tf.path):
                raise FileExistsError("a file with that name is already there")
            os.rename(p.tf.path, p.new)
            done.append(Rename(p.tf.path, p.new))
        except OSError as e:
            errors.append(f"{p.tf.filename}: {e}")
    return done, errors


def undo_renames(renames: list[Rename]) -> list[str]:
    errors = []
    for r in reversed(renames):
        try:
            os.rename(r.new, r.old)
            folder = os.path.dirname(r.new)
            try:
                if folder != os.path.dirname(r.old) and not os.listdir(folder):
                    os.rmdir(folder)  # a folder Tag - Filename made, now empty again
            except OSError:
                pass
        except OSError as e:
            errors.append(f"{os.path.basename(r.new)}: {e}")
    return errors


# ------------------------------------------------------------------------------------------ X - Tag
def _changes(values: dict[str, str]) -> dict:
    return {name: (v.split(SEP) if v else None) for name, v in values.items() if v}


def filename_to_tag(files: list[TagFile], fmt: str) -> list[Planned]:
    """'%track% - %title%' against the file name; with '\\' in the pattern, against that many folders too."""
    levels = fmt.replace("/", "\\").count("\\")
    out = []
    for tf in files:
        parts = re.split(r"[\\/]", os.path.splitext(tf.path)[0])
        text = "\\".join(parts[-(levels + 1):])
        got = script.guess(fmt.replace("/", "\\"), text)
        p = Planned(tf)
        if got is None:
            p.error = "The file name doesn't fit the pattern."
        else:
            p.changes = _changes(got)
        out.append(p)
    return out


def text_to_tag(files: list[TagFile], text: str, fmt: str) -> list[Planned]:
    """One line per file, in the list's order; empty lines at the end don't count."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n").split("\n") if text.strip() else []
    out = []
    for i, tf in enumerate(files):
        p = Planned(tf)
        if i >= len(lines):
            p.error = "No line for this file."
        else:
            got = script.guess(fmt, lines[i])
            if got is None:
                p.error = "The line doesn't fit the pattern."
            else:
                p.changes = _changes(got)
        out.append(p)
    return out


def tag_to_tag(files: list[TagFile], field: str, fmt: str) -> list[Planned]:
    nodes = script.parse(fmt)
    field = script.ALIASES.get(field.strip().upper(), field.strip().upper())
    out = []
    for i, tf in enumerate(files, 1):
        value = script._eval(nodes, script.Context(tf, counter=i))
        out.append(Planned(tf, changes={field: value.split(SEP) if value else None}))
    return out


# ------------------------------------------------------------------------------------------ numbering
def auto_number(files: list[TagFile], start: int = 1, leading_zero: bool = True, per_folder: bool = True,
                add_total: bool = False, discs: bool = False) -> list[Planned]:
    """Mp3tag's Auto-numbering Wizard: TRACK by the list's order, from `start`; again from `start` in each
    folder (when per_folder); 'n/total' with add_total; DISCNUMBER 'd/D' by folder with discs."""
    groups: dict[str, list[TagFile]] = {}
    for tf in files:
        key = os.path.normcase(os.path.dirname(tf.path)) if per_folder else ""
        groups.setdefault(key, []).append(tf)
    out = []
    disc_total = len(groups)
    for d, group in enumerate(groups.values(), 1):
        last = start + len(group) - 1
        width = max(2, len(str(last))) if leading_zero else 0
        for i, tf in enumerate(group):
            n = f"{start + i:0{width}d}"
            changes = {"TRACK": [f"{n}/{len(group):0{width}d}" if add_total else n]}
            if discs and per_folder:
                changes["DISCNUMBER"] = [f"{d}/{disc_total}"]
            out.append(Planned(tf, changes=changes))
    return out
