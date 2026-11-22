"""Windows Explorer: "PR7-L" on the right-click menu of folders and audio files, as Mp3tag adds "Mp3tag".

Plain registry verbs under HKEY_CURRENT_USER (this user only, no admin rights): one fixed item needs no
shell extension. Several selected files start one PR7-L each; app.collect() merges them into one window.
unregister() removes exactly what register() wrote.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from .tags import AUDIO_EXTENSIONS

VERB = "PR7L"
LABEL = "PR7-L"
KEYS = [r"Software\Classes\Directory\shell\PR7L"] + [
    rf"Software\Classes\SystemFileAssociations\{ext}\shell\PR7L" for ext in sorted(AUDIO_EXTENSIONS)]


def available() -> bool:
    return os.name == "nt"


def launcher() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable]
    py = Path(sys.executable)
    pyw = py.with_name("pythonw.exe")
    return [str(pyw if pyw.exists() else py), "-m", "pr7l"]


def command() -> str:
    exe = " ".join(f'"{p}"' if (" " in p or p.lower().endswith(".exe")) else p for p in launcher())
    return exe + ' --explorer "%1"'


def icon() -> str:
    return f"{sys.executable},0" if getattr(sys, "frozen", False) else str(Path(__file__).parent / "icons" / "app.ico")


def _set(path: str, values: dict):
    import winreg
    k = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_WRITE)
    for name, val in values.items():
        winreg.SetValueEx(k, name, 0, winreg.REG_SZ, val)
    winreg.CloseKey(k)


def _delete_tree(path: str):
    import winreg
    try:
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_ALL_ACCESS)
    except FileNotFoundError:
        return
    while True:
        try:
            sub = winreg.EnumKey(k, 0)
        except OSError:
            break
        _delete_tree(f"{path}\\{sub}")
    winreg.CloseKey(k)
    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)


def register_menu():
    for key in KEYS:
        _set(key, {"": LABEL, "MUIVerb": LABEL, "Icon": icon(), "MultiSelectModel": "Player"})
        _set(key + r"\command", {"": command()})
    _notify()


def unregister_menu():
    for key in KEYS:
        _delete_tree(key)
    _notify()


def menu_registered() -> bool:
    if not available():
        return False
    import winreg
    try:
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEYS[0]))
        return True
    except OSError:
        return False


def _notify():
    try:
        import ctypes
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)  # SHCNE_ASSOCCHANGED
    except Exception:
        pass


def run(action: str) -> int:
    """The installer's and the command line's --register / --unregister."""
    if not available():
        print("Explorer integration is for Windows.")
        return 1
    try:
        (register_menu if action in ("--register", "--register-menu") else unregister_menu)()
    except OSError as e:
        print(f"{action} failed: {e}")
        return 2
    return 0
