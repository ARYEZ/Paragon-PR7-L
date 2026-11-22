"""Mp3tag's format strings: %field% placeholders and $functions, used by every converter. (No Qt here.)

    %artist% - $num(%track%,2) $caps(%title%)          text, placeholders and functions, nested freely
    'quoted text'                                       literal: $ % , ( ) inside lose their meaning ('' is ')

Placeholders: any field (%title%, %albumartist% ...; %band% is ALBUMARTIST, as in Mp3tag) and the file's own:
%_filename% (no extension) %_filename_ext% %_extension% %_path% %_folderpath% %_directory% %_parent_directory%
%_length% %_length_seconds% %_bitrate% %_codec% %_tag% %_counter% (the file's position in the run, from 1).
A field with several values gives them joined with '\\\\', as the tag panel shows them.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass

from .tags import SEP


class ScriptError(Exception):
    pass


ALIASES = {"BAND": "ALBUMARTIST", "DISC": "DISCNUMBER", "TRACKNUMBER": "TRACK", "DATE": "YEAR"}


@dataclass
class _Text:
    text: str


@dataclass
class _Field:
    name: str


@dataclass
class _Func:
    name: str
    args: list  # list of node lists


# ------------------------------------------------------------------------------------------ parsing
def parse(fmt: str) -> list:
    nodes, i = _parse(fmt, 0, inside=False)
    return nodes


def _parse(s: str, i: int, inside: bool):
    """Nodes up to the end (or, inside a function's arguments, up to an unquoted ',' or ')')."""
    nodes: list = []
    buf = []

    def flush():
        if buf:
            nodes.append(_Text("".join(buf)))
            buf.clear()
    while i < len(s):
        c = s[i]
        if inside and c in ",)":
            break
        if c == "'" and s[i + 1:i + 2] == "'":  # '' outside quotes: one '
            buf.append("'")
            i += 2
            continue
        if c == "'":
            j = i + 1
            while True:
                k = s.find("'", j)
                if k < 0:
                    raise ScriptError("A quote ' isn't closed.")
                if s[k + 1:k + 2] == "'":  # '' inside quotes is one '
                    buf.append(s[j:k + 1])
                    j = k + 2
                    continue
                buf.append(s[j:k])
                i = k + 1
                break
            continue
        if c == "%":
            k = s.find("%", i + 1)
            name = s[i + 1:k] if k > 0 else ""
            if k > 0 and re.fullmatch(r"[A-Za-z0-9_]+", name):
                flush()
                nodes.append(_Field(name.strip().upper()))
                i = k + 1
                continue
            buf.append(c)
            i += 1
            continue
        if c == "$":
            m = re.match(r"\$([A-Za-z_][A-Za-z0-9_]*)\(", s[i:])
            if not m:
                buf.append(c)
                i += 1
                continue
            flush()
            name = m.group(1).lower()
            i += m.end()
            args = []
            while True:
                arg, i = _parse(s, i, inside=True)
                args.append(arg)
                if i >= len(s):
                    raise ScriptError(f"${name}( isn't closed with ).")
                if s[i] == ")":
                    i += 1
                    break
                i += 1  # ','
            nodes.append(_Func(name, args))
            continue
        buf.append(c)
        i += 1
    flush()
    return nodes, i


# ------------------------------------------------------------------------------------------ evaluating
def _int(text: str) -> int:
    m = re.match(r"\s*(-?\d+)", text or "")
    return int(m.group(1)) if m else 0


def _caps(text: str, rest_lower: bool) -> str:
    out, start = [], True
    for ch in text:
        if start and ch.isalpha():
            out.append(ch.upper())
            start = False
        else:
            out.append(ch.lower() if rest_lower and not start else ch)
            if not ch.isalnum() and ch not in "'’":
                start = True
            elif ch.isalnum():
                start = False
    return "".join(out)


def _regexp(text, expr, repl, flags=""):
    repl = re.sub(r"\$(\d+)", r"\\g<\1>", repl)  # Mp3tag writes $1 for a group
    try:
        return re.sub(expr, repl, text, flags=re.I if flags and flags != "0" else 0)
    except re.error as e:
        raise ScriptError(f"$regexp: {e}") from e


