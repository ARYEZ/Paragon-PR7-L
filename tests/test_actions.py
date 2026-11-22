"""Actions: each type on real files, groups run in order, one Undo step, and the dialogs that keep them."""

import io
import os
import shutil
from pathlib import Path

import pytest

from pr7l import actions, settings, tags
from pr7l.actions import convert_case

DATA = Path(__file__).parent / "data"


def jpeg(colour=(222, 6, 57)):
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (64, 64), colour).save(b, "JPEG")
    return b.getvalue()


@pytest.mark.parametrize("text, mode, want", [
    ("the LONG collapse", "mixed", "The Long Collapse"),
    ("ruins of elsewhere (live at o'neill's)", "mixed", "Ruins Of Elsewhere (Live At O'neill's)"),
    ("rock/pop-punk \"best\"", "mixed", "Rock/Pop-Punk \"Best\""),
    ("THE LONG COLLAPSE", "sentence", "The long collapse"),
    ("Mixed", "upper", "MIXED"), ("Mixed", "lower", "mixed"),
    ("back in black by ac/dc feat. someone part ii", "mixed", "Back In Black By AC/DC feat. Someone Part II"),
    ("2nd song", "mixed", "2nd Song"),
])
def test_case_conversion(text, mode, want):
    assert convert_case(text, mode, " ([{/-\"", "AC/DC DJ feat. II III IV") == want


@pytest.fixture
def files(tmp_path):
    out = []
    for name, ext, fields in (
            ("01_portal", "flac", {"TITLE": ["portal (feat. guest)"], "ARTIST": ["paragon"], "COMMENT": ["x"],
                                   "ENCODEDBY": ["lame"], "MUSICBRAINZ_ALBUMID": ["abc-def"]}),
            ("02_ruins", "mp3", {"TITLE": ["ruins"], "ARTIST": ["Paragon; Guest Singer"], "COMMENT": ["y"]})):
        p = shutil.copy(DATA / f"blank.{ext}", tmp_path / f"{name}.{ext}")
        tags.save(str(p), fields)
        out.append(tags.read(str(p)))
    return out


def fields_after(planned):
    return [p.changes for p in planned]


def test_replace_and_regexp(files):
    plan = actions.plan([{"type": "replace", "field": "TITLE", "find": "FEAT.", "replace": "ft.", "case": False}], files)
    assert plan[0].changes == {"TITLE": ["portal (ft. guest)"]} and plan[1].changes is None
    plan = actions.plan([{"type": "replace", "field": "TITLE", "find": "FEAT.", "replace": "ft.", "case": True}], files)
    assert plan[0].changes is None  # case-sensitive: no match
    plan = actions.plan([{"type": "replace", "field": "ARTIST", "find": "para", "replace": "X", "word": True}], files)
    assert plan[0].changes is None  # only whole words
    plan = actions.plan([{"type": "regexp", "field": "TITLE", "regex": r"\s*\(feat\. (.+)\)", "replace": " [with $1]"}],
                        files)
    assert plan[0].changes == {"TITLE": ["portal [with guest]"]}


def test_case_on_all_leaves_ids_alone(files):
    plan = actions.plan([actions.new_action("case")], files)  # _ALL, Mixed Case
    assert plan[0].changes == {"TITLE": ["Portal (feat. Guest)"], "ARTIST": ["Paragon"], "COMMENT": ["X"],
                               "ENCODEDBY": ["Lame"]}
    assert "MUSICBRAINZ_ALBUMID" not in plan[0].changes


