"""Reading and writing tags the way Mp3tag shows them, on top of mutagen. (No Qt here.)

Every format's own keys are mapped to one set of Mp3tag field names (TITLE, ARTIST, TRACK, ...), so the
grid, the tag panel and the tag sources only ever deal with those. The names for MusicBrainz data are
the ones MusicBrainz Picard writes (MUSICBRAINZ_ALBUMID ...), in each format's Picard spelling, so files
tagged here read the same in Picard, foobar2000 and Mp3tag.

Saving changes only the fields that were changed: everything else in the tag (frames we don't map,
ReplayGain, private frames) is kept, and mutagen rewrites only the tag, never the audio.
"""

from __future__ import annotations

import base64
import copy
import os
import struct
from dataclasses import dataclass, field
from pathlib import Path

import mutagen
from mutagen.apev2 import APEBinaryValue, APEv2, APEValue, BINARY, TEXT as APE_TEXT
from mutagen.asf import ASF, ASFByteArrayAttribute, ASFUnicodeAttribute
from mutagen.flac import FLAC, Picture as FlacPicture
from mutagen.id3 import APIC, COMM, ID3, ID3FileType, TXXX, UFID, USLT, Frames
from mutagen.mp4 import MP4, MP4Cover, MP4FreeForm

SEP = "\\\\"  # Mp3tag's separator between several values of one field (two backslashes)

AUDIO_EXTENSIONS = {".mp3", ".mp2", ".flac", ".ogg", ".oga", ".opus", ".spx", ".m4a", ".m4b", ".m4r", ".mp4",
                    ".ape", ".wv", ".mpc", ".ofr", ".tak", ".wma", ".asf", ".wav", ".aif", ".aiff", ".aifc",
                    ".dsf", ".dff", ".tta"}

# The tag panel's fields, in Mp3tag's order, and the grid's tag columns.
STANDARD = ["TITLE", "ARTIST", "ALBUM", "YEAR", "TRACK", "GENRE", "COMMENT", "ALBUMARTIST", "COMPOSER",
            "DISCNUMBER"]

PICTURE_TYPES = ["Other", "32x32 file icon", "Other file icon", "Front cover", "Back cover", "Leaflet page",
                 "Media", "Lead artist", "Artist", "Conductor", "Band", "Composer", "Lyricist",
                 "Recording location", "During recording", "During performance", "Video capture", "A bright fish",
                 "Illustration", "Band logotype", "Publisher logotype"]
FRONT = 3


@dataclass
class Picture:
    data: bytes
    mime: str = ""
    type: int = FRONT
    desc: str = ""

    def __post_init__(self):
        if not self.mime:
            self.mime = image_mime(self.data)


@dataclass
class Info:
    length: float = 0.0
    bitrate: int = 0          # bits per second
    sample_rate: int = 0
    channels: int = 0
    codec: str = ""


@dataclass
class TagFile:
    """One file as the grid sees it: its fields (name -> values), pictures and audio properties."""
    path: str
    kind: str                                   # "ID3", "Vorbis", "MP4", "APE", "ASF"
    fields: dict[str, list[str]] = field(default_factory=dict)
    pictures: list[Picture] = field(default_factory=list)
    info: Info = field(default_factory=Info)
    tag_label: str = ""                         # Mp3tag's "Tag" column: "ID3v2.3", "ID3v1 ID3v2.4", "FLAC" ...
    size: int = 0
    mtime: float = 0.0

    def get(self, name: str) -> str:
        """The field as Mp3tag shows it: several values joined with '\\\\'."""
        return SEP.join(self.fields.get(name.upper(), []))

    @property
    def filename(self) -> str:
        return os.path.basename(self.path)


class UnsupportedFile(Exception):
    pass


# ------------------------------------------------------------------------------------------ images
def image_mime(data: bytes) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:2] == b"BM":
        return "image/bmp"
    return "image/jpeg"


def image_size(data: bytes) -> tuple[int, int]:
    """Width and height from the image header (JPEG, PNG, GIF), or (0, 0)."""
    try:
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            return struct.unpack(">II", data[16:24])
        if data[:6] in (b"GIF87a", b"GIF89a"):
            return struct.unpack("<HH", data[6:10])
        if data[:2] == b"\xff\xd8":
            i = 2
            while i + 9 < len(data):
                if data[i] != 0xFF:
                    i += 1
                    continue
                marker = data[i + 1]
                if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                    i += 2
                    continue
                seg = struct.unpack(">H", data[i + 2:i + 4])[0]
                if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    h, w = struct.unpack(">HH", data[i + 5:i + 9])
                    return w, h
                i += 2 + seg
    except struct.error:
        pass
    return 0, 0


