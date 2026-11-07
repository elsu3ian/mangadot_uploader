# MangaDot Uploader

A multi-threaded, session-cloning batch uploader for [MangaDot.net](https://mangadot.net), available as a standalone desktop GUI application or an interactive terminal CLI (`mangadot.py`).

Both frontends automatically extract active login cookies from your browser, handle Cloudflare verification, upload archives in 20MB TUS chunks with automatic resume, provide an interactive title/number review pass, losslessly optimize CBZ archives, and support direct MangaBaka series creation.

## Which Version Should I Use?

| Feature / Role | Desktop GUI App | Terminal CLI (`mangadot.py`) |
|:---|:---|:---|
| **Best For** | Desktop users on Windows | Power users, scripting, headless servers, macOS/Linux |
| **Install** | Download release `.zip` or launch via batch script | Run directly via `uv run mangadot.py` or `python mangadot.py` |
| **Interface** | Native multi-screen Qt windows, tables, and dialogs | Interactive terminal dashboard with live meters and spinners |
| **Automation** | Visual review grid, history viewer, settings dialog | Scriptable CLI flags (`--dry-run`, `--optimize`, `--library`) |

Both share the exact same authentication, parsing, optimization, and TUS upload engine underneath. Pick whichever interface you prefer, or use both.

## Key Features

- **Browser Session Auto-Login**: Automatically scans and extracts active MangaDot session cookies from Chrome, Firefox, Brave, Edge, Opera, Vivaldi, or Zen (no manual cookie copying required).
- **CDP Fallback for Chromium Browsers**: When Windows encrypted cookie stores block direct extraction on Chromium browsers (Chrome, Edge, Brave, Opera, Vivaldi), CDP mode launches an isolated debug profile to retrieve the session over WebSocket without administrator privileges.
- **20MB Native TUS Resumable Uploads**: Streams archives in 20MB chunks matching MangaDot's official web uploader (73% fewer requests than legacy 5MB chunks). If a connection drops, it automatically resyncs the server offset (`HEAD`) and resumes where it left off without re-uploading completed chunks.
- **Multi-Threaded Parallel Uploads**: Upload multiple chapters concurrently (up to 12 threads safe zone, with an optional toggle up to 90 threads in the GUI for fast connections, and up to 30 threads in the CLI).
- **Fast Upload Verification**: Verifies uploaded chapters against your member upload queue (`/api/uploads/mine`) in ~1 second, supporting `pending`, `processing`, and `approved` states without slow public chapter list pagination.
- **Asynchronous Batch Completion**: Batch closing calls execute in a background daemon thread with rate-limit pacing (2.5s minimum interval), keeping the upload queue and UI responsive.
- **Pre-Upload Title & Number Review Pass**: Inspect detected chapter/volume numbers and titles before uploading: perform bulk find-and-replace (with live previews), edit individual entries, and catch duplicate numbers with instant warnings.
- **Built-in CBZ & Image Optimizer**: Re-compresses images inside `.cbz`/`.zip` archives before uploading (or standalone via `--optimize-only`). Uses lossless mozjpeg/Pillow or bundled `pingo.exe` on Windows to reduce archive sizes by 10-40% without touching visual quality. Optional lossy modes are also available.
- **MangaBaka Integration**: Search and create new titles on MangaDot directly from MangaBaka URLs or slugs without leaving the uploader (available in both the GUI creation dialog and the CLI prompt).
- **Bracket Tag & Scanlator Attribution**: Automatically extracts group names from filename `[Bracket]` tags, filters out technical tags (e.g. `[1080p]`), maps mixed groups in a single folder, and includes a group directory search with manual ID fallback.
- **Subset & Range Selection**: Upload specific chapters instead of whole folders using interactive checkbox pickers or numeric range syntax (e.g. `1-10, 15, 20-25`).
- **Upload History & Interrupted Batch Recovery**: Tracks previous uploads with direct links to MangaDot, and automatically prompts to resume paused or interrupted upload batches on launch.
- **Homoglyph Normalization**: Automatically normalizes look-alike Cyrillic or Greek characters in filenames so titles and numbers parse correctly.
- **Custom Proxy Support**: Tunnel traffic through HTTP/SOCKS proxies with optional SSL verification bypass for restricted networks.

### GUI-Specific Features
- **Visual Review Grid**: Sort, inline-edit, rename, and renumber chapters directly in a table, with duplicate-number highlighting and right-click bulk word replacement.
- **CBZ Optimizer Screen**: Dedicated visual interface to preview compression savings, select in-place vs subfolder output, and choose lossy/lossless modes.
- **Create Manga Dialog**: Paste a MangaBaka link to autofill title, alternative titles, author, genres, and cover art, and publish the title to MangaDot in one click.
- **Upload History Dialog**: Browse all previously uploaded series and double-click any entry to view it directly on MangaDot.
- **Settings Dialog**: Configure proxies, verification timeouts, debug logging, and thread limits directly from the UI (no flags to remember).

### CLI-Specific Features
- **Rich Terminal Dashboard**: Live multi-bar progress display, animated spinners, real-time speed/ETA meters, and inline cover art display via `chafa`.
- **Flexible File Picker Modes**: Choose between range-syntax input (`1-10, 15`) or an interactive checkbox list.
- **Scriptable Automation**: Comprehensive command-line arguments for automated pipelines, dry-runs, and directory scanning.

## Repository Structure

- **`mangadot.py`**: The standalone terminal CLI uploader with interactive terminal dashboards, live speed/ETA meters, automated dependency management, and lossless image optimization.
- **`app_bundle/`**: The modular PySide6 desktop GUI application source tree, featuring multi-screen workflows, group attribution pickers, title review dialogs, and built-in upload history.
- **`Setup_Runtime.bat`**: Automated 1-click runtime and dependency provisioner: downloads portable Python 3.12 (if no Python is found on your PC) and installs all dependencies into an isolated local folder.
- **`Start MangaDot GUI.bat`**: 1-click launcher for the desktop GUI (with automatic runtime provisioning on first run).
- **`Run MangaDot Uploader.bat`**: Smart launcher for the CLI (with automatic runtime provisioning on first run).

## Prerequisites

- **GUI App**: Windows only. No Python or dependencies required when running the portable release.
- **CLI**: **Python 3.12** (or Astral's `uv`).
- **Browser Login**: You must be logged in to [MangaDot.net](https://mangadot.net) in your web browser (Chrome, Firefox, Brave, Edge, Opera, Vivaldi, and Zen are all supported).
- **`chafa`** *(Optional, CLI only)*: Enables inline cover art rendering in the terminal.

## Installation & Setup

### 1-Click Portable Setup (Windows: Recommended)
If you do not have Python installed, you do not need administrator privileges or manual installation:
1. Clone or download this repository.
2. Double-click **`Start MangaDot GUI.bat`** or **`Run MangaDot Uploader.bat`** (or run `Setup_Runtime.bat`).
3. The launcher will automatically detect your environment:
   - If Python 3.12+ is installed, it sets up an isolated `.venv` and installs all dependencies.
   - If no Python is found, it downloads an official standalone Python 3.12 runtime into a local `runtime/` folder and configures dependencies automatically.
4. Launch the GUI or CLI anytime with 1 click.

### Manual Installation (Power Users / macOS / Linux)
1. Clone the repository:
   ```bash
   git clone https://github.com/elsu3ian/mangadot_uploader.git
   cd mangadot_uploader
   ```
2. Install dependencies:
   ```bash
   # CLI only:
   pip install -r requirements.txt

   # Both GUI and CLI:
   pip install -r requirements.txt -r app_bundle/requirements.txt
   ```
   > **Tip:** With Astral's `uv`, zero setup is needed. Just run `uv run mangadot.py`.

3. Ensure your browser is closed before launching so cookies can be read directly (unless using CDP mode for Chromium browsers).

4. *(Optional)* Install `chafa` for terminal cover art:
   | Platform | Command |
   |:---|:---|
   | Windows | `winget install hpjansson.Chafa` |
   | macOS | `brew install chafa` |
   | Linux | `sudo apt install chafa` |

## Usage

1. Place your `.cbz` or `.zip` files into a dedicated folder (e.g. `Chapter 01 - The Beginning.cbz` or `[Group] Vol. 01.cbz`).
2. **GUI**: Double-click `Start MangaDot GUI.bat`, select your browser, pick your folder, and choose the target manga.
3. **CLI**: Double-click `Run MangaDot Uploader.bat`, or run:
   ```bash
   uv run mangadot.py
   # or
   py -3.12 mangadot.py
   ```
4. Both frontends scan installed browsers for an active MangaDot session automatically.
5. Assign scanlator groups, review and clean detected titles and numbers in the review table, and begin uploading.

## Complete CLI Options Table

| Flag | Description |
|:---|:---|
| `-h`, `--help` | Show command-line help menu. |
| `--dry-run` | Scan directory and parse chapter numbers without uploading. |
| `--library <DIR>` | Open interactive manga picker inside a parent library directory. |
| `--optimize [DIR]` | Losslessly optimize images in `.cbz`/`.zip` archives, then continue into upload. |
| `--optimize-only [DIR]` | Optimize archives standalone without logging in or uploading. |
| `--optimize-replace` | Overwrite original archives in place (requires confirmation) instead of saving to `optimized/`. |
| `--optimize-lossy` | Opt-in lossy mode for higher compression (modifies pixel data). |
| `--optimize-jpeg-quality <1-95>` | JPEG quality for lossy mode (default: 85). |
| `--optimize-webp-quality <1-100>`| WebP quality for lossy mode (default: 85). |
| `--optimize-threads <N>` | Number of archives to optimize in parallel (default: 4). |
| `--pingo` | Use bundled `pingo.exe` on Windows instead of Python/mozjpeg for faster optimization. |
| `--verify-timeout <SECONDS>` | Timeout for server verification confirmation (default: 60s). |
| `--skip-verification` | Skip post-upload verification polling (default: True, recommended for high concurrency). |
| `--verify` | Enable post-upload verification polling. |
| `--proxy <URL>` | Tunnel traffic through an HTTP/SOCKS proxy. |
| `--proxy-no-verify` | Disable SSL certificate verification for TLS-intercepting proxies. |
| `--debug` | Log full HTTP request/response traffic to rotating `api_requests.log`. |
| `--refresh-uv-cache` | Clear Astral `uv` cached environment and re-resolve dependencies. |

## Troubleshooting Cookies (Windows)

If you are using Chrome, Edge, Brave, Vivaldi, or Opera, Windows encrypted cookie stores often block direct file extraction. If direct extraction fails or you do not wish to run as Administrator, select that browser's **CDP** option from the login picker. This launches an isolated debug instance of the browser and reads your session over its DevTools Protocol port, sidestepping the encrypted store completely. Firefox and Zen are read directly from disk and do not require CDP or elevated privileges.

## Log Files

- If an upload fails, a timestamped report (e.g. `failed_manga_{id}_{datetime}.txt`) is saved listing any uncompleted chapters.
- Detailed HTTP logs can be enabled with `--debug` (CLI) or the debug logging checkbox in the GUI Settings dialog.

## 🤝 Credits & Acknowledgments

This project began as a fork of the original single-file CLI uploader created by [@darwin-256](https://github.com/darwin-256/mangadot_uploader). Their original script established the core approach this tool still builds on: browser-cookie session cloning, User-Agent spoofing to bypass Cloudflare, and resumable chunked uploads over the TUS protocol.

Since then, the project has been substantially rewritten and extended: a full interactive terminal dashboard, mixed-group batching, ghost-chapter verification, homoglyph-safe filename parsing, an interactive title/number review pass, CDP-based cookie extraction for Chromium browsers, and a standalone desktop GUI application, among many other changes documented in the [changelog](https://github.com/elsu3ian/mangadot_uploader/blob/main/CHANGELOG.md).

## License

Distributed under the [MIT License](LICENSE).
