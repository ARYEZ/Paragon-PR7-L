"""Check a real install of PR7-L-Setup.exe (CI, Windows): python tools/verify_install.py installed|uninstalled

`installed` also runs the installed PR7-L.exe on the test files (--dump), so the frozen program is shown
to read every format with the mutagen it was built with."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import winreg
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pr7l import shell, tags  # noqa: E402

HKCU = winreg.HKEY_CURRENT_USER
APP = Path(os.environ["LOCALAPPDATA"]) / "Programs" / "PR7-L"
SHORTCUT = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Paragon PR7-L.lnk"
UNINSTALL = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{4C0E3F59-8A0B-4E7D-9B5A-2F7C61D3A9E1}_is1"


def value(path, name=""):
    try:
        k = winreg.OpenKey(HKCU, path)
    except OSError:
        return None
    try:
        return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None
    finally:
        winreg.CloseKey(k)


def check(ok, what, p):
    print(("ok    " if ok else "FAIL  ") + what)
    if not ok:
        p.append(what)


def installed():
    p = []
    exe = APP / "PR7-L.exe"
    for f in (exe, APP / "unins000.exe", APP / "_internal" / "pr7l" / "fonts" / "Inter-Regular.ttf",
              APP / "_internal" / "pr7l" / "icons" / "app.ico"):
        check(f.is_file(), f"file {f}", p)
    check(SHORTCUT.is_file(), "Start menu shortcut", p)
    check(value(UNINSTALL, "DisplayName") == "Paragon PR7-L", "Installed apps entry", p)
    for key, what in ((r"Software\Classes\Directory\shell\PR7L", "folders"),
                      (r"Software\Classes\SystemFileAssociations\.mp3\shell\PR7L", ".mp3"),
                      (r"Software\Classes\SystemFileAssociations\.flac\shell\PR7L", ".flac")):
        check(value(key, "MUIVerb") == "PR7-L", f'"PR7-L" on the menu of {what}', p)
        cmd = value(key + r"\command") or ""
        check(cmd.lower() == f'"{exe}" --explorer "%1"'.lower(), f"... runs the installed PR7-L ({cmd})", p)
    # The frozen program reads every format (mutagen and its format modules were bundled).
    with tempfile.TemporaryDirectory() as d:
        files = []
        for src in sorted((ROOT / "tests" / "data").glob("blank.*")):
            dst = Path(d) / src.name
            shutil.copy(src, dst)
            tags.save(str(dst), {"TITLE": ["Installed"], "ARTIST": ["Paragon"]})
            files.append(str(dst))
        out = Path(d) / "dump.json"
        subprocess.run([str(exe), "--dump", str(out)] + files, timeout=120, check=False)
        got = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
        for f in files:
            fields = got.get(f, {}).get("fields", {})
            check(fields.get("TITLE") == ["Installed"], f"PR7-L.exe reads {Path(f).suffix} ({got.get(f)})", p)
    return p


def uninstalled():
    deadline = time.time() + 60
    while True:
        p = []
        check(not (APP / "PR7-L.exe").exists(), "program files removed", p)
        check(not SHORTCUT.exists(), "Start menu shortcut removed", p)
        check(value(UNINSTALL, "DisplayName") is None, "Installed apps entry removed", p)
        check(all(value(k, "MUIVerb") is None for k in shell.KEYS), "Explorer menu removed", p)
        if not p or time.time() > deadline:
            return p
        print("... waiting for the uninstaller to finish")
        time.sleep(3)


if __name__ == "__main__":
    problems = {"installed": installed, "uninstalled": uninstalled}[sys.argv[1]]()
    print("\nALL OK" if not problems else f"\n{len(problems)} problem(s)")
    sys.exit(1 if problems else 0)