def picture_info(p: Picture) -> str:
    """'1200 x 1200  JPEG  245 KB  Front cover', for the cover box."""
    w, h = image_size(p.data)
    fmt = p.mime.split("/")[-1].upper().replace("JPG", "JPEG")
    kb = len(p.data) / 1024
    size = f"{kb / 1024:.1f} MB" if kb >= 1024 else f"{kb:.0f} KB"
    name = PICTURE_TYPES[p.type] if 0 <= p.type < len(PICTURE_TYPES) else "Other"
    dims = f"{w} x {h}  " if w else ""
    return f"{dims}{fmt}  {size}  {name}"


# ------------------------------------------------------------------------------------------ the mappings
# ID3: field -> frame id (text frames). Everything not here goes into TXXX with Picard's description.
ID3_FRAMES = {
    "TITLE": "TIT2", "ARTIST": "TPE1", "ALBUM": "TALB", "ALBUMARTIST": "TPE2", "TRACK": "TRCK",
    "DISCNUMBER": "TPOS", "YEAR": "TDRC", "GENRE": "TCON", "COMPOSER": "TCOM", "LABEL": "TPUB", "MEDIA": "TMED",
    "ISRC": "TSRC", "ARTISTSORT": "TSOP", "ALBUMARTISTSORT": "TSO2", "ALBUMSORT": "TSOA", "TITLESORT": "TSOT",
    "COMPOSERSORT": "TSOC", "BPM": "TBPM", "CONDUCTOR": "TPE3", "REMIXER": "TPE4", "LYRICIST": "TEXT",
    "ENCODEDBY": "TENC", "ENCODERSETTINGS": "TSSE", "COPYRIGHT": "TCOP", "ORIGINALDATE": "TDOR",
    "SUBTITLE": "TIT3", "CONTENTGROUP": "TIT1", "MOOD": "TMOO", "COMPILATION": "TCMP", "DISCSUBTITLE": "TSST",
    "LANGUAGE": "TLAN", "ORIGARTIST": "TOPE", "KEY": "TKEY", "RELEASETIME": "TDRL",
}
ID3_FRAME_NAMES = {v: k for k, v in ID3_FRAMES.items()}
# Picard's TXXX descriptions (and MP4 freeform names) for the MusicBrainz fields.
PICARD_NAMES = {
    "MUSICBRAINZ_ALBUMID": "MusicBrainz Album Id", "MUSICBRAINZ_ARTISTID": "MusicBrainz Artist Id",
    "MUSICBRAINZ_ALBUMARTISTID": "MusicBrainz Album Artist Id",
    "MUSICBRAINZ_RELEASEGROUPID": "MusicBrainz Release Group Id",
    "MUSICBRAINZ_RELEASETRACKID": "MusicBrainz Release Track Id", "RELEASETYPE": "MusicBrainz Album Type",
    "RELEASESTATUS": "MusicBrainz Album Status", "RELEASECOUNTRY": "MusicBrainz Album Release Country",
    "MUSICBRAINZ_TRACKID": "MusicBrainz Track Id", "ORIGINALYEAR": "originalyear",
}
PICARD_FIELDS = {v.upper(): k for k, v in PICARD_NAMES.items()}
MB_UFID = "http://musicbrainz.org"  # ID3 keeps the recording id in a UFID frame (Picard)

MP4_ATOMS = {
    "TITLE": "\xa9nam", "ARTIST": "\xa9ART", "ALBUM": "\xa9alb", "ALBUMARTIST": "aART", "YEAR": "\xa9day",
    "GENRE": "\xa9gen", "COMMENT": "\xa9cmt", "COMPOSER": "\xa9wrt", "CONTENTGROUP": "\xa9grp",
    "UNSYNCEDLYRICS": "\xa9lyr", "ENCODEDBY": "\xa9too", "COPYRIGHT": "cprt", "ALBUMSORT": "soal",
    "ARTISTSORT": "soar", "ALBUMARTISTSORT": "soaa", "TITLESORT": "sonm", "COMPOSERSORT": "soco",
    "DESCRIPTION": "desc",
}
MP4_ATOM_NAMES = {v: k for k, v in MP4_ATOMS.items()}
MP4_FREEFORM = "----:com.apple.iTunes:"

