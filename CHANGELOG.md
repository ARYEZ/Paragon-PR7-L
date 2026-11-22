# Changelog

## 0.4.0

- **Export** (Ctrl+E), as in Mp3tag: configurations in Mp3tag's export language (`$filename(csv,utf-8)`,
  `$loop(...)`/`$loopend()`, nested loops per group, `$loop(x,1)` once per group, `%_total_files%` `%_total_time%`
  `%_total_size%` `%_date%` ...), with an editor and a live preview. Comes with CSV (Excel), Text list, Album list
  and HTML table. Output file, append, open afterwards. UTF-8 (with BOM, for Excel), UTF-16 or ANSI;
  Windows line ends.
- New in format strings: `$csv(x)` (a safe CSV cell) and `$html(x)`, `%_file_size%`, `%_file_size_bytes%`,
  `%_file_mod_date%`, `%_samplerate%`, `%_channels%`.
- **Create Playlist** (Ctrl+L): M3U of the selected files (or all) in the list's order, next to the first file;
  name from a format string (`%_directory%`), extended `#EXTINF` lines, relative paths, `.m3u8` UTF-8 or
  `.m3u` ANSI.

## 0.3.0

- **Actions** (Alt+6), as in Mp3tag: named action groups, ticked and run in order on the selected files, kept between
  runs; New / Edit / Copy / Delete / Move. Action types: Replace, Replace with regular expression, Case conversion
  (lower, UPPER, First letter, Mixed Case; characters to capitalise after; exceptions such as AC/DC, feat.),
  Format value, Remove fields, Remove fields except, Guess values, Split field by separator, Merge duplicate fields,
  Import cover from file, Export cover to file. Fields: one, several with `;`, `_ALL`, and `_FILENAME` to rename.
- **Actions (Quick)** (Alt+7) and Case Conversion / Replace / Regular Expression / Remove Fields in the Actions
  menu: one action, run once; its form is remembered.
- A run is one Undo step (tags, covers and renames; exported images stay). Three example groups to start from.

## 0.2.0

- Convert menu, as in Mp3tag: **Tag - Filename** (Alt+1; a `\\` makes folders, illegal characters become `-`),
  **Filename - Tag** (Alt+2; also reads folder names, `%dummy%` skips a part), **Text file - Tag** (Alt+3; load a
  text file or paste a track list), **Tag - Tag** (Alt+5). Each shows a preview of every file first, keeps a
  history of format strings, and is one Undo step (renames are undone too, folders it made are removed).
- **Auto-numbering Wizard** (Ctrl+K): start number, leading zero, per-folder counter, track totals, disc numbers
  by folder.
- Format strings: Mp3tag's `%field%` placeholders, `%_filename%` and the other file placeholders, and its
  `$functions` (`$num $caps $left $right $mid $replace $regexp $if $if2 $ifgreater $meta` ... see `pr7l/script.py`).
- **File cache**: what PR7-L reads from each file is kept (`%LOCALAPPDATA%\\Paragon\\PR7-L\\cache`), so a folder
  opens from the cache next time and only new or changed files (by size and modification time) are read again.
  F5 still reads everything again. Options: switch it off, or clear it. The uninstaller removes it.
- The list no longer keeps every file's cover in memory, only its details and a fingerprint; the cover shown in
  the panel is read when it's needed.
- PR7-L reopens every folder that was open (Change Directory and the ones added), not just the first.
- MusicBrainz "busy" (503) answers are retried for longer (2, 4, 8, 8 s) and then explained in words.
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
