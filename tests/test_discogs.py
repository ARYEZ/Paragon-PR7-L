"""The Discogs source against recorded API answers (live, in CI, only when a DISCOGS_TOKEN secret is set)."""

import io
import json
import os
import shutil
from pathlib import Path

import pytest

from pr7l import discogs, musicbrainz as mb, settings, tags

DATA = Path(__file__).parent / "data"
REL = "31415926"


def _jpeg():
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (60, 60), (222, 6, 57)).save(b, "JPEG")
    return b.getvalue()


JPEG = _jpeg()


class Recorded:
    def __init__(self):
        self.asked = []
        self.routes = {
            "/database/search?": (200, (DATA / "discogs/search.json").read_bytes()),
            f"/releases/{REL}": (200, (DATA / "discogs/release.json").read_bytes()),
            "/releases/27182818": (200, (DATA / "discogs/vinyl.json").read_bytes()),
            "i.discogs.com/front.jpeg": (200, JPEG),
        }

    def __call__(self, url, headers):
        self.asked.append((url, headers))
        for k, v in self.routes.items():
            if k in url:
                return v
        return 404, b""


def client(token="T0KEN"):
    rec = Recorded()
    return discogs.Client(token, fetch=rec, pause=0), rec


def test_search_sends_the_token_and_reads_results():
    c, rec = client()
    got = c.search("Paragon", "ELSEWORLD")
    url, headers = rec.asked[0]
    assert url.startswith("https://api.discogs.com/database/search?") and "artist=Paragon" in url
    assert "release_title=ELSEWORLD" in url and "type=release" in url
    assert headers["Authorization"] == "Discogs token=T0KEN" and headers["User-Agent"].startswith("Paragon-PR7-L/")
    assert (got[0].id, got[0].artist, got[0].title, got[0].date, got[0].label, got[0].score) == (
        REL, "Paragon", "ELSEWORLD", "2026", "Paragon Productions", 100)
    assert got[1].artist == "Various" and got[1].score < got[0].score


def test_token_needed_for_search_but_not_for_a_release_link():
    c, rec = client(token="")
    with pytest.raises(mb.LookupFailed, match="token"):
        c.search("Paragon", "ELSEWORLD")
    hits = c.search("", f"https://www.discogs.com/release/{REL}-Paragon-ELSEWORLD")
    assert [h.id for h in hits] == [REL] and hits[0].tracks == 6
    assert "Authorization" not in rec.asked[-1][1]
    assert [h.id for h in client()[0].search("", "[r27182818]")] == ["27182818"]


def test_errors_in_words():
    for status, msg in ((401, "refused the token"), (404, "doesn't know"), (429, "busy"), (500, "answered 500")):
        c = discogs.Client("x", fetch=lambda u, h, s=status: (s, b""), pause=0)
        with pytest.raises(mb.LookupFailed, match=msg):
            c.release("1")


def test_release_becomes_tags():
    r = client()[0].release(REL)
    assert (r.title, r.artist, r.release_group, r.has_front) == ("ELSEWORLD", "Paragon", "2718281", True)
    assert [(t.disc, t.number, t.title) for t in r.tracks] == [
        (1, 1, "Portal"), (1, 2, "Ruins of Elsewhere"), (1, 3, "I. Descent"), (1, 4, "II. Fall"),
        (2, 1, "Static Bloom"), (2, 2, "Elseworld")]                    # headings dropped, the suite's parts kept
    t1, t2 = r.tracks[0], r.tracks[1]
    assert t1.tags["TRACK"] == ["1/4"] and t1.tags["DISCNUMBER"] == ["1/2"] and r.tracks[4].tags["TRACK"] == ["1/2"]
    assert t1.length == 252 and r.tracks[5].length == 0
    assert t1.tags["ARTIST"] == ["Paragon"] and t1.tags["COMPOSER"] == ["A. Writer"]   # " (2)" / " (3)" dropped
    assert t2.tags["ARTIST"] == ["Paragon Feat. G. Singer"]                              # anv and join
    assert t1.tags["GENRE"] == ["Rock", "Electronic"] and t1.tags["STYLE"] == ["Prog Metal", "Djent"]
    assert (t1.tags["YEAR"], t1.tags["LABEL"], t1.tags["CATALOGNUMBER"], t1.tags["BARCODE"]) == (
        ["2026"], ["Paragon Productions"], ["PRGN-007"], ["0123456789012"])
    assert t1.tags["DISCOGS_RELEASE_ID"] == [REL] and t1.tags["MEDIA"] == ["File"]