APE_KEYS = {"TITLE": "Title", "ARTIST": "Artist", "ALBUM": "Album", "ALBUMARTIST": "Album Artist",
            "TRACK": "Track", "DISCNUMBER": "Disc", "YEAR": "Year", "GENRE": "Genre", "COMMENT": "Comment",
            "COMPOSER": "Composer"}
APE_NAMES = {v.upper(): k for k, v in APE_KEYS.items()}
APE_PICTURES = {"COVER ART (FRONT)": 3, "COVER ART (BACK)": 4, "COVER ART (OTHER)": 0, "COVER ART (MEDIA)": 6,
                "COVER ART (LEAFLET)": 5, "COVER ART (ARTIST)": 8}

ASF_KEYS = {
    "TITLE": "Title", "ARTIST": "Author", "ALBUM": "WM/AlbumTitle", "ALBUMARTIST": "WM/AlbumArtist",
    "TRACK": "WM/TrackNumber", "DISCNUMBER": "WM/PartOfSet", "YEAR": "WM/Year", "GENRE": "WM/Genre",
    "COMMENT": "Description", "COMPOSER": "WM/Composer", "COPYRIGHT": "Copyright", "LABEL": "WM/Publisher",
    "BPM": "WM/BeatsPerMinute", "ISRC": "WM/ISRC", "CATALOGNUMBER": "WM/CatalogNo", "BARCODE": "WM/Barcode",
    "MEDIA": "WM/Media", "ORIGINALYEAR": "WM/OriginalReleaseYear", "CONDUCTOR": "WM/Conductor",
    "LYRICIST": "WM/Writer", "ENCODEDBY": "WM/EncodedBy", "MOOD": "WM/Mood", "ARTISTSORT": "WM/ArtistSortOrder",
    "ALBUMSORT": "WM/AlbumSortOrder", "ALBUMARTISTSORT": "WM/AlbumArtistSortOrder", "SUBTITLE": "WM/SubTitle",
    "CONTENTGROUP": "WM/ContentGroupDescription", "UNSYNCEDLYRICS": "WM/Lyrics",
    "MUSICBRAINZ_TRACKID": "MusicBrainz/Track Id", "MUSICBRAINZ_ALBUMID": "MusicBrainz/Album Id",
    "MUSICBRAINZ_ARTISTID": "MusicBrainz/Artist Id", "MUSICBRAINZ_ALBUMARTISTID": "MusicBrainz/Album Artist Id",
    "MUSICBRAINZ_RELEASEGROUPID": "MusicBrainz/Release Group Id",
    "MUSICBRAINZ_RELEASETRACKID": "MusicBrainz/Release Track Id", "RELEASETYPE": "MusicBrainz/Album Type",
    "RELEASESTATUS": "MusicBrainz/Album Status", "RELEASECOUNTRY": "MusicBrainz/Album Release Country",
}
ASF_NAMES = {v.upper(): k for k, v in ASF_KEYS.items()}
ASF_SKIP = {"WM/PICTURE", "WM/MEDIAPRIMARYCLASSID", "WMFSDKVERSION", "WMFSDKNEEDED", "ISVBR", "WM/ENCODINGTIME"}

# Vorbis comments use the field names themselves, except these.
VORBIS_KEYS = {"YEAR": "DATE", "TRACK": "TRACKNUMBER"}
VORBIS_NAMES = {"DATE": "YEAR", "TRACKNUMBER": "TRACK"}
VORBIS_TOTALS = {"TRACK": ("TRACKTOTAL", "TOTALTRACKS"), "DISCNUMBER": ("DISCTOTAL", "TOTALDISCS")}
VORBIS_SKIP = {"METADATA_BLOCK_PICTURE", "COVERART", "COVERARTMIME"}


# ------------------------------------------------------------------------------------------ options
@dataclass
class WriteOptions:
    """Mp3tag's Options > Tags > Mpeg defaults: write ID3v1 and ID3v2.3."""
    id3v2_version: int = 3              # 3 or 4
    id3v1: bool = True                  # also write ID3v1 (MP3 and TrueAudio only; it can't hold more)
    preserve_mtime: bool = False


