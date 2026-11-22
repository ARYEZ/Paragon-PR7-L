"""Mp3tag's actions: named groups of steps (replace, case conversion, format value, remove fields ...) run on
the selected files in one go. (No Qt here.)

An action is a dict: {"type": "replace", "field": "TITLE", "find": "feat.", "replace": "ft." ...}; a group is
{"name": ..., "actions": [...]}. `plan()` runs a list of actions on each file's fields in memory and returns
convert.Planned items (the tag changes, a new file name, a cover to embed or export), which the window applies
as one Undo step, like the converters.

Fields an action works on: one name, several separated by ';', or _ALL (every field but MusicBrainz ids).
_FILENAME is the file's name without its extension: an action that changes it renames the file.
PICTURE stands for the embedded pictures in Remove fields (except).
"""

from __future__ import annotations

import os
import re

from . import script
from .convert import Planned, clean_component
from .tags import FRONT, SEP, Picture, TagFile

TYPES = {  # type: (menu name, the form: [(key, label, kind, default)])  kind: text | field | check | mode
    "replace": ("Replace", [("field", "Field", "field", "TITLE"), ("find", "Original", "text", ""),
                            ("replace", "Replace with", "text", ""), ("case", "Case-sensitive", "check", False),
                            ("word", "Only whole words", "check", False)]),
    "regexp": ("Replace with regular expression", [("field", "Field", "field", "TITLE"),
                                                   ("regex", "Regular expression", "text", ""),
                                                   ("replace", "Replace matches with ($1 = group 1)", "text", ""),
                                                   ("case", "Case-sensitive", "check", False)]),
    "case": ("Case conversion", [("field", "Field", "field", "_ALL"), ("mode", "Mode", "mode", "mixed"),
                                 ("after", "Upper case after these characters", "text", " ([{/-\""),
                                 ("exceptions", "Exceptions (written exactly so)", "text", "AC/DC DJ feat. II III IV")]),
    "format": ("Format value", [("field", "Field", "field", "TITLE"), ("format", "Format string", "text", "%title%")]),
    "remove": ("Remove fields", [("fields", "Fields to remove (; between)", "text", "COMMENT;ENCODEDBY")]),
    "remove_except": ("Remove fields except", [
        ("fields", "Fields to keep (; between)", "text",
         "TITLE;ARTIST;ALBUM;ALBUMARTIST;TRACK;DISCNUMBER;YEAR;GENRE;COMPOSER;PICTURE")]),
    "guess": ("Guess values", [("source", "Source format", "text", "%_filename%"),
                               ("pattern", "Guessing pattern", "text", "%artist% - %title%")]),
    "split": ("Split field by separator", [("field", "Field", "field", "ARTIST"),
                                           ("separator", "Separator", "text", "; ")]),
    "merge": ("Merge duplicate fields", [("field", "Field", "field", "ARTIST"),
                                         ("separator", "Separator", "text", "; ")]),
    "import_cover": ("Import cover from file", [("file", "Image file (format string, next to the file)", "text",
                                                 "folder.jpg"),
                                                ("only_missing", "Only for files without a cover", "check", True)]),
    "export_cover": ("Export cover to file", [("file", "File name without extension (format string)", "text",
                                               "folder"),
                                              ("overwrite", "Overwrite existing files", "check", False)]),
}
MODES = {"lower": "lower case", "upper": "UPPER CASE", "sentence": "First letter upper case",
         "mixed": "Mixed Case (Every Word)"}

DEFAULT_GROUPS = [
    {"name": "Mixed Case: title, artist, album", "actions": [
        {"type": "case", "field": "TITLE;ARTIST;ALBUM;ALBUMARTIST", "mode": "mixed", "after": " ([{/-\"",
         "exceptions": "AC/DC DJ feat. II III IV"}]},
    {"name": "Remove comments and encoder fields", "actions": [
        {"type": "remove", "fields": "COMMENT;ENCODEDBY;ENCODER;ENCODERSETTINGS"}]},
    {"name": "Filename: underscores to spaces", "actions": [
        {"type": "replace", "field": "_FILENAME", "find": "_", "replace": " ", "case": False, "word": False}]},
]


def new_action(kind: str) -> dict:
    return {"type": kind, **{k: d for k, _, _, d in TYPES[kind][1]}}


