# MangaDot Uploader

A multi-threaded, session-cloning batch uploader for [MangaDot.net](https://mangadot.net) — available as a **terminal app** (`mangadot.py`) or a **standalone Windows GUI app**.

Both automatically extract your session cookies directly from your web browser and dynamically spoof your exact User-Agent to natively bypass Cloudflare. Uploads are handled via the resumable TUS protocol in 5MB chunks, with a review pass to fix titles/numbers before anything goes live and optional proxy tunneling for restrictive networks.

## Which one do I want?

| | GUI App | CLI (`mangadot.py`) |
|---|---|---|
| Best for | Most users, especially on Windows | Power users, scripting, headless/remote use, macOS/Linux |
| Install | Download and run the `.exe`, nothing else needed | Requires Python 3.12 |
| Interface | Native desktop windows, tables, and dialogs | Interactive terminal dashboard (`rich` + `questionary`) |
| Automation | — | `--dry-run`, `--debug`, `--library`, proxy flags, etc. |

They share the exact same login, parsing, verification, and upload engine underneath — pick whichever interface you prefer, or use both.

## Features

- **No Manual Cookies Needed:** Automatically extracts your active MangaDot session from Chrome, Firefox, Brave, Edge, Opera, Vivaldi, or Zen.
- **Auto-Scan Login:** Scans every supported browser for a valid MangaDot session on startup and logs in with the first one it finds — no need to pick a browser up front.
- **CDP Fallback for Chromium Browsers:** If Chrome, Edge, Brave, Vivaldi, or Opera's encrypted cookie store blocks direct extraction, a Chrome DevTools Protocol mode launches an isolated debug profile and reads the session over a WebSocket connection instead.
- **TUS Resumability:** True resumable uploads. If your internet drops on a 200MB volume, it resumes exactly where it left off, including HEAD-based offset recovery for partial-chunk conflicts (HTTP 409).
- **Concurrent Uploads:** Upload multiple chapters at the same time (up to 30 threads in the CLI), sharing one pooled, high-capacity connection across the whole run.
- **Bulletproof Retries:** Handles 502/503/429 Cloudflare and server errors gracefully, with abort-aware retry waits so cancelling lands immediately instead of after the current backoff.
- **Volume & Chapter Support:** Automatically formats titles and numbers properly (e.g., `Vol. 1`, `Chapter 12`), with automatic drift correction when chapter numbers and episode labels disagree within a batch.
- **Dynamic Title Picker:** Auto-detect naming presents a labeled picker of candidate titles (full, without episode/season/chapter label, bare, minimal) built from each filename's structure, memoized per filename "shape" across the batch.
- **Homoglyph-Safe Parsing:** Filenames with look-alike Cyrillic/Greek characters (e.g. a Cyrillic С instead of a Latin C) still match chapter/volume labels correctly instead of silently failing to parse.
- **Title & Number Review Pass:** Before anything uploads, review every detected title and number in one place — bulk find/replace across all titles (with a live preview), scoped find/replace by number range or a single file, redo the auto-detected title for a whole group at once, and manually override any file's number, with duplicate warnings.
- **Bracket Group Detection:** Automatically extracts scanlator release groups from `[Bracket]` tags in filenames, with intelligent filtering of technical metadata tags (e.g., `[1080p]`).
- **Mixed-Group Batching:** Chapters with different release groups in the same folder are automatically mapped to their respective group profiles in a single run, with a manual Group-ID fallback if a name can't be resolved via search.
- **Ownership-Aware Duplicate Detection:** Distinguishes your own prior uploads from someone else's when a chapter already exists, instead of lumping every duplicate together.
- **Persistent Preferences:** Remembers your last-used library directory and cached User-Agent across sessions.
- **Optional Routing Proxy:** Supports tunneling traffic through a custom proxy to bypass restrictive regional ISPs or server-side IP blocks.

### CLI-specific

- **Live Terminal Dashboard:** Full `rich`-powered interactive UI with animated progress bars, cover art rendering, and real-time speed/ETA.
- **Inline Cover Art:** Renders manga cover art directly in your terminal during confirmation and the final upload summary (requires `chafa`).
- **Auto-Dependency Installer:** Detects missing or outdated packages on startup and installs them automatically, aware of whether it's running inside a virtual environment.
- **Advanced Naming Mode:** Custom regex extraction and bracket/parenthesis-group stripping as combinable toggles for messy filenames.
- **Scriptable Flags:** `--dry-run`, `--debug`, `--library`, `--verify-timeout`, `--proxy`, `--proxy-no-verify` — see [Advanced Usage](#advanced-usage-command-line-flags).

### GUI-specific

- **Native Desktop App:** No terminal, no Python — download one `.exe` and run it.
- **Editable Review Table:** Sort, rename, and renumber detected files directly in a table, with duplicate numbers highlighted and a right-click "Remove word/phrase" dialog that shows a before/after preview before applying.
- **Manga Lookup by ID, URL, or Search:** Paste a MangaDot manga ID or URL, or search by title, directly from the picker screen.
- **Upload Summary with Cover Art:** After uploading, see the manga's cover, genres, and description, plus a table of every chapter you just uploaded — double-click any row to open it on MangaDot.
- **Settings Dialog:** Configure a proxy, disable SSL verification, or enable debug logging from a dialog at startup — no flags to remember.

## Repository Structure

- **`mangadot.py`** — The standalone, feature-complete terminal CLI uploader with interactive `rich` dashboards, live speed/ETA meters, automated dependency management, and lossless image optimization.
- **`app_bundle/`** — The modular PySide6 desktop GUI application source tree, featuring multi-screen workflows, group attribution pickers, title review dialogs, and built-in upload history.
- **`Setup_Runtime.bat`** — Automated 1-click runtime & dependency provisioner: downloads portable Python 3.12 (if no Python is found on your PC) and installs all dependencies into an isolated local folder.
- **`Start MangaDot GUI.bat`** — 1-click launcher for the desktop GUI (with automatic runtime provisioning on first run).
- **`Run MangaDot Uploader.bat`** — Smart launcher for the CLI (with automatic runtime provisioning on first run).

## Prerequisites

- **GUI App:** Windows only. No Python or dependencies required.
- **CLI:** **Python 3.12** (built specifically for 3.12).
- Either way, you must be **logged in** to [MangaDot.net](https://mangadot.net) in your web browser — Chrome, Firefox, Brave, Edge, Opera, Vivaldi, and Zen are all supported.
- **`chafa`** *(CLI only, optional)* — Enables inline cover art rendering in the terminal. Install instructions are shown at startup if missing.

## Installation & Setup

### ⚡ 1-Click Zero-Config Setup (Windows — Recommended)

No Python installed? No problem. You don't need administrator permissions or manual Python installs:

1. Clone or download this repository.
2. Double-click **`Setup_Runtime.bat`** (or simply double-click **`Start MangaDot GUI.bat`** or **`Run MangaDot Uploader.bat`**).
3. The script will automatically detect your environment:
   - If Python 3.12+ is installed, it sets up an isolated `.venv` and installs all dependencies.
   - If **no Python** is installed on your computer, it downloads an official standalone Python 3.12 runtime (~11 MB) into a local `runtime/` folder, bootstraps pip, and installs all dependencies automatically.
4. Launch the GUI or CLI anytime with 1 click!

### Manual Installation (Power Users / macOS / Linux)

1. Clone the repository:

```bash
git clone https://github.com/elsu3ian/mangadot_uploader.git
cd mangadot_uploader
```

2. Install the required dependencies:

```bash
# For CLI only:
pip install -r requirements.txt

# For both GUI and CLI:
pip install -r requirements.txt -r app_bundle/requirements.txt
```

> **Note:** When running via Astral's `uv`, zero setup is needed — just run `uv run mangadot.py`.

3. Ensure your browser is completely **closed** before running the script so it can successfully extract your session cookies — unless you're using **CDP mode** for a Chromium browser (see [Troubleshooting Cookies](#troubleshooting-cookies-windows) below), which launches its own isolated debug profile instead.

4. *(Optional)* Install `chafa` for inline cover art:

   | Platform | Command |
   | -------- | ------- |
   | Windows  | `winget install hpjansson.Chafa` |
   | macOS    | `brew install chafa` |
   | Linux    | `sudo apt install chafa` |

## Usage

1. Put your `.cbz` or `.zip` files into a dedicated folder. Ensure your files are named reasonably, e.g., `Chapter 1 - The Beginning.cbz` or `[GroupName] Volume 2.cbz`.

2. **GUI:** Double-click `Start MangaDot GUI.bat` (or run `python app_bundle/main.py`), log in, then pick your folder and target manga from the on-screen picker.

   **CLI:** Double-click `Run MangaDot Uploader.bat`, or run via terminal:

   ```bash
   uv run mangadot.py
   # or
   py -3.12 mangadot.py
   ```

3. Both scan every installed browser for a valid MangaDot session automatically and log in with the first one that works. If none succeed, you'll get a manual picker (including a CDP option for Chromium browsers — see [Troubleshooting Cookies](#troubleshooting-cookies-windows) below).

4. Assign scanlator groups, then review the detected titles and numbers before anything uploads — fix a typo, renumber a misdetected file, or bulk-clean titles across the whole batch. Once it looks right, start the upload.

## Advanced Usage (Command Line Flags)

*(CLI only — the GUI app exposes these same options through its Settings dialog instead.)*

| Flag | Description |
|---|---|
| `-h` | Shows the help menu with all available arguments. |
| `--dry-run` | Scans your directory, parses filenames, and flags missing chapters without uploading anything. |
| `--debug` | Dumps all HTTP traffic to `api_requests.log` using a rotating 10MB file system (3-file backup limit). |
| `--library <path>` | Opens the interactive manga picker directly inside your parent library folder instead of typing a path manually. |
| `--verify-timeout <seconds>` | Overrides how long the script waits for the server to confirm a successful upload before marking it as timed out (default: 60 seconds). Must be a positive integer. |
| `--skip-verification` | *(Default: true)* Skips post-upload verification polling because MangaDot's backend converts images asynchronously in a post-finish hook. Eliminates false-positive timeouts. |
| `--verify` | Enables legacy synchronous post-upload verification polling. |
| `--proxy <url>` | *(Optional)* Tunnel all HTTP/HTTPS traffic through a specific custom proxy server to bypass regional ISP restrictions or server-side Cloudflare blocks. |
| `--proxy-no-verify` | *(Optional)* Disables SSL certificate verification. Use only if your proxy actively intercepts TLS traffic (MITM). |

## Troubleshooting Cookies (Windows)

If you are using Chrome, Edge, Brave, Vivaldi, or Opera, their encrypted cookie stores often block direct extraction outright (not just on v130+ with elevated privileges). If direct extraction fails or you'd rather not run as Administrator, select that browser's **CDP** option from the browser picker instead — it launches an isolated debug profile for that browser and reads your session over its DevTools Protocol port, sidestepping the encrypted store entirely. Zen and Firefox are read directly from disk and don't need CDP or elevated privileges.

## Log Files

If any uploads fail permanently, the CLI will generate a timestamped file (e.g., `failed_manga_{id}_{datetime}.txt`) listing the chapters that didn't go through, so you can run multiple terminal tabs without conflicts.

Detailed HTTP request data is not saved by default to save disk space, but can be enabled with the `--debug` flag (CLI) or the debug logging checkbox in the GUI's startup Settings dialog.

## Patch Notes

See [CHANGELOG.md](CHANGELOG.md) for the full version history.

## 🤝 Credits & Acknowledgments

This project began as a fork of the original single-file CLI uploader created by [@darwin-256](https://github.com/darwin-256/mangadot_uploader). Their original script established the core approach this tool still builds on — browser-cookie session cloning, User-Agent spoofing to bypass Cloudflare, and resumable chunked uploads over the TUS protocol.

Since then, the project has been substantially rewritten and extended: a full interactive terminal dashboard, mixed-group batching, ghost-chapter verification, homoglyph-safe filename parsing, an interactive title/number review pass, CDP-based cookie extraction for Chromium browsers, and — new in v2.0.0 — a standalone desktop GUI application, among many other changes documented in the [changelog](CHANGELOG.md).

## License

Distributed under the MIT License. See [LICENSE](LICENSE) for more information.
