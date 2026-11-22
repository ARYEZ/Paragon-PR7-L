"""Export and playlists: the files they write, byte for byte where it matters (encodings, line ends)."""

import os
import shutil
from pathlib import Path

import pytest

from pr7l import export, settings, tags

DATA = Path(__file__).parent / "data"


@pytest.fixture
def files(tmp_path):
    d = tmp_path / "Paragon" / "ELSEWORLD"
    d.mkdir(parents=True)
    out = []
    for name, ext, f in (
            ("03 Static", "m4a", {"TITLE": ["Static <Bloom>"], "ARTIST": ["Paragon"], "ALBUM": ["ELSEWORLD"],
                                  "TRACK": ["3"], "ALBUMARTIST": ["Paragon"], "YEAR": ["2026"]}),
            ("01 Portal", "flac", {"TITLE": ["Portal; Part 1"], "ARTIST": ["Paragon", "Guest"], "ALBUM": ["ELSEWORLD"],
                                   "TRACK": ["1"], "ALBUMARTIST": ["Paragon"], "YEAR": ["2026"]}),
            ("01 Other", "mp3", {"TITLE": ["Café \"Noir\""], "ARTIST": ["Zed"], "ALBUM": ["Another"], "TRACK": ["1"],
                                 "ALBUMARTIST": ["Zed"]})):
        p = shutil.copy(DATA / f"blank.{ext}", d / f"{name}.{ext}")
        tags.save(str(p), f)
        out.append(tags.read(str(p)))
    return out


def test_csv_quotes_what_would_break_columns(files):
    text, ext, enc = export.render(export.DEFAULT_CONFIGS["CSV (Excel)"], files)
    lines = text.split("\n")
    assert (ext, enc) == ("csv", "utf-8-sig") and lines[0].startswith("Title;Artist;Album;Track")
    assert lines[1].startswith('"Café ""Noir""";Zed;Another;1;;')  # sorted by path: 01 Other, 01 Portal, 03
    assert lines[2].startswith('"Portal; Part 1";Paragon\\\\Guest;ELSEWORLD;1;2026;')
    assert lines[2].endswith(";01 Portal.flac") and len(lines) == 5 and lines[4] == ""


def test_nested_loops_group(files):
    text, _, _ = export.render(export.DEFAULT_CONFIGS["Album list"], files)
    assert text == ("Paragon - ELSEWORLD (2026)\n  01. Portal; Part 1  [0:02]\n  03. Static <Bloom>  [0:02]\n\n"
                    "Zed - Another (?)\n  01. Café \"Noir\"  [0:02]\n\n")
    text, _, _ = export.render("$loop(%album%,1)%album%|$loopend()", files)  # once per group
    assert text == "Another|ELSEWORLD|"
    text, _, _ = export.render("[%_total_files%]$loop(%title%)%_counter%:%title%,$loopend()", files)
    assert text == "[3]1:Café \"Noir\",2:Portal; Part 1,3:Static <Bloom>,"


def test_html_escapes(files):
    text, ext, _ = export.render(export.DEFAULT_CONFIGS["HTML table"], files)
    assert ext == "html" and "<td>Static &lt;Bloom&gt;</td>" in text and "<h1>3 files</h1>" in text


def test_template_errors():
    for bad, msg in (("$loop(%a%)x", "no \\$loopend"), ("x$loopend()", "without"), ("$loop(%a%", "isn't closed"),
                     ("$filename(txt,klingon)", "encoding")):
        with pytest.raises(export.ExportError, match=msg):
            export.render(bad, [])


def test_write_line_ends_bom_and_append(tmp_path):
    p = str(tmp_path / "out.csv")
    export.write(p, "a\nb\n", "utf-8-sig")
    export.write(p, "c\n", "utf-8-sig", append=True)
    assert Path(p).read_bytes() == b"\xef\xbb\xbfa\r\nb\r\nc\r\n"  # one BOM, Windows line ends
    export.write(p, "é\n", "cp1252")
    assert Path(p).read_bytes() == b"\xe9\r\n"
    with pytest.raises(UnicodeEncodeError):
        export.write(p, "✓", "cp1252")


