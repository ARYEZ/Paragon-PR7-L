"""The file cache: what PR7-L read from each file, so a folder of thousands opens in a second next time.

One SQLite table, keyed by the file's path, holding the file's size and modification time and what the list
shows (fields, audio properties, picture details; never the pictures themselves). A file whose size or time
differs from the cached ones is read again; so is everything after a PR7-L update that reads tags
differently (VERSION). Where it lives: %LOCALAPPDATA%\\Paragon\\PR7-L\\cache\\library.sqlite (Windows),
~/.cache/pr7l/library.sqlite (elsewhere); PR7L_CACHE points somewhere else (the tests do).
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import asdict

from .tags import Info, PictureMeta, TagFile

VERSION = 1  # bump when tags.read() would give different results for the same file


def default_path() -> str:
    if os.environ.get("PR7L_CACHE"):
        return os.environ["PR7L_CACHE"]
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        return os.path.join(os.environ["LOCALAPPDATA"], "Paragon", "PR7-L", "cache", "library.sqlite")
    return os.path.join(os.path.expanduser("~"), ".cache", "pr7l", "library.sqlite")


def _key(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


class Library:
    def __init__(self, path: str | None = None):
        self.path = path or default_path()
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        try:
            self.db = self._open()
        except sqlite3.DatabaseError:  # a damaged cache is only a cache: start a new one
            os.remove(self.path)
            self.db = self._open()
        self.pending = 0

    def _open(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        try:
            if db.execute("PRAGMA user_version").fetchone()[0] != VERSION:
                db.execute("DROP TABLE IF EXISTS files")
                db.execute(f"PRAGMA user_version = {VERSION}")
            db.execute("CREATE TABLE IF NOT EXISTS files (path TEXT PRIMARY KEY, size INTEGER, mtime INTEGER, "
                       "data TEXT)")
            db.commit()
        except sqlite3.DatabaseError:
            db.close()  # Windows can't delete a file that's still open
            raise
        return db

    def get(self, path: str, st: os.stat_result) -> TagFile | None:
        """The cached file, if the file on disk is still the one that was read."""
        row = self.db.execute("SELECT size, mtime, data FROM files WHERE path = ?", (_key(path),)).fetchone()
        if row is None or row[0] != st.st_size or row[1] != st.st_mtime_ns:
            return None
        try:
            d = json.loads(row[2])
            tf = TagFile(path=path, kind=d["kind"], fields=d["fields"], info=Info(**d["info"]),
                         tag_label=d["tag_label"], size=st.st_size, mtime=st.st_mtime,
                         meta=[PictureMeta(**m) for m in d["meta"]], pictures_loaded=False)
        except (ValueError, KeyError, TypeError):
            return None
        return tf

    def put(self, tf: TagFile, st: os.stat_result) -> None:
        if tf.pictures_loaded:
            tf.slim()
        data = json.dumps({"kind": tf.kind, "fields": tf.fields, "info": asdict(tf.info), "tag_label": tf.tag_label,
                           "meta": [asdict(m) for m in tf.meta]}, ensure_ascii=False)
        self.db.execute("INSERT OR REPLACE INTO files VALUES (?, ?, ?, ?)",
                        (_key(tf.path), st.st_size, st.st_mtime_ns, data))
        self.pending += 1
        if self.pending >= 200:
            self.commit()

    def forget(self, path: str) -> None:
        self.db.execute("DELETE FROM files WHERE path = ?", (_key(path),))

    def commit(self) -> None:
        self.db.commit()
        self.pending = 0

    def clear(self) -> None:
        self.db.execute("DELETE FROM files")
        self.db.commit()
        self.db.execute("VACUUM")

    def count(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM files").fetchone()[0]

    def close(self) -> None:
        self.commit()
        self.db.close()