def test_vinyl_sides_are_one_disc():
    r = client()[0].release("27182818")
    assert [(t.disc, t.tags["TRACK"][0]) for t in r.tracks] == [(1, "1/3"), (1, "2/3"), (1, "3/3")]
    assert r.tracks[0].artist == "Band A, Band B" and r.tracks[1].artist == "Various" and not r.has_front


def test_front_cover_is_the_primary_image():
    c, rec = client()
    assert c.front_cover(REL) == JPEG and rec.asked[-1][0] == "https://i.discogs.com/front.jpeg"
    assert c.front_cover("27182818") is None


# ------------------------------------------------------------------ through the window
@pytest.fixture
def window(qapp, tmp_path, monkeypatch):
    from pr7l.main_window import MainWindow
    monkeypatch.setattr("pr7l.main_window.QMessageBox.question", lambda *a, **k: 0)
    for i, ext in enumerate(("flac", "mp3", "m4a", "ogg", "opus", "wv"), 1):
        shutil.copy(DATA / f"blank.{ext}", tmp_path / f"{i:02} track.{ext}")
    w = MainWindow([str(tmp_path)])
    w.show()
    qapp.processEvents()
    yield w
    w.close()


def test_discogs_through_the_shared_dialog(window, tmp_path, monkeypatch):
    from pr7l.musicbrainz_dialog import MusicBrainzDialog
    settings.set("discogs_token", "")
    asked = []
    monkeypatch.setattr("pr7l.main_window.QInputDialog.getText",
                        lambda *a, **k: (asked.append(a[1]) or "  T0KEN ", True))
    c = window._discogs_client()
    assert asked == ["Discogs token"] and c.token == "T0KEN" and settings.get("discogs_token") == "T0KEN"
    assert window._discogs_client() is c                                   # asked once
    c.fetch = Recorded()
    c.pause = 0
    dlg = MusicBrainzDialog(window.model.rows, c, window, options=window._options())
    dlg.sync = True
    assert dlg.windowTitle() == "Discogs" and not dlg.cover_size.isVisibleTo(dlg)
    assert [lab for lab, _ in dlg.release_fields][4] == "Style"
    dlg.artist.setText("Paragon")
    dlg.album.setText("ELSEWORLD")
    dlg.search()
    assert dlg.release.id == REL and dlg.edits["STYLE"].text() == "Prog Metal\\\\Djent" and dlg.cover == JPEG
    dlg.folder_jpg.setChecked(True)
    dlg.write()
    got = {t.filename: tags.read(t.path) for t in window.model.rows}
    assert got["02 track.mp3"].fields["ARTIST"] == ["Paragon Feat. G. Singer"]
    assert got["05 track.opus"].fields["TRACK"] == ["1/2"] and got["05 track.opus"].fields["DISCNUMBER"] == ["2/2"]
    assert got["01 track.flac"].fields["STYLE"] == ["Prog Metal", "Djent"]
    assert all([p.data for p in g.pictures] == [JPEG] for g in got.values())
    assert (tmp_path / "folder.jpg").read_bytes() == JPEG
    settings.set("discogs_token", "")


def test_no_token_given_means_no_dialog(window, monkeypatch):
    settings.set("discogs_token", "")
    monkeypatch.setattr("pr7l.main_window.QInputDialog.getText", lambda *a, **k: ("", False))
    opened = []
    monkeypatch.setattr(window, "_tag_source", lambda *a, **k: opened.append(a))
    window.discogs()
    assert opened == [] and settings.get("discogs_token") == ""


def test_options_keep_the_token(qapp):
    from pr7l.dialogs import OptionsDialog
    settings.set("discogs_token", "old")
    dlg = OptionsDialog()
    assert dlg.discogs_token.text() == "old" and dlg.discogs_token.echoMode() == dlg.discogs_token.EchoMode.Password
    dlg.discogs_token.setText(" new ")
    dlg.apply()
    assert settings.get("discogs_token") == "new"
    settings.set("discogs_token", "")


live = pytest.mark.skipif(not os.environ.get("DISCOGS_TOKEN"),
                          reason="talks to api.discogs.com: needs a DISCOGS_TOKEN (a GitHub secret in CI)")


@live
def test_live_search_and_release():
    c = discogs.Client(os.environ["DISCOGS_TOKEN"])
    try:
        found = c.search("Radiohead", "OK Computer")
    except mb.LookupFailed as e:
        if "busy" in str(e):
            pytest.skip(str(e))
        raise
    assert found and any("OK Computer" in f.title for f in found)
    r = c.release(next(f.id for f in found if "OK Computer" in f.title))
    assert len(r.tracks) >= 12 and r.tracks[0].title == "Airbag" and r.tracks[0].length > 200
    assert json.dumps(r.tracks[0].tags)  # plain data, writable
