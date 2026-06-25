# Changelog

All notable changes to this project will be documented in this file.

## [1.2.0] - 2026-06-25

### Added
- **Interactive UI Engine:** Integrated `rich` and `questionary` to replace the outdated manual ANSI escape sequences with an interactive terminal dashboard featuring clear drop-down picker menus.
- **Auto-Dependency Installer:** Added an automated system setup pipeline that screens for required packages on boot and runs a sub-process `pip install --upgrade` automatically if things are missing.
- **Inline Image Rendering:** Enabled automated vertical terminal cover art display strings triggered through local integrations with `chafa`.
- **Persistent Local State:** Created a automated local JSON configuration engine (`~/.mangadot_uploader.json`) to remember root manga library paths and interface histories.
- **Dynamic Group Extraction:** Built regex parsing loops to scrape scanlator names directly from filename `[Bracket]` tags while systematically parsing out resolution asset metrics.

### Changed
- **Robust Log Rotation:** Converted standard `--debug` output file logging into a thread-safe rolling handler limited to 10MB across a 3-file automated backup queue.
- **Lowered Version Constraints:** Dropped strict minimal environment build constraints for standard tracking packages to increase backwards execution compatibility.

### Removed
- **Dead Dependency Purge:** Wiped old manual layout coloring modules (`colorama`) and redundant sub-packages (`urllib3`) from the explicit requirements registry.
- **Lenient Verification Loops:** Permanently deleted the unsafe number-only post-upload verification layer to eliminate platform ingestion false-positives.

### Fixed
- **Anti-Bot Scraping Integrity:** Hardened verification tracking to strictly demand absolute matches against live Session Group IDs or Scanlator Names, completely blocking nameless automated site rips from hijacking clean upload batches.