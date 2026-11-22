"""Format strings, the four converters and auto-numbering: what they do to the files' names and tags."""

import os
import shutil
from pathlib import Path

import pytest

from pr7l import convert, script, tags
from pr7l.script import Context, ScriptError, format_string as fmt, guess

DATA = Path(__file__).parent / "data"
F = {"TITLE": ["the long collapse"], "TRACK": ["6/9"], "ARTIST": ["Paragon", "Guest"], "YEAR": ["2026"]}


@pytest.mark.parametrize("text, want", [
    ("%title%", "the long collapse"),
    ("$num(%track%,2) - $caps(%title%)", "06 - The Long Collapse"),
    ("$num(%track%,3)", "006"),
    ("$caps2(%title%) $caps3(%title%)", "The Long Collapse The long collapse"),
    ("$upper($left(%title%,3))$lower(X)$len(%title%)", "THEx17"),
    ("$right(%year%,2) $mid(%title%,5,4) $cutleft(%title%,4) $cutright(%year%,2)", "26 long long collapse 20"),
    ("$replace(%title%,long,short,the,a)", "a short collapse"),
    ("$regexp(%title%,'^(\\w+) (\\w+)',$2 $1)", "long the collapse"),
    ("$if(%genre%,yes,no) $if2(%genre%,%year%) $if($eql(%year%,2026),new,old)", "no 2026 new"),
    ("$ifgreater(%track%,5,late,early) $iflonger(%title%,5,long,short)", "late long"),
    ("$add(%track%,1) $sub(10,%track%) $mul(2,3) $div(7,2) $mod(7,2)", "7 4 6 3 1"),
    ("%artist%", "Paragon\\\\Guest"),
    ("$meta(artist,1) $meta_sep(artist, & ) $meta(artist)", "Guest Paragon & Guest Paragon, Guest"),
    ("it''s 'a,b ($x) %y%'", "it's a,b ($x) %y%"),
    ("100% sure %band%", "100% sure "),
    ("$validate(a/b:c,_)$repeat(-,3)$trim(  x  )", "a_b_c---x"),
    ("$isdigit(12)$isdigit(1a)$not()$and(1,)$or(1,)", "111"),
])
def test_format_strings(text, want):
    assert fmt(text, Context(fields=F)) == want


def test_script_errors():
    for bad, msg in (("$nope(x)", "no function"), ("$num(%track%", "isn't closed"), ("'open", "quote"),
                     ("$left(x)", "different number")):
        with pytest.raises(ScriptError, match=msg):
            fmt(bad, Context(fields=F))


def test_guess():
    assert guess("%track% - %artist% - %title%", "01 - Paragon - Portal - Live") == \
        {"TRACK": "01", "ARTIST": "Paragon", "TITLE": "Portal - Live"}  # the last field takes the rest
    assert guess("%track%. %dummy% - %title%", "3. x - Bloom") == {"TRACK": "3", "TITLE": "Bloom"}
    assert guess("%track% - %title%", "no dash here") is None


# ------------------------------------------------------------------ on real files
@pytest.fixture
def album(tmp_path):
    d = tmp_path / "Paragon" / "ELSEWORLD"
    d.mkdir(parents=True)
    out = []
    for name, ext, title, track in (("a", "flac", "Portal", "1/3"), ("b", "mp3", "Ruins: Part I/II", "2/3"),
                                    ("c", "m4a", "Static Bloom?", "3/3")):
        p = shutil.copy(DATA / f"blank.{ext}", d / f"{name}.{ext}")
        tags.save(str(p), {"TITLE": [title], "TRACK": [track], "ARTIST": ["Paragon"], "ALBUM": ["ELSEWORLD"]})
        out.append(tags.read(str(p)))
    return d, out


def test_tag_to_filename(album):
    d, files = album
    plan = convert.tag_to_filename(files, "$num(%track%,2) - %title%")
    assert [os.path.basename(p.new) for p in plan] == ["01 - Portal.flac", "02 - Ruins - Part I-II.mp3",
                                                       "03 - Static Bloom.m4a"]  # illegal characters replaced
    done, errors = convert.apply_renames(plan)
    assert not errors and len(done) == 3
    assert sorted(os.listdir(d)) == ["01 - Portal.flac", "02 - Ruins - Part I-II.mp3", "03 - Static Bloom.m4a"]
    assert tags.read(str(d / "01 - Portal.flac")).fields["TITLE"] == ["Portal"]  # the tag went with it
    assert convert.undo_renames(done) == []
    assert sorted(os.listdir(d)) == ["a.flac", "b.mp3", "c.m4a"]


