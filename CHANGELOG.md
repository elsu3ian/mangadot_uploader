# Changelog

All notable changes to this project will be documented in this file.

## [1.2.2] - 2026-06-26

### Added
- CLI flags `--proxy` and `--proxy-no-verify` for custom network routing and SSL bypass.
- Secure Cloudflare-bypassing proxy health check routed against `1.1.1.1` to prevent false-positive failures.

### Fixed
- `UnicodeDecodeError` crash during Chromium version detection on non-UTF-8 Linux locales.
- Unnecessary 60-second verification loop hang when uploading exclusively under a Scanlator Name.
- Dictionary key lookup misses for mixed-group mapping caused by Windows vs. Linux slash direction mismatches.

### Changed
- Added explicit thread cancellation on `KeyboardInterrupt` for clean terminal exits.
- Implemented proactive warning triggers for undetectable API search schema changes.
- Added exception handling for Windows temp file locking during `chafa` rendering to prevent execution crashes.
- Fixed UI file size formatting precision to properly display files under 1MB.

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
