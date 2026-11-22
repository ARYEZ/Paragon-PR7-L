"""The window and dialogs, driven as a user would, checking what ends up in the files."""

import io
import os
import shutil
import time
from pathlib import Path

import pytest

from pr7l import musicbrainz as mb, settings, tags
from test_musicbrainz import JPEG, REL, Recorded

DATA = Path(__file__).parent / "data"


def jpeg(w, h):
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (w, h), (222, 6, 57)).save(b, "JPEG")
    return b.getvalue()


@pytest.fixture
def album(tmp_path):
    d = tmp_path / "ELSEWORLD"
    d.mkdir()
    for name, ext, title in (("01 Portal", "flac", "Portal"), ("02 Ruins", "mp3", "Ruins"),
                             ("03 Static", "m4a", "Static")):
        p = shutil.copy(DATA / f"blank.{ext}", d / f"{name}.{ext}")
        tags.save(str(p), {"TITLE": [title], "COMMENT": ["keep me"]})
    (d / "notes.txt").write_bytes(b"not audio")
    return d


@pytest.fixture
def window(qapp, album, monkeypatch):
    from pr7l.main_window import MainWindow
    monkeypatch.setattr("pr7l.main_window.QMessageBox.question", lambda *a, **k: 0)  # never block on a dialog
    w = MainWindow([str(album)], client=mb.Client(fetch=Recorded(), pause=0))
    w.show()
    qapp.processEvents()
    yield w
    w.panel.show_files([])
    w.close()


def select(w, rows):
    from PySide6.QtCore import QItemSelectionModel
    sm = w.view.selectionModel()
    sm.clearSelection()
    for r in rows:
        sm.select(w.model.index(r, 0), QItemSelectionModel.Select | QItemSelectionModel.Rows)


def by_name(w):
    return {Path(t.path).name: t for t in w.model.rows}


def test_loads_the_audio_files_only(window, album):
    names = sorted(by_name(window))
    assert names == ["01 Portal.flac", "02 Ruins.mp3", "03 Static.m4a"]
    assert window.windowTitle() == f"{album} - PR7-L"
    assert settings.get("last_dir") == str(album)
    row = by_name(window)["02 Ruins.mp3"]
    assert row.tag_label == "ID3v1 ID3v2.3" and row.info.codec.startswith("MPEG")


def test_panel_keep_save_and_undo(window, album):
    select(window, [0, 1, 2])
    p = window.panel
    assert p.fields["TITLE"].currentText() == "< keep >"      # three different titles
    assert p.fields["COMMENT"].currentText() == "keep me"     # one shared comment
    p.fields["ARTIST"].setEditText("Paragon")
    p.fields["ALBUM"].setEditText("ELSEWORLD")
    p.fields["COMMENT"].setEditText("")                       # empty removes the field
    assert window.windowTitle().startswith("*")
    window.save()
    for name, t in by_name(window).items():
        on_disk = tags.read(t.path).fields
        assert on_disk["ARTIST"] == ["Paragon"] and on_disk["ALBUM"] == ["ELSEWORLD"]
        assert "COMMENT" not in on_disk
        assert on_disk["TITLE"] == [{"01": "Portal", "02": "Ruins", "03": "Static"}[name[:2]]]  # kept
    assert not window.windowTitle().startswith("*")
    window.undo()
    for t in window.model.rows:
        assert tags.read(t.path).fields == {"TITLE": [t.get("TITLE")], "COMMENT": ["keep me"]}


def test_blank_and_multiple_values(window):
    select(window, [0])
    window.panel.fields["ARTIST"].setEditText("Paragon\\\\Guest")
    window.panel.fields["TITLE"].setEditText("< blank >")
    window.save()
    got = tags.read(window.model.rows[0].path).fields
    assert got["ARTIST"] == ["Paragon", "Guest"] and "TITLE" not in got


def test_unsaved_edits_are_offered_on_selection_change(window, monkeypatch):
    monkeypatch.setattr(window, "_ask_save", lambda files: True)
    select(window, [0])
    window.panel.fields["GENRE"].setEditText("Djent")
    select(window, [1])
    assert tags.read(window.model.rows[0].path).fields["GENRE"] == ["Djent"]
    monkeypatch.setattr(window, "_ask_save", lambda files: False)
    window.panel.fields["GENRE"].setEditText("Nope")
    select(window, [2])
    assert "GENRE" not in tags.read(window.model.rows[1].path).fields


