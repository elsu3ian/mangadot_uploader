# Changelog

All notable changes to this project will be documented in this file.

## [2.0.0] - 2026-07-18

### Added
- **Desktop GUI App:** A full PySide6 desktop application, distributed as a standalone Windows `.exe` (no Python install required). It walks through the same login → folder/manga picker → group attribution → title review → upload flow as the CLI, plus:
  - A sortable, editable table for reviewing detected chapter/volume numbers and titles before upload, with inline renaming, per-row number overrides, and duplicate-number highlighting.
  - A right-click "Remove word/phrase" dialog with a live before/after preview, scoped to all rows or a selection.
  - A post-upload summary screen with manga cover art, metadata, and a double-clickable table of uploaded chapters that opens each one directly on MangaDot.
  - A startup settings dialog for proxy URL, SSL verification, and debug logging — no command-line flags needed.
- **Interactive Title & Number Review Pass (CLI):** After scanning, the CLI now shows a review menu before upload instead of going straight to confirmation. From here you can:
  - Remove a word/phrase from every detected title at once, with a live preview of affected titles before committing.
  - Remove a word/phrase from a specific number range (e.g. `103-108,110`) or a single file found by filename search.
  - Redo the auto-detected title for an entire group of similarly-named files in one action.
  - Manually override the detected chapter/volume number for a specific file, with duplicate-number warnings.
- **Flexible Number-Range Input:** Ranges like `103-108,110,115-117` are now accepted anywhere the uploader asks which chapters/volumes to target, with invalid or out-of-batch numbers reported individually instead of rejecting the whole input.
- **Cyrillic/Greek Homoglyph Normalization:** Filenames containing visually-identical Cyrillic or Greek characters (e.g. a Cyrillic С standing in for a Latin C) now match chapter/episode/volume label patterns correctly instead of silently failing to parse.
- **Advanced Auto-Detect Naming Options:** The naming-format prompt now has a dedicated "Advanced" mode exposing custom regex extraction and bracket/parenthesis-group stripping as independent, combinable toggles instead of separate top-level choices.
- **Leading-Zero Title Cleanup:** Standalone zero-padded numbers inside detected titles (e.g. `Episode 001`) are automatically normalized to their plain form (`Episode 1`) without touching adjacent alphanumeric tokens like `S002`.
- **Virtualenv-Aware Auto-Installer:** The dependency auto-installer now detects whether it's running inside a venv/virtualenv/conda environment and adjusts its install behavior accordingly, instead of always assuming a system-wide Python install.
- **Dedicated Batch-Init Error Type:** Batch initialization failures now raise a specific `BatchInitError` instead of being caught by a broad generic exception handler, giving clearer log output when a batch fails to start.
- **Log Redaction Helpers:** Home directory paths and proxy credentials are now consistently scrubbed from log output and error messages through dedicated redaction helpers, rather than being handled ad hoc at each call site.

