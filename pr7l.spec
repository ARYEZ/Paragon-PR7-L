# PyInstaller build of PR7-L: pyinstaller pr7l.spec  ->  dist/PR7-L/PR7-L.exe  (folder build: starts fast)
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

root = Path(SPECPATH)
a = Analysis(
    [str(root / "tools" / "launcher.py")],
    pathex=[str(root)],
    datas=[(str(root / "pr7l" / "fonts"), "pr7l/fonts"), (str(root / "pr7l" / "icons"), "pr7l/icons")],
    hiddenimports=["PySide6.QtNetwork"] + collect_submodules("mutagen"),  # mutagen.File picks formats at run time
    excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQml", "PySide6.QtQuick",
              "PySide6.QtMultimedia", "PySide6.QtPdf", "PySide6.Qt3DCore"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="PR7-L", console=False,
          icon=str(root / "pr7l" / "icons" / "app.ico"))
coll = COLLECT(exe, a.binaries, a.datas, name="PR7-L")
