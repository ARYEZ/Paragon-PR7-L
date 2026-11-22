"""Explorer integration and the command line."""

import os
import shutil
from pathlib import Path

import pytest

from pr7l import app, shell

windows_ci = pytest.mark.skipif(os.name != "nt" or not os.environ.get("CI"),
                                reason="writes Explorer's registration; Windows CI machines only")


@windows_ci
def test_register_and_unregister():
    import winreg
    assert shell.run("--register") == 0
    try:
        for key in (r"Software\Classes\Directory\shell\PR7L", r"Software\Classes\SystemFileAssociations\.flac\shell\PR7L"):
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key)
            assert winreg.QueryValueEx(k, "MUIVerb")[0] == "PR7-L"
            cmd = winreg.QueryValueEx(winreg.OpenKey(winreg.HKEY_CURRENT_USER, key + r"\command"), "")[0]
            assert cmd.endswith('--explorer "%1"') and "pr7l" in cmd.lower()
        assert shell.menu_registered()
    finally:
        assert shell.run("--unregister") == 0
    assert not shell.menu_registered()


def test_menu_covers_every_audio_type():
    assert len(shell.KEYS) == 1 + len(shell.AUDIO_EXTENSIONS)
    assert shell.command().endswith(' --explorer "%1"')


def test_command_line(tmp_path):
    d = tmp_path / "Album"
    d.mkdir()
    assert app.parse([str(d)]) == (None, [str(d)])
    assert app.parse([f"/fp:{d}"]) == (None, [str(d)])                     # Mp3tag's switch
    assert app.parse(["--explorer", str(d), str(tmp_path / "gone")]) == ("--explorer", [str(d)])


def test_dump(tmp_path):
    import json
    p = shutil.copy(Path(__file__).parent / "data" / "blank.opus", tmp_path / "a.opus")
    from pr7l import tags
    tags.save(str(p), {"TITLE": ["t"]})
    out = tmp_path / "out.json"
    assert app.main(["--dump", str(out), str(p), str(tmp_path / "x.mp3")]) == 0
    got = json.loads(out.read_text())
    assert got[str(p)]["fields"]["TITLE"] == ["t"] and got[str(p)]["codec"] == "Opus"
    assert "error" in got[str(tmp_path / "x.mp3")]


def test_tests_never_touch_the_real_settings(qapp, tmp_path_factory):
    from pr7l import settings
    path = settings._s().fileName()
    assert path.endswith(".ini") and str(tmp_path_factory.getbasetemp()) in path
