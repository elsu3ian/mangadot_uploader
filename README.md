# MangaDot.net Batch Uploader

A multi-threaded, session-cloning batch uploader for [MangaDot.net](https://mangadot.net).  
This tool automatically extracts your session cookies directly from your web browser to natively bypass Cloudflare, and securely uploads massive batches of `.cbz` or `.zip` chapters/volumes using the resumable TUS protocol.

## Features

- **No Manual Cookies Needed:** Automatically extracts your active MangaDot session from Chrome, Firefox, Brave, Edge, Opera, or Vivaldi.
- **Auto-Dependency Installer:** Detects missing or outdated packages on startup and installs them automatically — no manual `pip` setup required.
- **TUS Resumability:** True resumable uploads. If your internet drops on a 200MB volume, it resumes exactly where it left off, including HEAD-based offset recovery for partial-chunk conflicts (HTTP 409).
- **Concurrent Uploads:** Upload multiple chapters at the same time (up to 10 threads), each with an isolated, high-capacity connection pool.
- **Bulletproof Retries:** Handles 502/503/429 Cloudflare and server errors gracefully.
- **Volume & Chapter Support:** Automatically formats titles and numbers properly (e.g., `Vol. 1`, `Chapter 12`).
- **Live Terminal Dashboard:** Full `rich`-powered interactive UI with animated progress bars, cover art rendering, and real-time speed/ETA.
- **Inline Cover Art:** Renders manga cover art directly in your terminal during confirmation and the final upload summary (requires `chafa`).
- **Bracket Group Detection:** Automatically extracts scanlator release groups from `[Bracket]` tags in filenames, with intelligent filtering of technical metadata tags (e.g., `[1080p]`).
- **Mixed-Group Batching:** Chapters with different release groups in the same folder are automatically mapped to their respective group profiles in a single run.
- **Persistent Preferences:** Remembers your last-used library directory across sessions via `~/.mangadot_uploader.json`.
- **Dynamic User-Agent Spoofing:** Queries your local registry, plist, or CLI to build a User-Agent string from your actual installed browser version.
- **Parallel Processing Safety:** Dynamic error logging with rotating file support allows multiple instances to run simultaneously without log conflicts.
- **Advanced Naming:** Custom regex extraction and renaming modes for messy filenames.

## The Two Versions

Both scripts run on the exact same core engine and contain identical bug fixes and network logic. The only difference is the terminal rendering methodology:

- **`mangadot_ui.py`** — The advanced UI build. Uses `rich.progress` and `rich.live` to render a flicker-free dashboard with animated progress bars, and natively handles dynamic transfer speed and ETA calculations via rich's built-in columns.
- **`mangadot_basic.py`** — The static UI build. Uses `rich.table` to draw a basic, static layout and manually calculates upload speeds and progress metrics in the background. Note: This version still requires the `rich` dependency to function.

## Prerequisites

- **Python 3.12** (the scripts are built specifically for 3.12).
- You must be **logged in** to [MangaDot.net](https://mangadot.net) on your web browser.
- **`chafa`** *(optional)* — Enables inline cover art rendering in the terminal. Install instructions are shown at startup if missing.

## Installation

1. Clone the repository:

```bash
git clone https://github.com/elsu3ian/mangadot_uploader.git
cd mangadot_uploader
```

2. Install the required dependencies:

```bash
pip install --upgrade requests rookiepy questionary rich
```

> **Note:** As of v1.2.0, the script also auto-installs missing or outdated packages on launch. Manual installation is only necessary for the very first run.

3. Ensure your browser is completely **closed** before running the script so it can successfully extract your session cookies.

4. *(Optional)* Install `chafa` for inline cover art:

| Platform | Command |
|---|---|
| Windows | `winget install hpjansson.Chafa` |
| macOS | `brew install chafa` |
| Linux | `sudo apt install chafa` |

## Usage

1. Put your `.cbz` or `.zip` files into a dedicated folder. Ensure your files are named reasonably, e.g., `Chapter 1 - The Beginning.cbz` or `[GroupName] Volume 2.cbz`.

2. Run your preferred version of the script:

```bash
py -3.12 mangadot_ui.py
```

or

```bash
py -3.12 mangadot_basic.py
```

3. Follow the on-screen prompts to select your browser, search for the target manga, assign scanlator groups, and start the upload.

## Advanced Usage (Command Line Flags)

| Flag | Description |
|---|---|
| `--dry-run` | Scans your directory, parses filenames, and flags missing chapters without uploading anything. |
| `--debug` | Dumps all HTTP traffic to `api_requests.log` using a rotating 10MB file system (3-file backup limit). |
| `--library <path>` | Opens the interactive manga picker directly inside your parent library folder instead of typing a path manually. |
| `--verify-timeout <seconds>` | Overrides how long the script waits for the server to confirm a successful upload before marking it as timed out (default: 60 seconds). |

## Troubleshooting Cookies (Windows)

If you are using Chrome or Edge v130+, they require Administrator privileges to extract cookies. Right-click your terminal and select **Run as Administrator**, or use Firefox instead.

## Log Files

If any uploads fail permanently, the script will generate a timestamped file (e.g., `failed_manga_{id}_{datetime}.txt`) listing the chapters that didn't go through. This allows you to run multiple terminal tabs without conflicts.

Detailed HTTP request data is not saved by default to save disk space, but can be enabled by running the script with the `--debug` flag.

## Patch Notes

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