def test_playlist(files):
    path, text, enc = export.playlist(files)
    folder = os.path.dirname(files[0].path)
    assert path == os.path.join(folder, "ELSEWORLD.m3u8") and enc == "utf-8"
    assert text.split("\n") == ["#EXTM3U", "#EXTINF:2,Paragon - Static <Bloom>", "03 Static.m4a",
                                "#EXTINF:2,Paragon, Guest - Portal; Part 1", "01 Portal.flac",
                                "#EXTINF:2,Zed - Café \"Noir\"", "01 Other.mp3", ""]  # the list's order
    path, text, enc = export.playlist(files, export.PlaylistOptions("%album% - $num(%track%,2)", False, False, False))
    assert path.endswith("ELSEWORLD - 03.m3u") and enc == "cp1252"
    assert text.split("\n")[0] == files[0].path  # full paths, no #EXT lines


# ------------------------------------------------------------------ through the window
@pytest.fixture
def window(qapp, files, monkeypatch):
    from pr7l.main_window import MainWindow
    monkeypatch.setattr("pr7l.export_dialog.QMessageBox.question", lambda *a, **k: __import__(
        "PySide6.QtWidgets").QtWidgets.QMessageBox.Yes)
    w = MainWindow([os.path.dirname(files[0].path)])
    w.show()
    qapp.processEvents()
    yield w
    w.close()


def test_export_dialog_writes_the_file(window, files):
    from pr7l.export_dialog import ExportDialog
    dlg = ExportDialog(window.model.rows, window)
    assert dlg.current() == "CSV (Excel)"
    assert dlg.output.text() == os.path.join(os.path.dirname(files[0].path), "CSV Excel.csv")
    dlg.list.setCurrentRow(list(dlg.configs).index("Text list"))
    assert dlg.output.text().endswith("Text list.txt")
    dlg.open_after.setChecked(False)
    dlg.accept()
    data = Path(dlg.written).read_bytes()
    assert data.startswith(b"\xef\xbb\xbf3 files, 0:0") and b"\r\nParagon\\\\Guest - Portal; Part 1  [0:02]\r\n" in data
    assert settings.get("export_last") == "Text list"


def test_export_configs_are_saved(window, monkeypatch):
    from pr7l.export_dialog import ConfigEditor, ExportDialog, load_configs
    dlg = ExportDialog(window.model.rows, window)

    def edit(self):
        self.name.setText("Titles")
        self.template.setPlainText("$filename(titles.txt,ansi)$loop(%title%)%title%\n$loopend()")
        self.refresh()
        assert self.preview.toPlainText().startswith("Café")
        return 1
    monkeypatch.setattr(ConfigEditor, "exec", edit)
    dlg.new()
    assert load_configs()["Titles"].startswith("$filename(titles.txt,ansi)")
    assert dlg.current() == "Titles" and dlg.output.text().endswith("titles.txt")
    dlg.open_after.setChecked(False)
    dlg.accept()
    assert Path(dlg.written).read_bytes().startswith(b"Caf\xe9 \"Noir\"\r\nPortal")  # ANSI, as asked
    dlg.delete()
    assert "Titles" not in load_configs()
    ed = ConfigEditor("x", "$loop(%a%)", [])
    assert ed.preview.toPlainText().startswith("Error: A $loop( has no $loopend()")
    settings.set("export_configs", "")


def test_playlist_dialog_and_no_selection_means_all(window, files):
    from pr7l.export_dialog import PlaylistDialog
    window.view.clearSelection()
    assert window._list_files("x") == window.model.rows
    dlg = PlaylistDialog(window._list_files("x"), window)
    dlg.extended.setChecked(False)
    dlg.accept()
    m3u = Path(os.path.dirname(files[0].path)) / "ELSEWORLD.m3u8"
    assert m3u.read_bytes().split(b"\r\n")[:3] == [f.filename.encode() for f in window.model.rows]
    assert settings.get_bool("playlist_extended", True) is False
    settings.set("playlist_extended", True)