def _open(path: str):
    if Path(path).suffix.lower() not in AUDIO_EXTENSIONS:
        raise UnsupportedFile(path)
    try:
        f = mutagen.File(path)
    except mutagen.MutagenError as e:
        raise UnsupportedFile(f"{path}: {e}") from e
    if f is None:
        raise UnsupportedFile(path)
    return f


def _kind(f) -> str:
    if isinstance(f, MP4):
        return "MP4"
    if isinstance(f, ASF):
        return "ASF"
    if isinstance(f, FLAC) or type(f).__module__.startswith("mutagen.ogg"):
        return "Vorbis"
    if isinstance(f, ID3FileType) or type(f).__name__ in ("AIFF", "WAVE", "DSF", "DSDIFF"):
        return "ID3"
    if type(f).__name__ in ("MonkeysAudio", "WavPack", "Musepack", "OptimFROG", "TAK", "APEv2File"):
        return "APE"
    raise UnsupportedFile(type(f).__name__)


def _codec(f) -> str:
    name = type(f).__name__
    info = f.info
    if name in ("MP3", "EasyMP3"):
        return f"MPEG-{info.version:g} Layer {info.layer}"
    if isinstance(f, MP4):
        return getattr(info, "codec_description", "") or "AAC"
    if isinstance(f, ASF):
        return getattr(info, "codec_name", "") or "WMA"
    return {"OggVorbis": "Vorbis", "OggOpus": "Opus", "OggSpeex": "Speex", "OggFLAC": "FLAC", "WAVE": "PCM",
            "AIFF": "PCM", "MonkeysAudio": "Monkey's Audio", "TrueAudio": "True Audio",
            "OptimFROG": "OptimFROG"}.get(name, name)


def _has_id3v1(path: str) -> bool:
    try:
        with open(path, "rb") as fh:
            fh.seek(-128, os.SEEK_END)
            return fh.read(3) == b"TAG"
    except OSError:
        return False


# ------------------------------------------------------------------------------------------ reading
def read(path: str) -> TagFile:
    f = _open(path)
    kind = _kind(f)
    st = os.stat(path)
    tf = TagFile(path=str(path), kind=kind, size=st.st_size, mtime=st.st_mtime)
    i = f.info
    length = float(getattr(i, "length", 0) or 0)
    bitrate = int(getattr(i, "bitrate", 0) or 0)
    tf.info = Info(length, bitrate, int(getattr(i, "sample_rate", 0) or 0), int(getattr(i, "channels", 0) or 0),
                   _codec(f))
    reader = {"ID3": _read_id3, "Vorbis": _read_vorbis, "MP4": _read_mp4, "APE": _read_ape, "ASF": _read_asf}[kind]
    reader(f, tf)
    if not bitrate and length:  # formats mutagen gives no bitrate for: the file's size, less its pictures
        audio = st.st_size - sum(len(p.data) for p in tf.pictures)
        tf.info.bitrate = max(0, int(audio * 8 / length))
    tf.fields = {k: v for k, v in tf.fields.items() if v}
    if not tf.fields and not tf.pictures:
        tf.tag_label = ""  # an empty tag block shows as no tag, as in Mp3tag
    return tf


def _add(tf: TagFile, name: str, values) -> None:
    vals = [str(v) for v in values if str(v) != ""]
    if vals:
        have = tf.fields.setdefault(name.upper(), [])
        have.extend(v for v in vals if not (name.upper().startswith("MUSICBRAINZ_") and v in have))