def describe(a: dict) -> str:
    """One line per action, as Mp3tag lists them in a group."""
    t = a.get("type")
    if t == "replace":
        return f'Replace "{a.get("find", "")}" with "{a.get("replace", "")}" in {a.get("field", "")}'
    if t == "regexp":
        return f'Replace /{a.get("regex", "")}/ with "{a.get("replace", "")}" in {a.get("field", "")}'
    if t == "case":
        return f'{MODES.get(a.get("mode"), "Case")} in {a.get("field", "")}'
    if t == "format":
        return f'{a.get("field", "")} = {a.get("format", "")}'
    if t == "remove":
        return f'Remove {a.get("fields", "")}'
    if t == "remove_except":
        return f'Remove all fields except {a.get("fields", "")}'
    if t == "guess":
        return f'Guess {a.get("pattern", "")} from {a.get("source", "")}'
    if t == "split":
        return f'Split {a.get("field", "")} at "{a.get("separator", "")}"'
    if t == "merge":
        return f'Merge {a.get("field", "")} with "{a.get("separator", "")}"'
    if t == "import_cover":
        return f'Import cover from {a.get("file", "")}'
    if t == "export_cover":
        return f'Export cover to {a.get("file", "")}'
    return str(t)


# ------------------------------------------------------------------------------------------ case conversion
def convert_case(text: str, mode: str, after: str = " ", exceptions: str = "") -> str:
    if mode == "lower":
        out = text.lower()
    elif mode == "upper":
        out = text.upper()
    elif mode == "sentence":
        out = text[:1].upper() + text[1:].lower()
    else:  # mixed: upper case at the start and after any of `after`, lower case elsewhere
        chars, start = [], True
        for ch in text:
            if ch.isalpha():
                chars.append(ch.upper() if start else ch.lower())
                start = False
            else:
                chars.append(ch)
                start = ch in after or ch.isspace() or (start and not ch.isalnum())
                if ch.isdigit():
                    start = False
        out = "".join(chars)
    if mode in ("lower", "upper"):
        return out  # all of it, as asked: exceptions are for the capitalising modes
    for word in exceptions.split():  # exceptions keep their exact spelling wherever they stand as a word
        out = re.sub(rf"(?<![\w]){re.escape(word)}(?![\w])", lambda m, w=word: w, out, flags=re.I)
    return out


# ------------------------------------------------------------------------------------------ running
class _State:
    def __init__(self, tf: TagFile):
        self.tf = tf
        self.fields = {k: list(v) for k, v in tf.fields.items()}
        self.filename = os.path.splitext(os.path.basename(tf.path))[0]
        self.pictures: list[Picture] | None = None  # None: unchanged
        self.exports: list[tuple[str, bytes]] = []
        self.notes: list[str] = []

    def pictures_now(self) -> list[Picture]:
        return self.pictures if self.pictures is not None else self.tf.load_pictures()

    def targets(self, spec: str) -> list[str]:
        names = [n.strip().upper() for n in spec.split(";") if n.strip()]
        out = []
        for n in names:
            if n == "_ALL":
                out += [k for k in self.fields if not k.startswith("MUSICBRAINZ_")]
            else:
                out.append(script.ALIASES.get(n, n))
        return list(dict.fromkeys(out))

    def edit(self, spec: str, fn) -> None:
        """Apply fn to every value of the target fields (and the file name, for _FILENAME)."""
        for name in self.targets(spec):
            if name == "_FILENAME":
                self.filename = fn(self.filename)
                continue
            if name in self.fields:
                values = [fn(v) for v in self.fields[name]]
                self.fields[name] = [v for v in values if v != ""]
                if not self.fields[name]:
                    del self.fields[name]

    def context(self, counter: int) -> script.Context:
        return script.Context(self.tf, counter=counter, fields=self.fields)


def _replace(a: dict):
    find, repl = a.get("find", ""), a.get("replace", "")
    if not find:
        return lambda v: v
    pattern = re.escape(find)
    if a.get("word"):
        pattern = rf"(?<!\w){pattern}(?!\w)"
    rx = re.compile(pattern, 0 if a.get("case") else re.I)
    return lambda v: rx.sub(lambda _m: repl, v)


def _regexp(a: dict):
    try:
        rx = re.compile(a.get("regex", ""), 0 if a.get("case") else re.I)
    except re.error as e:
        raise script.ScriptError(f"The regular expression: {e}") from e
    repl = re.sub(r"\$(\d+)", r"\\g<\1>", a.get("replace", ""))  # Mp3tag's $1 is Python's \g<1>
    return lambda v: rx.sub(repl, v)