### Changed
- **Project Versioning:** Bumped to v2.0.0 to reflect the GUI release alongside the CLI, and to mark the point where this project is being published as a public, independent fork rather than a personal script.
- **Repository Structure:** `mangadot.py` is now the sole maintained CLI script going forward; the legacy ANSI-console build is kept only as an archived reference (see [Repository Structure](README.md#repository-structure) in the README).

---

## [1.3.0] - 2026-07-12

### Added
- **Zen Browser Support:** Session cookies can now be read directly from the Zen browser's Gecko-based profile store, with automatic profile discovery and a WAL/SHM-safe copy fallback if the live database is locked.
- **CDP Fallback for Chromium Browsers:** Chrome, Edge, Brave, Vivaldi, and Opera now have a Chrome DevTools Protocol option (`Browser (CDP)`) that launches an isolated debug profile and reads cookies over a WebSocket connection, bypassing the OS-level encrypted cookie store that normally blocks direct extraction from these browsers.
- **Auto-Scan Login:** Login no longer defaults to a single browser (previously Firefox). The uploader now scans every supported browser automatically for a valid MangaDot session and stops at the first hit; a manual picker (including the new CDP options) still appears if none succeed.
- **Dynamic Title Picker:** Auto-detect naming now always presents a labeled picker of candidate titles (e.g. "Full title as detected," "Without episode label," "Without season tag," "Bare title only," "Minimal") built dynamically from the filename's structure, memoized per detected filename "shape" so it only has to be answered once per batch.
- **Episode/Chapter Number Drift Correction:** When chapter numbers and episode labels disagree within a batch, numbering is now reconciled and interpolated across the run instead of trusting whichever value was parsed first.
- **Manual Group-ID Fallback:** If a scanlator group name can't be resolved through search (fuzzy or otherwise), you can now type in its numeric MangaDot Group ID directly instead of the file being dropped from the group mapping.
- **Unverified-Upload Warning State:** Files in a group upload that don't resolve to any specific group now upload with an explicit `⚠️ Uploaded (Unverified — no group)` status instead of silently reusing the generic "uploaded" success label.
- **`websocket-client` Dependency:** Added to support the new CDP cookie-retrieval path.

### Changed
- **Higher Thread Ceiling:** Parallel upload threads raised from a 1–10 cap (default 3) to 1–30 (default 5), with an on-screen warning about Cloudflare rate-limiting before you commit to a high count.
- **Shared Upload Connection Pool:** Worker threads now share one pooled `requests.Session` (32 connections) for the whole run instead of each opening and tearing down its own session per chunk.
- **Ghost Chapter Verification Pagination:** The post-upload verification check now pages through the server's chapter/volume listing instead of trusting only the first page, closing a gap where a match on a later page could be missed and falsely reported as a Ghost Chapter conflict.
- **Group Name Detection Across Mixed Batches:** Filename group-tag detection now collects every unique group name seen across the batch instead of only surfacing the single most-frequent group's names.
- **Natural Sort Hyphen Fix:** Numeric sorting no longer treats a leading `-` used as a filename separator (e.g. `Chapter-5`) as part of the number; true negative numbers are still sorted correctly via value inversion.
- **Interruptible Retry Waits:** All inter-retry sleeps (chunk retries, verification polling, batch-complete retries) now check the abort signal every 100ms instead of blocking for the full delay, so `Ctrl+C` and session-expiry aborts land immediately instead of after the current backoff finishes.
- **TUS Offset Recovery:** If the server returns a 204 on a chunk PATCH without an `Upload-Offset` header, the uploader now falls back to an explicit `HEAD` offset check instead of guessing the new offset from the chunk size.

### Fixed
- **Dead `ctypes` Import:** Removed an unused, unconditionally-imported `ctypes` module left over from earlier Windows-specific code.
- **Stale CDP Process Safety:** Before relaunching a browser for CDP mode, the uploader now verifies a previously tracked PID still belongs to the expected browser executable before killing it, preventing an unrelated process from being terminated if the PID was recycled.
- **`--verify-timeout` Validation:** The flag now requires a positive integer and rejects zero, negative, or non-numeric values with a clear error instead of accepting them silently.

---

## [1.2.3] - 2026-06-30

### Added
- **Ownership-Aware Labeling:** The uploader now fetches your MangaDot user ID at login and compares it against the uploader of any chapter flagged as a duplicate, distinguishing your own prior uploads (`✅ Already Uploaded`) from someone else's (`✅ Already Exists`).
- **Persistent User-Agent Cache:** Resolved browser/User-Agent strings are now cached in `~/.mangadot_uploader.json`, avoiding repeated registry/plist/CLI probes on every launch.
- **Verification Concurrency Limiter:** Added a semaphore capping simultaneous server-side verification checks at 3, preventing large batches from hammering the API with parallel polling requests.
- **Fuzzy Group Search:** Scanlator group lookups now retry with camelCase-split and progressively spaced variations of the entered name (e.g. `GroupName` → `Group Name`) to find matches that wouldn't surface from an exact-string query.

### Fixed
- **Mixed-Group Batching Bug:** Files that didn't resolve to an explicit group in a mixed-group run no longer silently inherit the combined group list of every *other* resolved group in the batch.
- **Create-Conflict Ghost Chapters:** An HTTP 409 on the initial upload creation call (meaning the chapter already exists) now falls through to full Ghost Chapter verification instead of being trusted as an automatic success, closing a gap where someone else's pre-existing chapter could be miscounted as yours.
- **Case-Sensitive Scanlator Matching:** Scanlator name verification is now case-insensitive, preventing false negatives from minor capitalization differences.
- **Search Query Encoding:** Manga and group search requests now use `requests`'s `params=` encoding instead of raw f-string concatenation, fixing failures on queries containing special characters.
- **Localized API Fields:** Manga title, status, description, and alt-titles are now safely unpacked when the API returns them as localized objects (e.g. `{"en": ...}`) instead of plain strings, preventing blank or crashed confirmation screens.
- **Batch Completion Call:** The batch-complete API call is now skipped if a batch chunk had zero successful uploads, avoiding incorrect "complete" signals to the server.
- **ID Input Parsing:** Manga ID and Group ID prompts now use safe integer parsing instead of `.isdigit()`, correctly handling malformed input without crashing.
- **Proxy Health Check Rework:** Replaced the `1.1.1.1` Cloudflare-DNS probe with a dedicated no-content endpoint (`google.com/generate_204`) and wired the `--proxy-no-verify` flag through to the health check itself, so it now properly respects your SSL verification setting.
- **Sub-1KB File Sizes:** Files smaller than 1KB now display in bytes (e.g. `512 B`) instead of a misleading fractional KB value like `0.05 KB`.

### Changed
- **Genres Display:** The manga confirmation screen now shows a dedicated "Genres" line alongside "Tags".
- **Color Theme Sync:** Finished syncing the cyan/amber color scheme across the Cover Art, MangaDot, and MangaBaka links in the confirmation panel.
- **Directory & Archive Scanning:** Switched from `os.listdir` to `os.scandir` for faster directory traversal, added zero-byte file detection, and hardened `.cbz`/`.zip` validation against corrupt archives (`BadZipFile`).
- **Bracket/Title Extraction:** Group-tag and title stripping now uses match-position slicing instead of `str.replace()`, preventing accidental removal of duplicate substrings elsewhere in a filename.
- **Worker Session Lifecycle:** Each upload worker thread now opens its `requests.Session` as a context manager and inherits the parent session's SSL verification setting, ensuring sockets are cleaned up properly and `--proxy-no-verify` is honored on every worker.
- **Graceful Ctrl+C Feedback:** Added an explicit status message while in-flight uploads finish during a `KeyboardInterrupt` abort.
- Internal: `finished_order` upload-history tracking switched from a list to a `deque` for O(1) trimming at high throughput.

---

## [1.2.2] - 2026-06-26

### Added
- CLI flags `--proxy` and `--proxy-no-verify` for custom network routing and SSL bypass.
- Initial pre-flight proxy health check, routed against `1.1.1.1` with a spoofed User-Agent, to catch obviously dead proxies before a batch starts.

### Fixed
- `UnicodeDecodeError` crash during Chromium version detection on non-UTF-8 Linux locales.
- Unnecessary 60-second verification loop hang when uploading exclusively under a Scanlator Name.
- Dictionary key lookup misses for mixed-group mapping caused by Windows vs. Linux slash direction mismatches.

### Changed
- Added explicit thread cancellation on `KeyboardInterrupt` for clean terminal exits.
- Implemented proactive warning triggers for undetectable API search schema changes.
- Added exception handling for Windows temp file locking during `chafa` rendering to prevent execution crashes.
- Reworked human-readable file size formatting to use tiered GB/MB/KB units instead of a flat KB-only display.

---

## [1.2.0] - 2026-06-25

### Added
- **Interactive UI Engine:** Integrated `rich` and `questionary` to replace the outdated manual ANSI escape sequences with an interactive terminal dashboard featuring clear drop-down picker menus.
- **Auto-Dependency Installer:** Added an automated system setup pipeline that screens for required packages on boot and runs a sub-process `pip install --upgrade` automatically if things are missing.
- **Inline Image Rendering:** Enabled automated vertical terminal cover art display strings triggered through local integrations with `chafa`.
- **Persistent Local State:** Created an automated local JSON configuration engine (`~/.mangadot_uploader.json`) to remember root manga library paths and interface histories. Exposed via `--library <path>` CLI flag.
- **Dynamic Group Extraction:** Built regex parsing loops to scrape scanlator names directly from filename `[Bracket]` tags while systematically parsing out resolution asset metrics.
- **Mixed-Group Batching:** Rewrote the upload payload structure to support chapters from different scanlator groups in a single execution queue, each mapping to their own group profile automatically.
- **HTTP 409 Conflict Resolution:** Added a `HEAD` request check (`_tus_offset`) to recover from byte-offset mismatches caused by partial chunk landings during network hiccups.
- **Advanced User-Agent Spoofing:** Implemented an automated registry, plist, and CLI probe pipeline to look up the actual installed browser version and generate accurate User-Agent signatures for Cloudflare bypass.
- **High-Capacity Thread Pooling:** Each concurrent worker thread now mounts an isolated `HTTPAdapter` with `pool_connections=10` and `pool_maxsize=25` to prevent socket starvation under aggressive multi-threading.

### Changed
- **Robust Log Rotation:** Converted standard `--debug` output file logging into a thread-safe rolling handler limited to 10MB across a 3-file automated backup queue.
- **Lowered Version Constraints:** Dropped strict minimal environment build constraints for standard tracking packages to increase backwards execution compatibility.

### Removed
- **Dead Dependency Purge:** Wiped old manual layout coloring modules (`colorama`) and redundant sub-packages (`urllib3`) from the explicit requirements registry.
- **Lenient Verification Loops:** Permanently deleted the unsafe number-only post-upload verification layer to eliminate platform ingestion false-positives.

### Fixed
- **Anti-Bot Scraping Integrity:** Hardened verification tracking to strictly demand absolute matches against live Session Group IDs or Scanlator Names, completely blocking nameless automated site rips from hijacking clean upload batches.