def _read_id3(f, tf: TagFile) -> None:
    tags = f.tags
    labels = []
    if type(f).__name__ in ("MP3", "TrueAudio") and _has_id3v1(tf.path):
        labels.append("ID3v1")
    if tags is None or not len(tags):
        tf.tag_label = " ".join(labels)
        return
    if tags.version >= (2, 2, 0):
        labels.append(f"ID3v2.{tags.version[1]}")
    tf.tag_label = " ".join(labels)
    for frame in tags.values():
        fid = frame.FrameID
        if fid in ID3_FRAME_NAMES:
            _add(tf, ID3_FRAME_NAMES[fid], [str(t) for t in frame.text])
        elif fid == "TXXX":
            name = PICARD_FIELDS.get(frame.desc.upper(), frame.desc.upper())
            _add(tf, name, frame.text)
        elif fid == "COMM" and frame.desc == "":
            _add(tf, "COMMENT", frame.text)
        elif fid == "USLT" and frame.desc == "":
            _add(tf, "UNSYNCEDLYRICS", [frame.text])
        elif fid == "UFID" and frame.owner == MB_UFID:
            _add(tf, "MUSICBRAINZ_TRACKID", [frame.data.decode("ascii", "replace")])
        elif fid == "APIC":
            tf.pictures.append(Picture(frame.data, frame.mime, int(frame.type), frame.desc))
        elif fid == "WXXX" and frame.desc == "":
            _add(tf, "WWW", [frame.url])


def _read_vorbis(f, tf: TagFile) -> None:
    tf.tag_label = "FLAC" if isinstance(f, FLAC) else "Vorbis Comment"
    tags = f.tags
    if tags is None:
        if isinstance(f, FLAC) and not f.pictures:
            tf.tag_label = ""
        return
    totals = {}
    for key, value in tags:
        k = key.upper()
        if k in VORBIS_SKIP:
            if k == "METADATA_BLOCK_PICTURE":
                try:
                    p = FlacPicture(base64.b64decode(value))
                    tf.pictures.append(Picture(p.data, p.mime, int(p.type), p.desc))
                except Exception:  # a broken picture is skipped, not fatal
                    pass
            continue
        if k in ("TRACKTOTAL", "TOTALTRACKS", "DISCTOTAL", "TOTALDISCS"):
            totals.setdefault(k, value)
            continue
        _add(tf, VORBIS_NAMES.get(k, k), [value])
    for name, (a, b) in VORBIS_TOTALS.items():
        total = totals.get(a) or totals.get(b)
        if not total:
            continue
        vals = tf.fields.get(name)
        if vals and "/" not in vals[0]:
            vals[0] = f"{vals[0]}/{total}"
        elif not vals:
            tf.fields[a] = [total]  # a total without a number: show it as its own field
    if isinstance(f, FLAC):
        for p in f.pictures:
            tf.pictures.append(Picture(p.data, p.mime, int(p.type), p.desc))


def _read_mp4(f, tf: TagFile) -> None:
    tags = f.tags
    tf.tag_label = "MP4" if tags else ""
    if not tags:
        return
    for key, value in tags.items():
        if key in MP4_ATOM_NAMES:
            _add(tf, MP4_ATOM_NAMES[key], value)
        elif key in ("trkn", "disk"):
            n, total = value[0] if value else (0, 0)
            if n or total:
                _add(tf, "TRACK" if key == "trkn" else "DISCNUMBER", [f"{n}/{total}" if total else f"{n}"])
        elif key == "tmpo":
            _add(tf, "BPM", value)
        elif key == "cpil":
            _add(tf, "COMPILATION", ["1" if value else "0"])
        elif key == "covr":
            for c in value:
                mime = "image/png" if c.imageformat == MP4Cover.FORMAT_PNG else "image/jpeg"
                tf.pictures.append(Picture(bytes(c), mime, FRONT))
        elif key.startswith(MP4_FREEFORM):
            name = key[len(MP4_FREEFORM):]
            name = PICARD_FIELDS.get(name.upper(), name.upper())
            _add(tf, name, [bytes(v).decode("utf-8", "replace") for v in value])


def _read_ape(f, tf: TagFile) -> None:
    tags = f.tags
    tf.tag_label = "APEv2" if tags else ""
    if not tags:
        return
    for key, value in tags.items():
        k = key.upper()
        if value.kind == BINARY:
            if k in APE_PICTURES:
                data = bytes(value)
                _, _, img = data.partition(b"\x00")
                tf.pictures.append(Picture(img, "", APE_PICTURES[k]))
            continue
        if value.kind != APE_TEXT:
            continue
        _add(tf, APE_NAMES.get(k, k), list(value))
    tf.pictures.sort(key=lambda p: (p.type != FRONT, p.type))  # APE items have no order: front first


