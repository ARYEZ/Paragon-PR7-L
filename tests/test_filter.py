"""The filter (F3): the expression language, and the list showing (and editing) only what matches."""

import shutil
from pathlib import Path

import pytest

from pr7l import settings, tags
from pr7l.filter import FilterError, compile_filter
from pr7l.tags import Info, TagFile

DATA = Path(__file__).parent / "data"
T = TagFile(path="/m/01 Come Together.mp3", kind="ID3", info=Info(length=259, bitrate=320000),
            fields={"ARTIST": ["The Beatles"], "YEAR": ["1969"], "GENRE": ["Rock"], "TITLE": ["Come Together"]})


@pytest.mark.parametrize("query, want", [
    ("beatles come", True), ("BEATLES", True), ("beatles zzz", False), ("together.mp3", True),
    ("artist HAS beatl", True), ("%artist% HAS stones", False),
    ('artist IS "the beatles"', True), ("artist IS beatles", False),
    ("genre MATCHES ^(rock|pop)$", True), ("genre MATCHES ^pop", False),
    ("year LESS 1970", True), ("year GREATER 1969", False), ("year EQUAL 1969", True),
    ("%_length_seconds% GREATER 240", True), ("%_bitrate% LESS 320", False),
    ("comment MISSING", True), ("comment PRESENT", False), ("NOT comment PRESENT", True),
    ("%_covers% MISSING", True),
    ("artist HAS stones OR year LESS 1970", True), ("artist HAS stones AND year LESS 1970", False),
    ("NOT (artist HAS stones OR genre IS pop)", True),
    ('"$len(%title%)" GREATER 10', True), ('"%artist% - %title%" HAS "beatles - come"', True),
    ('title IS "Say ""Hello"""', False),
])
def test_language(query, want):
    assert compile_filter(query)(T) is want


def test_empty_shows_everything_and_errors_explain():
    assert compile_filter("  ") is None
    for bad, msg in (("artist HAS", "needs a value"), ("artist FOO x AND y", "After artist"),
                     ("(artist PRESENT", "isn't closed"), ("year GREATER abc", "needs a number"),
                     ("AND x", "field was expected"), ('artist HAS "open', "quote"),
                     ("genre MATCHES (", "MATCHES"), ("artist HAS a b", "Not understood")):
        with pytest.raises(FilterError, match=msg):
            compile_filter(bad)


@pytest.fixture
def window(qapp, tmp_path, monkeypatch):
    from pr7l.main_window import MainWindow
    monkeypatch.setattr("pr7l.main_window.QMessageBox.question", lambda *a, **k: 0)
    for name, ext, f in (("a", "flac", {"ARTIST": ["Paragon"], "YEAR": ["2026"], "GENRE": ["Metal"]}),
                         ("b", "mp3", {"ARTIST": ["Beatles"], "YEAR": ["1969"], "GENRE": ["Rock"]}),
                         ("c", "m4a", {"ARTIST": ["Paragon"], "YEAR": ["2019"]}),
                         ("d", "ogg", {"ARTIST": ["Stones"], "YEAR": ["1971"], "GENRE": ["Rock"]})):
        p = shutil.copy(DATA / f"blank.{ext}", tmp_path / f"{name}.{ext}")
        tags.save(str(p), f)
    w = MainWindow([str(tmp_path)])
    w.show()
    qapp.processEvents()
    yield w
    w.panel.show_files([])
    w.close()


def names(w):
    return sorted(t.filename for t in w.model.rows)


def test_f3_filters_the_list(window):
    window.toggle_filter()
    assert window.filter_bar.isVisible()
    window.apply_filter("genre IS rock")
    assert names(window) == ["b.mp3", "d.ogg"]
    assert window.status[0].text() == "2 of 4 file(s)"
    window.apply_filter("paragon")
    assert names(window) == ["a.flac", "c.m4a"]
    window.apply_filter("genre IS")                                  # unfinished: explained, list unchanged
    assert "needs a value" in window.filter_bar.message.text() and names(window) == ["a.flac", "c.m4a"]
    window.toggle_filter()                                           # F3 again: every file back
    assert not window.filter_bar.isVisible() and len(window.model.rows) == 4
    assert window.status[0].text() == "4 file(s)"


def test_commands_work_on_what_is_shown(window):
    window.apply_filter("year LESS 2000")
    window.select_all()
    assert sorted(t.filename for t in window.selected()) == ["b.mp3", "d.ogg"]
    window.panel.fields["COMMENT"].setEditText("oldie")
    window.save()
    got = {t.filename: tags.read(t.path).fields.get("COMMENT") for t in window.model.all_rows}
    assert got == {"a.flac": None, "b.mp3": ["oldie"], "c.m4a": None, "d.ogg": ["oldie"]}
    window.view.clearSelection()
    assert sorted(t.filename for t in window._list_files("Export")) == ["b.mp3", "d.ogg"]  # nothing selected: shown


def test_edited_file_stays_until_the_filter_changes(window):
    window.apply_filter("genre IS rock")
    window.select_all()
    window.panel.fields["GENRE"].setEditText("Pop")
    window.save()
    assert names(window) == ["b.mp3", "d.ogg"]                       # still shown, now "Pop"
    window.apply_filter("genre IS rock")
    assert names(window) == []


def test_hidden_files_survive_refresh_add_and_remove(window, tmp_path):
    window.apply_filter("artist IS paragon")
    window.refresh()
    assert names(window) == ["a.flac", "c.m4a"] and len(window.model.all_rows) == 4
    other = tmp_path / "more"
    other.mkdir()
    for n, a in (("x", "Paragon"), ("y", "Nobody")):
        p = shutil.copy(DATA / "blank.opus", other / f"{n}.opus")
        tags.save(str(p), {"ARTIST": [a]})
    window.load([str(other)], add=True)
    assert names(window) == ["a.flac", "c.m4a", "x.opus"] and len(window.model.all_rows) == 6
    window.view.selectionModel().select(window.model.index(0, 0), __import__("PySide6.QtCore").QtCore.
                                        QItemSelectionModel.Select | __import__("PySide6.QtCore").QtCore.
                                        QItemSelectionModel.Rows)
    window.remove_from_list()
    assert len(window.model.rows) == 2 and len(window.model.all_rows) == 5
    window.apply_filter("")
    assert len(window.model.rows) == 5


def test_history(window):
    window.toggle_filter()
    window.filter_bar.box.setEditText("genre IS rock")
    window.filter_bar.remember()                                     # Enter
    assert settings.get_list("filter_history")[0] == "genre IS rock" and names(window) == ["b.mp3", "d.ogg"]
    from pr7l.main_window import FilterBar
    assert FilterBar().box.itemText(0) == "genre IS rock"
    settings.set("filter_history", [])
