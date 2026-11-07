# MangaDot Uploader (modularized + GUI)

## First-time setup
    pip install -r requirements.txt

## Running the app
Double-click `Mangadot Uploader.bat`, or from a terminal:
    python main.py

## Runtime data location
All mutable state (config, upload history DB, paused-upload state, image
cache, crash/fault logs) lives in the per-user app-data directory -
`%LOCALAPPDATA%\MangaDotUploader\cache` on Windows - NOT next to the code,
so read-only installs work and upgrades don't touch user state. If an older
build left a `mangadot_app\cache\` folder behind, its files are copied over
automatically on first run.

## Running the tests
    python -m unittest discover -s tests -t .

Covers the parser (filename/chapter/volume parsing, language detection,
drift correction, custom regex), config (history DB, paused-upload state,
atomic writes), and util helpers.

## Current flow
0. **Settings dialog** - optional proxy configuration and debug HTTP logging.
1. **Login screen** - scans your browsers for a saved MangaDot session.
2. **Picker screen** - pick your manga folder (auto-fills and auto-runs a
   search from the folder name), or search by title/ID/pasted manga URL.
   Shows the selected manga's live details (cover, status, genres) inline.
3. **Group config screen** (embedded, not a popup) - group vs individual
   scanlator upload, auto-detects group tags from filenames, resolves
   against MangaDot's group search API, manual search/ID entry fallback.
4. **Title review screen** - editable table of every detected chapter.
5. **Upload progress screen** - live per-file progress, session-expiry
   re-auth, failed-upload retry with a saved log file.
6. A final summary screen.

## What changed in this round (bug fixes from real usage)
- **Fixed a crash**: the title review screen expected every file entry to
  have "title" and "size" keys that the directory scanner never actually
  set - this always crashed. Fixed in parser.py's
  scan_directory_files_auto (now calls a new finalize_file_entries step).
- **Picker screen rewritten**: auto-fills and auto-searches from the
  folder name, accepts a manga ID or a pasted manga URL directly (not
  just a title search), shows the selected manga's cover/status/genres
  inline, and moved the network search off the GUI thread (it used to
  freeze the whole window while searching).
- **Group config converted from a popup dialog to an embedded screen**,
  consistent with every other screen in the app, instead of opening as a
  separate floating window.
- Added: proxy support + debug HTTP request logging (settings dialog
  before login), and net.fetch_manga_full_details for richer manga info
  display.

## What's built so far
- Backend modules (`mangadot_app/`): config, net, util, parser, auth,
  uploader, optimizer, debugging.
- GUI (`mangadot_app/gui/`): theme.py + widgets.py (shared styling),
  login_screen.py, picker_screen.py, group_config_dialog.py
  (GroupConfigScreen), subset_picker_screen.py, title_review_screen.py,
  upload_progress_screen.py, optimizer_progress_screen.py,
  summary_screen.py, dry_run_screen.py, settings_dialog.py.
- `main.py`: wires everything together into one continuous flow
  (plus the separate dry-run and standalone-optimizer entry points).

## Still to build / polish
- The settings dialog's `verify=False` proxy option disables TLS
  verification for ALL traffic (login + uploads), not just the proxy check -
  intentional for MITM-proxy debugging, but worth knowing.
- Several GUI screens are very large (>1500 lines) and would benefit from
  being split before growing further.

## This round: CLI parity + full visual redesign
Four CLI-only features that had no GUI equivalent are now wired in:
- **Chapter naming mode** - the picker screen now has the same
  Preset/"Force Chapter N" vs Auto-detect choice the CLI has (was
  silently hardcoded to auto-detect before).
- **Dry run** - a "Dry Run" button on the startup settings dialog opens
  a folder+options picker that scans and previews parsing with zero
  login/network, same as the CLI's `--dry-run`.
- **Optimizer destructive-replace confirmation** - overwriting originals
  now shows a final confirmation with the exact file count right before
  it happens, matching the CLI's safety check (the settings checkbox
  alone used to be the only guard).
- **Upfront file-subset picker** - a new screen between attribution and
  title review lets you upload everything, type a range
  (`103-108,110,115-117`), or hand-pick files via checklist, instead of
  only being able to exclude files by deleting rows after the fact.
  Skipped automatically for small batches (<=3 files).

Also: a full visual redesign. New `theme.py` (dark palette, cyan accent,
consistent QSS) and `widgets.py` (Card, StatusPill, StatCard, StepStrip,
etc.) are shared across every screen. The three tables that felt roughest
(title review, upload progress, and the new dedicated `summary_screen.py`,
extracted out of what used to be inline code in main.py) got the most
attention: fixed column sizing, alternating rows, status pills instead of
raw emoji-prefixed text, and stat cards up top instead of just a wall of
rows. A `StepStrip` breadcrumb now shows where you are in the flow
(hidden for dry-run/standalone-optimizer since those bypass the normal
flow).

## Note on testing
This round was tested with a real (headless/offscreen) PySide6 install
in the build environment, not just reviewed - every screen was actually
instantiated and driven through its logic, and the full login -> picker
-> attribution -> subset picker -> title review -> upload -> summary
flow was run end-to-end with real temp files, plus the dry-run and
standalone-optimizer entry points separately. Screenshots were rendered
and checked (structure + actual pixel colors) for every screen. That
said, this was all headless/offscreen - a first real run on a real
desktop is still worth doing before relying on it, especially anything
touching actual browser cookie extraction, real network calls, or
PyInstaller packaging.