def test_format_remove_split_merge_guess(files):
    plan = actions.plan([{"type": "format", "field": "ALBUM", "format": "$caps(%artist%) best of [%_counter%]"},
                         {"type": "remove", "fields": "COMMENT;ENCODEDBY"},
                         {"type": "split", "field": "ARTIST", "separator": "; "}], files)
    assert plan[1].changes == {"ALBUM": ["Paragon; Guest Singer best of [2]"], "COMMENT": None,
                               "ARTIST": ["Paragon", "Guest Singer"]}
    assert plan[0].changes == {"ALBUM": ["Paragon best of [1]"], "COMMENT": None, "ENCODEDBY": None}
    plan = actions.plan([{"type": "split", "field": "ARTIST", "separator": "; "},
                         {"type": "merge", "field": "ARTIST", "separator": " & "}], files[1:])
    assert plan[0].changes == {"ARTIST": ["Paragon & Guest Singer"]}
    plan = actions.plan([{"type": "guess", "source": "%_filename%", "pattern": "%track%_%title%"}], files)
    assert plan[0].changes == {"TRACK": ["01"], "TITLE": ["portal"]}
    plan = actions.plan([{"type": "guess", "source": "%title%", "pattern": "%artist% - %title%"}], files)
    assert plan[0].error == "didn't fit the guessing pattern"


def test_remove_except_and_picture(files):
    tags.save(files[0].path, {}, [tags.Picture(jpeg())])
    tf = tags.read(files[0].path).slim()
    plan = actions.plan([{"type": "remove_except", "fields": "TITLE;ARTIST"}], [tf])
    assert plan[0].changes == {"COMMENT": None, "ENCODEDBY": None, "MUSICBRAINZ_ALBUMID": None}
    assert plan[0].pictures == []                     # PICTURE wasn't kept
    plan = actions.plan([{"type": "remove_except", "fields": "TITLE;PICTURE"}], [tf])
    assert plan[0].pictures is None


def test_import_and_export_cover(files, tmp_path):
    (tmp_path / "folder.jpg").write_bytes(jpeg())
    plan = actions.plan([actions.new_action("import_cover")], files)
    assert [x.data for x in plan[0].pictures] == [jpeg()]
    tags.save(files[0].path, {}, [tags.Picture(jpeg((1, 2, 3)))])
    has = tags.read(files[0].path).slim()
    assert actions.plan([actions.new_action("import_cover")], [has])[0].pictures is None  # only missing
    plan = actions.plan([{"type": "export_cover", "file": "%artist%\\cover", "overwrite": False}], [has, files[1]])
    assert plan[0].exports == [(os.path.join(str(tmp_path), "paragon", "cover.jpg"), jpeg((1, 2, 3)))]
    assert plan[1].error == "no cover to export"
    (tmp_path / "folder.jpg").write_bytes(b"old")
    assert actions.plan([actions.new_action("export_cover")], [has])[0].exports == []  # no overwrite


def test_filename_actions_and_clash(files, tmp_path):
    plan = actions.plan([actions.DEFAULT_GROUPS[2]["actions"][0]], files)  # underscores to spaces
    assert [os.path.basename(p.new) for p in plan] == ["01 portal.flac", "02 ruins.mp3"]
    (tmp_path / "02 ruins.mp3").write_bytes(b"x")
    plan = actions.plan([actions.DEFAULT_GROUPS[2]["actions"][0]], files)
    assert plan[1].error == "A file with the new name is already there." and not plan[1].new


# ------------------------------------------------------------------ through the window
@pytest.fixture
def window(qapp, files, monkeypatch):
    from pr7l.main_window import MainWindow
    monkeypatch.setattr("pr7l.main_window.QMessageBox.question", lambda *a, **k: 0)
    w = MainWindow([os.path.dirname(files[0].path)])
    w.show()
    w.view.selectAll()
    qapp.processEvents()
    yield w
    w.panel.show_files([])
    w.close()