def test_cover_add_resize_remove(window, tmp_path):
    from pr7l.main_window import shrink_image
    select(window, [0, 1, 2])
    big = jpeg(1600, 1200)
    window.panel.set_pending_cover(big)
    assert "(on save)" in window.panel.cover_info.text()
    window.save()
    for t in window.model.rows:
        assert [p.data for p in tags.read(t.path).pictures] == [big]
    assert window.panel.cover_info.text().startswith("1600 x 1200  JPEG")
    assert tags.image_size(shrink_image(big, 500)) == (500, 375)
    assert shrink_image(big, 2000) == big  # never enlarged
    window.panel.pending_pictures = [tags.Picture(shrink_image(big, 600))]
    window.save()
    assert tags.image_size(tags.read(window.model.rows[0].path).pictures[0].data) == (600, 450)
    window.panel.set_pending_cover(None)
    window.save()
    assert all(tags.read(t.path).pictures == [] for t in window.model.rows)
    window.undo()
    assert tags.image_size(tags.read(window.model.rows[2].path).pictures[0].data) == (600, 450)


def test_options_shrink_added_covers(window):
    settings.set("cover_max_side", 300)
    window.panel.max_cover = 300
    select(window, [0])
    window.panel.set_pending_cover(jpeg(900, 900))
    window.save()
    assert tags.image_size(tags.read(window.model.rows[0].path).pictures[0].data) == (300, 300)
    settings.set("cover_max_side", 0)


def test_remove_tag_and_undo(window):
    select(window, [1])
    path = window.model.rows[1].path
    window.remove_tag(confirm=False)
    assert tags.read(path).fields == {} and window.model.rows[1].tag_label == ""
    window.undo()
    assert tags.read(path).fields["COMMENT"] == ["keep me"]


def test_copy_and_paste_tag(window):
    select(window, [0])
    window.copy_tag()
    select(window, [1, 2])
    window.paste_tag()
    for t in window.model.rows:
        assert tags.read(t.path).fields == {"TITLE": ["Portal"], "COMMENT": ["keep me"]}


def test_add_directory_and_drop(window, tmp_path):
    other = tmp_path / "more"
    other.mkdir()
    shutil.copy(DATA / "blank.ogg", other / "x.ogg")
    window.load([str(other)], add=True)
    assert len(window.model.rows) == 4
    window.load([str(other / "x.ogg")], add=True)  # already there: not twice
    assert len(window.model.rows) == 4
    window.view.dropped.emit([str(DATA / "blank.wv")])
    assert len(window.model.rows) == 5


def test_sorting_by_track_is_numeric(window):
    for row, n in zip(range(3), ("10", "2", "1")):
        select(window, [row])
        window.panel.fields["TRACK"].setEditText(n)
        window.save()
    from pr7l.main_window import COLUMNS
    window.model.sort([c[0] for c in COLUMNS].index("Track"))
    assert [t.get("TRACK") for t in window.model.rows] == ["1", "2", "10"]


def test_extended_tags(window):
    from pr7l.dialogs import ExtendedTagsDialog
    select(window, [0])
    dlg = ExtendedTagsDialog(window.selected(), window)
    dlg.add_field("MOOD", "dark")
    row = [dlg.table.item(r, 0).text() for r in range(dlg.table.rowCount())].index("COMMENT")
    dlg.table.selectRow(row)
    dlg.remove_field()
    assert dlg.changes() == {"MOOD": ["dark"], "COMMENT": None}
    window._write(window.selected(), dlg.changes(), None)
    assert tags.read(window.model.rows[0].path).fields == {"TITLE": ["Portal"], "MOOD": ["dark"]}


def test_options_and_aurora(window):
    from pr7l import theme
    from pr7l.dialogs import OptionsDialog
    dlg = OptionsDialog(window)
    dlg.id3v2.setCurrentIndex(1)
    dlg.id3v1.setChecked(False)
    dlg.finish.setCurrentText("AURORA")
    dlg.apply()
    window.set_finish(settings.get("finish"))
    assert theme.FINISH == "aurora" and theme.BACKGROUND == "#D9D0D4"
    select(window, [1])
    window.panel.fields["ARTIST"].setEditText("v24")
    window.save()
    from mutagen.id3 import ID3
    path = window.model.rows[1].path
    assert ID3(path).version == (2, 4, 0) and Path(path).read_bytes()[-128:-125] != b"TAG"
    for k, v in (("id3v2_version", 3), ("id3v1", True), ("finish", "obsidian")):
        settings.set(k, v)
    window.set_finish("obsidian")


# ------------------------------------------------------------------ MusicBrainz, through the dialog
def mb_dialog(window, files=None, **kw):
    from pr7l.musicbrainz_dialog import MusicBrainzDialog
    dlg = MusicBrainzDialog(files or list(window.model.rows), window._client(), window, options=window._options(), **kw)
    dlg.sync = True
    return dlg


