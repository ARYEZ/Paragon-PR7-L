"""The MusicBrainz tag source and the Cover Art Archive. (No Qt here.)

MusicBrainz's web service (WS/2, JSON): search releases, look one up with its tracks, and turn it into the
same tags MusicBrainz Picard writes. Its rules, which this follows: a User-Agent naming the application
and where to find it, and on average no more than one request a second (else it answers 503).
https://musicbrainz.org/doc/MusicBrainz_API  https://musicbrainz.org/doc/Cover_Art_Archive/API
"""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from . import __version__

API = "https://musicbrainz.org/ws/2"
CAA = "https://coverartarchive.org"
USER_AGENT = f"Paragon-PR7-L/{__version__} ( https://github.com/ARYEZ/Paragon-PR7-L )"
MBID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
COVER_SIZES = ["500", "1200", "original"]


class LookupFailed(Exception):
    """Shown to the user as it is: what failed, in words."""


@dataclass
class ReleaseSummary:
    """One row of the search results."""
    id: str
    score: int
    title: str
    artist: str
    date: str
    country: str
    label: str
    format: str
    tracks: int
    status: str = ""
    disambiguation: str = ""


@dataclass
class Track:
    disc: int
    discs: int
    number: int          # position on its disc
    total: int           # tracks on its disc
    title: str
    artist: str
    length: float        # seconds (0 when MusicBrainz doesn't know)
    tags: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class Release:
    id: str
    title: str
    artist: str
    date: str
    album_tags: dict[str, list[str]]   # the fields every track shares (ALBUM, ALBUMARTIST, YEAR ...)
    tracks: list[Track]
    release_group: str = ""
    has_front: bool = False


# --------------------------------------------------------------------------------------------- HTTP
def _urllib_fetch(url: str, headers: dict) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read() if e.fp else b""


class Client:
    """`fetch(url, headers) -> (status, body)` is replaceable, so tests can answer with recorded responses."""

    NAME = "MusicBrainz"            # what the shared dialog (musicbrainz_dialog.py) calls things, per source
    COVER_NAME = "COVER ART ARCHIVE"
    COVER_SIZES = COVER_SIZES
    RELEASE_FIELDS = [("Album", "ALBUM"), ("Album artist", "ALBUMARTIST"), ("Year", "YEAR"), ("Genre", "GENRE"),
                      ("Label", "LABEL"), ("Catalog #", "CATALOGNUMBER"), ("Type", "RELEASETYPE")]
    ID_HINT = "Album, or a MusicBrainz release ID / link"

    def __init__(self, fetch=None, pause: float = 1.0):
        self.fetch = fetch or _urllib_fetch
        self.pause = pause
        self._lock = threading.Lock()
        self._last = 0.0

    def _get(self, url: str, accept: str = "application/json") -> tuple[int, bytes]:
        headers = {"User-Agent": USER_AGENT, "Accept": accept}
        waits = [2, 4, 8, 8]  # "slow down" (503): back off, as the API asks; shared networks hit it most
        for attempt in range(len(waits) + 1):
            if url.startswith(API):
                with self._lock:  # MusicBrainz: one request a second, from all our threads together
                    wait = self._last + self.pause - time.monotonic()
                    if wait > 0:
                        time.sleep(wait)
                    self._last = time.monotonic()
            try:
                status, body = self.fetch(url, headers)
            except OSError as e:
                raise LookupFailed(f"Can't reach {urllib.parse.urlsplit(url).hostname}: {e}") from e
            if status == 503 and attempt < len(waits):
                time.sleep(self.pause * waits[attempt])
                continue
            return status, body
        return status, body

    def _json(self, url: str) -> dict:
        status, body = self._get(url)
        if status == 404:
            raise LookupFailed("MusicBrainz doesn't know that release.")
        if status != 200:
            raise LookupFailed("MusicBrainz is busy (503): try again in a minute." if status == 503
                               else f"MusicBrainz answered {status}.")
        try:
            return json.loads(body)
        except ValueError as e:
            raise LookupFailed("MusicBrainz sent something that isn't JSON.") from e

    # ------------------------------------------------------------------------------------ search
    def search(self, artist: str = "", album: str = "", limit: int = 25) -> list[ReleaseSummary]:
        """Search by artist and album, as Mp3tag's MusicBrainz source does. A release id (or a
        musicbrainz.org release link) in either box looks that release up directly."""
        for text in (album, artist):
            m = MBID.search(text or "")
            if m:
                return [summary(self._json(f"{API}/release/{m.group(0).lower()}?inc=artist-credits+labels+media"
                                           "&fmt=json"), score=100)]
        parts = []
        if album.strip():
            parts.append(f'release:"{_escape(album.strip())}"')
        if artist.strip():
            parts.append(f'artist:"{_escape(artist.strip())}"')
        if not parts:
            raise LookupFailed("Type an artist or an album to search for.")
        q = urllib.parse.quote(" AND ".join(parts), safe="")
        data = self._json(f"{API}/release/?query={q}&limit={limit}&fmt=json")
        return [summary(r) for r in data.get("releases", [])]

    def release(self, mbid: str) -> Release:
        inc = "artist-credits+labels+recordings+release-groups+media+genres+isrcs"
        return parse_release(self._json(f"{API}/release/{mbid}?inc={inc}&fmt=json"))

    # ------------------------------------------------------------------------------------ cover art
    def cover_list(self, release_id: str, release_group: str = "") -> list[dict]:
        """The Cover Art Archive's images for the release (or, when it has none, its release group)."""
        for kind, mbid in (("release", release_id), ("release-group", release_group)):
            if not mbid:
                continue
            status, body = self._get(f"{CAA}/{kind}/{mbid}")
            if status == 404:
                continue
            if status != 200:
                raise LookupFailed(f"The Cover Art Archive answered {status}.")
            try:
                images = json.loads(body).get("images", [])
            except ValueError:
                continue
            if images:
                return images
        return []

    def front_cover(self, release_id: str, release_group: str = "", size: str = "1200") -> bytes | None:
        """The front cover's image bytes at `size` ("500", "1200" or "original"), or None if there is none."""
        images = self.cover_list(release_id, release_group)
        front = next((i for i in images if i.get("front") or "Front" in i.get("types", [])), None)
        if front is None:
            return None
        url = front.get("image", "") if size == "original" else (
            front.get("thumbnails", {}).get(size) or front.get("thumbnails", {}).get("large") or front.get("image", ""))
        if not url:
            return None
        url = url.replace("http://", "https://", 1)
        status, body = self._get(url, accept="image/*")
        if status != 200 or not body:
            raise LookupFailed(f"The cover couldn't be downloaded ({status}).")
        return body