def test_group_runs_in_order_and_undoes_in_one_step(window, files, tmp_path):
    (tmp_path / "folder.jpg").write_bytes(jpeg())
    group = [{"type": "replace", "field": "_FILENAME", "find": "_", "replace": " "},
             {"type": "case", "field": "TITLE;_FILENAME", "mode": "mixed", "after": " (", "exceptions": "feat."},
             {"type": "remove", "fields": "COMMENT"}, {"type": "import_cover", "file": "folder.jpg",
                                                       "only_missing": True}]
    window.apply_actions(group)
    names = sorted(os.listdir(tmp_path))
    assert names == ["01 Portal.flac", "02 Ruins.mp3", "folder.jpg"]
    got = tags.read(str(tmp_path / "01 Portal.flac"))
    assert got.fields["TITLE"] == ["Portal (feat. Guest)"] and "COMMENT" not in got.fields
    assert [p.data for p in got.pictures] == [jpeg()]
    assert sorted(t.filename for t in window.model.rows) == ["01 Portal.flac", "02 Ruins.mp3"]
    assert window.status[3].text() == "2 file(s) changed"
    window.undo()
    assert sorted(os.listdir(tmp_path)) == ["01_portal.flac", "02_ruins.mp3", "folder.jpg"]
    back = tags.read(str(tmp_path / "01_portal.flac"))
    assert back.fields["TITLE"] == ["portal (feat. guest)"] and back.fields["COMMENT"] == ["x"] and not back.pictures


def test_actions_dialog_saves_groups_and_runs_ticked_ones(window, monkeypatch, files):
    from PySide6.QtCore import Qt
    from pr7l.actions_dialog import ActionsDialog, GroupEditor, load_groups
    dlg = ActionsDialog(2, window)
    assert [g["name"] for g in dlg.groups] == [g["name"] for g in actions.DEFAULT_GROUPS]
    monkeypatch.setattr(GroupEditor, "exec", lambda self: (self.name.setText("Upper titles"),
                                                           self.add("case", edit=False),
                                                           self.group["actions"][0].update(field="TITLE", mode="upper"),
                                                           1)[-1])
    dlg.new()
    assert load_groups()[-1] == {"name": "Upper titles", "actions": [
        {**actions.new_action("case"), "field": "TITLE", "mode": "upper"}]}           # saved straight away
    for i in range(dlg.list.count()):
        dlg.list.item(i).setCheckState(Qt.Checked if dlg.groups[i]["name"] in ("Upper titles",
                                                                                 "Remove comments and encoder fields")
                                       else Qt.Unchecked)
    chosen = dlg.chosen()
    assert [a["type"] for a in chosen] == ["remove", "case"]                          # list order
    assert set(settings.get_list("action_checked")) == {"Upper titles", "Remove comments and encoder fields"}
    window.apply_actions(chosen)
    got = {t.filename: tags.read(t.path).fields for t in window.model.rows}
    assert got["01_portal.flac"]["TITLE"] == ["PORTAL (FEAT. GUEST)"] and "COMMENT" not in got["02_ruins.mp3"]
    dlg.list.setCurrentRow(len(dlg.groups) - 1)
    monkeypatch.setattr("pr7l.actions_dialog.QMessageBox.question", lambda *a, **k: __import__(
        "PySide6.QtWidgets").QtWidgets.QMessageBox.Yes)
    dlg.delete()
    assert "Upper titles" not in [g["name"] for g in load_groups()]
    settings.set("action_groups", "")


def test_action_editor_round_trip(qapp):
    from pr7l.actions_dialog import ActionEditor
    for kind in actions.TYPES:
        a = actions.new_action(kind)
        assert ActionEditor(a).value() == a  # every form shows and returns every setting
    ed = ActionEditor(actions.new_action("case"))
    ed.widgets["mode"][1].setCurrentIndex(1)
    ed.widgets["field"][1].setCurrentText("title")
    assert ed.value()["mode"] == "upper" and ed.value()["field"] == "TITLE"


def test_quick_action_remembers_its_form(window, monkeypatch):
    from pr7l.actions_dialog import ActionEditor

    def fill(self):
        self.widgets["find"][1].setText("ruins")
        self.widgets["replace"][1].setText("Ruins of Elsewhere")
        return 1
    monkeypatch.setattr(ActionEditor, "exec", fill)
    window.quick_replace()
    assert "Ruins of Elsewhere" in [tags.read(t.path).fields["TITLE"][0] for t in window.model.rows]
    seen = []
    monkeypatch.setattr(ActionEditor, "exec", lambda self: seen.append(self.widgets["find"][1].text()) or 0)
    window.quick_replace()
    assert seen == ["ruins"]
