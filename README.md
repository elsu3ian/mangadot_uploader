# MangaDot.net Batch Uploader

A multi-threaded, session-cloning batch uploader for [MangaDot.net](https://mangadot.net).  
This tool automatically extracts your session cookies directly from your web browser and dynamically spoofs your exact User-Agent to natively bypass Cloudflare. Uploads are handled via the resumable TUS protocol in 5MB chunks with optional proxy tunneling.

## Features

- **No Manual Cookies Needed:** Automatically extracts your active MangaDot session from Chrome, Firefox, Brave, Edge, Opera, Vivaldi, or Zen.
- **Auto-Scan Login:** Scans every supported browser for a valid MangaDot session on startup and logs in with the first one it finds — no need to pick a browser up front.
- **CDP Fallback for Chromium Browsers:** If Chrome, Edge, Brave, Vivaldi, or Opera's encrypted cookie store blocks direct extraction, a Chrome DevTools Protocol mode launches an isolated debug profile and reads the session over a WebSocket connection instead.
- **Auto-Dependency Installer:** Detects missing or outdated packages on startup and installs them automatically — no manual `pip` setup required.
- **TUS Resumability:** True resumable uploads. If your internet drops on a 200MB volume, it resumes exactly where it left off, including HEAD-based offset recovery for partial-chunk conflicts (HTTP 409).
- **Concurrent Uploads:** Upload multiple chapters at the same time (up to 30 threads), sharing one pooled, high-capacity connection pool across the whole run.
- **Bulletproof Retries:** Handles 502/503/429 Cloudflare and server errors gracefully, with abort-aware retry waits so `Ctrl+C` lands immediately instead of after the current backoff.
- **Volume & Chapter Support:** Automatically formats titles and numbers properly (e.g., `Vol. 1`, `Chapter 12`), with automatic drift correction when chapter numbers and episode labels disagree within a batch.
- **Dynamic Title Picker:** Auto-detect naming presents a labeled picker of candidate titles (full, without episode/season/chapter label, bare, minimal) built from each filename's structure, memoized per filename "shape" across the batch.
- **Live Terminal Dashboard:** Full `rich`-powered interactive UI with animated progress bars, cover art rendering, and real-time speed/ETA.
- **Inline Cover Art:** Renders manga cover art directly in your terminal during confirmation and the final upload summary (requires `chafa`).
- **Bracket Group Detection:** Automatically extracts scanlator release groups from `[Bracket]` tags in filenames, with intelligent filtering of technical metadata tags (e.g., `[1080p]`).
- **Mixed-Group Batching:** Chapters with different release groups in the same folder are automatically mapped to their respective group profiles in a single run, with a manual Group-ID fallback if a name can't be resolved via search.
- **Persistent Preferences:** Remembers your last-used library directory across sessions via `~/.mangadot_uploader.json`.
- **Dynamic User-Agent Spoofing:** Queries your local registry, plist, or CLI to build a User-Agent string from your actual installed browser version, cached in `~/.mangadot_uploader.json` to skip repeated lookups.
- **Parallel Processing Safety:** Dynamic error logging with rotating file support allows multiple instances to run simultaneously without log conflicts.
- **Advanced Naming:** Custom regex extraction and renaming modes for messy filenames.
- **Optional Routing Proxy:** Supports passing a custom network tunnel directly via the command line to cleanly bypass restrictive regional ISPs or server-side IP blocks.

## The Two Versions

Both scripts run on the exact same core engine and contain identical bug fixes and network logic. The only difference is the terminal rendering methodology: `mangadot.py` uses the modern `rich`-powered interactive dashboard with live progress bars and inline cover art, while `mangadot_v1.1.3.py` uses the older manual ANSI console logger. Functionally they upload the same way — pick whichever interface you prefer.

## Repository Structure

- **`mangadot.py`** — The main production release (v1.3.0). It features the full interactive `rich` dashboard, live progress bars, automated dependency checks, and the hardened network layer.
- **`mangadot_v1.1.3.py`** — An archived, legacy backup of the stable v1.1.3 build. It uses the old manual ANSI console logger and lacks the advanced v1.2.x automation features, preserved strictly for regression testing.

## Prerequisites

- **Python 3.12** (the scripts are built specifically for 3.12).
- You must be **logged in** to [MangaDot.net](https://mangadot.net) on your web browser — Chrome, Firefox, Brave, Edge, Opera, Vivaldi, and Zen are all supported.
- **`chafa`** *(optional)* — Enables inline cover art rendering in the terminal. Install instructions are shown at startup if missing.

## Installation

1. Clone the repository:

```bash
git clone https://github.com/elsu3ian/mangadot_uploader.git
cd mangadot_uploader
```

2. Install the required dependencies:

```bash
pip install --upgrade requests rookiepy questionary rich websocket-client
```

> **Note:** As of v1.2.0, the script also auto-installs missing or outdated packages on launch. Manual installation is only necessary for the very first run.

3. Ensure your browser is completely **closed** before running the script so it can successfully extract your session cookies — unless you're using the **CDP mode** for a Chromium browser (see [Troubleshooting Cookies](#troubleshooting-cookies-windows) below), which launches its own isolated debug profile instead.

4. *(Optional)* Install `chafa` for inline cover art:

   | Platform | Command |
   | -------- | ------- |
   | Windows  | `winget install hpjansson.Chafa` |
   | macOS    | `brew install chafa` |
   | Linux    | `sudo apt install chafa` |

## Usage

1. Put your `.cbz` or `.zip` files into a dedicated folder. Ensure your files are named reasonably, e.g., `Chapter 1 - The Beginning.cbz` or `[GroupName] Volume 2.cbz`.

2. Run your preferred version of the script:

```bash
py -3.12 mangadot.py
```

or

```bash
py -3.12 mangadot_v1.1.3.py
```

3. The script automatically scans all your installed browsers for a valid MangaDot session and logs in with the first one it finds. If none succeed, you'll get a manual picker (including a CDP option for Chromium browsers — see [Troubleshooting Cookies](#troubleshooting-cookies-windows) below). From there, follow the on-screen prompts to search for the target manga, assign scanlator groups, and start the upload.

## Advanced Usage (Command Line Flags)

| Flag | Description |
|---|---|
| `-h` | Shows the help menu with all available arguments. |
| `--dry-run` | Scans your directory, parses filenames, and flags missing chapters without uploading anything. |
| `--debug` | Dumps all HTTP traffic to `api_requests.log` using a rotating 10MB file system (3-file backup limit). |
| `--library <path>` | Opens the interactive manga picker directly inside your parent library folder instead of typing a path manually. |
| `--verify-timeout <seconds>` | Overrides how long the script waits for the server to confirm a successful upload before marking it as timed out (default: 60 seconds). Must be a positive integer. |
| `--proxy <url>` | *(Optional)* Tunnel all HTTP/HTTPS traffic through a specific custom proxy server to bypass regional ISP restrictions or server-side Cloudflare blocks. |
| `--proxy-no-verify` | *(Optional)* Disables SSL certificate verification. Use only if your proxy actively intercepts TLS traffic (MITM). |

## Troubleshooting Cookies (Windows)

If you are using Chrome, Edge, Brave, Vivaldi, or Opera, their encrypted cookie stores often block direct extraction outright (not just on v130+ with elevated privileges). If direct extraction fails or you'd rather not run as Administrator, select that browser's **`(CDP)`** option from the manual browser picker instead — it launches an isolated debug profile for that browser and reads your session over its DevTools Protocol port, sidestepping the encrypted store entirely. Zen and Firefox are read directly from disk and don't need CDP or elevated privileges.

## Log Files

If any uploads fail permanently, the script will generate a timestamped file (e.g., `failed_manga_{id}_{datetime}.txt`) listing the chapters that didn't go through. This allows you to run multiple terminal tabs without conflicts.

Detailed HTTP request data is not saved by default to save disk space, but can be enabled by running the script with the `--debug` flag.

## Patch Notes

### v1.3.0

**🔑 Browser & Session Handling**
- **Zen Browser Support:** Session cookies can now be read directly from Zen's Gecko-based profile store, with automatic profile discovery and a safe fallback copy if the live database is locked.
- **CDP Fallback for Chromium Browsers:** Chrome, Edge, Brave, Vivaldi, and Opera now have a `(CDP)` mode that launches an isolated debug profile and reads your session over a WebSocket connection, bypassing the encrypted cookie stores that normally block direct extraction from these browsers.
- **Auto-Scan Login:** The uploader now automatically scans every supported browser for a valid MangaDot session on startup instead of defaulting to one browser, stopping at the first successful match.

**🏷️ Smarter Naming**
- **Dynamic Title Picker:** Auto-detect naming now always shows a labeled picker of candidate titles (full, without episode/season/chapter label, bare, minimal) built dynamically from each filename's structure, and remembers your choice per detected filename "shape" so you're not asked twice for the same layout.
- **Episode/Chapter Drift Correction:** Chapter numbers and episode labels that disagree within a batch are now reconciled and interpolated instead of one silently overriding the other.
- **Group Detection Across Mixed Batches:** Filename group-tag scanning now collects every unique group name seen in the folder instead of only the single most common one.
- **Manual Group-ID Fallback:** If a group name can't be resolved via search, you can now type its numeric MangaDot Group ID directly instead of losing that mapping.

**⚡ Performance & Reliability**
- **Higher Thread Ceiling:** Parallel uploads raised from 1–10 (default 3) to 1–30 (default 5), with an on-screen heads-up about Cloudflare rate-limiting at high thread counts.
- **Shared Connection Pool:** Upload workers now share one pooled session for the whole run instead of opening and closing a new one per chunk.
- **Ghost Chapter Verification Pagination:** Post-upload verification now pages through the server's full chapter/volume listing instead of only checking the first page.
- **Interruptible Retries:** Retry and verification waits now check for abort every 100ms, so `Ctrl+C` and session-expiry aborts take effect immediately instead of waiting out the current backoff.
- **TUS Offset Recovery:** Falls back to an explicit `HEAD` offset check if the server confirms a chunk without returning its new offset.
- **Natural Sort Fix:** Numeric sorting no longer misreads a filename separator hyphen (e.g. `Chapter-5`) as a negative number.

**🐛 Fixes**
- **Unverified-Upload Warning:** Files with no resolvable group now upload with a clear `⚠️ Uploaded (Unverified — no group)` status instead of the generic success label.
- **Stale CDP Process Safety:** Verifies a tracked PID still belongs to the expected browser before killing it when relaunching CDP mode.
- **`--verify-timeout` Validation:** Now requires a positive integer instead of silently accepting invalid values.
- Removed a dead, unused `ctypes` import.

### v1.2.3

**🛡️ Ghost Chapter & Verification Hardening**
- **Ownership-Aware Labeling:** The uploader now resolves your MangaDot user ID at login and compares it against the existing chapter's uploader, so duplicates are correctly labeled `✅ Already Uploaded` (yours) vs. `✅ Already Exists` (someone else's).
- **Create-Conflict Verification:** An HTTP 409 on the initial upload call (chapter already exists) no longer auto-succeeds — it now runs through the same Ghost Chapter verification as a normal upload before being accepted.
- **Case-Insensitive Scanlator Matching:** Scanlator name verification now ignores capitalization differences to reduce false-negative ghost-chapter flags.
- **Verification Concurrency Cap:** Limited simultaneous server-side verification polling to 3 in-flight requests, easing API load on large batches.

**🔍 Search & Group Matching**
- **Fuzzy Group Search:** Scanlator group lookups now automatically retry with camelCase-split and progressively spaced name variations to find groups that don't match an exact-string search.
- **Proper Query Encoding:** Manga and group searches now use safe URL parameter encoding instead of raw string concatenation, fixing failures on special characters.

**🐛 Mixed-Group & Stability Fixes**
- **Mixed-Group Mapping Fix:** Files without an explicit group assignment in a mixed-group batch no longer incorrectly inherit the combined group list from other resolved groups in the same run.
- **Localized API Field Handling:** Manga title, status, description, and alt-titles are now safely unpacked when MangaDot returns them as localized objects, preventing blank or broken confirmation screens.
- **Batch Completion Safety:** The batch-complete signal is now skipped if a batch chunk had zero successful uploads.
- **Safer ID Parsing:** Manga ID and Group ID prompts use proper integer parsing instead of `.isdigit()`, avoiding crashes on malformed input.
- **Sub-1KB File Sizes:** Files smaller than 1KB now display in bytes (e.g. `512 B`) instead of a misleading fractional KB value like `0.05 KB`.
- **Reworked Proxy Health Check:** Swapped the Cloudflare DNS probe for a dedicated no-content endpoint and ensured `--proxy-no-verify` is actually honored during the health check itself.

**⚡ Performance & UX**
- **Persistent User-Agent Cache:** Browser/User-Agent detection results are now cached in `~/.mangadot_uploader.json`, skipping repeated registry/plist/CLI lookups on subsequent runs.
- **Faster Directory Scans:** Switched to `os.scandir` for directory traversal, with zero-byte file detection and hardened corrupt-archive handling.
- **Cleaner Worker Sessions:** Each upload thread now manages its own `requests.Session` as a context manager and correctly inherits SSL verification settings.
- **Genres Display:** Added a dedicated "Genres" line to the manga confirmation screen, alongside "Tags".
- **Graceful Ctrl+C Feedback:** Added an on-screen status message while in-flight uploads finish during an abort.

### v1.2.2

**🛡️ Security & Routing**
- **Proxy Tunneling:** Added `--proxy` and `--proxy-no-verify` CLI flags to route traffic through custom network tunnels and bypass MITM SSL errors.
- **Smart Health Check:** Implemented an initial pre-flight proxy check against `1.1.1.1` with a spoofed User-Agent to catch obviously dead proxies before a batch starts.

**🐛 Critical Bug Fixes**
- **Locale Crash Prevented:** Fixed a `UnicodeDecodeError` in the Chromium CLI version checker on non-UTF-8 Linux distributions.
- **Verification Hang Resolved:** Bypassed the 60-second verification timeout loop when uploading strictly under a Scanlator Name without a Group ID.
- **Cross-Platform Pathing:** Normalized all filepath dictionary keys to prevent mixed-group assignments from failing due to Windows/Linux slash direction mismatches.

**⚡ Performance & UX**
- **Graceful Aborts:** Added explicit thread cancellation on `KeyboardInterrupt` (`Ctrl+C`) to instantly kill the executor without traceback vomits.
- **API Schema Detection:** Added a proactive warning trigger if MangaDot changes its obfuscated search payload structure.
- **Windows Temp Locking:** Trapped OS-level file locking exceptions during `chafa` image rendering to prevent random crashes.
- **UI Formatting:** Reworked human-readable file size display to use tiered GB/MB/KB units instead of a flat KB-only format.

### v1.2.0

**🚀 Modern Interactive Terminal Dashboard**
- **Rich UI Engine:** Ditched manual ANSI string manipulation and the old `colorama` setup. The entire application now uses `rich` and `questionary` for interactive multi-column tables, clean selectors, and a real-time layout.
- **Auto-Dependency Installer:** The script now detects missing or outdated Python packages (`requests`, `rookiepy`, `questionary`, `rich`) and installs them automatically on launch, eliminating manual environment setup friction.
- **Inline Cover Art:** Integrated native image rendering using `chafa`. If installed, the uploader displays high-fidelity cover art during manga confirmation and inside the final upload summary.

**🔍 Automated Release Group & Bracket Parsing**
- **Bracket Detection Logic:** Automatically extracts scanlator release groups from `[Bracket]` tags in filenames while intelligently ignoring technical asset metrics such as resolution tags (`[1080p]`).
- **Mixed-Group Batching:** Rewrote the payload structure to support mixed-group chapters in a single execution queue. Different chapters inside the same folder can now map to entirely separate group profiles automatically.

**🛡️ Hardened Network Layer & TUS Protocol Resilience**
- **Strict Server-Side Verification:** Completely eliminated lenient verification fallbacks. The script now strictly enforces Group ID or Scanlator Name matches during post-upload validation, ensuring nameless bot scrapes are ignored and only your files are counted.
- **HTTP 409 Conflict Resolution:** Added a `HEAD` request check (`_tus_offset`) to handle byte mismatch conflicts. If an upload chunk partially lands during a network hiccup, the script queries the server's true offset and resumes instead of failing.
- **Advanced User-Agent Spoofing:** Added an automated registry, plist, and CLI probe pipeline to look up your actual installed browser version, generating accurate User-Agent signatures for reliable Cloudflare bypass.
- **High-Capacity Thread Pooling:** Every concurrent worker thread now mounts an isolated `HTTPAdapter` with `pool_connections=10` and `pool_maxsize=25` to prevent socket starvation under aggressive multi-threading.

**⚙️ Workspace Optimization**
- **Persistent Preferences:** Added a local configuration file (`~/.mangadot_uploader.json`) that automatically remembers your root library directory and layout history across terminal sessions. Pass `--library <path>` to set or override it.
- **Robust Logging:** Revamped `--debug` output to use a rotating file handler capped at 10MB with a 3-file circular backup limit.

### v1.1.5 and earlier

**Thread Safety:** Isolated `requests.Session` cookie jars for individual TUS worker threads, eliminating race conditions that previously corrupted headers during concurrent file uploads.

**Hang Prevention:** Prioritized authorization validation states and explicitly caught `SessionExpiredError` exceptions to prevent the verification loop from silently hanging for 60 seconds upon token expiration.

**Batch Init Auth Recovery:** Added an explicit `SessionExpiredError` catch before the broad exception handler in the batch init block, so a 401/403 correctly triggers session recovery instead of silently marking all chapters as failed.

**Ghost Chapter Fix:** Removed an erroneous unconditional fallback branch in scanlator verification that previously set `found = True` regardless of whether the server actually matched the scanlator name, defeating Ghost Chapter Prevention for standalone scanlators entirely.

**Disk Optimization:** Prevented O(n²) redundant file pointer drift by only triggering file seeks when the pointer is out of alignment.

**Terminal Safety:** Wrapped the terminal line-wrapping sequence (`\033[?7h`) inside an `atexit` handler so the console safely restores itself even during sudden interpreter crashes.

**UI Freeze Fix:** Split the generic connection timeout into granular `(10, 45)` second connect/read timeouts during batch initialization to prevent dead servers from permanently freezing the script.

**Memory Leaks Plugged:** Instantiated fresh `threading.Event()` abort objects directly inside the orchestration loop to prevent retry state leakage between expired sessions.

**Data Integrity:** Replaced volatile string comparisons with `math.isclose` absolute delta tolerances for accurate floating-point verification of chapter numbers.

**Log Scrubbing:** Broadened the ANSI sanitization regex to cover all escape sequences, ensuring cursor movement and mode-set codes are also scrubbed from `api_requests.log`.

**Render Race Fix** *(basic only)*: Snapshotted all shared state under the lock at the start of each render cycle, eliminating torn reads of the progress table at high thread counts.

**Dead Code Removal** *(ui only)*: Removed manual speed/ETA tracking variables in the upload worker that were computed every chunk but silently ignored by the rich renderer.

## License

Distributed under the MIT License. See [LICENSE](LICENSE) for more information.
