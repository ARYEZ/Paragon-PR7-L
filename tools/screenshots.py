"""Screenshots of the real window (offscreen): python tools/screenshots.py OUT_DIR [COVER_IMAGE]

Builds a small album from the test files in a temp folder, tags it, embeds COVER_IMAGE if given, and
shows the MusicBrainz dialog answering from the recorded responses in tests/data/mb.
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

_cfg = Path(tempfile.gettempdir()) / "pr7l_offscreen.json"
_cfg.write_text(json.dumps({"screens": [{"name": "s", "x": 0, "y": 0, "width": 2880, "height": 3200,
                                          "logicalDpi": 96, "logicalBaseDpi": 96, "dpr": 1}]}))
os.environ.setdefault("QT_QPA_PLATFORM", f"offscreen:configfile={_cfg}")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from PySide6.QtCore import QItemSelectionModel, QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

QSettings.setDefaultFormat(QSettings.IniFormat)  # never the real settings
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, tempfile.mkdtemp())

from pr7l import musicbrainz as mb, tags, theme  # noqa: E402

out = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/screenshots")
out.mkdir(parents=True, exist_ok=True)
cover = Path(sys.argv[2]).read_bytes() if len(sys.argv) > 2 else None

album = Path(tempfile.mkdtemp()) / "Paragon" / "ELSEWORLD"
album.mkdir(parents=True)
TRACKS = [("Portal", "flac"), ("Ruins of Elsewhere", "flac"), ("Static Bloom", "mp3"), ("Signal Lost", "mp3"),
          ("Arc Light", "m4a"), ("The Long Collapse", "flac"), ("Afterimage", "opus"), ("Neon Requiem", "wv"),
          ("Elseworld", "ogg")]
for i, (title, ext) in enumerate(TRACKS, 1):
    p = shutil.copy(ROOT / "tests" / "data" / f"blank.{ext}", album / f"{i:02} {title}.{ext}")
    tags.save(str(p), {"TITLE": [title], "ARTIST": ["Paragon"], "ALBUM": ["ELSEWORLD"], "TRACK": [f"{i}/9"],
                       "YEAR": ["2026"], "GENRE": ["Progressive Metal" if i != 6 else "Djent"],
                       "ALBUMARTIST": ["Paragon"], "DISCNUMBER": ["1/1"]},
              [tags.Picture(cover)] if cover else None)

app = QApplication([])
theme.load_fonts()
app.setPalette(theme.palette())
app.setStyleSheet(theme.stylesheet())
from test_musicbrainz import Recorded  # noqa: E402
from pr7l.main_window import MainWindow  # noqa: E402

w = MainWindow([str(album)], client=mb.Client(fetch=Recorded(), pause=0))
w.show()
sm = w.view.selectionModel()
for r in range(w.model.rowCount()):
    sm.select(w.model.index(r, 0), QItemSelectionModel.Select | QItemSelectionModel.Rows)
app.processEvents()
w.grab().save(str(out / "main_window.png"))

from pr7l.musicbrainz_dialog import MusicBrainzDialog  # noqa: E402
d = MusicBrainzDialog(w.model.rows[:3], w._client(), w)
d.sync = True
d.artist.setText("Paragon")
d.album.setText("ELSEWORLD")
if cover:  # show the real cover in place of the recorded one
    d.client.fetch.routes["/1-1200.jpg"] = (200, cover)
d.search()
d.show()
app.processEvents()
d.grab().save(str(out / "musicbrainz.png"))
print("ok")

from pr7l.convert_dialog import AutoNumberDialog, ConvertDialog  # noqa: E402
c = ConvertDialog("tag2file", w.model.rows, w)
c.format.setEditText("$num(%track%,2) - %title%")
c.refresh()
c.show()
app.processEvents()
c.grab().save(str(out / "tag_filename.png"))
n = AutoNumberDialog(w.model.rows, w)
n.total.setChecked(True)
n.show()
app.processEvents()
n.grab().save(str(out / "auto_numbering.png"))
print("ok")

from pr7l.actions_dialog import ActionEditor, ActionsDialog, GroupEditor  # noqa: E402
from pr7l import actions as _actions  # noqa: E402
a = ActionsDialog(len(w.model.rows), w)
a.list.item(0).setCheckState(__import__("PySide6.QtCore").QtCore.Qt.Checked)
a.show()
app.processEvents()
a.grab().save(str(out / "actions.png"))
g = GroupEditor({"name": "Tidy an album", "actions": [
    {"type": "replace", "field": "_FILENAME", "find": "_", "replace": " "},
    {"type": "case", "field": "TITLE;ARTIST;ALBUM", "mode": "mixed"},
    {"type": "regexp", "field": "TITLE", "regex": r"\s*\(feat\. (.+)\)", "replace": " [with $1]"},
    {"type": "remove", "fields": "COMMENT;ENCODEDBY"}, {"type": "export_cover", "file": "folder"}]}, w)
g.show()
app.processEvents()
g.grab().save(str(out / "action_group.png"))
e = ActionEditor(_actions.new_action("case"), w)
e.show()
app.processEvents()
e.grab().save(str(out / "action_case.png"))
print("ok")