def _read_asf(f, tf: TagFile) -> None:
    tags = f.tags
    tf.tag_label = "WMA" if tags and len(tags.keys()) else ""
    if not tags:
        return
    for key in tags.keys():
        k = key.upper()
        values = tags[key]
        if k == "WM/PICTURE":
            for v in values:
                p = _asf_picture_read(bytes(v.value))
                if p:
                    tf.pictures.append(p)
            continue
        if k in ASF_SKIP:
            continue
        name = ASF_NAMES.get(k, k)
        _add(tf, name, [v.value if not isinstance(v.value, bytes) else "" for v in values])


def _asf_picture_read(data: bytes) -> Picture | None:
    try:
        ptype, size = struct.unpack_from("<bi", data)
        pos = 5
        end = data.index(b"\x00\x00", pos)
        while (end - pos) % 2:
            end = data.index(b"\x00\x00", end + 1)
        mime = data[pos:end].decode("utf-16-le")
        pos = end + 2
        end = data.index(b"\x00\x00", pos)
        while (end - pos) % 2:
            end = data.index(b"\x00\x00", end + 1)
        desc = data[pos:end].decode("utf-16-le")
        pos = end + 2
        return Picture(data[pos:pos + size], mime, ptype, desc)
    except (ValueError, struct.error, UnicodeDecodeError):
        return None


def _asf_picture(p: Picture) -> bytes:
    return (struct.pack("<bi", p.type, len(p.data)) + p.mime.encode("utf-16-le") + b"\x00\x00"
            + p.desc.encode("utf-16-le") + b"\x00\x00" + p.data)


# ------------------------------------------------------------------------------------------ writing
def save(path: str, changes: dict[str, list[str] | None], pictures: list[Picture] | None = None,
         options: WriteOptions | None = None) -> None:
    """Write `changes` (field -> values; None or [] removes the field) and, unless None, replace all
    pictures with `pictures`. Fields not in `changes` stay as they are."""
    options = options or WriteOptions()
    st = os.stat(path)
    f = _open(path)
    kind = _kind(f)
    if f.tags is None:
        f.add_tags()
    changes = {k.upper(): [v for v in (vals or []) if v != ""] for k, vals in changes.items()}
    {"ID3": _write_id3, "Vorbis": _write_vorbis, "MP4": _write_mp4, "APE": _write_ape,
     "ASF": _write_asf}[kind](f, changes, pictures)
    _save(f, kind, options)
    if options.preserve_mtime:
        os.utime(path, (st.st_atime, st.st_mtime))


def _save(f, kind: str, options: WriteOptions, v2: int | None = None, v1: bool | None = None) -> None:
    if kind == "ID3":
        # v23_sep=None: several values are null-separated in v2.3 too (Mp3tag, foobar2000 read them back
        # as separate values); "/" would turn "AC/DC" ambiguous.
        kw = {"v2_version": v2 or options.id3v2_version, "v23_sep": None}
        if isinstance(f, ID3FileType):  # MP3 and TrueAudio can carry ID3v1 too
            keep_v1 = options.id3v1 if v1 is None else v1
            kw["v1"] = 2 if keep_v1 else 0
        f.save(**kw)
    else:
        f.save()


def _write_id3(f, changes, pictures) -> None:
    tags: ID3 = f.tags
    for name, values in changes.items():
        if name in ID3_FRAMES:
            fid = ID3_FRAMES[name]
            tags.delall(fid)
            if values:
                tags.add(Frames[fid](encoding=3, text=values))
        elif name == "COMMENT":
            for fr in [fr for fr in tags.getall("COMM") if fr.desc == ""]:
                del tags[fr.HashKey]
            if values:
                tags.add(COMM(encoding=3, lang="eng", desc="", text=values))
        elif name == "UNSYNCEDLYRICS":
            for fr in [fr for fr in tags.getall("USLT") if fr.desc == ""]:
                del tags[fr.HashKey]
            if values:
                tags.add(USLT(encoding=3, lang="eng", desc="", text="\n".join(values)))
        else:
            desc = PICARD_NAMES.get(name, name)
            for fr in [fr for fr in tags.getall("TXXX")
                       if PICARD_FIELDS.get(fr.desc.upper(), fr.desc.upper()) == name]:
                del tags[fr.HashKey]
            if name == "MUSICBRAINZ_TRACKID":  # Picard keeps the recording id in UFID only
                tags.delall(f"UFID:{MB_UFID}")
                if values:
                    tags.add(UFID(owner=MB_UFID, data=values[0].encode("ascii", "replace")))
                continue
            if values:
                tags.add(TXXX(encoding=3, desc=desc, text=values))
    if pictures is not None:
        tags.delall("APIC")
        for i, p in enumerate(pictures):
            # APIC frames are keyed by description, so two pictures need different ones.
            desc = p.desc if p.desc not in [q.desc for q in pictures[:i]] else f"{p.desc} ({i})"
            tags.add(APIC(encoding=3, mime=p.mime, type=p.type, desc=desc, data=p.data))


