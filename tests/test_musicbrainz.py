"""The MusicBrainz source against recorded WS/2 answers (this sandbox can't reach musicbrainz.org; CI also
runs the live tests at the end, which talk to the real service)."""

import json
import os
import shutil
from pathlib import Path

import pytest

from pr7l import musicbrainz as mb, tags

DATA = Path(__file__).parent / "data"
REL = "6f1c0d6e-0000-4000-8000-00000000a3e2"


def _jpeg() -> bytes:
    import io
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (60, 60), (205, 102, 25)).save(b, "JPEG")
    return b.getvalue()


JPEG = _jpeg()  # what the "Cover Art Archive" sends


class Recorded:
    """Answers like the real services, and remembers what was asked."""

    def __init__(self, extra=None):
        self.asked = []
        self.routes = {  # first match wins: the image files before the release's image list
            "/1-1200.jpg": (200, JPEG), "/1-500.jpg": (200, JPEG + b"500"), "/1.jpg": (200, JPEG + b"full"),
            "/ws/2/release/?query=": (200, (DATA / "mb/search.json").read_bytes()),
            f"/ws/2/release/{REL}?inc=artist-credits+labels+recordings": (200, (DATA / "mb/release.json").read_bytes()),
            f"/ws/2/release/{REL}?inc=artist-credits+labels+media": (200, (DATA / "mb/release.json").read_bytes()),
            f"coverartarchive.org/release/{REL}": (200, (DATA / "mb/caa.json").read_bytes()),
        }
        self.routes = {**(extra or {}), **self.routes} if extra else self.routes
        for k in (extra or {}):
            self.routes[k] = extra[k]

    def __call__(self, url, headers):
        self.asked.append((url, headers))
        for key, answer in sorted(self.routes.items(), key=lambda kv: not kv[0].endswith(".jpg")):
            if key in url:  # image files first: their URLs contain the release's image-list URL
                return answer
        return 404, b""


def client(extra=None):
    rec = Recorded(extra)
    return mb.Client(fetch=rec, pause=0), rec


def test_search_builds_the_query_and_reads_the_results():
    c, rec = client()
    results = c.search("Paragon", "ELSEWORLD")
    url, headers = rec.asked[0]
    assert url.startswith("https://musicbrainz.org/ws/2/release/?query=")
    assert "release%3A%22ELSEWORLD%22%20AND%20artist%3A%22Paragon%22" in url and url.endswith("&fmt=json")
    assert headers["User-Agent"].startswith("Paragon-PR7-L/") and "github.com/ARYEZ/Paragon-PR7-L" in headers["User-Agent"]
    top = results[0]
    assert (top.id, top.score, top.title, top.artist, top.date, top.country) == (REL, 100, "ELSEWORLD", "Paragon",
                                                                                 "2026-11-20", "XW")
    assert (top.label, top.format, top.tracks) == ("Paragon Productions", "Digital Media", 3)
    assert results[2].format == "2xCD" and results[2].tracks == 14


def test_search_escapes_lucene_and_accepts_an_id():
    c, rec = client()
    c.search('AC/DC', 'Who "Made" Who')
    assert "AC%5C%2FDC" in rec.asked[0][0] and "Who%20%5C%22Made%5C%22%20Who" in rec.asked[0][0]
    hits = c.search("", f"https://musicbrainz.org/release/{REL}")
    assert [h.id for h in hits] == [REL] and f"/release/{REL}?" in rec.asked[-1][0]
    with pytest.raises(mb.LookupFailed):
        c.search("", "")


def test_release_becomes_picard_tags():
    c, _ = client()
    r = c.release(REL)
    assert (r.title, r.artist, r.release_group, r.has_front) == ("ELSEWORLD", "Paragon",
                                                                 "6f1c0d6e-0000-4000-8000-0000000000aa", True)
    assert len(r.tracks) == 3
    t1, t2, t3 = r.tracks
    assert t1.tags["TITLE"] == ["Portal"] and t1.tags["TRACK"] == ["1/3"] and t1.tags["DISCNUMBER"] == ["1/1"]
    assert t1.length == 252.0 and t3.length == 0
    assert t1.tags["ALBUM"] == ["ELSEWORLD"] and t1.tags["ALBUMARTIST"] == ["Paragon"] and t1.tags["YEAR"] == ["2026"]
    assert t1.tags["GENRE"] == ["Progressive Metal"]  # the most-voted genre, words capitalised
    assert t1.tags["LABEL"] == ["Paragon Productions"] and t1.tags["CATALOGNUMBER"] == ["PRGN-007"]
    assert t1.tags["RELEASETYPE"] == ["album"] and t1.tags["RELEASESTATUS"] == ["official"]
    assert t1.tags["MUSICBRAINZ_ALBUMID"] == [REL] and t1.tags["ISRC"] == ["XXA012600001"]
    assert t1.tags["MUSICBRAINZ_TRACKID"] == ["88880000-0000-4000-8000-000000000001"]  # the recording
    assert t1.tags["MUSICBRAINZ_RELEASETRACKID"] == ["77770000-0000-4000-8000-000000000001"]
    assert t1.tags["BARCODE"] == ["0123456789012"] and "ASIN" not in t1.tags  # null in the answer: left out
    assert t2.artist == "Paragon feat. Guest Singer" and t2.tags["ARTISTSORT"] == ["Paragon feat. Singer, Guest"]
    assert len(t2.tags["MUSICBRAINZ_ARTISTID"]) == 2


def test_front_cover_picks_the_front_at_the_size_asked():
    c, rec = client()
    assert c.front_cover(REL) == JPEG
    assert rec.asked[-1][0] == f"https://coverartarchive.org/release/{REL}/1-1200.jpg"  # https, and not the back
    assert c.front_cover(REL, size="500").endswith(b"500")
    assert c.front_cover(REL, size="original").endswith(b"full")


