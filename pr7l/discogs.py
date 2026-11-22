"""The Discogs tag source (Tag Sources > Discogs), as Mp3tag's. (No Qt here.)

Discogs' API needs a personal access token for searching (discogs.com > Settings > Developers > Generate new
token); PR7-L keeps it in its settings (`discogs_token`), never anywhere else. Answers become the same Release /
Track objects as MusicBrainz's, so the dialog, the track matching, writing and Undo are shared.
Rules followed: a User-Agent naming the application; at most 60 requests a minute (one a second here; 429 is
waited out). https://www.discogs.com/developers
"""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.parse

from .musicbrainz import LookupFailed, Release, ReleaseSummary, Track, USER_AGENT, _urllib_fetch

API = "https://api.discogs.com"


def release_id(text: str) -> str | None:
    """A release asked for directly: a discogs.com/release/... link, [r12345] (Discogs' own notation) or the
    bare number."""
    text = (text or "").strip()
    m = (re.search(r"discogs\.com/(?:[^/\s]+/)?release/(\d+)", text, re.I) or re.fullmatch(r"\[r(\d+)\]", text, re.I)
         or re.fullmatch(r"(\d+)", text))
    return m.group(1) if m else None


def _clean(name: str) -> str:
    return re.sub(r" \(\d+\)$", "", name or "").strip()  # Discogs tells same-named artists apart with " (2)"


def credit(artists: list | None) -> str:
    """Discogs' artist list as it prints it: the name variation (anv) when given, joined by their joins."""
    out = []
    for i, a in enumerate(artists or []):
        out.append(_clean(a.get("anv") or a.get("name", "")))
        join = (a.get("join") or "").strip()
        if i < len(artists) - 1:
            out.append(", " if join in ("", ",") else f" {join} ")
    return "".join(out)


def _seconds(duration: str) -> float:
    parts = [int(p) for p in re.findall(r"\d+", duration or "")]
    total = 0
    for p in parts:
        total = total * 60 + p
    return float(total)


def _disc(position: str) -> int | None:
    """'2-5', '2.5', 'CD2-5' -> disc 2; 'A1', '5' -> None (one disc, vinyl sides included)."""
    m = re.match(r"^(?:CD|DVD|Disc|D)?\s*(\d+)\s*[-.]\s*\d+", position or "", re.I)
    return int(m.group(1)) if m else None


class Client:
    NAME = "Discogs"
    COVER_NAME = "DISCOGS IMAGES"
    COVER_SIZES = ["original"]
    RELEASE_FIELDS = [("Album", "ALBUM"), ("Album artist", "ALBUMARTIST"), ("Year", "YEAR"), ("Genre", "GENRE"),
                      ("Style", "STYLE"), ("Label", "LABEL"), ("Catalog #", "CATALOGNUMBER")]
    ID_HINT = "Album, or a Discogs release link / [r12345]"

    def __init__(self, token: str = "", fetch=None, pause: float = 1.0):
        self.token = token.strip()
        self.fetch = fetch or _urllib_fetch
        self.pause = pause
        self._lock = threading.Lock()
        self._last = 0.0

    def _get(self, url: str, accept: str = "application/vnd.discogs.v2.discogs+json") -> tuple[int, bytes]:
        headers = {"User-Agent": USER_AGENT, "Accept": accept}
        if self.token and url.startswith(API):
            headers["Authorization"] = f"Discogs token={self.token}"
        waits = [2, 5, 10]
        for attempt in range(len(waits) + 1):
            with self._lock:
                wait = self._last + self.pause - time.monotonic()
                if wait > 0:
                    time.sleep(wait)
                self._last = time.monotonic()
            try:
                status, body = self.fetch(url, headers)
            except OSError as e:
                raise LookupFailed(f"Can't reach {urllib.parse.urlsplit(url).hostname}: {e}") from e
            if status in (429, 503) and attempt < len(waits):  # too many requests: wait, as the API asks
                time.sleep(self.pause * waits[attempt])
                continue
            return status, body
        return status, body

    def _json(self, url: str) -> dict:
        status, body = self._get(url)
        if status == 401:
            raise LookupFailed("Discogs refused the token: check it in Options > Discogs token.")
        if status == 404:
            raise LookupFailed("Discogs doesn't know that release.")
        if status in (429, 503):
            raise LookupFailed("Discogs is busy (too many requests): try again in a minute.")
        if status != 200:
            raise LookupFailed(f"Discogs answered {status}.")
        try:
            return json.loads(body)
        except ValueError as e:
            raise LookupFailed("Discogs sent something that isn't JSON.") from e

    # ------------------------------------------------------------------------------------ search
    def search(self, artist: str = "", album: str = "", limit: int = 25) -> list[ReleaseSummary]:
        for text in (album, artist):
            rid = release_id(text)
            if rid:
                return [summary_from_release(self._json(f"{API}/releases/{rid}"))]
        if not self.token:
            raise LookupFailed("Searching Discogs needs your personal token (Options > Discogs token).")
        if not (artist.strip() or album.strip()):
            raise LookupFailed("Type an artist or an album to search for.")
        q = {"type": "release", "per_page": str(limit)}
        if artist.strip():
            q["artist"] = artist.strip()
        if album.strip():
            q["release_title"] = album.strip()
        data = self._json(f"{API}/database/search?{urllib.parse.urlencode(q)}")
        return [summary(r, i) for i, r in enumerate(data.get("results", []))]

    def release(self, rid: str) -> Release:
        return parse_release(self._json(f"{API}/releases/{rid}"))

    def front_cover(self, release_id: str, release_group: str = "", size: str = "original") -> bytes | None:
        data = self._json(f"{API}/releases/{release_id}")
        images = data.get("images") or []
        img = next((i for i in images if i.get("type") == "primary"), images[0] if images else None)
        if not img or not img.get("uri"):
            return None
        status, body = self._get(img["uri"], accept="image/*")
        if status != 200 or not body:
            raise LookupFailed(f"The cover couldn't be downloaded ({status}).")
        return body


