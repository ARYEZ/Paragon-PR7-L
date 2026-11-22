# Paragon PR7-L: notes for Claude

**Paragon PR7-L** is the owner's personal tag editor: Python (**PySide6** + **mutagen**) that **works the way
Mp3tag works**, in the Paragon family look (the PR7 plugins, Paragon Photo, Paragon PR7-Z `ARYEZ/Paragon-PR7-Z`,
PR7-W `ARYEZ/Paragon-PR7-W`). Windows 10/11 x64 is the target; it runs on Linux for tests. The owner writes
Python; explain the why of changes.

## How it's built

- `pr7l/tags.py` (no Qt): every format mapped to Mp3tag's field names (TITLE, ARTIST, TRACK "1/9", DISCNUMBER,
  YEAR ...). MusicBrainz fields use **Picard's** names per format (ID3 TXXX descriptions, UFID for the recording
  id, MP4 `----:com.apple.iTunes:` freeforms, ASF `MusicBrainz/...`). `save(path, changes, pictures)` touches
  only the fields in `changes` (None/[] removes) and replaces pictures only when `pictures` is not None.
  `snapshot`/`restore` deep-copy mutagen's whole tag for Undo. ID3: v2.3 + v1 by default (Mp3tag), several
  values null-separated (`v23_sep=None`). Vorbis TRACK "3/9" = TRACKNUMBER + TRACKTOTAL (TOTALTRACKS read too).
- `pr7l/musicbrainz.py` (no Qt): WS/2 JSON search and release lookup, Cover Art Archive; `Client(fetch=)` is
  injectable; one request a second to musicbrainz.org (shared lock), 503 retried; User-Agent names the repo
  (never the owner's details). `parse_release` -> per-track tags; `initial_order` lines files up by disc/track
  tags else natural file name; `write_release` returns snapshots for Undo.
- `pr7l/discogs.py` (no Qt): the Discogs API as a second client with MusicBrainz's interface (`search`, `release`,
  `front_cover`, giving `musicbrainz.Release/Track/ReleaseSummary`); the token is the user's, in the
  `discogs_token` setting only. Each client names itself (`NAME`, `COVER_NAME`, `COVER_SIZES`, `RELEASE_FIELDS`,
  `ID_HINT`) for the shared `musicbrainz_dialog.py`; the window's `_tag_source(client)` opens it. CI's live
  Discogs test runs only with a `DISCOGS_TOKEN` secret.
- `pr7l/main_window.py`: `FileModel` is a plain Python list model (**not** QStandardItemModel: PR7-Z's crash);
  `FileView.drawRow` paints the family selection band; `TagPanel` keeps edits (`dirty`, `pending_pictures`)
  until Save; menu items with no slot yet are greyed out. `musicbrainz_dialog.py` runs network calls on
  QThreadPool and answers through queued signals; `dlg.sync = True` runs them inline (tests).
- `pr7l/script.py` (no Qt): Mp3tag format strings (`%field%`, `%_filename%`..., `$func(...)`, `'quoted'`);
  `guess(pattern, text)` reads fields back out (Filename/Text - Tag). `pr7l/convert.py` (no Qt): each converter
  returns `Planned` items (new path or changes, or an error) for the preview; the window's `apply_plan` applies
  them as one Undo step, which may hold `convert.Rename` records next to tag snapshots.
- `pr7l/actions.py` (no Qt): action dicts `{"type": ..., form keys}` (`TYPES` holds each type's form);
  `plan(actions, files)` runs them in memory per file and returns `Planned` (changes, `new` path for `_FILENAME`,
  `pictures`, `exports`). `apply_plan` saves tags first, then exports, then renames (Undo reverses renames first).
  `actions_dialog.py`: groups in the `action_groups` setting (JSON); the forms are built from `TYPES`.
- `pr7l/export.py` (no Qt): Mp3tag export templates parsed into text + `_Loop` nodes (`$loop` sorts by its
  expression; a loop holding a loop, or `$loop(x,1)`, runs per group); `write()` uses CRLF and a single BOM when
  appending; `playlist()` builds M3U. `export_dialog.py`: configs in the `export_configs` setting (JSON dict).
- `pr7l/filter.py` (no Qt): Mp3tag's filter language -> a predicate on TagFile (plain words, or HAS/IS/MATCHES/
  PRESENT/MISSING/GREATER/LESS/EQUAL with AND/OR/NOT). `FileModel.all_rows` holds every file, `rows` the shown ones
  (what all commands use); `replace()` keeps an edited row shown until the filter changes.
- `pr7l/cache.py`: SQLite cache of what `tags.read` gave (fields, info, picture *meta*), keyed by path, valid
  while size + `st_mtime_ns` match; bump `cache.VERSION` whenever reading changes. The window reads through
  `MainWindow._read` (cache, else read + store); rows are `slim()` (no picture bytes: `load_pictures()` on demand,
  `front_meta()` to compare covers). Tests point `PR7L_CACHE` at a temp file (conftest).
- `pr7l/shell.py`: registry verbs "PR7-L" on `Directory` and `SystemFileAssociations\<ext>` (HKCU);
  `app.collect` merges the one-process-per-file launches into one window (PR7-Z's scheme).
- `pr7l/settings.py`: typed QSettings getters (registry values come back as strings). Always
  `QSettings(QSettings.defaultFormat(), UserScope, ...)`: `QSettings(org, app)` ignores the tests' redirect.
- Installer `installer/pr7l.iss` (Inno Setup 6, per user, AppId {4C0E3F59-8A0B-4E7D-9B5A-2F7C61D3A9E1}
  permanent). CI installs it silently, runs `tools/verify_install.py installed` (which also runs the installed
  exe with `--dump` on every test format), uninstalls, `... uninstalled`.

## The look (family rules)

- Theme is PR7-W's (OBSIDIAN + AURORA via `theme.set_finish`), in PySide6. Colours: the family's only (hues
  ~318 -> 0 -> 42 deg, pearl and onyx greys); Inter; labels UPPER CASE; file names keep their case.
- The PR7-L mark: PR7 `Logo.cpp` geometry plus an L (`widgets.L_SHAPE`); icon by `tools/make_icon.py`, wizard
  art by `tools/make_installer_art.py`. Check visuals with `QT_SCALE_FACTOR=2 python tools/screenshots.py OUT [cover]`.

## Rules

- Behaviour questions: do what Mp3tag does (menus, shortcuts, dialogs, defaults).
- Tests: `python -m pytest` (offscreen). Tag tests compare the audio bytes before/after (`audio_payload`).
  Network tests use recorded answers (`tests/data/mb`); `PR7L_LIVE=1` (set in CI) also hits the real service.
  Tests never write the real settings (conftest) or, outside CI, the registry. Use `write_bytes` in tests.
- Releases: bump `__version__` in `pr7l/__init__.py`, add a `## x.y.z` section to CHANGELOG.md; a `v*` tag publishes.
