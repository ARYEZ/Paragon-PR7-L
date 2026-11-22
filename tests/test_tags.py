"""The tag engine on real files of every format: what's written is what's read back (by us and by mutagen
directly, in the keys other players use), nothing else in the tag is lost, and the audio never changes."""

import io
import shutil
import struct
from pathlib import Path

import mutagen
import pytest
from mutagen.id3 import ID3, PRIV
from mutagen.ogg import OggPage

from pr7l import tags

DATA = Path(__file__).parent / "data"
FORMATS = ["mp3", "flac", "ogg", "opus", "m4a", "wma", "wv", "wav", "aiff", "tta"]


def jpeg(w=40, h=30, colour=(222, 6, 57)) -> bytes:
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (w, h), colour).save(b, "JPEG")
    return b.getvalue()


def png(w=16, h=8) -> bytes:
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (w, h), (205, 102, 25)).save(b, "PNG")
    return b.getvalue()


@pytest.fixture
def copy(tmp_path):
    def make(ext):
        return str(shutil.copy(DATA / f"blank.{ext}", tmp_path / f"song.{ext}"))
    return make


# ------------------------------------------------------------------ the audio itself, per container
def _strip_ape(data: bytes) -> bytes:
    if data[-32:-24] == b"APETAGEX":
        size, _, flags = struct.unpack("<III", data[-20:-8])
        return data[:len(data) - size - (32 if flags & 0x80000000 else 0)]
    return data


def audio_payload(path: str) -> bytes:
    """The audio data with every tag taken away: must be identical before and after any tag edit."""
    data = Path(path).read_bytes()
    ext = Path(path).suffix.lower()
    if ext in (".mp3", ".tta", ".wv"):
        if data[:3] == b"ID3":
            s = data[6:10]
            size = (s[0] << 21) | (s[1] << 14) | (s[2] << 7) | s[3]
            data = data[10 + size + (10 if data[5] & 0x10 else 0):]
        if data[-128:-125] == b"TAG":
            data = data[:-128]
        return _strip_ape(data)
    if ext == ".flac":
        pos = 4
        while True:
            head, size = data[pos], int.from_bytes(data[pos + 1:pos + 4], "big")
            pos += 4 + size
            if head & 0x80:
                return data[pos:]
    if ext in (".ogg", ".opus"):
        with open(path, "rb") as fh:
            pages = []
            while True:
                try:
                    pages.append(OggPage(fh))
                except EOFError:
                    break
        packets = OggPage.to_packets(pages)
        headers = 2 if ext == ".opus" else 3
        return b"".join(packets[headers:])
    if ext in (".wav", ".aiff"):
        want, endian = (b"data", "<") if ext == ".wav" else (b"SSND", ">")
        pos = 12
        while pos < len(data):
            cid, size = data[pos:pos + 4], struct.unpack(endian + "I", data[pos + 4:pos + 8])[0]
            if cid == want:
                return data[pos + 8:pos + 8 + size]
            pos += 8 + size + (size & 1)
        raise AssertionError("no audio chunk")
    if ext == ".m4a":
        pos = 0
        while pos < len(data):
            size, kind = struct.unpack(">I4s", data[pos:pos + 8])
            if kind == b"mdat":
                return data[pos + 8:pos + size]
            pos += size
        raise AssertionError("no mdat")
    if ext == ".wma":
        guid = bytes.fromhex("3626b2758e66cf11a6d900aa0062ce6c")
        i = data.index(guid, 16)
        size = struct.unpack("<Q", data[i + 16:i + 24])[0]
        return data[i + 24:i + size]
    raise AssertionError(ext)


ALL = {"TITLE": ["Portal"], "ARTIST": ["Paragon", "Guest Singer"], "ALBUM": ["ELSEWORLD"], "TRACK": ["1/9"],
       "DISCNUMBER": ["1/2"], "YEAR": ["2026"], "GENRE": ["Progressive Metal"], "COMMENT": ["first take"],
       "ALBUMARTIST": ["Paragon"], "COMPOSER": ["A. Writer"], "LABEL": ["Paragon Productions"],
       "CATALOGNUMBER": ["PRGN-007"], "MUSICBRAINZ_ALBUMID": ["6f1c0d6e-1111-2222-3333-44445555a3e2"],
       "MUSICBRAINZ_TRACKID": ["0a0b0c0d-1111-2222-3333-444455556666"], "MYFIELD": ["custom ünïcode ✓"]}