def _escape(text: str) -> str:
    """Lucene's special characters, escaped, inside a quoted phrase."""
    return re.sub(r'([+\-&|!(){}\[\]^"~*?:\\/])', r"\\\1", text)


# --------------------------------------------------------------------------------------------- parsing
def credit(ac: list | None) -> str:
    """An artist credit as MusicBrainz prints it: names joined by their join phrases."""
    return "".join(c.get("name", c.get("artist", {}).get("name", "")) + c.get("joinphrase", "") for c in ac or [])


def credit_sort(ac: list | None) -> str:
    return "".join(c.get("artist", {}).get("sort-name", c.get("name", "")) + c.get("joinphrase", "")
                   for c in ac or [])


def credit_ids(ac: list | None) -> list[str]:
    return [c["artist"]["id"] for c in ac or [] if c.get("artist", {}).get("id")]


def summary(r: dict, score: int | None = None) -> ReleaseSummary:
    media = r.get("media", [])
    formats = []
    for m in media:
        f = m.get("format") or "(unknown)"
        formats.append(f)
    fmt = " + ".join(f"{formats.count(f)}x{f}" if formats.count(f) > 1 else f for f in dict.fromkeys(formats))
    labels = [li.get("label", {}).get("name", "") for li in r.get("label-info", []) or [] if li.get("label")]
    tracks = r.get("track-count") or sum(m.get("track-count", 0) for m in media)
    return ReleaseSummary(id=r["id"], score=int(r.get("score", score if score is not None else 0)),
                          title=r.get("title", ""), artist=credit(r.get("artist-credit")), date=r.get("date", ""),
                          country=r.get("country", "") or "", label=", ".join(dict.fromkeys(labels)), format=fmt,
                          tracks=int(tracks or 0), status=r.get("status", "") or "",
                          disambiguation=r.get("disambiguation", "") or "")


def _top_genre(r: dict) -> str:
    genres = r.get("genres") or r.get("release-group", {}).get("genres") or []
    if not genres:
        return ""
    best = max(genres, key=lambda g: g.get("count", 0))
    return " ".join(w[:1].upper() + w[1:] for w in best.get("name", "").split(" "))


