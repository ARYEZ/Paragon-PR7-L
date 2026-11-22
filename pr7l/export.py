"""Export (Ctrl+E) and Create Playlist (Ctrl+L), as in Mp3tag. (No Qt here.)

An export configuration is a template in Mp3tag's export language:

    $filename(csv,utf-8)Title;Artist;Album          the output's extension (or name) and encoding, first
    $loop(%album%)...$loopend()                       repeat for every file, sorted by the expression;
                                                      a loop inside a loop: the outer one runs once per group
    $loop(%album%,1)...$loopend()                     once per group (its first file)
    everything else: text and format strings (%title%, $num(...), $csv(...), $html(...)), line breaks as written

Outside a loop: %_total_files% %_total_time% %_total_size% %_date% %_time% %_app% %_workingpath%.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field

from . import __version__, script
from .musicbrainz import fmt_length
from .tags import TagFile

ENCODINGS = {"utf-8": "utf-8-sig", "utf-8 no bom": "utf-8", "utf8": "utf-8-sig", "utf-16": "utf-16",
             "ansi": "cp1252", "latin1": "latin-1", "ascii": "ascii"}

DEFAULT_CONFIGS = {
    "CSV (Excel)": (
        "$filename(csv,utf-8)Title;Artist;Album;Track;Year;Genre;Length;Size;Last modified;Path;Filename\n"
        "$loop(%_path%)$csv(%title%);$csv(%artist%);$csv(%album%);$csv(%track%);$csv(%year%);$csv(%genre%);"
        "%_length%;%_file_size%;%_file_mod_date%;$csv(%_folderpath%);$csv(%_filename_ext%)\n"
        "$loopend()"),
    "Text list": (
        "$filename(txt,utf-8)%_total_files% files, %_total_time%, %_total_size% (%_date%)\n\n"
        "$loop(%_path%)%artist% - %title%  [%_length%]\n$loopend()"),
    "Album list": (
        "$filename(txt,utf-8)$loop(%albumartist% %album%)$if2(%albumartist%,%artist%) - %album% ($if2(%year%,?))\n"
        "$loop($num(%discnumber%,3)$num(%track%,3))  $num(%track%,2). %title%  [%_length%]\n$loopend()\n$loopend()"),
    "HTML table": (
        "$filename(html,utf-8)<!doctype html>\n<html><head><meta charset=\"utf-8\"><title>Music list</title>\n"
        "<style>body{font-family:Inter,Segoe UI,sans-serif;background:#060407;color:#E8E8EA}"
        "table{border-collapse:collapse}td,th{padding:4px 12px;border-bottom:1px solid #27222A;text-align:left}"
        "th{color:#8A8A92;font-size:11px;letter-spacing:.05em}</style></head><body>\n"
        "<h1>%_total_files% files</h1><p>%_total_time% &middot; %_total_size% &middot; %_date%</p>\n"
        "<table><tr><th>ARTIST</th><th>TITLE</th><th>ALBUM</th><th>TRACK</th><th>YEAR</th><th>LENGTH</th></tr>\n"
        "$loop(%_path%)<tr><td>$html(%artist%)</td><td>$html(%title%)</td><td>$html(%album%)</td>"
        "<td>%track%</td><td>%year%</td><td>%_length%</td></tr>\n$loopend()</table>\n</body></html>\n"),
}


class ExportError(Exception):
    pass


@dataclass
class _Loop:
    expr: str
    first_only: bool
    children: list = field(default_factory=list)


def _split_args(text: str) -> list[str]:
    """Top-level comma split, honouring quotes and nested brackets (format-string rules)."""
    out, depth, cur, quoted = [], 0, [], False
    for ch in text:
        if ch == "'":
            quoted = not quoted
        elif not quoted and ch == "(":
            depth += 1
        elif not quoted and ch == ")":
            depth -= 1
        elif not quoted and ch == "," and depth == 0:
            out.append("".join(cur))
            cur = []
            continue
        cur.append(ch)
    out.append("".join(cur))
    return out


def _close(text: str, i: int) -> int:
    """Index of the ')' closing the '(' just before i."""
    depth, quoted = 1, False
    while i < len(text):
        ch = text[i]
        if ch == "'":
            quoted = not quoted
        elif not quoted and ch == "(":
            depth += 1
        elif not quoted and ch == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise ExportError("A $loop( isn't closed with ).")


def parse(template: str) -> tuple[str, str, list]:
    """(extension or file name, encoding, tree of text and loops)."""
    name, enc = "txt", "utf-8"
    m = re.match(r"\s*\$filename\(([^,)]*)(?:,([^)]*))?\)", template)
    if m:
        name = m.group(1).strip() or "txt"
        enc = (m.group(2) or "utf-8").strip().lower()
        template = template[m.end():]
    if enc not in ENCODINGS:
        raise ExportError(f"Unknown encoding: {enc} (use utf-8, utf-16 or ansi).")
    root: list = []
    stack = [root]
    pos = 0
    for m in re.finditer(r"\$loop\(|\$loopend\(\)", template):
        if m.start() < pos:
            continue  # inside a $loop( ... ) expression already read
        stack[-1].append(template[pos:m.start()])
        if m.group(0) == "$loopend()":
            if len(stack) == 1:
                raise ExportError("$loopend() without a $loop(.")
            stack.pop()
            pos = m.end()
            continue
        end = _close(template, m.end())
        args = _split_args(template[m.end():end])
        loop = _Loop(args[0], len(args) > 1 and args[1].strip() == "1")
        stack[-1].append(loop)
        stack.append(loop.children)
        pos = end + 1
    stack[-1].append(template[pos:])
    if len(stack) != 1:
        raise ExportError("A $loop( has no $loopend().")
    return name, enc, root


def _totals(files: list[TagFile]) -> dict:
    return {"_total_files": len(files), "_total_time": fmt_length(sum(f.info.length for f in files)) or "0:00",
            "_total_size": script.size_text(sum(f.size for f in files)), "_date": time.strftime("%Y-%m-%d"),
            "_time": time.strftime("%H:%M"), "_app": f"PR7-L {__version__}",
            "_workingpath": os.path.dirname(files[0].path) if files else ""}


def _render(nodes: list, files: list[TagFile], tf: TagFile | None, counter: int, extra: dict, out: list) -> None:
    for n in nodes:
        if isinstance(n, str):
            out.append(script.format_string(n, script.Context(tf, counter=counter, extra=extra)))
            continue
        keyed = [(script.format_string(n.expr, script.Context(f, extra=extra)).lower(), f) for f in files]
        keyed.sort(key=lambda kf: kf[0])  # stable: equal keys keep the list's order
        groups: list[list[TagFile]] = []
        last = object()
        for key, f in keyed:
            if key != last:
                groups.append([])
                last = key
            groups[-1].append(f)
        nested = any(isinstance(c, _Loop) for c in n.children)
        i = 0
        for group in groups:
            if nested or n.first_only:  # once per group; an inner loop gets the group's files
                i += 1
                _render(n.children, group, group[0], i, extra, out)
            else:
                for f in group:
                    i += 1
                    _render(n.children, [f], f, i, extra, out)


def render(template: str, files: list[TagFile]) -> tuple[str, str, str]:
    """The export's text, its extension (or file name) and its Python encoding."""
    name, enc, tree = parse(template)
    out: list[str] = []
    _render(tree, files, None, 0, _totals(files), out)
    return "".join(out), name, ENCODINGS[enc]