def _write_vorbis(f, changes, pictures) -> None:
    tags = f.tags
    for name, values in changes.items():
        key = VORBIS_KEYS.get(name, name)
        if name in VORBIS_TOTALS:
            a, b = VORBIS_TOTALS[name]
            for k in (key, a, b):
                if k in tags:
                    del tags[k]
            if values:
                n, _, total = values[0].partition("/")
                tags[key] = [n] + values[1:]
                if total:
                    tags[a] = [total]
            continue
        if name in ("TRACKTOTAL", "TOTALTRACKS", "DISCTOTAL", "TOTALDISCS"):
            for k in VORBIS_TOTALS["TRACK" if "TRACK" in name else "DISCNUMBER"][:2]:
                if k in tags:
                    del tags[k]
            if values:
                tags[name] = values
            continue
        if key in tags:
            del tags[key]
        if values:
            tags[key] = values
    if pictures is not None:
        if isinstance(f, FLAC):
            f.clear_pictures()
            for p in pictures:
                f.add_picture(_flac_picture(p))
        else:
            if "METADATA_BLOCK_PICTURE" in tags:
                del tags["METADATA_BLOCK_PICTURE"]
            for k in ("COVERART", "COVERARTMIME"):
                if k in tags:
                    del tags[k]
            if pictures:
                tags["METADATA_BLOCK_PICTURE"] = [base64.b64encode(_flac_picture(p).write()).decode("ascii")
                                                  for p in pictures]


def _flac_picture(p: Picture) -> FlacPicture:
    fp = FlacPicture()
    fp.data, fp.mime, fp.type, fp.desc = p.data, p.mime, p.type, p.desc
    w, h = image_size(p.data)
    fp.width, fp.height, fp.depth = w, h, 24
    return fp


def _number_pair(text: str) -> tuple[int, int]:
    n, _, total = text.partition("/")
    try:
        return int(n or 0), int(total or 0)
    except ValueError:
        return 0, 0


def _write_mp4(f, changes, pictures) -> None:
    tags = f.tags
    for name, values in changes.items():
        if name in MP4_ATOMS:
            key = MP4_ATOMS[name]
            tags.pop(key, None)
            if values:
                tags[key] = values
        elif name in ("TRACK", "DISCNUMBER"):
            key = "trkn" if name == "TRACK" else "disk"
            tags.pop(key, None)
            if values:
                tags[key] = [_number_pair(values[0])]
        elif name == "BPM":
            tags.pop("tmpo", None)
            if values and values[0].isdigit():
                tags["tmpo"] = [int(values[0])]
        elif name == "COMPILATION":
            tags.pop("cpil", None)
            if values:
                tags["cpil"] = values[0] not in ("0", "")
        else:
            for k in [k for k in tags.keys() if k.startswith(MP4_FREEFORM)
                      and PICARD_FIELDS.get(k[len(MP4_FREEFORM):].upper(), k[len(MP4_FREEFORM):].upper()) == name]:
                del tags[k]
            if values:
                tags[MP4_FREEFORM + PICARD_NAMES.get(name, name)] = [MP4FreeForm(v.encode("utf-8")) for v in values]
    if pictures is not None:
        tags.pop("covr", None)
        if pictures:
            tags["covr"] = [MP4Cover(p.data, MP4Cover.FORMAT_PNG if p.mime == "image/png" else MP4Cover.FORMAT_JPEG)
                            for p in pictures]