def test_cover_falls_back_to_the_release_group():
    rg = "6f1c0d6e-0000-4000-8000-0000000000aa"
    c, rec = client({f"coverartarchive.org/release/{REL}": (404, b""),
                     f"coverartarchive.org/release-group/{rg}": (200, (DATA / "mb/caa.json").read_bytes())})
    assert c.front_cover(REL, rg) == JPEG
    c, _ = client({f"coverartarchive.org/release/{REL}": (404, b"")})
    assert c.front_cover(REL) is None


def test_503_is_retried_then_reported():
    calls = []

    def busy(url, headers):
        calls.append(url)
        return (503, b"") if len(calls) < 3 else (200, (DATA / "mb/search.json").read_bytes())
    assert mb.Client(fetch=busy, pause=0).search("Paragon", "ELSEWORLD")[0].id == REL
    assert len(calls) == 3
    with pytest.raises(mb.LookupFailed, match="503"):
        mb.Client(fetch=lambda u, h: (503, b""), pause=0).search("a", "b")

    def down(url, headers):
        raise OSError("connection refused")
    with pytest.raises(mb.LookupFailed, match="musicbrainz.org"):
        mb.Client(fetch=down, pause=0).search("a", "b")


def test_requests_are_spaced_a_second_apart():
    import time
    c = mb.Client(fetch=Recorded(), pause=0.2)
    t0 = time.monotonic()
    c.search("a", "b")
    c.search("a", "b")
    c.search("a", "b")
    assert time.monotonic() - t0 >= 0.4


def test_initial_order_and_lengths(tmp_path):
    files = []
    for name, track in (("10 c.flac", "3"), ("2 b.flac", "2"), ("1 a.flac", "1")):
        p = shutil.copy(DATA / "blank.flac", tmp_path / name)
        tags.save(str(p), {"TRACK": [track]})
        files.append(tags.read(str(p)))
    r = mb.parse_release(json.loads((DATA / "mb/release.json").read_text()))
    assert [f.filename for f in mb.initial_order(files, r)] == ["1 a.flac", "2 b.flac", "10 c.flac"]
    tags.save(files[0].path, {"TRACK": ["1"]})  # two files say track 1: fall back to natural name order
    files = [tags.read(f.path) for f in files]
    assert [f.filename for f in mb.initial_order(files, r)] == ["1 a.flac", "2 b.flac", "10 c.flac"]
    assert mb.lengths_match(252.0, 250.5) and not mb.lengths_match(252.0, 240) and not mb.lengths_match(0, 0)
    assert mb.fmt_length(252) == "4:12" and mb.fmt_length(3725) == "1:02:05" and mb.fmt_length(0) == ""


def test_write_release_tags_cover_folder_jpg_and_undo(tmp_path):
    r = mb.parse_release(json.loads((DATA / "mb/release.json").read_text()))
    files = []
    for i, ext in enumerate(("flac", "mp3", "m4a")):
        p = shutil.copy(DATA / f"blank.{ext}", tmp_path / f"0{i + 1} track.{ext}")
        tags.save(str(p), {"COMMENT": ["mine"], "TITLE": ["old"]})
        files.append(tags.read(str(p)))
    pairs = list(zip(files, r.tracks))
    snaps = mb.write_release(pairs, r, {"GENRE": "Djent", "LABEL": ""}, cover=JPEG, folder_jpg=True)
    for f, t in pairs:
        got = tags.read(f.path)
        assert got.fields["TITLE"] == [t.title] and got.fields["ARTIST"] == [t.artist]
        assert got.fields["GENRE"] == ["Djent"]           # edited in the dialog
        assert got.fields.get("LABEL") is None            # emptied in the dialog: not written
        assert got.fields["COMMENT"] == ["mine"]          # not MusicBrainz's: kept
        assert got.fields["MUSICBRAINZ_ALBUMID"] == [REL]
        assert [p.data for p in got.pictures] == [JPEG]
    assert (tmp_path / "folder.jpg").read_bytes() == JPEG
    assert tags.read(pairs[1][0].path).fields["ARTIST"] == ["Paragon feat. Guest Singer"]
    for s in snaps:
        tags.restore(s)
    for f in files:
        got = tags.read(f.path)
        assert got.fields == {"COMMENT": ["mine"], "TITLE": ["old"]} and got.pictures == []


# ------------------------------------------------------------------ live: the real MusicBrainz (CI only)
live = pytest.mark.skipif(not os.environ.get("PR7L_LIVE"), reason="talks to musicbrainz.org (set PR7L_LIVE=1)")


@live
def test_live_search_lookup_and_cover():
    c = mb.Client()
    results = c.search("Radiohead", "OK Computer")
    assert results and results[0].score >= 90 and "OK Computer" in results[0].title
    assert all(r.id and mb.MBID.fullmatch(r.id) for r in results)
    got_cover = False
    for s in [r for r in results if r.tracks == 12][:4]:
        r = c.release(s.id)
        assert len(r.tracks) == 12 and r.tracks[0].title == "Airbag" and r.tracks[0].length > 200
        assert r.tracks[0].tags["ALBUMARTIST"] == ["Radiohead"] and r.tracks[0].tags["TRACK"] == ["1/12"]
        assert r.tracks[0].tags["MUSICBRAINZ_TRACKID"] and r.tracks[0].tags["MUSICBRAINZ_ALBUMID"] == [s.id]
        cover = c.front_cover(r.id, r.release_group, size="500")
        if cover:
            assert tags.image_mime(cover) in ("image/jpeg", "image/png")
            w, h = tags.image_size(cover)
            assert max(w, h) <= 500 + 1 and w > 100
            got_cover = True
            break
    assert got_cover
