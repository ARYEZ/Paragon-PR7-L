"""Screenshots (offscreen): python tools/screenshots.py OUT_DIR [COVER_IMAGE]"""
import json
import os
import sys
import tempfile
from pathlib import Path

_cfg = Path(tempfile.gettempdir()) / "pr7l_offscreen.json"
_cfg.write_text(json.dumps({"screens": [{"name": "s", "x": 0, "y": 0, "width": 2880, "height": 3200,
                                          "logicalDpi": 96, "logicalBaseDpi": 96, "dpr": 1}]}))
os.environ.setdefault("QT_QPA_PLATFORM", f"offscreen:configfile={_cfg}")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QItemSelectionModel  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from pr7l import theme  # noqa: E402
from pr7l.main_window import MainWindow  # noqa: E402

out = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/screenshots")
out.mkdir(parents=True, exist_ok=True)
app = QApplication([])
theme.load_fonts()
app.setPalette(theme.palette())
app.setStyleSheet(theme.stylesheet())
w = MainWindow(sys.argv[2] if len(sys.argv) > 2 else None)
w.show()
sm = w.view.selectionModel()
for r in range(w.model.rowCount()):
    sm.select(w.model.index(r, 0), QItemSelectionModel.Select | QItemSelectionModel.Rows)
app.processEvents()
w.grab().save(str(out / "main_window.png"))
from pr7l.musicbrainz_dialog import MusicBrainzDialog  # noqa: E402
d = MusicBrainzDialog(w, sys.argv[2] if len(sys.argv) > 2 else None)
d.show()
app.processEvents()
d.grab().save(str(out / "musicbrainz.png"))
print("ok")