@pytest.mark.parametrize("ext", FORMATS)
def test_round_trip_every_field_and_cover(copy, ext):
    p = copy(ext)
    before = audio_payload(p)
    cover = jpeg()
    tags.save(p, ALL, [tags.Picture(cover)])
    t = tags.read(p)
    for k, v in ALL.items():
        assert t.fields.get(k) == v, (k, t.fields.get(k))
    assert [pic.data for pic in t.pictures] == [cover]
    assert t.pictures[0].mime == "image/jpeg" and t.pictures[0].type == tags.FRONT
    assert t.get("ARTIST") == "Paragon\\\\Guest Singer"  # Mp3tag's display of two values
    assert audio_payload(p) == before
    assert t.info.length == pytest.approx(1.5, abs=0.1)
    assert 0 < t.info.bitrate < 2_000_000  # never the cover's bytes counted as audio


@pytest.mark.parametrize("ext", FORMATS)
def test_changing_one_field_keeps_the_rest(copy, ext):
    p = copy(ext)
    tags.save(p, ALL, [tags.Picture(jpeg())])
    tags.save(p, {"TITLE": ["Portal (Remastered)"], "COMMENT": None})
    t = tags.read(p)
    assert t.fields["TITLE"] == ["Portal (Remastered)"]
    assert "COMMENT" not in t.fields
    for k, v in ALL.items():
        if k not in ("TITLE", "COMMENT"):
            assert t.fields.get(k) == v, k
    assert len(t.pictures) == 1  # pictures=None means: leave them


@pytest.mark.parametrize("ext", FORMATS)
def test_remove_tag_and_undo(copy, ext):
    p = copy(ext)
    before = audio_payload(p)
    tags.save(p, ALL, [tags.Picture(jpeg())])
    snap = tags.snapshot(p)
    tags.remove_tags(p)
    t = tags.read(p)
    assert t.pictures == [] and not any(k in t.fields for k in ALL)
    assert audio_payload(p) == before
    tags.restore(snap)  # Undo
    t = tags.read(p)
    assert {k: t.fields.get(k) for k in ALL} == ALL and len(t.pictures) == 1
    assert audio_payload(p) == before


@pytest.mark.parametrize("ext", FORMATS)
def test_undo_a_save_on_an_untagged_file(copy, ext):
    p = copy(ext)
    original = tags.read(p).fields
    snap = tags.snapshot(p)
    tags.save(p, {"TITLE": ["x"]}, [tags.Picture(png())])
    tags.restore(snap)
    t = tags.read(p)
    assert t.fields == original and t.pictures == []


@pytest.mark.parametrize("ext", FORMATS)
def test_several_pictures_and_png(copy, ext):
    p = copy(ext)
    pics = [tags.Picture(jpeg(), type=3), tags.Picture(png(), type=4)]
    tags.save(p, {}, pics)
    got = tags.read(p).pictures
    if ext in ("m4a",):  # MP4 has no picture types: every covr is a front cover
        assert [g.data for g in got] == [pics[0].data, pics[1].data]
    else:
        assert [(g.data, g.type) for g in got] == [(q.data, q.type) for q in pics]
    assert got[1].mime == "image/png"
    tags.save(p, {}, [])
    assert tags.read(p).pictures == []


def test_id3_is_written_the_way_picard_and_mp3tag_read_it(copy):
    p = copy("mp3")
    tags.save(p, ALL)
    raw = ID3(p)
    assert raw.version == (2, 3, 0)  # Mp3tag's default: ID3v2.3 ...
    assert Path(p).read_bytes()[-128:-125] == b"TAG"  # ... plus ID3v1
    assert raw["TPE1"].text == ["Paragon", "Guest Singer"]  # null-separated, not "Paragon/Guest Singer"
    assert raw["TXXX:MusicBrainz Album Id"].text == ALL["MUSICBRAINZ_ALBUMID"]
    assert raw["UFID:http://musicbrainz.org"].data.decode() == ALL["MUSICBRAINZ_TRACKID"][0]
    assert "TXXX:MusicBrainz Track Id" not in raw
    assert raw["TPUB"].text == ["Paragon Productions"] and raw["TXXX:CATALOGNUMBER"].text == ["PRGN-007"]
    assert str(ID3(p, translate=False)["TYER"].text[0]) == "2026"  # v2.3 keeps the year in TYER
    assert tags.read(p).tag_label == "ID3v1 ID3v2.3"