def test_tag_to_filename_makes_folders_and_undo_removes_them(album):
    d, files = album
    plan = convert.tag_to_filename(files, "%album% (2026)\\$num(%track%,2) %title%")
    assert all(p.new.startswith(str(d / "ELSEWORLD (2026)")) for p in plan)
    done, _ = convert.apply_renames(plan)
    assert (d / "ELSEWORLD (2026)" / "01 Portal.flac").is_file()
    convert.undo_renames(done)
    assert not (d / "ELSEWORLD (2026)").exists() and (d / "a.flac").is_file()


def test_tag_to_filename_clashes(album):
    d, files = album
    plan = convert.tag_to_filename(files, "%artist%")  # all three would be "Paragon"
    assert plan[0].new.endswith("Paragon.flac") and not plan[0].error
    shutil.copy(DATA / "blank.flac", d / "Paragon.mp3")  # a file already has b's new name
    plan = convert.tag_to_filename(files, "%artist%")
    assert plan[1].error == "A file with that name is already there."
    plan = convert.tag_to_filename([files[0], files[0]], "%artist%")
    assert plan[1].error.startswith("Same new name")
    assert convert.tag_to_filename(files, "%nothing%")[0].error == "The format string gives an empty name."


def test_filename_to_tag(album):
    d, files = album
    p = shutil.copy(DATA / "blank.ogg", d / "07 - Afterimage (Live).ogg")
    tf = tags.read(str(p))
    plan = convert.filename_to_tag([tf], "%track% - %title%")
    assert plan[0].changes == {"TRACK": ["07"], "TITLE": ["Afterimage (Live)"]}
    plan = convert.filename_to_tag([tf], "%artist%\\%album%\\%track% - %title%")  # folders too
    assert plan[0].changes == {"ARTIST": ["Paragon"], "ALBUM": ["ELSEWORLD"], "TRACK": ["07"],
                               "TITLE": ["Afterimage (Live)"]}
    plan = convert.filename_to_tag(files[:1], "%track% - %title%")
    assert plan[0].error == "The file name doesn't fit the pattern." and plan[0].changes is None


def test_text_to_tag(album):
    _, files = album
    plan = convert.text_to_tag(files, "1. Portal (Intro)\r\n2. Ruins of Elsewhere\n\n", "%track%. %title%")
    assert plan[0].changes == {"TRACK": ["1"], "TITLE": ["Portal (Intro)"]}
    assert plan[1].changes == {"TRACK": ["2"], "TITLE": ["Ruins of Elsewhere"]}
    assert plan[2].error == "No line for this file."
    assert convert.text_to_tag(files, "bad line", "%track%. %title%")[0].error.startswith("The line")


def test_tag_to_tag(album):
    _, files = album
    plan = convert.tag_to_tag(files, "title", "$caps(%title%) [%_counter%]")
    assert [p.changes for p in plan][0] == {"TITLE": ["Portal [1]"]}
    assert convert.tag_to_tag(files, "COMMENT", "")[0].changes == {"COMMENT": None}  # empty removes
    assert convert.tag_to_tag(files, "band", "%artist%\\\\Guest")[0].changes == {"ALBUMARTIST": ["Paragon", "Guest"]}
    assert convert.tag_to_tag(files, "COMMENT", "%_filename% %_extension% %_directory% %_codec%")[0].changes == \
        {"COMMENT": ["a flac ELSEWORLD FLAC"]}


def test_auto_number(tmp_path, album):
    d, files = album
    other = tmp_path / "CD2"
    other.mkdir()
    extra = tags.read(str(shutil.copy(DATA / "blank.opus", other / "x.opus")))
    every = files + [extra]
    tracks = lambda plan: [p.changes["TRACK"][0] for p in plan]  # noqa: E731
    assert tracks(convert.auto_number(every)) == ["01", "02", "03", "01"]
    assert tracks(convert.auto_number(every, per_folder=False, leading_zero=False)) == ["1", "2", "3", "4"]
    assert tracks(convert.auto_number(every, start=9, add_total=True)) == ["09/03", "10/03", "11/03", "09/01"]
    assert tracks(convert.auto_number(every, add_total=True)) == ["01/03", "02/03", "03/03", "01/01"]
    discs = convert.auto_number(every, discs=True)
    assert [p.changes["DISCNUMBER"][0] for p in discs] == ["1/2", "1/2", "1/2", "2/2"]


