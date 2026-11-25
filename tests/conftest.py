import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PARAGON_FAMILY_FILE"] = os.path.join(__import__("tempfile").mkdtemp(prefix="family-"), "finish")  # never the real choice
# Tests never use the real file cache either.
os.environ["PR7L_CACHE"] = os.path.join(__import__("tempfile").mkdtemp(prefix="pr7l-cache-"), "library.sqlite")


@pytest.fixture(scope="session")
def qapp(tmp_path_factory):
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    from pr7l import theme
    # Tests must never touch the real PR7-L settings.
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path_factory.mktemp("settings")))
    app = QApplication.instance() or QApplication([])
    theme.load_fonts()
    app.setStyleSheet(theme.stylesheet())
    yield app
    # End cleanly, so Qt never shuts down under running work: the tag-source lookups (QThreadPool, live MusicBrainz
    # in CI) finish first; windows left open close; the clipboard is cleared (Qt's offscreen platform crashes at exit
    # if the cover tests left a picture there).
    from PySide6.QtCore import QThreadPool
    QThreadPool.globalInstance().waitForDone(15000)
    for w in app.topLevelWidgets():
        w.close()
        w.deleteLater()
    app.clipboard().clear()
    app.processEvents()