def test_musicbrainz_search_match_and_write(window, album):
    dlg = mb_dialog(window)
    assert dlg.album.text() == "" and dlg.artist.text() == ""   # no shared album yet
    dlg.artist.setText("Paragon")
    dlg.album.setText("ELSEWORLD")
    dlg.search()
    assert dlg.results.rowCount() == 3 and dlg.rv.currentIndex().row() == 0  # the first with 3 tracks
    assert dlg.release.id == REL and dlg.edits["ALBUM"].text() == "ELSEWORLD"
    assert dlg.edits["GENRE"].text() == "Progressive Metal" and dlg.release_id.text() == REL
    assert dlg.cover == JPEG and dlg.cover_info.text().endswith("Front cover")
    # no track tags yet: lined up by file name
    assert [f.filename for f in dlg.order] == ["01 Portal.flac", "02 Ruins.mp3", "03 Static.m4a"]
    dlg.tv.setCurrentIndex(dlg.match.index(2, 0))
    dlg.move(-1)                                   # swap 2 and 3
    assert [f.filename for f in dlg.order] == ["01 Portal.flac", "03 Static.m4a", "02 Ruins.mp3"]
    dlg.move(1)
    dlg.edits["GENRE"].setText("Djent")
    dlg.folder_jpg.setChecked(True)
    dlg.write()
    assert dlg.result() == dlg.DialogCode.Accepted
    got = {Path(t.path).name: tags.read(t.path).fields for t in window.model.rows}
    assert got["01 Portal.flac"]["TITLE"] == ["Portal"] and got["01 Portal.flac"]["TRACK"] == ["1/3"]
    assert got["02 Ruins.mp3"]["ARTIST"] == ["Paragon feat. Guest Singer"]
    assert got["03 Static.m4a"]["TRACK"] == ["3/3"] and got["03 Static.m4a"]["GENRE"] == ["Djent"]
    assert all(f["COMMENT"] == ["keep me"] and f["MUSICBRAINZ_ALBUMID"] == [REL] for f in got.values())
    assert all(tags.read(t.path).pictures[0].data == JPEG for t in window.model.rows)
    assert (album / "folder.jpg").read_bytes() == JPEG
    window.undo_stack.append(dlg.snapshots)
    window.undo()
    assert all(tags.read(t.path).fields.keys() == {"TITLE", "COMMENT"} for t in window.model.rows)


def test_musicbrainz_prefills_and_remove_file(window):
    select(window, [0, 1, 2])
    window.panel.fields["ALBUM"].setEditText("ELSEWORLD")
    window.panel.fields["ALBUMARTIST"].setEditText("Paragon")
    window.save()
    dlg = mb_dialog(window)
    assert (dlg.artist.text(), dlg.album.text()) == ("Paragon", "ELSEWORLD")
    dlg.search()
    dlg.tv.setCurrentIndex(dlg.match.index(1, 0))
    dlg.remove_file()                               # 02 Ruins.mp3 is left out; 03 moves up to track 2
    assert [f.filename for f in dlg.order] == ["01 Portal.flac", "03 Static.m4a"]
    assert len(dlg.pairs()) == 2
    dlg.save_cover.setChecked(False)
    dlg.write()
    ruins = next(t for t in window.model.rows if t.filename.startswith("02"))
    assert "MUSICBRAINZ_ALBUMID" not in tags.read(ruins.path).fields
    static = next(t for t in window.model.rows if t.filename.startswith("03"))
    assert tags.read(static.path).fields["TITLE"] == ["Ruins of Elsewhere"]  # what was lined up is written
    assert tags.read(static.path).pictures == []


def test_cover_only(window, album):
    dlg = mb_dialog(window, cover_only=True)
    dlg.album.setText(REL)                          # a release id looks it up directly
    dlg.search()
    assert dlg.release.id == REL
    dlg.write()
    for t in window.model.rows:
        got = tags.read(t.path)
        assert [p.data for p in got.pictures] == [JPEG] and "MUSICBRAINZ_ALBUMID" not in got.fields


def test_errors_are_shown_not_raised(window):
    from pr7l.musicbrainz_dialog import MusicBrainzDialog

    def down(url, headers):
        raise OSError("no network")
    dlg = MusicBrainzDialog(window.model.rows, mb.Client(fetch=down, pause=0), window)
    dlg.sync = True
    dlg.artist.setText("x")
    dlg.search()
    assert "Can't reach musicbrainz.org" in dlg.message.text() and not dlg.ok.isEnabled()


def test_network_runs_off_the_gui_thread(window, qapp):
    import threading
    seen = []
    rec = Recorded()

    def fetch(url, headers):
        seen.append(threading.current_thread() is threading.main_thread())
        return rec(url, headers)
    from pr7l.musicbrainz_dialog import MusicBrainzDialog
    dlg = MusicBrainzDialog(window.model.rows, mb.Client(fetch=fetch, pause=0), window)
    dlg.artist.setText("Paragon")
    dlg.search()
    end = time.monotonic() + 10
    while (dlg.busy or dlg.cover is None) and time.monotonic() < end:
        qapp.processEvents()
        time.sleep(0.01)
    assert dlg.release is not None and dlg.cover == JPEG and dlg.ok.isEnabled()
    assert seen and not any(seen)