def summary(r: dict, rank: int = 0) -> ReleaseSummary:
    """A search result. Discogs gives no score: the order it answers in (best first) becomes one."""
    artist, _, title = (r.get("title") or "").partition(" - ")
    if not title:
        artist, title = "", artist
    fmt = r.get("format") or []
    return ReleaseSummary(id=str(r.get("id", "")), score=max(0, 100 - rank * 4), title=title.strip(),
                          artist=_clean(artist.strip()), date=str(r.get("year") or ""), country=r.get("country") or "",
                          label=", ".join(dict.fromkeys(r.get("label") or [])),
                          format=", ".join(fmt[:3]), tracks=0, disambiguation=r.get("catno") or "")


def summary_from_release(d: dict) -> ReleaseSummary:
    rel = parse_release(d)
    fmt = ", ".join(f.get("name", "") for f in d.get("formats") or [])
    return ReleaseSummary(id=rel.id, score=100, title=rel.title, artist=rel.artist, date=d.get("released") or
                          str(d.get("year") or ""), country=d.get("country") or "",
                          label=", ".join(dict.fromkeys(_clean(l.get("name", "")) for l in d.get("labels") or [])),
                          format=fmt, tracks=len(rel.tracks))


def _flatten(tracklist: list) -> list[dict]:
    """Real tracks only: headings dropped; an index track (a suite) gives its sub-tracks, or itself."""
    out = []
    for t in tracklist or []:
        kind = t.get("type_", "track")
        if kind == "heading":
            continue
        if kind == "index":
            subs = [s for s in t.get("sub_tracks") or [] if s.get("type_", "track") == "track"]
            out.extend(subs or [dict(t, type_="track")])
            continue
        out.append(t)
    return out


def parse_release(d: dict) -> Release:
    album_artist = credit(d.get("artists"))
    labels = d.get("labels") or []
    year = str(d.get("year") or "") if d.get("year") else (d.get("released") or "")[:4]
    barcodes = [i.get("value", "") for i in d.get("identifiers") or [] if i.get("type") == "Barcode"]
    album = {
        "ALBUM": [d.get("title", "")], "ALBUMARTIST": [album_artist],
        "ALBUMARTISTSORT": [d.get("artists_sort") or ""], "YEAR": [year if year != "0" else ""],
        "GENRE": list(d.get("genres") or []), "STYLE": list(d.get("styles") or []),
        "LABEL": list(dict.fromkeys(_clean(lb.get("name", "")) for lb in labels)),
        "CATALOGNUMBER": list(dict.fromkeys(lb.get("catno", "") for lb in labels if lb.get("catno") not in (None, "none"))),
        "BARCODE": barcodes[:1], "RELEASECOUNTRY": [d.get("country") or ""],
        "MEDIA": [(d.get("formats") or [{}])[0].get("name", "")],
        "DISCOGS_RELEASE_ID": [str(d.get("id", ""))],
    }
    album = {k: [x for x in v if x] for k, v in album.items() if any(v)}
    flat = _flatten(d.get("tracklist"))
    discs_seen = [_disc(t.get("position", "")) for t in flat]
    multi = len({x for x in discs_seen if x}) > 1
    per_disc: dict[int, list[dict]] = {}
    for t, disc in zip(flat, discs_seen):
        per_disc.setdefault(disc if multi and disc else 1, []).append(t)
    discs = len(per_disc)
    tracks = []
    for disc_no in sorted(per_disc):
        items = per_disc[disc_no]
        for n, t in enumerate(items, 1):
            ac = t.get("artists") or d.get("artists")
            composers = [_clean(x.get("anv") or x.get("name", "")) for x in t.get("extraartists") or []
                         if re.search(r"Written-By|Composed By|Music By", x.get("role", ""))]
            tt = dict(album)
            tt.update({"TITLE": [t.get("title", "")], "ARTIST": [credit(ac)], "TRACK": [f"{n}/{len(items)}"],
                       "DISCNUMBER": [f"{disc_no}/{discs}"], "COMPOSER": list(dict.fromkeys(composers))})
            tt = {k: [x for x in v if x] for k, v in tt.items() if any(v)}
            tracks.append(Track(disc_no, discs, n, len(items), t.get("title", ""), credit(ac),
                                _seconds(t.get("duration", "")), tt))
    images = d.get("images") or []
    return Release(id=str(d.get("id", "")), title=d.get("title", ""), artist=album_artist,
                   date=d.get("released") or year, album_tags=album, tracks=tracks,
                   release_group=str(d.get("master_id") or ""), has_front=bool(images))
