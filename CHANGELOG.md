# Changelog

## 0.1.0

First version.

- Tag engine on mutagen: ID3v1/v2.3/v2.4, Vorbis comments (FLAC, Ogg, Opus), MP4, APEv2 (WavPack, Monkey's,
  Musepack), WMA; one set of Mp3tag field names; MusicBrainz fields in Picard's spelling for each format.
  Saves change only the edited fields; Undo restores the whole previous tag.
- The window: tag panel with `< keep >`, file grid (sortable, drag and drop), save, remove, undo, copy and
  paste tag, Extended Tags, Options (ID3 version, ID3v1, keep file dates, subdirectories, cover size, finish).
- Covers: add, extract, replace, resize, remove, copy and paste, drop an image.
- MusicBrainz: search, release lookup, track matching by order and length, write tags and the Cover Art
  Archive's front cover, folder.jpg. Cover Art Archive alone for covers only.
- Explorer "PR7-L" item for folders and audio files; per-user installer; CI with a live MusicBrainz test.