def parse_release(r: dict) -> Release:
    """A release lookup (with recordings) turned into tags per track, in Picard's field names."""
    rg = r.get("release-group", {}) or {}
    labels = [li for li in r.get("label-info", []) or []]
    album_artist = credit(r.get("artist-credit"))
    date = r.get("date", "") or ""
    first = rg.get("first-release-date", "") or ""
    album: dict[str, list[str]] = {
        "ALBUM": [r.get("title", "")],
        "ALBUMARTIST": [album_artist],
        "ALBUMARTISTSORT": [credit_sort(r.get("artist-credit"))],
        "YEAR": [date[:4]],
        "ORIGINALDATE": [first],
        "ORIGINALYEAR": [first[:4]],
        "GENRE": [_top_genre(r)],
        "LABEL": list(dict.fromkeys(li["label"]["name"] for li in labels if li.get("label"))),
        "CATALOGNUMBER": list(dict.fromkeys(li["catalog-number"] for li in labels if li.get("catalog-number"))),
        "BARCODE": [r.get("barcode") or ""],
        "ASIN": [r.get("asin") or ""],
        "RELEASECOUNTRY": [r.get("country") or ""],
        "RELEASESTATUS": [(r.get("status") or "").lower()],
        "RELEASETYPE": [t.lower() for t in [rg.get("primary-type")] + (rg.get("secondary-types") or []) if t],
        "SCRIPT": [(r.get("text-representation") or {}).get("script") or ""],
        "MUSICBRAINZ_ALBUMID": [r["id"]],
        "MUSICBRAINZ_RELEASEGROUPID": [rg.get("id", "")],
        "MUSICBRAINZ_ALBUMARTISTID": credit_ids(r.get("artist-credit")),
    }
    album = {k: [x for x in v if x] for k, v in album.items() if any(v)}
    media = [m for m in r.get("media", []) if m.get("tracks")]
    tracks: list[Track] = []
    for disc_index, m in enumerate(media, 1):
        disc = int(m.get("position") or disc_index)
        total = int(m.get("track-count") or len(m["tracks"]))
        for t in m["tracks"]:
            rec = t.get("recording", {}) or {}
            ac = t.get("artist-credit") or rec.get("artist-credit") or r.get("artist-credit")
            length_ms = t.get("length") or rec.get("length") or 0
            number = int(t.get("position") or len(tracks) + 1)
            tt = dict(album)
            tt.update({
                "TITLE": [t.get("title") or rec.get("title", "")],
                "ARTIST": [credit(ac)],
                "ARTISTSORT": [credit_sort(ac)],
                "TRACK": [f"{number}/{total}"],
                "DISCNUMBER": [f"{disc}/{len(media)}"],
                "MEDIA": [m.get("format") or ""],
                "DISCSUBTITLE": [m.get("title") or ""],
                "ISRC": list(rec.get("isrcs") or []),
                "MUSICBRAINZ_TRACKID": [rec.get("id", "")],
                "MUSICBRAINZ_RELEASETRACKID": [t.get("id", "")],
                "MUSICBRAINZ_ARTISTID": credit_ids(ac),
            })
            tt = {k: [x for x in v if x] for k, v in tt.items() if any(v)}
            tracks.append(Track(disc, len(media), number, total, tt["TITLE"][0] if tt.get("TITLE") else "",
                                credit(ac), length_ms / 1000.0, tt))
    caa = r.get("cover-art-archive") or {}
    return Release(id=r["id"], title=r.get("title", ""), artist=album_artist, date=date, album_tags=album,
                   tracks=tracks, release_group=rg.get("id", ""), has_front=bool(caa.get("front")))


# --------------------------------------------------------------------------------------------- matching
def _int(text: str) -> int | None:
    m = re.match(r"\s*(\d+)", text or "")
    return int(m.group(1)) if m else None


def _natural(name: str):
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", name)]


def initial_order(files: list, release: Release) -> list:
    """The order the files are first lined up with the release's tracks: by their disc and track numbers
    when every file has them and they're all different, else by file name (natural order: 2 before 10)."""
    keys = []
    for f in files:
        track = _int(f.get("TRACK"))
        disc = _int(f.get("DISCNUMBER")) or 1
        keys.append((disc, track))
    if all(k[1] is not None for k in keys) and len(set(keys)) == len(keys):
        return [f for _, f in sorted(zip(keys, files), key=lambda kf: kf[0])]
    return sorted(files, key=lambda f: _natural(f.filename))


def lengths_match(a: float, b: float, tolerance: float = 3.0) -> bool:
    return bool(a and b) and abs(a - b) <= tolerance


def fmt_length(seconds: float) -> str:
    if not seconds:
        return ""
    s = int(round(seconds))
    h, rest = divmod(s, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02}:{s:02}" if h else f"{m}:{s:02}"


# --------------------------------------------------------------------------------------------- writing
def track_changes(release: Release, track: Track, album_edits: dict[str, str] | None = None) -> dict[str, list[str]]:
    """The fields to write for one track: the release's, with the dialog's edits to the album fields
    (empty edit = leave that field out). Fields the release doesn't have are not touched."""
    changes = dict(track.tags)
    for name, text in (album_edits or {}).items():
        values = [v for v in text.split("\\\\")] if text else []
        if values:
            changes[name] = values
        else:
            changes.pop(name, None)
    return changes


def write_release(pairs: list, release: Release, album_edits: dict[str, str] | None = None,
                  cover: bytes | None = None, folder_jpg: bool = False, options=None) -> list:
    """Write the release's tags to each (TagFile, Track) pair (and the front cover, replacing the files'
    pictures, when given); save the cover as folder.jpg next to the files when asked.
    Returns the files' snapshots from before, for Undo."""
    import os
    from . import tags
    snaps = []
    pictures = [tags.Picture(cover, type=tags.FRONT)] if cover else None
    for tf, track in pairs:
        snaps.append(tags.snapshot(tf.path))
        tags.save(tf.path, track_changes(release, track, album_edits), pictures, options)
    if cover and folder_jpg:
        for folder in dict.fromkeys(os.path.dirname(tf.path) for tf, _ in pairs):
            ext = "png" if tags.image_mime(cover) == "image/png" else "jpg"
            with open(os.path.join(folder, f"folder.{ext}"), "wb") as fh:
                fh.write(cover)
    return snaps