def run(actions: list[dict], tf: TagFile, counter: int = 1) -> _State:
    s = _State(tf)
    for a in actions:
        t = a.get("type")
        if t == "replace":
            s.edit(a.get("field", ""), _replace(a))
        elif t == "regexp":
            s.edit(a.get("field", ""), _regexp(a))
        elif t == "case":
            s.edit(a.get("field", ""), lambda v, a=a: convert_case(v, a.get("mode", "mixed"), a.get("after", " "),
                                                                    a.get("exceptions", "")))
        elif t == "format":
            value = script.format_string(a.get("format", ""), s.context(counter))
            for name in s.targets(a.get("field", "")):
                if name == "_FILENAME":
                    s.filename = value
                elif value:
                    s.fields[name] = value.split(SEP)
                else:
                    s.fields.pop(name, None)
        elif t in ("remove", "remove_except"):
            names = set(s.targets(a.get("fields", "")))
            drop = names if t == "remove" else set(s.fields) - names
            for name in drop:
                s.fields.pop(name, None)
            if ("PICTURE" in names) == (t == "remove"):
                s.pictures = []
        elif t == "guess":
            text = script.format_string(a.get("source", ""), s.context(counter))
            got = script.guess(a.get("pattern", ""), text)
            if got is None:
                s.notes.append("didn't fit the guessing pattern")
            else:
                for name, value in got.items():
                    if value:
                        s.fields[name] = value.split(SEP)
        elif t == "split":
            sep = a.get("separator", "")
            for name in s.targets(a.get("field", "")):
                if sep and name in s.fields:
                    s.fields[name] = [p.strip() for v in s.fields[name] for p in v.split(sep) if p.strip()]
        elif t == "merge":
            for name in s.targets(a.get("field", "")):
                if len(s.fields.get(name, [])) > 1:
                    s.fields[name] = [a.get("separator", "").join(s.fields[name])]
        elif t == "import_cover":
            if a.get("only_missing", True) and s.pictures_now():
                continue
            name = script.format_string(a.get("file", ""), s.context(counter))
            path = os.path.join(os.path.dirname(tf.path), name)
            if os.path.isfile(path):
                with open(path, "rb") as fh:
                    s.pictures = [Picture(fh.read(), type=FRONT)]
            else:
                s.notes.append(f"no {name}")
        elif t == "export_cover":
            pics = s.pictures_now()
            front = next((p for p in pics if p.type == FRONT), pics[0] if pics else None)
            if front is None:
                s.notes.append("no cover to export")
                continue
            ext = {"image/png": ".png", "image/gif": ".gif", "image/bmp": ".bmp", "image/webp": ".webp"}.get(
                front.mime, ".jpg")
            name = script.format_string(a.get("file", ""), s.context(counter))
            path = os.path.join(os.path.dirname(tf.path), *[clean_component(p) for p in re.split(r"[\\/]", name)
                                                            if clean_component(p)]) + ext
            if a.get("overwrite") or not os.path.exists(path):
                s.exports.append((path, front.data))
        else:
            raise script.ScriptError(f"Unknown action: {t}")
    return s


def plan(actions: list[dict], files: list[TagFile]) -> list[Planned]:
    """What the actions would do to each file: changed fields, a new name, pictures, covers to export."""
    out = []
    taken: set[str] = set()
    for i, tf in enumerate(files, 1):
        s = run(actions, tf, i)
        p = Planned(tf)
        old = tf.fields
        changes = {k: v for k, v in s.fields.items() if old.get(k) != v}
        changes.update({k: None for k in old if k not in s.fields})
        p.changes = changes or None
        p.pictures = s.pictures if s.pictures is not None and (s.pictures or tf.front_meta()) else None
        exports = []
        for path, data in s.exports:
            if os.path.normcase(path) not in taken:  # one folder.jpg per folder, not one per file
                taken.add(os.path.normcase(path))
                exports.append((path, data))
        p.exports = exports
        stem = clean_component(s.filename)
        if stem and stem != os.path.splitext(os.path.basename(tf.path))[0]:
            new = os.path.join(os.path.dirname(tf.path), stem + os.path.splitext(tf.path)[1])
            if os.path.exists(new) and os.path.normcase(new) != os.path.normcase(tf.path):
                p.error = "A file with the new name is already there."
            else:
                p.new = new
        if not (p.changes or p.pictures is not None or p.exports or p.new) and s.notes and not p.error:
            p.error = "; ".join(s.notes)
        out.append(p)
    return out