def _write_ape(f, changes, pictures) -> None:
    tags: APEv2 = f.tags
    for name, values in changes.items():
        key = APE_KEYS.get(name, name)
        for k in [k for k in tags.keys() if APE_NAMES.get(k.upper(), k.upper()) == name]:
            del tags[k]
        if values:
            tags[key] = APEValue("\x00".join(values), APE_TEXT)
    if pictures is not None:
        for k in [k for k in tags.keys() if k.upper() in APE_PICTURES]:
            del tags[k]
        names = {v: f"Cover Art ({k[11:-1].title()})" for k, v in APE_PICTURES.items()}
        for p in pictures:
            key = names.get(p.type, "Cover Art (Other)")
            ext = {"image/png": "png", "image/gif": "gif"}.get(p.mime, "jpg")
            if key not in tags:  # APE holds one picture per kind
                tags[key] = APEBinaryValue(f"cover.{ext}".encode() + b"\x00" + p.data, BINARY)


def _write_asf(f, changes, pictures) -> None:
    tags = f.tags
    for name, values in changes.items():
        key = ASF_KEYS.get(name, name)
        for k in [k for k in tags.keys() if ASF_NAMES.get(k.upper(), k.upper()) == name]:
            del tags[k]
        if values:
            tags[key] = [ASFUnicodeAttribute(v) for v in values]
    if pictures is not None:
        if "WM/Picture" in tags:
            del tags["WM/Picture"]
        if pictures:
            tags["WM/Picture"] = [ASFByteArrayAttribute(_asf_picture(p)) for p in pictures]


def remove_tags(path: str, options: WriteOptions | None = None) -> None:
    """File > Remove Tag: every tag the file has (ID3v1 and v2, APE on MP3 too), pictures included."""
    options = options or WriteOptions()
    st = os.stat(path)
    f = _open(path)
    kind = _kind(f)
    if isinstance(f, FLAC):
        f.delete()
        f.clear_pictures()
        f.save()
    elif kind == "ID3" and isinstance(f, ID3FileType):
        from mutagen.id3 import delete as id3_delete
        id3_delete(path, delete_v1=True, delete_v2=True)
        try:
            from mutagen.apev2 import delete as ape_delete
            ape_delete(path)
        except mutagen.MutagenError:
            pass
    else:
        f.delete()
    if options.preserve_mtime:
        os.utime(path, (st.st_atime, st.st_mtime))


# ------------------------------------------------------------------------------------------ undo
@dataclass
class Snapshot:
    """A file's whole tag as it was before a save, so Undo puts it back exactly (unmapped frames too)."""
    path: str
    tags: object
    pictures: list
    id3_version: int = 0
    id3v1: bool = False


def snapshot(path: str) -> Snapshot:
    f = _open(path)
    snap = Snapshot(str(path), copy.deepcopy(f.tags) if f.tags is not None else None,
                    copy.deepcopy(list(f.pictures)) if isinstance(f, FLAC) else [])
    if isinstance(f.tags, ID3):
        snap.id3_version = f.tags.version[1]
    if isinstance(f, ID3FileType):
        snap.id3v1 = _has_id3v1(path)
    return snap


def restore(snap: Snapshot, options: WriteOptions | None = None) -> None:
    options = options or WriteOptions()
    f = _open(snap.path)
    kind = _kind(f)
    if snap.tags is None:  # there was no tag at all
        if isinstance(f, FLAC):
            f.delete()
            f.clear_pictures()
            for p in snap.pictures:
                f.add_picture(p)
            f.save()
        else:
            remove_tags(snap.path, options)
        return
    if f.tags is None:
        f.add_tags()
    tags = f.tags
    if kind == "ID3":
        tags.clear()
        for frame in snap.tags.values():
            tags.add(copy.deepcopy(frame))
        v2 = snap.id3_version if snap.id3_version in (3, 4) else None
        _save(f, kind, options, v2=v2, v1=snap.id3v1)
        return
    if kind == "Vorbis":
        tags.clear()
        tags.extend(copy.deepcopy(list(snap.tags)))
        if isinstance(f, FLAC):
            f.clear_pictures()
            for p in snap.pictures:
                f.add_picture(p)
    elif kind == "ASF":
        for k in list(tags.keys()):
            del tags[k]
        for k, v in snap.tags.as_dict().items():
            tags[k] = v
    else:  # MP4, APE: dictionaries
        for k in list(tags.keys()):
            del tags[k]
        for k in snap.tags.keys():
            tags[k] = copy.deepcopy(snap.tags[k])
    f.save()
