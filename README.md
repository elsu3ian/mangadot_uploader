# MangaDot.net Batch Uploader

A multi-threaded, session-cloning batch uploader for [MangaDot.net](https://mangadot.net).  
This tool automatically extracts your session cookies directly from your web browser to natively bypass Cloudflare, and securely uploads massive batches of `.cbz` or `.zip` chapters/volumes using the resumable TUS protocol.

## Features

- **No Manual Cookies Needed:** Automatically extracts your active MangaDot session from Chrome, Firefox, Brave, Edge, Opera, or Vivaldi.
- **TUS Resumability:** True resumable uploads. If your internet drops on a 200MB volume, it resumes exactly where it left off.
- **Concurrent Uploads:** Upload multiple chapters at the same time (up to 10 threads).
- **Bulletproof Retries:** Handles 502/503/429 Cloudflare and server errors gracefully.
- **Volume & Chapter Support:** Automatically formats titles and numbers properly (e.g., `Vol. 1`, `Chapter 12`).
- **Live Terminal UI:** Beautiful progress bars and status updates in the console.
- **Parallel Processing Safety:** Dynamic error logging allows multiple instances of the script to run simultaneously without overwriting data.
- **Advanced Naming:** Custom regex extraction and renaming modes for messy filenames.

## The Two Versions

Both scripts run on the exact same core engine and contain identical bug fixes and network logic. The only difference is the terminal rendering methodology:

- **`mangadot_ui.py`** — The advanced UI build. Uses `rich.progress` and `rich.live` to render a flicker-free dashboard with animated progress bars, and natively handles dynamic transfer speed and ETA calculations via rich's built-in columns.
- **`mangadot_basic.py`** — The static UI build. Uses `rich.table` to draw a basic, static layout and manually calculates upload speeds and progress metrics in the background. Note: This version still requires the `rich` dependency to function.

## Prerequisites

- **Python 3.12** (the scripts are built specifically for 3.12).
- You must be **logged in** to [MangaDot.net](https://mangadot.net) on your web browser.

## Installation

1. Clone the repository:

```bash
git clone https://github.com/elsu3ian/mangadot_uploader.git
cd mangadot_uploader
```

2. Install the required dependencies:

```bash
pip install --upgrade requests rookiepy colorama rich
```

3. Ensure your browser is completely **closed** before running the script so it can successfully extract your session cookies.

## Usage

1. Put your `.cbz` or `.zip` files into a dedicated folder. Ensure your files are named reasonably, e.g., `Chapter 1 - The Beginning.cbz` or `Volume 2.cbz`.

2. Run your preferred version of the script:

```bash
py -3.12 mangadot_ui.py
```

or

```bash
py -3.12 mangadot_basic.py
```

3. Follow the on-screen prompts to select your browser, search for the target manga, assign scanlator groups, and start the upload!

## Advanced Usage (Command Line Flags)

- `--dry-run` : Scans your directory, parses filenames, and flags missing chapters without uploading anything.
- `--debug` : Dumps all HTTP traffic to `api_requests.log` for troubleshooting.
- `--verify-timeout SECONDS` : Overrides how long the script waits for the server to confirm a successful upload before marking it as timed out (default: 60 seconds).

## Patch Notes & Fixes Applied

Both scripts include the following critical stability and performance fixes:

- **Thread Safety:** Isolated `requests.Session` cookie jars for individual TUS worker threads, eliminating race conditions that previously corrupted headers during concurrent file uploads.
- **Hang Prevention:** Prioritized authorization validation states and explicitly caught `SessionExpiredError` exceptions to prevent the verification loop from silently hanging for 60 seconds upon token expiration.
- **Batch Init Auth Recovery:** Added an explicit `SessionExpiredError` catch before the broad exception handler in the batch init block, so a 401/403 that surfaces as an exception correctly triggers session recovery instead of silently marking all chapters as failed.
- **Ghost Chapter Fix:** Removed an erroneous unconditional fallback branch in scanlator verification that previously set `found = True` regardless of whether the server actually matched the scanlator name, defeating Ghost Chapter Prevention for standalone scanlators entirely.
- **Disk Optimization:** Prevented O(n²) redundant file pointer drift by only triggering file seeks when the pointer is out of alignment, massively speeding up chunk processing.
- **Terminal Safety:** Wrapped the terminal line-wrapping sequence (`\033[?7h`) inside an `atexit` handler so the console layout safely restores itself even during sudden interpreter crashes.
- **UI Freeze Fix:** Split the generic connection timeout into granular `(10, 45)` second connect/read timeouts during batch initialization to prevent dead servers from permanently freezing the script.
- **Memory Leaks Plugged:** Instantiated fresh `threading.Event()` abort objects directly inside the orchestration loop to prevent retry state leakage between expired sessions.
- **Data Integrity:** Replaced volatile string comparisons with `math.isclose` absolute delta tolerances for accurate floating-point verification of chapter numbers.
- **Log Scrubbing:** Broadened the ANSI sanitization regex to cover all escape sequences (not just color codes), ensuring cursor movement and mode-set codes are also scrubbed from `api_requests.log` files.
- **Render Race Fix** *(basic only)*: Snapshotted all shared state under the lock at the start of each render cycle, eliminating torn reads of the progress table at high thread counts.
- **Dead Code Removal** *(ui only)*: Removed manual speed/ETA tracking variables in the upload worker that were being computed every chunk but silently ignored by the rich renderer, which derives both natively from byte counts.

## Troubleshooting Cookies (Windows)

If you are using Chrome or Edge v130+, they require Administrator privileges to extract cookies. Right-click your terminal and select **Run as Administrator**, or use Firefox instead.

## Log Files

If any uploads fail permanently, the script will generate a timestamped file (e.g., `failed_manga_{id}_{datetime}.txt`) listing the chapters that didn't go through. This allows you to run multiple terminal tabs without conflicts.

Detailed HTTP request data is not saved by default to save disk space, but can be enabled by running the script with the `--debug` flag.

## License

Distributed under the MIT License. See [LICENSE](LICENSE) for more information.