def _num(text, n):
    v = _int(text)
    return f"{v:0{max(0, _int(n))}d}" if v >= 0 else "-" + f"{-v:0{max(0, _int(n))}d}"


FUNCS = {
    "num": _num,
    "left": lambda x, n: x[:max(0, _int(n))],
    "right": lambda x, n: x[len(x) - max(0, _int(n)):] if _int(n) > 0 else "",
    "mid": lambda x, i, n: x[max(0, _int(i) - 1):max(0, _int(i) - 1) + max(0, _int(n))],
    "len": lambda x: str(len(x)),
    "upper": str.upper, "lower": str.lower,
    "caps": lambda x: _caps(x, True),      # Every Word Capitalised, the rest lower case
    "caps2": lambda x: _caps(x, False),    # Every Word Capitalised, the rest as it was
    "caps3": lambda x: x[:1].upper() + x[1:].lower(),
    "trim": str.strip, "trimleft": str.lstrip, "trimright": str.rstrip,
    "cutleft": lambda x, n: x[max(0, _int(n)):],
    "cutright": lambda x, n: x[:len(x) - max(0, _int(n))] if _int(n) > 0 else x,
    "repeat": lambda x, n: x * max(0, _int(n)),
    "strstr": lambda x, y: str(x.find(y) + 1),
    "isdigit": lambda x: "1" if x.strip().isdigit() else "",
    "regexp": _regexp,
    "validate": lambda x, c: re.sub(r'[\\/:*?"<>|]', c, x),
    "add": lambda a, b: str(_int(a) + _int(b)), "sub": lambda a, b: str(_int(a) - _int(b)),
    "mul": lambda a, b: str(_int(a) * _int(b)),
    "div": lambda a, b: str(_int(a) // _int(b)) if _int(b) else "",
    "mod": lambda a, b: str(_int(a) % _int(b)) if _int(b) else "",
    "eql": lambda a, b: "1" if a == b else "", "neql": lambda a, b: "1" if a != b else "",
    "grtr": lambda a, b: "1" if _int(a) > _int(b) else "", "less": lambda a, b: "1" if _int(a) < _int(b) else "",
    "geql": lambda a, b: "1" if _int(a) >= _int(b) else "", "leql": lambda a, b: "1" if _int(a) <= _int(b) else "",
    "not": lambda x: "" if x else "1",
    "char": lambda n: chr(_int(n)) if 0 < _int(n) < 0x110000 else "",
    "csv": lambda x: _csv(x),  # defined further down: looked up when called
    "html": lambda x: x.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"),
}
LAZY = {"if", "if2", "ifgreater", "iflonger", "and", "or", "replace", "meta", "meta_sep"}


class Context:
    """What placeholders read: a TagFile's fields and properties (or a plain dict, for tests)."""

    def __init__(self, tf=None, counter: int = 0, fields: dict | None = None, extra: dict | None = None):
        self.tf = tf
        self.counter = counter
        self.fields = fields if fields is not None else (tf.fields if tf is not None else {})
        self.extra = extra or {}  # more placeholders: Export's %_total_files%, %_date% ...

    def values(self, name: str) -> list[str]:
        return self.fields.get(ALIASES.get(name, name), [])

    def get(self, name: str) -> str:
        if name.startswith("_"):
            return self._special(name.lower())
        return SEP.join(self.values(name))

    def _special(self, name: str) -> str:
        if name == "_counter":
            return str(self.counter)
        if name in self.extra:
            return str(self.extra[name])
        tf = self.tf
        if tf is None:
            return ""
        path = tf.path
        base, ext = os.path.splitext(os.path.basename(path))
        folder = os.path.dirname(path)
        from .musicbrainz import fmt_length
        return {
            "_filename": base, "_filename_ext": os.path.basename(path), "_extension": ext[1:],
            "_path": path, "_folderpath": folder + os.sep, "_directory": os.path.basename(folder),
            "_parent_directory": os.path.basename(os.path.dirname(folder)),
            "_length": fmt_length(tf.info.length), "_length_seconds": str(int(round(tf.info.length))),
            "_bitrate": str(round(tf.info.bitrate / 1000)) if tf.info.bitrate else "", "_codec": tf.info.codec,
            "_tag": tf.tag_label, "_file_size": size_text(tf.size), "_file_size_bytes": str(tf.size),
            "_file_mod_date": time.strftime("%Y-%m-%d %H:%M", time.localtime(tf.mtime)) if tf.mtime else "",
            "_samplerate": str(tf.info.sample_rate or ""), "_channels": str(tf.info.channels or ""),
            "_covers": _covers(tf),
        }.get(name, "")


def _covers(tf) -> str:
    """How many pictures the file has ('' when none, so %_covers% MISSING finds files without a cover)."""
    n = len(tf.pictures) if getattr(tf, "pictures_loaded", True) else len(tf.meta)
    return str(n) if n else ""


def size_text(n: int) -> str:
    if n >= 1 << 30:
        return f"{n / (1 << 30):.2f} GB"
    if n >= 1 << 20:
        return f"{n / (1 << 20):.1f} MB"
    return f"{n / 1024:.0f} KB"


def _csv(x: str) -> str:
    """A CSV cell for the ';' separated files Excel opens: quoted when it holds ; " or a line break."""
    return '"' + x.replace('"', '""') + '"' if any(c in x for c in ';"\r\n') else x


def _eval(nodes: list, ctx: Context) -> str:
    out = []
    for n in nodes:
        if isinstance(n, _Text):
            out.append(n.text)
        elif isinstance(n, _Field):
            out.append(ctx.get(n.name))
        else:
            out.append(_call(n, ctx))
    return "".join(out)


def _call(f: _Func, ctx: Context) -> str:
    a = f.args
    ev = (lambda k: _eval(a[k], ctx) if k < len(a) else "")
    if f.name == "if":
        return ev(1) if ev(0) else ev(2)
    if f.name == "if2":
        return ev(0) or ev(1)
    if f.name == "ifgreater":
        return ev(2) if _int(ev(0)) > _int(ev(1)) else ev(3)
    if f.name == "iflonger":
        return ev(2) if len(ev(0)) > _int(ev(1)) else ev(3)
    if f.name == "and":
        return "1" if all(_eval(x, ctx) for x in a) else ""
    if f.name == "or":
        return "1" if any(_eval(x, ctx) for x in a) else ""
    if f.name == "replace":  # $replace(text,from,to[,from2,to2 ...])
        text = ev(0)
        for k in range(1, len(a) - 1, 2):
            frm = ev(k)
            if frm:
                text = text.replace(frm, ev(k + 1))
        return text
    if f.name in ("meta", "meta_sep"):  # $meta(field[,n]) one value (0-based) or all ', '; $meta_sep(field,sep)
        name = ev(0).strip("%").upper()
        values = ctx.values(name)
        if f.name == "meta_sep":
            return ev(1).join(values)
        if len(a) > 1:
            k = _int(ev(1))
            return values[k] if 0 <= k < len(values) else ""
        return ", ".join(values)
    fn = FUNCS.get(f.name)
    if fn is None:
        raise ScriptError(f"There's no function ${f.name}.")
    args = [_eval(x, ctx) for x in a]
    try:
        return fn(*args)
    except TypeError as e:
        raise ScriptError(f"${f.name} takes a different number of values ({len(args)} given).") from e


def format_string(fmt: str, ctx: Context) -> str:
    return _eval(parse(fmt), ctx)


# ------------------------------------------------------------------------------------------ guessing
def guess(fmt: str, text: str) -> dict[str, str] | None:
    """Filename - Tag / Text file - Tag: read field values out of `text` with a pattern like
    '%track% - %artist% - %title%'. %dummy% matches and is thrown away. None when it doesn't fit."""
    pattern, names = [], []
    parts = re.split(r"(%[A-Za-z0-9_]+%)", fmt)
    fields = [p for p in parts if p.startswith("%") and p.endswith("%") and len(p) > 2]
    seen = 0
    for p in parts:
        if p in fields and p.startswith("%"):
            seen += 1
            name = p[1:-1].upper()
            names.append(ALIASES.get(name, name))
            pattern.append("(.*)" if seen == len(fields) else "(.*?)")
        elif p:
            pattern.append(re.escape(p))
    m = re.fullmatch("".join(pattern), text, re.S)
    if not m:
        return None
    out: dict[str, str] = {}
    for name, value in zip(names, m.groups()):
        if name != "DUMMY":
            out[name] = value.strip()
    return out
