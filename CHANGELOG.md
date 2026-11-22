# Changelog

## 0.2.0

- Convert menu, as in Mp3tag: **Tag - Filename** (Alt+1; a `\\` makes folders, illegal characters become `-`),
  **Filename - Tag** (Alt+2; also reads folder names, `%dummy%` skips a part), **Text file - Tag** (Alt+3; load a
  text file or paste a track list), **Tag - Tag** (Alt+5). Each shows a preview of every file first, keeps a
  history of format strings, and is one Undo step (renames are undone too, folders it made are removed).
- **Auto-numbering Wizard** (Ctrl+K): start number, leading zero, per-folder counter, track totals, disc numbers
  by folder.
- Format strings: Mp3tag's `%field%` placeholders, `%_filename%` and the other file placeholders, and its
  `$functions` (`$num $caps $left $right $mid $replace $regexp $if $if2 $ifgreater $meta` ... see `pr7l/script.py`).
- Fixed: tests wrote PR7-L's real settings; they now go to a temp folder like PR7-W's and PR7-Z's.

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