def test_id3_v24_without_v1(copy):
    p = copy("mp3")
    tags.save(p, {"TITLE": ["t"], "YEAR": ["2026-11-20"]}, options=tags.WriteOptions(id3v2_version=4, id3v1=False))
    raw = ID3(p)
    assert raw.version == (2, 4, 0) and str(raw["TDRC"].text[0]) == "2026-11-20"
    assert Path(p).read_bytes()[-128:-125] != b"TAG"
    assert tags.read(p).tag_label == "ID3v2.4"


def test_unmapped_frames_survive_a_save(copy):
    p = copy("mp3")
    tags.save(p, {"TITLE": ["a"]})
    raw = ID3(p)
    raw.add(PRIV(owner="www.example.com", data=b"\x01\x02"))
    raw.save(v2_version=3)
    tags.save(p, {"TITLE": ["b"], "ARTIST": ["c"]})
    raw = ID3(p)
    assert raw["PRIV:www.example.com:\x01\x02"].data == b"\x01\x02"
    assert raw["TIT2"].text == ["b"]


def test_vorbis_keys_and_totals(copy):
    p = copy("flac")
    tags.save(p, {"TRACK": ["3/9"], "DISCNUMBER": ["1/2"], "YEAR": ["2026"]})
    raw = mutagen.File(p)
    assert raw["TRACKNUMBER"] == ["3"] and raw["TRACKTOTAL"] == ["9"]
    assert raw["DISCNUMBER"] == ["1"] and raw["DISCTOTAL"] == ["2"]
    assert raw["DATE"] == ["2026"]
    raw["REPLAYGAIN_TRACK_GAIN"] = ["-6.20 dB"]
    raw.save()
    tags.save(p, {"TRACK": ["4"]})
    raw = mutagen.File(p)
    assert raw["TRACKNUMBER"] == ["4"] and "TRACKTOTAL" not in raw
    assert raw["REPLAYGAIN_TRACK_GAIN"] == ["-6.20 dB"]
    # foobar2000's TOTALTRACKS is read too
    raw["TOTALTRACKS"] = ["12"]
    raw.save()
    assert tags.read(p).fields["TRACK"] == ["4/12"]


def test_mp4_atoms(copy):
    p = copy("m4a")
    tags.save(p, ALL)
    raw = mutagen.File(p)
    assert raw["\xa9nam"] == ["Portal"] and raw["trkn"] == [(1, 9)] and raw["disk"] == [(1, 2)]
    assert bytes(raw["----:com.apple.iTunes:MusicBrainz Album Id"][0]).decode() == ALL["MUSICBRAINZ_ALBUMID"][0]


def test_ape_and_asf_keys(copy):
    p = copy("wv")
    tags.save(p, ALL)
    raw = mutagen.File(p)
    assert str(raw["Album Artist"]) == "Paragon" and list(raw["Artist"]) == ["Paragon", "Guest Singer"]
    p = copy("wma")
    tags.save(p, ALL)
    raw = mutagen.File(p)
    assert raw["WM/AlbumTitle"][0].value == "ELSEWORLD" and raw["Author"][0].value == "Paragon"
    assert raw["MusicBrainz/Album Id"][0].value == ALL["MUSICBRAINZ_ALBUMID"][0]


def test_preserve_mtime(copy):
    import os
    p = copy("flac")
    os.utime(p, (1_000_000_000, 1_000_000_000))
    tags.save(p, {"TITLE": ["x"]}, options=tags.WriteOptions(preserve_mtime=True))
    assert os.stat(p).st_mtime == 1_000_000_000
    tags.save(p, {"TITLE": ["y"]})
    assert os.stat(p).st_mtime > 1_000_000_000


def test_image_info():
    assert tags.image_size(jpeg(1200, 900)) == (1200, 900)
    assert tags.image_size(png(16, 8)) == (16, 8)
    assert tags.image_mime(png()) == "image/png"
    assert tags.picture_info(tags.Picture(jpeg(500, 500))).startswith("500 x 500  JPEG  ")


def test_unsupported(tmp_path):
    p = tmp_path / "notes.txt"
    p.write_bytes(b"hello")
    with pytest.raises(tags.UnsupportedFile):
        tags.read(str(p))
    q = tmp_path / "broken.mp3"
    q.write_bytes(b"\x00" * 10)
    with pytest.raises(tags.UnsupportedFile):
        tags.read(str(q))
