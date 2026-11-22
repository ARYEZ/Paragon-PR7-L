"""The file cache: a folder opened again reads only new or changed files; the list keeps no cover bytes."""

import io
import os
import shutil
import sqlite3
from pathlib import Path

import pytest

from pr7l import cache, settings, tags

DATA = Path(__file__).parent / "data"


def jpeg():
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (300, 200), (222, 6, 57)).save(b, "JPEG")
    return b.getvalue()


@pytest.fixture
def lib(tmp_path):
    lib = cache.Library(str(tmp_path / "c" / "library.sqlite"))
    yield lib
    lib.close()


def test_get_put_and_staleness(lib, tmp_path):
    p = str(shutil.copy(DATA / "blank.flac", tmp_path / "a.flac"))
    tags.save(p, {"TITLE": ["Portal"], "ARTIST": ["A", "B"]}, [tags.Picture(jpeg())])
    tf = tags.read(p)
    st = os.stat(p)
    lib.put(tf, st)
    got = lib.get(p, st)
    assert got.fields == {"TITLE": ["Portal"], "ARTIST": ["A", "B"]} and got.info.codec == "FLAC"
    assert got.pictures == [] and not got.pictures_loaded
    assert got.meta[0].width == 300 and got.meta[0].type == tags.FRONT
    assert [x.data for x in got.load_pictures()] == [jpeg()]  # read from the file when asked
    tags.save(p, {"TITLE": ["Changed"]})
    assert lib.get(p, os.stat(p)) is None  # changed on disk: not from the cache


def test_new_version_and_damaged_cache_start_empty(tmp_path):
    path = str(tmp_path / "library.sqlite")
    lib = cache.Library(path)
    p = str(shutil.copy(DATA / "blank.mp3", tmp_path / "a.mp3"))
    lib.put(tags.read(p), os.stat(p))
    lib.close()
    db = sqlite3.connect(path)
    db.execute(f"PRAGMA user_version = {cache.VERSION + 1}")  # cached by another PR7-L version
    db.commit()
    db.close()
    lib = cache.Library(path)
    assert lib.count() == 0
    lib.close()
    Path(path).write_bytes(b"not a database" * 100)
    lib = cache.Library(path)
    assert lib.count() == 0
    lib.close()


@pytest.fixture
def folder(tmp_path):
    d = tmp_path / "Music"
    d.mkdir()
    for i, ext in enumerate(("flac", "mp3", "m4a", "ogg", "wv")):
        p = shutil.copy(DATA / f"blank.{ext}", d / f"{i} song.{ext}")
        tags.save(str(p), {"TITLE": [f"Song {i}"]}, [tags.Picture(jpeg())])
    return d


def counted(monkeypatch):
    calls = []
    real = tags.read

    def read(path):
        calls.append(os.path.basename(path))
        return real(path)
    monkeypatch.setattr(tags, "read", read)
    return calls


def open_window(path=None):
    from pr7l.main_window import MainWindow
    return MainWindow([str(path)] if path else None)


def test_second_open_reads_only_what_changed(qapp, folder, monkeypatch, tmp_path):
    monkeypatch.setenv("PR7L_CACHE", str(tmp_path / "cache.sqlite"))
    calls = counted(monkeypatch)
    w = open_window(folder)
    assert len(calls) == 5 and len(w.model.rows) == 5
    assert "5 read from disk" in w.status[3].text()
    w.close()
    calls.clear()
    w = open_window(folder)                       # again: everything from the cache
    assert calls == [] and sorted(t.get("TITLE") for t in w.model.rows) == [f"Song {i}" for i in range(5)]
    assert "0 read from disk" in w.status[3].text()
    w.close()
    tags.save(str(folder / "2 song.m4a"), {"TITLE": ["Edited elsewhere"]})  # another program changes one file
    shutil.copy(DATA / "blank.opus", folder / "5 new.opus")                # and one is added
    w = open_window(folder)
    assert sorted(calls) == ["2 song.m4a", "5 new.opus"]
    assert "Edited elsewhere" in [t.get("TITLE") for t in w.model.rows]
    calls.clear()
    w.refresh()                                   # F5: everything read again
    assert len(calls) == 6
    w.close()


def test_rows_keep_no_cover_bytes_and_the_panel_still_shows_it(qapp, folder, monkeypatch, tmp_path):
    monkeypatch.setenv("PR7L_CACHE", str(tmp_path / "cache.sqlite"))
    w = open_window(folder)
    assert all(t.pictures == [] and t.meta and not t.pictures_loaded for t in w.model.rows)
    w.view.selectAll()
    qapp.processEvents()
    assert w.panel.cover_info.text().startswith("300 x 200  JPEG")  # all share one cover
    loaded = [t for t in w.model.rows if t.pictures_loaded]
    assert len(loaded) == 1                                          # only the shown one was read
    w.panel.show_files([])
    w.close()


def test_saves_and_renames_keep_the_cache_right(qapp, folder, monkeypatch, tmp_path):
    from pr7l import convert
    monkeypatch.setenv("PR7L_CACHE", str(tmp_path / "cache.sqlite"))
    w = open_window(folder)
    w.view.selectAll()
    qapp.processEvents()
    w.panel.fields["ARTIST"].setEditText("Paragon")
    w.save()
    w.apply_plan(convert.tag_to_filename(w.selected(), "%title%"))
    w.panel.show_files([])
    w.close()
    calls = counted(monkeypatch)
    w = open_window(folder)
    assert calls == []                            # what PR7-L wrote itself is already cached
    assert sorted(t.filename for t in w.model.rows) == sorted(os.listdir(folder))
    assert {t.get("ARTIST") for t in w.model.rows} == {"Paragon"}
    w.close()


def test_reopens_every_folder_that_was_open(qapp, folder, tmp_path):
    other = tmp_path / "More"
    other.mkdir()
    shutil.copy(DATA / "blank.opus", other / "x.opus")
    w = open_window(folder)
    w.load([str(other)], add=True)                # Add Directory
    w.close()
    w = open_window()                             # started with no folder: the last ones come back
    assert len(w.model.rows) == 6 and {Path(t.path).parent.name for t in w.model.rows} == {"Music", "More"}
    w.close()
    w = open_window(other)                        # Change Directory starts a new set
    w.close()
    assert settings.get_list("open_paths") == [str(other)]


def test_cache_can_be_switched_off(qapp, folder, monkeypatch, tmp_path):
    monkeypatch.setenv("PR7L_CACHE", str(tmp_path / "cache.sqlite"))
    settings.set("use_cache", False)
    try:
        w = open_window(folder)
        w.close()
        calls = counted(monkeypatch)
        w = open_window(folder)
        assert len(calls) == 5 and not (tmp_path / "cache.sqlite").exists()
        w.close()
    finally:
        settings.set("use_cache", True)