def default_output(name_or_ext: str, config: str, files: list[TagFile]) -> str:
    folder = os.path.dirname(files[0].path) if files else os.path.expanduser("~")
    if "." in name_or_ext:
        return os.path.join(folder, name_or_ext)
    base = re.sub(r"[^\w\- ]+", "", config).strip() or "export"
    return os.path.join(folder, f"{base}.{name_or_ext}")


def write(path: str, text: str, encoding: str, append: bool = False) -> None:
    """Windows line ends; 'append' adds to an existing file (no second byte-order mark)."""
    if append and os.path.exists(path) and encoding == "utf-8-sig":
        encoding = "utf-8"
    with open(path, "a" if append else "w", encoding=encoding, newline="\r\n", errors="strict") as fh:
        fh.write(text)


# ------------------------------------------------------------------------------------------ playlists
@dataclass
class PlaylistOptions:
    name: str = "%_directory%"     # format string, from the first file
    extended: bool = True          # #EXTM3U and #EXTINF:seconds,Artist - Title lines
    relative: bool = True          # paths relative to the playlist's folder
    utf8: bool = True              # .m3u8 in UTF-8; else .m3u in Windows' ANSI (cp1252)


def playlist(files: list[TagFile], options: PlaylistOptions | None = None) -> tuple[str, str, str]:
    """(path, text, encoding) of the playlist for `files`, in the list's order, saved in the folder of the
    first file, as Mp3tag does."""
    o = options or PlaylistOptions()
    if not files:
        raise ExportError("No files for the playlist.")
    from .convert import clean_component
    folder = os.path.dirname(files[0].path)
    name = clean_component(script.format_string(o.name, script.Context(files[0]))) or "playlist"
    path = os.path.join(folder, name + (".m3u8" if o.utf8 else ".m3u"))
    lines = ["#EXTM3U"] if o.extended else []
    for f in files:
        if o.extended:
            who = " - ".join(x for x in (f.get("ARTIST").replace(script.SEP, ", "), f.get("TITLE")) if x)
            lines.append(f"#EXTINF:{int(round(f.info.length)) if f.info.length else -1},"
                         f"{who or os.path.splitext(f.filename)[0]}")
        entry = f.path
        if o.relative:
            try:
                entry = os.path.relpath(f.path, folder)
            except ValueError:  # another drive: only a full path works
                pass
        lines.append(entry)
    return path, "\n".join(lines) + "\n", "utf-8" if o.utf8 else "cp1252"