# ------------------------------------------------------------------ through the window
@pytest.fixture
def window(qapp, album, monkeypatch):
    from pr7l.main_window import MainWindow
    monkeypatch.setattr("pr7l.main_window.QMessageBox.question", lambda *a, **k: 0)
    w = MainWindow([str(album[0])])
    w.show()
    w.view.selectAll()
    qapp.processEvents()
    yield w
    w.panel.show_files([])
    w.close()


def test_window_tag_to_filename_and_undo(window, album, monkeypatch):
    from pr7l.convert_dialog import ConvertDialog
    from pr7l import settings
    d, _ = album
    monkeypatch.setattr(ConvertDialog, "exec", lambda self: (self.format.setEditText("$num(%track%,1). %title%"),
                                                             self.refresh(), self.accept(), 1)[-1])
    window.tag_to_filename()
    assert sorted(os.listdir(d)) == ["1. Portal.flac", "2. Ruins - Part I-II.mp3", "3. Static Bloom.m4a"]
    assert sorted(t.filename for t in window.model.rows) == sorted(os.listdir(d))  # the list follows
    assert settings.get_list("format_tag2file")[0] == "$num(%track%,1). %title%"           # history remembered
    window.undo()
    assert sorted(os.listdir(d)) == ["a.flac", "b.mp3", "c.m4a"]
    assert sorted(t.filename for t in window.model.rows) == ["a.flac", "b.mp3", "c.m4a"]


def test_window_tag_to_tag_and_number_undo(window, monkeypatch):
    from pr7l.convert_dialog import AutoNumberDialog, ConvertDialog

    def run(self):
        self.field.setCurrentText("TITLE")
        self.format.setEditText("$upper(%title%)")
        self.accept()
        return 1
    monkeypatch.setattr(ConvertDialog, "exec", run)
    window.tag_to_tag()
    assert sorted(tags.read(t.path).fields["TITLE"][0] for t in window.model.rows) == \
        ["PORTAL", "RUINS: PART I/II", "STATIC BLOOM?"]

    def number(self):
        self.total.setChecked(True)
        self.zero.setChecked(False)
        self.accept()
        return 1
    monkeypatch.setattr(AutoNumberDialog, "exec", number)
    window.auto_number()
    assert [tags.read(t.path).fields["TRACK"] for t in window.model.rows] == [["1/3"], ["2/3"], ["3/3"]]
    window.undo()
    window.undo()
    assert sorted(tags.read(t.path).fields["TITLE"][0] for t in window.model.rows) == \
        ["Portal", "Ruins: Part I/II", "Static Bloom?"]


def test_dialog_preview_and_syntax_error(window):
    from PySide6.QtWidgets import QDialogButtonBox
    from pr7l.convert_dialog import ConvertDialog
    dlg = ConvertDialog("tag2file", window.selected(), window)
    dlg.format.setEditText("$num(%track%,2")
    dlg.refresh()
    assert "isn't closed" in dlg.message.text() and not dlg.buttons.button(QDialogButtonBox.Ok).isEnabled()
    dlg.format.setEditText("$num(%track%,2) %title%")
    dlg.refresh()
    assert dlg.preview.rows[0][1] == "01 Portal.flac" and dlg.buttons.button(QDialogButtonBox.Ok).isEnabled()
    assert dlg.message.text() == "3 of 3 file(s) will change."
    t = ConvertDialog("text2tag", window.selected(), window)
    t.text.setPlainText("A\nB")
    t.format.setEditText("%title%")
    t.refresh()
    assert t.message.text() == "2 of 3 file(s) will change; 1 left as they are."


def test_nothing_selected(window, monkeypatch):
    shown = []
    monkeypatch.setattr("pr7l.main_window.QMessageBox.information", lambda *a: shown.append(a[2]))
    window.view.clearSelection()
    window.auto_number()
    assert shown == ["Select the files first (Ctrl+A for all)."]
