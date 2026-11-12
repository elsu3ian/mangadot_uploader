#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "requests>=2.34.2",
#     "rookiepy>=0.5.6",
#     "questionary>=2.1.1",
#     "rich>=15.0.0",
#     "websocket-client>=1.9.0",
# ]
# ///
"""
==============================================================================
🚀 MANGADOT UPLOADER v2.1.0: ADVANCED FEATURES & USAGE
==============================================================================
[Public Release: Full Site Update Compatibility, 20MB Native TUS Chunks,
  Authoritative Fast Verification via /api/uploads/mine, Decoupled Paced
  Background Batch Complete, and Modular Desktop GUI (app_bundle v3).
  See README.md and CHANGELOG.md for full details.]

[v2.1.0: Upgraded to 100% compliance with MangaDot site update:
  - 20MB native TUS chunks (73% fewer requests, eliminates edge throttling).
  - TUS offset resync via HEAD on retryable errors (429, 500, 502, 504, 524).
  - Decoupled background batch complete with 2.5s cross-worker pacing.
  - Authoritative fast verification via /api/uploads/mine (1-second checks).
  - 1-click zero-config runtime provisioner (Setup_Runtime.bat).]

[v2.1.0: CBZ Optimizer — re-compresses images inside .cbz/.zip archives
  (JPEG/PNG/WebP/BMP), run standalone with --optimize-only or chained
  straight into the upload flow with --optimize. STRICTLY LOSSLESS BY
  DEFAULT: JPEGs are re-optimized via mozjpeg (Huffman/entropy coding
  only, pixel-identical output), PNG/WEBP use their native lossless
  encoders, BMP is losslessly repacked to PNG. Pixel data is only ever
  altered if --optimize-lossy is explicitly passed. Fully isolated from
  the upload pipeline: Pillow/mozjpeg are imported lazily and only when
  one of these flags is used, so normal uploads are unaffected.
  Also: uv + PEP 723 support — run via 'uv run mangadot.py' with zero setup
  (isolated, cached environment, no system/venv installs); plain 'python
  mangadot.py' still works exactly as before. New --refresh-uv-cache flag
  clears uv's cached resolution on demand. Weekly (non-blocking, offline-safe)
  PyPI freshness check reports if a dependency floor is behind the latest
  release — informational only, never auto-updates anything. Language code
  and parallel-upload thread count are now remembered across runs, with the
  language prompt upgraded to type-to-filter autocomplete. New one-time
  "which file picker do you prefer" setting: choose between the existing
  range-syntax picker (e.g. '103-108,110') or a checkbox picker (tick
  individual files) when not uploading everything; the choice is remembered.
  All dependency version floors bumped to latest-published.]

[v2.0.0: Interactive title/number review pass before upload — bulk and
  ranged find/replace with live preview, redo-title-for-group, manual
  number overrides with duplicate warnings. Homoglyph-safe filename
  parsing (Cyrillic/Greek look-alikes), flexible range input (e.g.
  "103-108,110"), advanced auto-detect naming submenu, leading-zero
  title cleanup, virtualenv-aware installer, dedicated BatchInitError,
  centralized log/path redaction]

[v1.3.0: Auto-detect title now always shows a picker with dynamically-built,
  labeled candidates (full/without-episode-label/without-season/bare/minimal),
  memoized per detected filename "shape" across the batch. Core architecture
  patch: pagination for Ghost Chapter verifier, dynamic decimal interpolation,
  TUS HEAD fallback, natural sort hyphen fix, and thread pool thrashing eliminated]

WHAT THIS SCRIPT DOES:
  A multi-threaded batch uploader for .cbz/.zip files to MangaDot.net.
  It extracts active browser cookies (Chrome, Firefox, Edge, Brave, Opera,
  Vivaldi, Zen) and dynamically spoofs your exact User-Agent to natively
  bypass Cloudflare. Uploads are handled via the resumable TUS protocol in
  20MB chunks with optional proxy tunneling.

  A standalone desktop GUI is also available (same engine, no terminal
  required) — see README.md.

ADVANCED NAMING & UI:
  - Bracket Detection: Automatically detects and assigns release groups from [Bracket] tags.
  - Mixed-Group Batching: Seamlessly uploads and assigns multiple release groups in a single run.
  - Custom Regex: Use 'Pattern -> Replace' syntax to quickly rename files, or '()' to extract titles.
  - Advanced Auto-Detect: Combine custom regex with bracket/parenthesis-group stripping independently.
  - Homoglyph-Safe Parsing: Look-alike Cyrillic/Greek characters no longer break label detection.
  - Terminal Dashboard: Renders high-fidelity cover art directly in the terminal (requires 'chafa').

REVIEW BEFORE YOU UPLOAD:
  - Title & Number Review: Before anything uploads, bulk find/replace across all titles
    (with live preview), scope a find/replace to a number range or single file, redo the
    auto-detected title for a whole group, or manually override any file's number.
  - Flexible Ranges: Accepts range syntax like '103-108,110,115-117' anywhere a chapter
    or volume selection is asked for.

SMART PROTECTIONS:
  - Auto-Session Recovery: Pauses if your token expires mid-batch, allowing browser refreshes.
  - TUS Conflict Resolution: Automatically queries server offsets to rescue stalled or dropped chunks.
  - Ghost Chapter Prevention: Strictly verifies server ingestion to your specific Scanlator Name/Group ID.
  - API Schema Detection: Warns you immediately if MangaDot changes its search payload structure.
  - Failure State Recovery: Saves failures to 'logs/failed_manga_[id]_[timestamp].txt' for isolated retries.

COMMAND LINE FLAGS:
  py -3.12 mangadot.py -h                 : Shows the help menu with all available arguments.
  py -3.12 mangadot.py --dry-run          : Scans directory, parses names, and flags missing chapters without uploading.
  py -3.12 mangadot.py --debug            : Dumps HTTP traffic to 'api_requests.log' with circular file rotation.
  py -3.12 mangadot.py --library <path>   : Opens the interactive picker directly in your parent manga folder.
  py -3.12 mangadot.py --verify-timeout X : Overrides the default 60s timeout for verifying server-side chapter ingestion.
  py -3.12 mangadot.py --proxy <url>      : Routes all HTTP traffic through a specified proxy.
  py -3.12 mangadot.py --proxy-no-verify  : Disables SSL certificate verification (use only if your proxy intercepts TLS).
  uv run mangadot.py                      : Runs the script via uv using its PEP 723 inline metadata — no pip/venv setup needed; all flags above work identically.
  uv run mangadot.py --refresh-uv-cache   : Clears uv's cached environment for this script and exits, forcing the next run to re-resolve dependencies.

CBZ OPTIMIZER (lossless by default; requires: pip install Pillow mozjpeg-lossless-optimization):
  py -3.12 mangadot.py --optimize-only              : Prompts for a folder, losslessly shrinks every .cbz/.zip inside it, then exits.
  py -3.12 mangadot.py --optimize-only <path>       : Same, but skips the folder prompt.
  py -3.12 mangadot.py --optimize <path>            : Losslessly shrinks the folder, then continues straight into the normal upload flow on it.
  py -3.12 mangadot.py --optimize-lossy             : OPT-IN ONLY. Allows lossy JPEG/WEBP re-encoding for bigger savings — pixel data WILL change. Off unless typed explicitly.
  py -3.12 mangadot.py --optimize-replace           : Overwrites originals in-place instead of writing to an 'optimized' subfolder. Asks for confirmation before doing so.
  py -3.12 mangadot.py --optimize-jpeg-quality 90   : JPEG quality, only used with --optimize-lossy (default: 85).
  py -3.12 mangadot.py --optimize-webp-quality 90   : WEBP quality, only used with --optimize-lossy (default: 85).
  py -3.12 mangadot.py --optimize-threads 8         : Archives optimized in parallel (default: 4; CPU-bound, separate from upload threads).

  --pingo is a MODIFIER, not a standalone command — it must be combined with
  --optimize-only or --optimize, otherwise it does nothing on its own:
  py -3.12 mangadot.py --optimize-only --pingo             : Use a local pingo binary (next to mangadot.py) instead of mozjpeg/Pillow. Win/Linux only; falls back with a visible notice elsewhere.
  py -3.12 mangadot.py --optimize-only <path> --pingo      : Same, on a specific folder.
  py -3.12 mangadot.py --optimize <path> --pingo --optimize-replace : Pingo backend, overwriting originals in-place (after confirmation), then continuing into upload.
==============================================================================
"""
import io
import os
import re
import sys
import json
import queue
import base64
import time
import random
import datetime
import threading
import concurrent.futures
import argparse
import importlib.metadata
import subprocess
import platform
import logging
import logging.handlers
import atexit
import math
import tempfile
import shutil
import zipfile
import sqlite3
from collections import deque, Counter
from pathlib import Path
from urllib.parse import urljoin

# ==============================================================================
# 🔄 UV CACHE REFRESH (handled before the dependency check, on purpose: this
# needs to work even if none of REQUIRED_PACKAGES are installed yet)
# ==============================================================================
if "--refresh-uv-cache" in sys.argv:
    import shutil as _shutil
    sep = "=" * 62
    print(sep)
    print("  🔄 Refreshing uv's cached environment for this script")
    print(sep)
    uv_path = _shutil.which("uv")
    if uv_path is None:
        print("  ❌ 'uv' was not found on PATH — nothing to refresh.")
        print("     (This flag only does something when the script is run via uv,")
        print("      e.g. 'uv run mangadot.py --refresh-uv-cache'.)")
        sys.exit(1)
    try:
        script_path = os.path.abspath(__file__)
    except NameError:
        script_path = os.path.abspath(sys.argv[0])
    print("  Running: uv cache clean")
    result = subprocess.run([uv_path, "cache", "clean"])
    if result.returncode != 0:
        print("  ❌ 'uv cache clean' failed — see output above.")
        sys.exit(result.returncode)
    print("  ✅ uv cache cleared.")
    print()
    print("  Next 'uv run mangadot.py' will re-resolve every dependency in the")
    print("  PEP 723 block to the newest version that satisfies each floor, and")
    print("  re-cache it. This does NOT change the floors themselves — to bump")
    print("  a floor (e.g. require a newer rich), edit the '# dependencies ='")
    print("  block at the top of this file, or run:")
    print(f"      uv add --script {os.path.basename(script_path)} <package>>=<version>")
    print(sep)
    sys.exit(0)

# ==============================================================================
# ⚙️  DEPENDENCY CHECK
# ==============================================================================

REQUIRED_PACKAGES = {
    "requests":         "2.34.2",
    "rookiepy":         "0.5.6",
    "questionary":      "2.1.1",
    "rich":             "15.0.0",
    "websocket-client": "1.9.0",
}
OPTIMIZER_PACKAGES = {
    "Pillow":                        "12.3.0",
    "mozjpeg-lossless-optimization": "1.3.2",
}

def _parse_version_tuple(version_str):
    match = re.match(r'(\d+(?:\.\d+)*)', str(version_str))
    if not match:
        return (0,)
    return tuple(map(int, match.group(1).split('.')))

def _version_lt(installed, required):
    a = _parse_version_tuple(installed)
    b = _parse_version_tuple(required)
    length = max(len(a), len(b))
    a += (0,) * (length - len(a))
    b += (0,) * (length - len(b))
    return a < b

def _in_virtualenv():
    return (
        hasattr(sys, "real_prefix")
        or sys.base_prefix != sys.prefix
        or bool(os.environ.get("CONDA_DEFAULT_ENV"))
    )

def _pip_available():
    try:
        import importlib.util
        return importlib.util.find_spec("pip") is not None
    except Exception:
        return False

def _running_under_uv():
    if os.environ.get("UV") or os.environ.get("UV_RUN_RECURSION_DEPTH"):
        return True
    prefix = (getattr(sys, "prefix", "") or "").replace("\\", "/").lower()
    return "/uv/" in prefix and ("environments-" in prefix or "archive-" in prefix)

def _script_name():
    try:
        return os.path.basename(sys.argv[0]) or "mangadot.py"
    except Exception:
        return "mangadot.py"

def _print_uv_dep_hint(sep, packages):
    name = _script_name()
    print(sep)
    print("  ℹ️   Dependencies are declared in this script's PEP 723 metadata block.")
    print("  Since you're running under uv, the fix is to (re)declare the")
    print("  dependency there instead of pip-installing it:")
    print()
    print(f"      uv add --script {name} {' '.join(packages)}")
    print()
    print(f"  Or just: uv run {name}   (uv will provision everything declared)")
    print(sep)

def check_dependencies():
    sep   = "=" * 62
    ok    = True

    missing_pip  = []
    outdated_pip = []

    for pkg, min_version in REQUIRED_PACKAGES.items():
        try:
            installed = importlib.metadata.version(pkg)
            if _version_lt(installed, min_version):
                outdated_pip.append((pkg, min_version, installed))
        except importlib.metadata.PackageNotFoundError:
            missing_pip.append(pkg)
        except (ValueError, TypeError) as e:
            print(f"  ⚠️  Could not read version metadata for '{pkg}' ({e}); treating as missing.")
            missing_pip.append(pkg)

    if missing_pip or outdated_pip:
        ok = False
        print(sep)
        print("  ⚠️  MISSING / OUTDATED PYTHON PACKAGES")
        print(sep)
        if missing_pip:
            print("\n  Not installed:")
            for pkg in missing_pip:
                print(f"    ✗  {pkg}")
        if outdated_pip:
            print("\n  Outdated (need upgrade):")
            for pkg, req, inst in outdated_pip:
                print(f"    ✗  {pkg}  (have {inst}, need >= {req})")

        to_install = missing_pip + [p for p, _, _ in outdated_pip]

        if _running_under_uv() or not _pip_available():
            print("\n  ℹ️   pip is not available in this environment, so packages can't be")
            print("      auto-installed here.")
            _print_uv_dep_hint(sep, to_install)
            print()
            
        else:
            if not _in_virtualenv():
                print("\n  ℹ️   You're not inside a virtual environment - installing now would")
                print("      affect your system-wide Python packages.")
                print("\n      requirements.txt is included next to this script. You can instead run:")
                print("        python -m venv .venv")
                print("        .venv\\Scripts\\activate      (Windows)   OR   source .venv/bin/activate  (macOS/Linux)")
                print("        pip install -r requirements.txt\n")
                print(f"      Or, with uv installed:  uv run {_script_name()}\n")
                proceed = input("  Install these packages to your system Python anyway? [y/N]: ").strip().lower()
                if proceed != "y":
                    print("\n  Skipped. Install the packages above, then re-run this script.")
                    print(sep)
                    return False

            print(f"\n  🔧 Installing missing/outdated packages: {' '.join(to_install)}...")
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade"] + to_install)
                print("  ✅ All dependencies verified and updated.\n")
                ok = True
            except subprocess.CalledProcessError as e:
                print(f"  ❌ Auto-install failed (pip exited with code {e.returncode}).")
                print("    Try running this manually:")
                print(f"    pip install --upgrade {' '.join(to_install)}\n")
            except FileNotFoundError:
                print("  ❌ Could not find pip for this Python interpreter.")
                print(f"    Try running manually: pip install --upgrade {' '.join(to_install)}\n")

    if shutil.which("chafa") is None:
        _sys = platform.system()
        if _sys == "Windows":
            chafa_hint = "winget install hpjansson.Chafa"
        elif _sys == "Darwin":
            chafa_hint = "brew install chafa"
        else:
            chafa_hint = "sudo apt install chafa  # or your distro's package manager"
        print(sep)
        print("  ℹ️   OPTIONAL: chafa not found (cover art will not display)")
        print(f"  Install: {chafa_hint}")
        print(sep)
        print()

    if not ok:
        print(sep)
        print("  Script cannot start until required packages are installed.")
        print(sep)

    return ok

def check_optimizer_dependencies(need_mozjpeg=True):
    sep = "=" * 62
    ok  = True

    packages = dict(OPTIMIZER_PACKAGES)
    if not need_mozjpeg:
        packages.pop("mozjpeg-lossless-optimization", None)

    missing_pip  = []
    outdated_pip = []

    for pkg, min_version in packages.items():
        try:
            installed = importlib.metadata.version(pkg)
            if _version_lt(installed, min_version):
                outdated_pip.append((pkg, min_version, installed))
        except importlib.metadata.PackageNotFoundError:
            missing_pip.append(pkg)
        except (ValueError, TypeError) as e:
            print(f"  ⚠️  Could not read version metadata for '{pkg}' ({e}); treating as missing.")
            missing_pip.append(pkg)

    if missing_pip or outdated_pip:
        ok = False
        print(sep)
        print("  ⚠️  MISSING / OUTDATED OPTIMIZER PACKAGES")
        print(sep)
        if missing_pip:
            print("\n  Not installed:")
            for pkg in missing_pip:
                print(f"    ✗  {pkg}")
        if outdated_pip:
            print("\n  Outdated (need upgrade):")
            for pkg, req, inst in outdated_pip:
                print(f"    ✗  {pkg}  (have {inst}, need >= {req})")

        to_install = missing_pip + [p for p, _, _ in outdated_pip]

        if _running_under_uv() or not _pip_available():
            print("\n  ℹ️   pip is not available in this environment, so packages can't be")
            print("      auto-installed here.")
            _print_uv_dep_hint(sep, to_install)
            print()
            ok = False
        else:
            if not _in_virtualenv():
                print("\n  ℹ️   You're not inside a virtual environment - installing now would")
                print("      affect your system-wide Python packages.")
                proceed = input("  Install these packages to your system Python anyway? [y/N]: ").strip().lower()
                if proceed != "y":
                    print("\n  Skipped. Install the packages above, then re-run with --optimize/--optimize-only.")
                    print(sep)
                    return False

            print(f"\n  🔧 Installing missing/outdated packages: {' '.join(to_install)}...")
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade"] + to_install)
                print("  ✅ Optimizer dependencies verified and updated.\n")
                ok = True
            except subprocess.CalledProcessError as e:
                print(f"  ❌ Auto-install failed (pip exited with code {e.returncode}).")
                print("    Try running this manually:")
                print(f"    pip install --upgrade {' '.join(to_install)}\n")
                ok = False
            except FileNotFoundError:
                print("  ❌ Could not find pip for this Python interpreter.")
                print(f"    Try running manually: pip install --upgrade {' '.join(to_install)}\n")
                ok = False

    return ok

if not check_dependencies():
    sys.exit(1)

try:
    import requests
    from requests.adapters import HTTPAdapter
    import rookiepy
    import questionary
    import websocket
    from rich.console import Console, Group
    from rich.live import Live
    from rich.markup import escape as rich_escape
    from rich.rule import Rule
    from rich.table import Table
    from rich.text import Text
    from rich import box
    from rich.progress import (
        Progress, TextColumn, BarColumn, TaskProgressColumn,
        SpinnerColumn, DownloadColumn, TransferSpeedColumn, TimeRemainingColumn
    )

    console = Console()
except ImportError as _import_err:
    print(f"A required package failed to import even after the dependency check: {_import_err}")
    print("Try reinstalling it manually, e.g.: pip install --upgrade " + str(_import_err.name or ""))
    sys.exit(1)

# ==============================================================================
# ⚙️  CONFIGURATION
# ==============================================================================

BASE_URL             = "https://mangadot.net"
TUS_ENDPOINT         = f"{BASE_URL}/api/tus/"
BATCH_INIT_ENDPOINT  = f"{BASE_URL}/api/uploads/batch/init"

MAX_BATCH_SIZE       = 100
MAX_RETRIES          = 3
RETRY_DELAY          = 5
_VERIFY_CONCURRENCY  = 5
RETRYABLE_STATUSES   = [429, 500, 502, 503, 504, 524]
FATAL_SIZE_STATUSES  = [413, 415]


# ==============================================================================
# 🔑 CDP (Chrome DevTools Protocol) fallback for Chromium browsers
# ==============================================================================

CDP_BASE_PORT = 9222
CDP_PORT_OFFSETS = {"chrome": 0, "edge": 1, "brave": 2, "vivaldi": 3, "opera": 4}

def _cdp_port_for(browser_key):
    return CDP_BASE_PORT + CDP_PORT_OFFSETS.get(browser_key, 99)

def _cdp_profile_dir_for(browser_key):
    return os.path.join(CDP_PROFILE_ROOT, browser_key)

def _platform_data_root():
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser(r"~\AppData\Local")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return base

def _default_cdp_profile_dir():
    return os.path.join(_platform_data_root(), "MangaDotUploader", "cdp_profile")

def _default_gecko_debug_profile_dir():
    return os.path.join(_platform_data_root(), "MangaDotUploader", "gecko_debug_profile")

CDP_PROFILE_ROOT = _default_cdp_profile_dir()
GECKO_DEBUG_PROFILE_ROOT = _default_gecko_debug_profile_dir()
CDP_STARTUP_WAIT = 20
# Generous on purpose: a human needs time to actually log in through a
# Cloudflare managed challenge in the opened debug window.
GECKO_DEBUG_STARTUP_WAIT = 180

def _gecko_debug_profile_dir_for(browser_key):
    return os.path.join(GECKO_DEBUG_PROFILE_ROOT, browser_key)

CDP_BROWSER_EXECUTABLES = {
    "chrome": {
        "win32":  [r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe",
                   r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe",
                   r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"],
        "darwin": ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"],
        "linux":  ["google-chrome", "google-chrome-stable"],
    },
    "edge": {
        "win32":  [r"%PROGRAMFILES(X86)%\Microsoft\Edge\Application\msedge.exe",
                   r"%PROGRAMFILES%\Microsoft\Edge\Application\msedge.exe"],
        "darwin": ["/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"],
        "linux":  ["microsoft-edge", "microsoft-edge-stable"],
    },
    "brave": {
        "win32":  [r"%PROGRAMFILES%\BraveSoftware\Brave-Browser\Application\brave.exe",
                   r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe"],
        "darwin": ["/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"],
        "linux":  ["brave-browser"],
    },
    "vivaldi": {
        "win32":  [r"%PROGRAMFILES%\Vivaldi\Application\vivaldi.exe",
                   r"%LOCALAPPDATA%\Vivaldi\Application\vivaldi.exe"],
        "darwin": ["/Applications/Vivaldi.app/Contents/MacOS/Vivaldi"],
        "linux":  ["vivaldi", "vivaldi-stable"],
    },
        "opera": {
            "win32":  [r"%PROGRAMFILES%\Opera\opera.exe",
                       r"%LOCALAPPDATA%\Programs\Opera\opera.exe"],
            "darwin": ["/Applications/Opera.app/Contents/MacOS/Opera"],
            "linux":  ["opera"],
        },
}

CHROMIUM_BROWSERS = {"chrome", "brave", "edge", "opera", "vivaldi"}

GECKO_REGISTRY_APP_NAMES = {
    "firefox": "firefox.exe",
    "zen":     "zen.exe",
}

GECKO_BROWSER_EXECUTABLES = {
    "firefox": {
        "win32":  [r"%PROGRAMFILES%\Mozilla Firefox\firefox.exe",
                   r"%PROGRAMFILES(X86)%\Mozilla Firefox\firefox.exe",
                   r"%LOCALAPPDATA%\Mozilla Firefox\firefox.exe"],
        "darwin": ["/Applications/Firefox.app/Contents/MacOS/firefox"],
        "linux":  ["firefox"],
    },
    "zen": {
        "win32":  [r"%PROGRAMFILES%\Zen Browser\zen.exe",
                   r"%LOCALAPPDATA%\Programs\Zen Browser\zen.exe",
                   r"%LOCALAPPDATA%\zen-browser\zen.exe"],
        "darwin": ["/Applications/Zen Browser.app/Contents/MacOS/zen"],
        "linux":  ["zen", "zen-browser"],
    },
}
# Gecko debug-profile login: MangaDot serves a Cloudflare *managed* challenge
# (Cf-Mitigated: challenge) that requires executing JavaScript in a real
# browser engine to earn a fresh cf_clearance cookie - no HTTP client,
# however well it spoofs its TLS fingerprint, can clear it. Chromium browsers
# get past this via the CDP path (a real Chromium engine is driven); this
# Gecko section gives Zen/Firefox the same capability using a dedicated,
# isolated debug profile (-profile + -no-remote), NOT Marionette on the
# person's real profile - enabling remote-debugging there changes fingerprint
# signals (navigator.webdriver etc.) in a way that can make Cloudflare MORE
# suspicious. The dedicated profile logs in once; its cookies.sqlite is then
# read like any other profile.

MAX_VERIFY_SECONDS   = 60
DEFAULT_CHAPTERS_DIR = "chapters"
DEFAULT_LIBRARY_DIR  = ""
CONFIG_PATH          = Path.home() / ".mangadot_uploader.json"
DB_PATH               = Path.home() / ".mangadot_uploader_db.json"
PAUSED_UPLOAD_PATH    = Path.home() / ".mangadot_paused_upload.json"
PAUSED_UPLOAD_SCHEMA_VERSION = 1

# Guards paused_upload.json against concurrent writes (same rationale as GUI's
# config.py — only one batch runs at once, so a plain threading.Lock is enough).
_paused_upload_lock = threading.Lock()

DEFAULT_USER_AGENTS = {
    "chrome":  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
    "firefox": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0",
    "brave":   "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
    "edge":    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36 Edg/137.0.0.0",
    "opera":   "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36 OPR/122.0.0.0",
    "vivaldi": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36 Vivaldi/7.4.3684.38",
}

_WEB_VERSION_APIS = {
    "chrome":  "https://versionhistory.googleapis.com/v1/chrome/platforms/win/channels/stable/versions?pageSize=1",
    "edge":    "https://edgeupdates.microsoft.com/api/products?view=enterprise",
    "firefox": "https://product-details.mozilla.org/1.0/firefox_versions.json",
}

_UA_CACHE      = {}
_UA_CACHE_LOCK = threading.Lock()

_VERIFY_SEM      = None
_VERIFY_SEM_LOCK = threading.Lock()

def _verify_concurrency_for(thread_count):
    """A fixed handful of verify slots starves big batches: with 30 threads,
    most files sat in the semaphore queue burning their own verify_timeout
    and ended as "Pending Index". Scale with the thread count instead — about
    a third of the upload threads, never below the old floor and capped at 15
    (each poll is a real server round-trip). Mirrors the GUI uploader."""
    return max(_VERIFY_CONCURRENCY, min(15, thread_count // 3))

def get_verify_sem(thread_count=None):
    """Module-level singleton: the first caller's thread_count sizes it (one
    batch runs per process)."""
    global _VERIFY_SEM
    if _VERIFY_SEM is None:
        with _VERIFY_SEM_LOCK:
            if _VERIFY_SEM is None:
                size = _verify_concurrency_for(thread_count) if thread_count else _VERIFY_CONCURRENCY
                _VERIFY_SEM = threading.Semaphore(size)
    return _VERIFY_SEM

# ==============================================================================
# 🔍  BROWSER VERSION DETECTION
# ==============================================================================

def _clean_version(raw):
    if not raw: return None
    m = re.search(r'(\d+(?:\.\d+)*)', str(raw))
    return m.group(1) if m else None

def _detect_windows_arch():
    machine = platform.machine().lower()
    if machine in ('amd64', 'x86_64'): return 'Win64; x64'
    if machine in ('arm64', 'aarch64'): return 'ARM64'
    return 'Win64; x64'

def _detect_macos_ver():
    try:
        ver = platform.mac_ver()[0]
        if ver:
            parts = ver.split('.')
            if len(parts) >= 2:
                base = f"{parts[0]}_{parts[1]}"
                if len(parts) >= 3 and parts[2]:
                    base += f"_{parts[2]}"
                return base
    except (IndexError, ValueError, OSError) as e:
        logging.debug("_detect_macos_ver: falling back to default (%s)", e)
    return "10_15_7"

def _read_windows_registry(browser):
    try:
        import winreg
        paths = {
            "chrome":  [(winreg.HKEY_CURRENT_USER, r"SOFTWARE\Google\Chrome\BLBeacon", "version"),
                        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Google\Chrome\BLBeacon", "version")],
            "edge":    [(winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{56EB18F8-B008-4CBD-B6D2-8C97FE7E7558}", "pv"),
                        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{56EB18F8-B008-4CBD-B6D2-8C97FE7E7558}", "pv")],
            "brave":   [(winreg.HKEY_CURRENT_USER, r"SOFTWARE\BraveSoftware\Brave-Browser\BLBeacon", "version")],
            "opera":   [(winreg.HKEY_CURRENT_USER, r"SOFTWARE\Opera Software\BLBeacon", "version")],
            "vivaldi": [(winreg.HKEY_CURRENT_USER, r"SOFTWARE\Vivaldi\BLBeacon", "version")],
            "firefox": [(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Mozilla\Mozilla Firefox", "CurrentVersion"),
                        (winreg.HKEY_CURRENT_USER,  r"SOFTWARE\Mozilla\Mozilla Firefox", "CurrentVersion"),
                        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Mozilla\Mozilla Firefox", "CurrentVersion")],
        }
        for hive, path, key in paths.get(browser, []):
            try:
                with winreg.OpenKey(hive, path) as k:
                    val, _ = winreg.QueryValueEx(k, key)
                    v = _clean_version(val)
                    if v: return v
            except OSError: continue
    except ImportError:
        return None  # winreg unavailable (not on Windows)
    return None

def _read_mac_plist(browser):
    try:
        import plistlib
        plist_paths = {
            "chrome":  "/Applications/Google Chrome.app/Contents/Info.plist",
            "edge":    "/Applications/Microsoft Edge.app/Contents/Info.plist",
            "brave":   "/Applications/Brave Browser.app/Contents/Info.plist",
            "firefox": "/Applications/Firefox.app/Contents/Info.plist",
            "opera":   "/Applications/Opera.app/Contents/Info.plist",
            "vivaldi": "/Applications/Vivaldi.app/Contents/Info.plist",
        }
        path = plist_paths.get(browser)
        if not path or not os.path.exists(path): return None
        with open(path, 'rb') as f:
            plist = plistlib.load(f)
            raw = plist.get('KSVersion') or plist.get('CFBundleShortVersionString')
            return _clean_version(raw)
    except (OSError, ValueError) as e:
        logging.debug("_read_mac_plist(%s): %s", browser, e)
        return None

def _read_linux_version(browser):
    cmds = {
        "chrome":  ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"],
        "edge":    ["microsoft-edge", "microsoft-edge-stable"],
        "brave":   ["brave-browser", "brave"],
        "firefox": ["firefox", "firefox-esr"],
        "opera":   ["opera"],
        "vivaldi": ["vivaldi", "vivaldi-stable"],
    }
    for cmd in cmds.get(browser, []):
        try:
            out = subprocess.run([cmd, "--version"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5, check=False)
            if out.returncode == 0 and out.stdout: return _clean_version(out.stdout)
        except (OSError, subprocess.SubprocessError): continue
    return None

def _fetch_web_version(browser, timeout=5):
    try:
        if browser == "firefox":
            r = requests.get(_WEB_VERSION_APIS["firefox"], timeout=timeout)
            if r.status_code == 200: return _clean_version(r.json().get("LATEST_FIREFOX_VERSION"))
        elif browser == "edge":
            r = requests.get(_WEB_VERSION_APIS["edge"], timeout=timeout)
            if r.status_code == 200:
                for product in r.json():
                    if product.get("Product") == "Stable":
                        releases = product.get("Releases", [])
                        if releases: return _clean_version(releases[0].get("ProductVersion"))
        elif browser == "chrome":
            r = requests.get(_WEB_VERSION_APIS["chrome"], timeout=timeout)
            if r.status_code == 200:
                versions = r.json().get("versions") or []
                if versions: return _clean_version(versions[0].get("version"))
    except (requests.exceptions.RequestException, json.JSONDecodeError, ValueError) as e:
        logging.debug("_fetch_web_version(%s): %s", browser, e)
        return None
    return None

def _get_chromium_version_for_browser(browser):
    if browser not in ("vivaldi", "opera", "brave"): return None
    cli_map = {
        "vivaldi": ["vivaldi", "vivaldi-stable"],
        "opera":   ["opera"],
        "brave":   ["brave-browser", "brave"],
    }
    for cmd in cli_map.get(browser, []):
        try:
            out = subprocess.run([cmd, "--version"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5, check=False)
            if out.returncode == 0 and out.stdout:
                m = re.search(r'Chromium[/ ](\d+\.\d+\.\d+(?:\.\d+)?)', out.stdout, re.IGNORECASE)
                if m: return _clean_version(m.group(1))
        except (OSError, subprocess.SubprocessError): continue
    return _fetch_web_version("chrome", timeout=5)

def _build_user_agent(browser, version, chromium_version=None):
    if not version: return DEFAULT_USER_AGENTS.get(browser, DEFAULT_USER_AGENTS["firefox"])
    own_major    = version.split('.')[0]
    chrome_major = chromium_version.split('.')[0] if chromium_version else own_major

    if sys.platform == 'win32':
        arch = _detect_windows_arch()
        arch_clause = f"Windows NT 10.0; {arch}"
        if browser == "firefox": return f"Mozilla/5.0 ({arch_clause}; rv:{own_major}.0) Gecko/20100101 Firefox/{own_major}.0"
        if browser == "edge":    return f"Mozilla/5.0 ({arch_clause}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_major}.0.0.0 Safari/537.36 Edg/{own_major}.0.0.0"
        if browser == "opera":   return f"Mozilla/5.0 ({arch_clause}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_major}.0.0.0 Safari/537.36 OPR/{own_major}.0.0.0"
        if browser == "vivaldi": return f"Mozilla/5.0 ({arch_clause}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_major}.0.0.0 Safari/537.36 Vivaldi/{version}"
        return f"Mozilla/5.0 ({arch_clause}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_major}.0.0.0 Safari/537.36"
    elif sys.platform == 'darwin':
        mac_ver = _detect_macos_ver()
        if browser == "firefox": return f"Mozilla/5.0 (Macintosh; Intel Mac OS X {mac_ver}; rv:{own_major}.0) Gecko/20100101 Firefox/{own_major}.0"
        if browser == "edge":    return f"Mozilla/5.0 (Macintosh; Intel Mac OS X {mac_ver}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_major}.0.0.0 Safari/537.36 Edg/{own_major}.0.0.0"
        if browser == "opera":   return f"Mozilla/5.0 (Macintosh; Intel Mac OS X {mac_ver}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_major}.0.0.0 Safari/537.36 OPR/{own_major}.0.0.0"
        if browser == "vivaldi": return f"Mozilla/5.0 (Macintosh; Intel Mac OS X {mac_ver}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_major}.0.0.0 Safari/537.36 Vivaldi/{version}"
        return f"Mozilla/5.0 (Macintosh; Intel Mac OS X {mac_ver}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_major}.0.0.0 Safari/537.36"
    else:
        if browser == "firefox": return f"Mozilla/5.0 (X11; Linux x86_64; rv:{own_major}.0) Gecko/20100101 Firefox/{own_major}.0"
        if browser == "edge":    return f"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_major}.0.0.0 Safari/537.36 Edg/{own_major}.0.0.0"
        if browser == "opera":   return f"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_major}.0.0.0 Safari/537.36 OPR/{own_major}.0.0.0"
        if browser == "vivaldi": return f"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_major}.0.0.0 Safari/537.36 Vivaldi/{version}"
        return f"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_major}.0.0.0 Safari/537.36"

_UA_CACHE_MAX_AGE_SECONDS = 24 * 3600

def get_dynamic_user_agent(browser, force_refresh=False):
    """Cached per browser for a day. force_refresh=True re-detects now — used
    when replayed cookies didn't log in, since a stale UA (the browser updated
    since it was cached) looks exactly like an invalid session to Cloudflare.
    Old bare-string cache entries (no timestamp) are treated as expired."""
    with _UA_CACHE_LOCK:
        if force_refresh:
            _UA_CACHE.pop(browser, None)
        else:
            if browser in _UA_CACHE: return _UA_CACHE[browser]
            config = load_config()
            entry = config.get("cached_user_agents", {}).get(browser)
            if isinstance(entry, dict) and entry.get("ua") and \
                    time.time() - float(entry.get("cached_at", 0) or 0) < _UA_CACHE_MAX_AGE_SECONDS:
                _UA_CACHE[browser] = entry["ua"]
                return entry["ua"]

    version = None
    try:
        if sys.platform == 'win32':    version = _read_windows_registry(browser)
        elif sys.platform == 'darwin': version = _read_mac_plist(browser)
        else:                          version = _read_linux_version(browser)
    except (OSError, ValueError) as e:
        logging.debug("get_dynamic_user_agent: local version detection failed for %s: %s", browser, e)
        version = None

    if not version and browser in ("chrome", "edge", "firefox"):
        try:
            version = _fetch_web_version(browser, timeout=5)
        except (requests.exceptions.RequestException, json.JSONDecodeError, ValueError) as e:
            logging.debug("get_dynamic_user_agent: web version fetch failed for %s: %s", browser, e)
            version = None

    chromium_version = _get_chromium_version_for_browser(browser)
    ua = _build_user_agent(browser, version, chromium_version)

    with _UA_CACHE_LOCK:
        _UA_CACHE[browser] = ua
        try:
            fresh_config = load_config()
            cached_uas = fresh_config.get("cached_user_agents", {})
            cached_uas[browser] = {"ua": ua, "cached_at": time.time()}
            fresh_config["cached_user_agents"] = cached_uas
            save_config(fresh_config)
        except OSError as e:
            logging.debug("get_dynamic_user_agent: failed to persist UA cache: %s", e)

    return ua

def restore_terminal():
    try:
        sys.stdout.write("\033[?7h")
        sys.stdout.flush()
    except (OSError, ValueError): pass

atexit.register(restore_terminal)

# ==============================================================================
# 🐛  DEBUG LOGGING
# ==============================================================================

_SENSITIVE_HEADERS = frozenset({"cookie", "set-cookie", "authorization", "x-auth-token", "x-session-token"})

_STRIP_ANSI_RE = re.compile(r'\033\[[0-9;?]*[A-Za-z]')
def strip_ansi(text):
    return _STRIP_ANSI_RE.sub('', str(text))

_HOME_DIR_STR = str(Path.home())
def _redact_home_path(text):
    text = str(text)
    if _HOME_DIR_STR and _HOME_DIR_STR in text:
        text = text.replace(_HOME_DIR_STR, "~")
    return text

def _redact_proxy_url(proxy_url):
    import urllib.parse
    try:
        parsed = urllib.parse.urlsplit(proxy_url)
        if parsed.username or parsed.password:
            netloc = parsed.hostname or ""
            if parsed.port:
                netloc += f":{parsed.port}"
            return urllib.parse.urlunsplit((parsed.scheme, f"[REDACTED]@{netloc}", parsed.path, parsed.query, parsed.fragment))
        return proxy_url
    except ValueError:
        return proxy_url

def log_request_response(response, *args, **kwargs):
    req = response.request

    logging.debug(strip_ansi(f"=== HTTP {req.method} {req.url} ==="))
    logging.debug("--- REQUEST HEADERS ---")
    for k, v in req.headers.items():
        if k.lower() in _SENSITIVE_HEADERS: logging.debug("%s: [REDACTED]", k)
        else: logging.debug(strip_ansi(f"{k}: {v}"))
    if req.body:
        try:
            body_len = len(req.body)
            logging.debug("--- REQUEST BODY (Size: %d bytes) ---", body_len)
            if body_len < 2000 and not isinstance(req.body, bytes):
                logging.debug(strip_ansi(req.body))
            elif isinstance(req.body, bytes):
                logging.debug("<Binary Data / File Chunk>")
        except TypeError: logging.debug("--- REQUEST BODY (Size: Unknown) ---")
    logging.debug("--- RESPONSE STATUS: %s %s ---", response.status_code, response.reason)
    logging.debug("--- RESPONSE HEADERS ---")
    for k, v in response.headers.items():
        if k.lower() in _SENSITIVE_HEADERS: logging.debug("%s: [REDACTED]", k)
        else: logging.debug(strip_ansi(f"{k}: {v}"))
    logging.debug("--- RESPONSE BODY ---")
    try:
        resp_text = response.text
        logging.debug(strip_ansi(f"{resp_text[:1000]}... (truncated)" if len(resp_text) > 1000 else resp_text))
    except UnicodeDecodeError: logging.debug("<Binary or Unreadable Response>")
    logging.debug("=" * 63 + "\n")

# ==============================================================================
# 🖥️ UI RENDERER
# ==============================================================================

class UIRenderer:
    FINAL_MARKERS = ("✅", "❌", "⏸️", "⚠️")
    MAX_VISIBLE_FINISHED = 15

    def __init__(self, chapter_keys, row_numbers=None, footer_fn=None):
        self.lock = threading.Lock()
        self.sorted_keys = chapter_keys
        self.row_numbers = row_numbers or {}
        self.footer_fn = footer_fn
        self.total_chapters = len(chapter_keys)
        self.completed_chapters = 0

        self.overall_progress = Progress(
            TextColumn("[bold cyan]Overall[/bold cyan]"),
            BarColumn(bar_width=60),
            TaskProgressColumn(),
            TextColumn("[cyan]{task.completed:.0f}/{task.total:.0f} chapters[/cyan]"),
            console=console,
        )
        self.overall_task = self.overall_progress.add_task("overall", total=max(self.total_chapters, 1))

        self.chapter_progress = Progress(
            SpinnerColumn(),
            TextColumn("{task.fields[label]}", justify="left"),
            BarColumn(bar_width=30),
            TaskProgressColumn(),
            DownloadColumn(),
            TransferSpeedColumn(),
            TimeRemainingColumn(),
            console=console,
        )

        self.chapter_tasks = {}
        self.finished_order = deque()
        self._was_done = set()

        renderer = self

        class _Footer:
            def __rich__(self_inner):
                if renderer.footer_fn is None:
                    return Text("")
                try:
                    return renderer.footer_fn() or Text("")
                except Exception:
                    return Text("")

        self.live = Live(
            Group(self.overall_progress, Rule(style="dim cyan"), self.chapter_progress, _Footer()),
            console=console, refresh_per_second=8, transient=False,
        )

    def _label(self, filename, status):
        name = rich_escape(filename if len(filename) <= 40 else filename[:37] + "...")
        row = self.row_numbers.get(filename)
        if row is not None:
            name = f"[dim]#{row}[/dim] {name}"
        if "✅" in status: color = "green"
        elif "❌" in status: color = "red"
        elif "⏸️" in status: color = "yellow"
        elif "⚠️" in status: color = "yellow"
        else: color = "white"
        return f"[{color}]{name}[/{color}]  [dim]{rich_escape(status)}[/dim]"

    def _get_task(self, task_id):
        return next((t for t in self.chapter_progress.tasks if t.id == task_id), None)

    def update_chapter_status(self, chap_key, status, progress=None, current=None, total=None, speed=None, eta=None):
        with self.lock:
            if chap_key not in self.chapter_tasks:
                self.chapter_tasks[chap_key] = self.chapter_progress.add_task(
                    chap_key, total=total, completed=current or 0, label=self._label(chap_key, status)
                )

            task_id = self.chapter_tasks[chap_key]
            task = self._get_task(task_id)

            updates = {"label": self._label(chap_key, status)}
            if total is not None: updates["total"] = total
            if current is not None: updates["completed"] = current
            elif progress is not None and task is not None and task.total:
                updates["completed"] = progress * task.total

            is_final = any(marker in status for marker in self.FINAL_MARKERS)
            if is_final:
                effective_total = total if total is not None else (task.total if task else None)
                if not effective_total:
                    updates["total"] = 1
                    updates["completed"] = 1
                elif "completed" not in updates:
                    updates["completed"] = effective_total

            self.chapter_progress.update(task_id, **updates)

            if is_final:
                if ("✅" in status or "⚠️" in status) and chap_key not in self._was_done:
                    self._was_done.add(chap_key)
                    self.completed_chapters += 1
                    self.overall_progress.update(self.overall_task, completed=self.completed_chapters)
                if chap_key not in self.finished_order:
                    self.finished_order.append(chap_key)
                    self._trim_finished()

    def _trim_finished(self):
        while len(self.finished_order) > self.MAX_VISIBLE_FINISHED:
            oldest = self.finished_order.popleft()
            task_id = self.chapter_tasks.pop(oldest, None)
            if task_id is not None:
                try: self.chapter_progress.remove_task(task_id)
                except KeyError: pass

    def start(self):
        self.live.start()

    def stop(self):
        self.live.stop()

# ==============================================================================
# 🔧 HELPER FUNCTIONS & INTERACTIVE UI
# ==============================================================================

def print_success(msg): console.print(f"[bold green]✅[/bold green] {msg}")
def print_info(msg):    console.print(f"[bold cyan]ℹ️[/bold cyan]  {msg}")
def print_warning(msg): console.print(f"[bold yellow]⚠️[/bold yellow]  {msg}")
def print_error(msg):   console.print(f"[bold red]❌[/bold red] {msg}")

def flush_input_buffer():
    try:
        import msvcrt
        while msvcrt.kbhit(): msvcrt.getch()
    except ImportError:
        import termios
        try:
            if sys.stdin.isatty():
                termios.tcflush(sys.stdin, termios.TCIFLUSH)
        except (termios.error, OSError, ValueError): pass

def prompt(text, default=None, required=True):
    while True:
        prompt_text = f"{text} [{default}]: " if default else f"{text}: "
        try:
            user_input = input(prompt_text).strip()
        except EOFError:
            print_warning("Input closed — exiting.")
            sys.exit(0)
        if not user_input and default is not None: return default
        if required and not user_input:
            print_warning("This field is required.")
            continue
        return user_input

# ==============================================================================
# 🌍 LANGUAGES (full list used by the language autocomplete prompt; folder-name
# auto-guess also uses this list to pre-fill a default)
# ==============================================================================
LANGUAGES = [
    ("ar", "Arabic"), ("bn", "Bengali"), ("bg", "Bulgarian"), ("my", "Burmese"),
    ("zh", "Chinese (Simplified)"), ("zh-hk", "Chinese (Traditional)"), ("cs", "Czech"),
    ("da", "Danish"), ("nl", "Dutch"), ("en", "English"), ("tl", "Filipino"),
    ("fi", "Finnish"), ("fr", "French"), ("ka", "Georgian"), ("de", "German"),
    ("el", "Greek"), ("he", "Hebrew"), ("hi", "Hindi"), ("hu", "Hungarian"),
    ("id", "Indonesian"), ("it", "Italian"), ("ja", "Japanese"), ("ko", "Korean"),
    ("la", "Latin"), ("lt", "Lithuanian"), ("ms", "Malay"), ("mn", "Mongolian"),
    ("no", "Norwegian"), ("fa", "Persian"), ("pl", "Polish"), ("pt", "Portuguese"),
    ("pt-br", "Portuguese (Brazil)"), ("ro", "Romanian"), ("ru", "Russian"),
    ("es", "Spanish"), ("es-la", "Spanish (Latin America)"), ("sv", "Swedish"),
    ("th", "Thai"), ("tr", "Turkish"), ("uk", "Ukrainian"), ("vi", "Vietnamese"),
]

def _guess_language_from_path(directory):
    """Checks folder names in the path (right to left) for a language code or
    name match (e.g. a folder named 'French' or 'fr') to pre-fill a default.
    Falls back to None (caller decides the ultimate default) if nothing matches."""
    if not directory:
        return None
    lang_map = {}
    for code, name in LANGUAGES:
        lang_map[code.lower()] = code
        lang_map[name.lower()] = code
    for part in reversed(Path(directory).parts):
        clean_part = part.strip().lower()
        if clean_part in lang_map:
            return lang_map[clean_part]
    return None

def ask_autocomplete(message, choices, default=None, required=True, meta_information=None):
    """Like prompt(), but with type-to-filter suggestions (questionary.autocomplete).
    meta_information (optional): dict of {choice: hint_text}, shown alongside each
    suggestion when the list is displayed (e.g. Tab pressed with empty input)."""
    while True:
        try:
            answer = questionary.autocomplete(
                message,
                choices=choices,
                default=default or "",
                qmark="?",
                meta_information=meta_information,
            ).ask()
        except KeyboardInterrupt:
            answer = None

        if answer is None:
            print_warning("No selection made — exiting.")
            sys.exit(0)

        answer = answer.strip()
        if not answer and default is not None:
            return default
        if required and not answer:
            print_warning("This field is required.")
            continue
        return answer

def ask_select(message, choices, default=None, auto_number=True):
    use_shortcuts = auto_number if len(choices) <= 36 else False
    try:
        answer = questionary.select(
            message,
            choices=choices,
            default=default,
            qmark="?",
            use_shortcuts=use_shortcuts
        ).ask()
    except KeyboardInterrupt:
        answer = None

    if answer is None:
        print_warning("No selection made — exiting.")
        sys.exit(0)
    return answer

def ask_confirm(message, default=True):
    choices = [questionary.Choice(title="Yes", value=True), questionary.Choice(title="No", value=False)]
    if not default:
        choices.reverse()
    return ask_select(message, choices, auto_number=False)

def parse_number_ranges(text, valid_numbers=None):
    result = set()
    unmatched = []
    valid_set = set(valid_numbers) if valid_numbers is not None else None

    def _to_num(s):
        s = s.strip()
        try:
            return int(s) if float(s) == int(float(s)) else float(s)
        except ValueError:
            return None

    for raw_token in text.split(","):
        token = raw_token.strip()
        if not token:
            continue
        if "-" in token[1:]:  # skip leading '-' for negative-safety, not expected but harmless
            left, _, right = token.partition("-")
            lo, hi = _to_num(left), _to_num(right)
            if lo is None or hi is None:
                unmatched.append(token)
                continue
            if lo > hi:
                lo, hi = hi, lo
            if valid_set is not None:
                matches = {n for n in valid_set if lo <= n <= hi}
                if not matches:
                    unmatched.append(token)
                result |= matches
            else:
                # No known valid set — expand integer range only
                if isinstance(lo, float) or isinstance(hi, float):
                    unmatched.append(token)
                else:
                    result |= set(range(int(lo), int(hi) + 1))
        else:
            n = _to_num(token)
            if n is None:
                unmatched.append(token)
                continue
            if valid_set is not None and n not in valid_set:
                unmatched.append(token)
                continue
            result.add(n)

    return result, unmatched

def ask_number_range(message, valid_numbers, allow_all=False):
    valid_sorted = sorted(valid_numbers)
    lo, hi = (valid_sorted[0], valid_sorted[-1]) if valid_sorted else (None, None)
    hint = f" (available: {fmt_num(lo)}\u2013{fmt_num(hi)})" if lo is not None else ""
    while True:
        raw = prompt(f"{message}{hint}", default="" if allow_all else None, required=not allow_all)
        if allow_all and not raw:
            return None
        matched, unmatched = parse_number_ranges(raw, valid_numbers=valid_numbers)
        if unmatched:
            print_warning(f"Not found / invalid: {', '.join(str(u) for u in unmatched)}. Try again.")
            continue
        if not matched:
            print_warning("No chapters matched that range. Try again.")
            continue
        return matched

def fmt_num(n):
    return str(int(n)) if isinstance(n, (int, float)) and float(n) == int(n) else str(n)

def to_full_cover_url(photo):
    if not photo: return None
    return photo if photo.startswith(("http://", "https://")) else f"{BASE_URL}{photo}"

def fetch_manga_brief(manga_id, session):
    try:
        res = session.get(f"{BASE_URL}/api/manga/{manga_id}", timeout=15)
        if res.status_code == 200:
            data = res.json().get("manga", {})
            title = data.get("title")
            if title: return title, to_full_cover_url(data.get("photo", ""))
    except requests.exceptions.RequestException as e:
        logging.debug("fetch_manga_brief(%s): network error: %s", manga_id, e)
        print_warning(f"Network error while looking up manga ID {manga_id}: {e}")
    except json.JSONDecodeError as e:
        logging.debug("fetch_manga_brief(%s): bad JSON response: %s", manga_id, e)
        print_warning(f"Unexpected response while looking up manga ID {manga_id} — the site API may have changed.")
    return None, None

def _render_cover(image_url: str, session: requests.Session, silent: bool = False) -> None:
    if shutil.which('chafa') is None:
        return

    try:
        resp = session.get(image_url, timeout=10)
        resp.raise_for_status()
        tmp = tempfile.NamedTemporaryFile(suffix='.jpg', delete=False)
        tmp.write(resp.content)
        tmp.close()
        try:
            subprocess.run(['chafa', '--size=20x30', tmp.name], stderr=subprocess.DEVNULL, check=False)
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass
    except (requests.exceptions.RequestException, OSError) as e:
        if not silent:
            print_warning(f"Could not display cover art: {e}")
            print_info(f"Cover: {image_url}")

def show_cover(image_url: str, session: requests.Session):
    _render_cover(image_url, session, silent=False)

def _norm_filepath(path):
    return os.path.normcase(os.path.normpath(path))

def natural_sort_key(s):
    def encode(text):
        value = float(text)
        if value < 0:
            inverted = 10 ** 12 + value
            return f"0{inverted:015.4f}"
        return f"1{value:015.4f}"

    return [encode(text) if re.match(r'^\d+(?:\.\d+)?$', text) else text.lower()
            for text in re.split(r'(\d+(?:\.\d+)?)', str(s))]

def encode_tus_metadata(meta_dict):
    pairs = []
    for k, v in meta_dict.items():
        if v is None: continue
        if isinstance(v, list):
            val_str = json.dumps(v)
        elif isinstance(v, float) and v.is_integer():
            val_str = str(int(v))
        else:
            val_str = str(v)
        encoded_val = base64.b64encode(val_str.encode('utf-8')).decode('utf-8')
        pairs.append(f"{k} {encoded_val}")
    return ",".join(pairs)

def _extract_bracket_groups(name_without_ext):
    bracket_re = re.compile(r'\[([A-Za-z][^\]]*?)\]')
    raw_groups = []
    clean_name = name_without_ext
    for m in bracket_re.finditer(name_without_ext):
        content = m.group(1).strip()
        names = [n.strip() for n in content.split(',') if n.strip()]
        raw_groups.extend(names)
        clean_name = clean_name.replace(m.group(0), '')
    return raw_groups, clean_name.strip(' -_')

def _extract_parenthesis_groups(name_without_ext):
    paren_re = re.compile(r'\(([A-Za-z0-9][^\)]*?)\)')
    raw_groups = []
    clean_name = name_without_ext
    for m in paren_re.finditer(name_without_ext):
        content = m.group(1).strip()
        if not content or re.match(r'^\d{4}$', content): continue
        names = [n.strip() for n in content.split(',') if n.strip()]
        raw_groups.extend(names)
        clean_name = clean_name.replace(m.group(0), '')
    return raw_groups, clean_name.strip(' -_')

def parse_custom_regex_input(raw):
    renames = []
    extractor = None
    if not raw:
        return renames, extractor

    parts = [p for p in raw.split(';;') if p.strip()]
    for part in parts:
        if '->' in part:
            pattern, replacement = part.split('->', 1)
            pattern = pattern.strip().strip("'\"")
            replacement = replacement.strip().strip("'\"")
            if pattern:
                try:
                    compiled = re.compile(pattern)
                    compiled.sub(replacement, "")
                    renames.append((pattern, replacement))
                except re.error as e:
                    print_warning(f"Ignoring invalid custom regex rule '{part.strip()}': {e}")
        else:
            pattern = part.strip().strip("'\"")
            if pattern:
                try:
                    compiled = re.compile(pattern, re.IGNORECASE)
                    if compiled.groups >= 1:
                        extractor = compiled
                    else:
                        print_warning(f"Custom regex '{pattern}' has no capture group () — ignoring, nothing to extract.")
                except re.error as e:
                    print_warning(f"Ignoring invalid custom regex pattern '{pattern}': {e}")

    return renames, extractor

def _ask_chapter_naming():
    chapter_naming = ask_select("Chapter naming format?", [
        questionary.Choice(title="Force 'Chapter X' (Default)", value="preset"),
        questionary.Choice(title="Auto-detect title (Recommended)", value="extract"),
        questionary.Choice(title="Auto-detect title (Advanced)", value="advanced"),
    ])

    custom_regex = None
    custom_renames = None
    advanced_strip_groups = False

    if chapter_naming == "advanced":
        chapter_naming = "extract"  # advanced options augment auto-detect, they don't replace it
        adv_choices = questionary.checkbox(
            "Advanced auto-detect options (space to toggle, enter to confirm):",
            choices=[
                questionary.Choice(title="Custom regex...", value="regex"),
                questionary.Choice(title="Strip bracket/parenthesis groups before detection", value="strip_groups"),
            ],
            qmark="?",
        ).ask()
        if adv_choices is None:
            print_warning("No selection made — exiting.")
            sys.exit(0)

        if "regex" in adv_choices:
            print_info("Regex Tip: Use a capture group () to extract a title, or 'Find -> Replace' to rename.")
            custom_regex_input = prompt("Enter your regex pattern")
            custom_renames, custom_regex = parse_custom_regex_input(custom_regex_input)
        if "strip_groups" in adv_choices:
            advanced_strip_groups = True

    return chapter_naming, custom_regex, custom_renames, advanced_strip_groups

# Cyrillic/Greek characters that are visually identical or near-identical to Latin
# letters and can accidentally end up in filenames (e.g. pasted from a source using
# a different keyboard layout or font). Without normalizing these, a filename like
# "Сh.002" (Cyrillic С) fails to match the chapter/episode label regex entirely,
# since it only recognizes Latin "ch"/"chapter"/"episode"/"ep".
_HOMOGLYPH_MAP = {
    'А': 'A', 'а': 'a', 'В': 'B', 'С': 'C', 'с': 'c', 'Е': 'E', 'е': 'e',
    'Н': 'H', 'І': 'I', 'і': 'i', 'Ѕ': 'S', 'О': 'O', 'о': 'o', 'Р': 'P',
    'р': 'p', 'Т': 'T', 'т': 't', 'Х': 'X', 'х': 'x', 'Ү': 'Y',
}
_HOMOGLYPH_TABLE = str.maketrans(_HOMOGLYPH_MAP)

def normalize_homoglyphs(text):
    return text.translate(_HOMOGLYPH_TABLE)

def strip_leading_zeros_in_title(text):
    return re.sub(r'\b0+(\d+)\b', r'\1', text)

def compile_removal_pattern(pattern_input):
    looks_like_regex = bool(re.search(r'\\[dwsSDWbB]|[*+?^$|]|\{\d*,?\d*\}', pattern_input))
    if looks_like_regex:
        try:
            re.compile(pattern_input)
            return pattern_input
        except re.error:
            return re.escape(pattern_input)
    return re.escape(pattern_input)

def apply_removal_pattern(pattern, text):
    try:
        result = re.sub(pattern, "", text, flags=re.IGNORECASE).strip()
        result = re.sub(r'\(\s*\)|\[\s*\]', '', result)
        result = re.sub(r'\s{2,}', ' ', result).strip(' -_')
        return result if result else None
    except re.error:
        return None

def parse_filename_details(filename, upload_type="chapter", chapter_naming="extract", custom_regex=None, strip_groups=False, custom_renames=None):
    name_no_ext = re.sub(r'\.(cbz|zip)$', '', filename, flags=re.IGNORECASE)

    if upload_type == "volume":
        raw_groups, name_clean = _extract_parenthesis_groups(name_no_ext)
    else:
        raw_groups, name_clean = _extract_bracket_groups(name_no_ext)

    if not strip_groups:
        name_clean = name_no_ext

    if custom_renames:
        for pattern, replacement in custom_renames:
            try:
                name_clean = re.sub(pattern, replacement, name_clean, flags=re.IGNORECASE)
            except re.error:
                continue

    custom_extracted_title = None
    if custom_regex:
        try:
            extractor = custom_regex if hasattr(custom_regex, 'search') else re.compile(custom_regex, re.IGNORECASE)
            m = extractor.search(name_no_ext)
            if m and extractor.groups >= 1:
                extracted = m.group(1).strip()
                if extracted:
                    custom_extracted_title = extracted
        except re.error:
            pass

    num = None
    num_source = None
    episode_label_num = None
    num_came_from_episode_label = False 

    if upload_type == "volume":
        num_pattern = r'(?i)(?:(?:\b|_)?(?:volume|vol)|(?:\b|_)v)[\.\-_\s]*(\d+(?:\.\d+)?)'
    else:
        # Latin-script chapter labels: English/British (chapter/chap/ch),
        # German (kapitel/kap), French (chapitre/chap), Spanish/Portuguese
        # (capitulo/capítulo/cap), plus episode/ep.
        num_pattern = (
            r"(?i)(?:(?:\b|_)?"
            r"(?:chap['\-]?t?er|chapter|chap|ch"  # incl. "chap'er"/"chaper" stylized typo
            r'|kapitel|kap'
            r'|chapitre'
            r'|cap[ií]tulo|cap'
            r'|episode|ep)'
            r'|(?:\b|_)c)'
            r'[\.\-_\s]*(\d+(?:\.\d+)?)'
        )

    matches = list(re.finditer(num_pattern, normalize_homoglyphs(name_clean)))

    # CJK chapter labels (Chinese/Japanese/Korean) have no Latin word boundary
    # and the number sits between marker characters (e.g. "第5章", "5話",
    # "제5화"), so they need a separate pattern rather than a regex alternate.
    # Only checked as a fallback when the Latin pattern above finds nothing,
    # so behavior for existing/working Latin-script filenames is unchanged.
    if upload_type != "volume" and not matches:
        cjk_pattern = (
            r'第?\s*(\d+(?:\.\d+)?)\s*(?:章|話|话|回)'   # Chinese/Japanese
            r'|제?\s*(\d+(?:\.\d+)?)\s*(?:화|장)'          # Korean
        )
        cjk_matches = list(re.finditer(cjk_pattern, name_clean))
        if cjk_matches:
            # Normalize into the same shape as a single Latin match so the
            # logic below (single-match branch) can handle it unchanged:
            # fabricate an object with .group(0)/.group(1)/.start()/.end().
            class _CjkMatch:
                def __init__(self, m):
                    self._m = m
                    self._num = m.group(1) or m.group(2)
                def group(self, i):
                    return self._m.group(0) if i == 0 else self._num
                def start(self):
                    return self._m.start()
                def end(self):
                    return self._m.end()
            matches = [_CjkMatch(m) for m in cjk_matches]

    if len(matches) > 1:
        num = float(matches[0].group(1))
        num_source = "sequence_index"
        episode_label_num = float(matches[-1].group(1))
        
        if 'ep' in matches[-1].group(0).lower() or 'episode' in matches[-1].group(0).lower():
            num_came_from_episode_label = True
        name_clean = name_clean[:matches[0].start()] + name_clean[matches[0].end():]
        
    elif len(matches) == 1:
        val = float(matches[0].group(1))
        matched_str = matches[0].group(0).lower()
        has_explicit_label = bool(re.search(r'(?i)chapter|ch\b|episode|ep\b', matched_str))
        is_bare_sequence_prefix = bool(re.fullmatch(r'ch\d+', matched_str)) and not has_explicit_label

        if matches[0].start() == 0 and is_bare_sequence_prefix:
            num = val
            num_source = "sequence_index"
            episode_label_num = None
        else:
            num = val
            num_source = "chapter_or_volume_label"
            episode_label_num = val
            if 'ep' in matched_str or 'episode' in matched_str:
                num_came_from_episode_label = True
                
        name_clean = name_clean[:matches[0].start()] + name_clean[matches[0].end():]
    else:
        leading_prefix_match = re.match(r'^0*(\d+(?:\.\d+)?)[\s\-_\.]+', name_clean)
        if leading_prefix_match:
            num = float(leading_prefix_match.group(1))
            num_source = "fallback"
            name_clean = name_clean[:leading_prefix_match.start()] + name_clean[leading_prefix_match.end():]
        else:
            all_nums = [(m.group(1), m) for m in re.finditer(r'(?<!\d)(\d+(?:\.\d+)?)(?!\d)', name_clean)]
            if all_nums:
                valid_nums = [n for n in all_nums if not (len(n[0]) == 4 and n[0].startswith(('19', '20')))]
                target = valid_nums[-1] if valid_nums else all_nums[-1]
                num = float(target[0])
                num_source = "fallback"
                name_clean = name_clean[:target[1].start()] + name_clean[target[1].end():]

    if num is None:
        return None, [], raw_groups, None, None, None


    if upload_type == "volume":
        return num, [("Vol. N.NN", f"Vol. {num:.2f}")], raw_groups, "volume", num_source, None
    if chapter_naming == "preset":
        return num, [("Chapter N", f"Chapter {num:g}")], raw_groups, "preset", num_source, episode_label_num

    had_season = bool(re.search(r'(?i)[\(\[\s]*s(?:eason)?[\.\-_\s]*\d+[\)\]\s]*', name_clean))
    had_episode_label = episode_label_num is not None
    had_chapter_label = (not num_came_from_episode_label and upload_type != "volume" and
                          bool(re.search(r'(?i)(?:\b|_)?(?:chapter|ch)[\.\-_\s]*\d+(?:\.\d+)?', name_clean)))
    had_leading_prefix = bool(re.match(r'^0*\d+[\s\-_\.]+', name_clean))

    def wash_title(s):
        s = s.replace('_', ' ')
        s = re.sub(r'\s+[\.\~\|]+', ' - ', s)
        s = re.sub(r'\bv\d+\b', '', s, flags=re.IGNORECASE)
        s = re.sub(r'^[\s\-\.\~\|]+|[\s\-\.\~\|]+$', '', s)
        s = re.sub(r'\s{2,}', ' ', s)
        s = re.sub(r'\s+-\s+', ' - ', s)
        return s.strip()

    minimal_wash = wash_title(name_clean)

    def _season_bracketed_sub(m):
        season_num = int(m.group(1))
        trailing = m.group(2).strip()
        tag = f" (S{season_num}) "
        return f"{tag}{trailing} " if trailing else tag

    name_clean = re.sub(
        r'(?i)[\(\[]\s*s(?:eason)?[\.\-_\s]*(\d+)\s*([^\)\]]*)[\)\]]',
        _season_bracketed_sub,
        name_clean
    )

    name_clean = re.sub(
        r'(?i)(?<!\()(?:\b|_)s(?:eason)?[\.\-_\s]*(\d+)\b',
        lambda m: f" (S{int(m.group(1))}) ",
        name_clean
    )
    name_clean = re.sub(r'(?i)(?:\b|_)?(?:episode|ep)[\.\-_\s]*(\d+(?:\.\d+)?)', lambda m: f" Episode {float(m.group(1)):g} ", name_clean)

    candidates = []
    seen_texts = set()

    def add_candidate(label, text):
        text = text.strip()
        if text and text not in seen_texts:
            candidates.append((label, text))
            seen_texts.add(text)

    washed_full = wash_title(name_clean)
    default_label = "Full title (as detected)"

    if not washed_full:
        fallback_word = "Episode" if had_episode_label or re.search(r'(?i)(episode|ep)', filename) else "Chapter"
        add_candidate(default_label, f"{fallback_word} {num:g}")
    else:
        add_candidate(default_label, washed_full)

        if had_episode_label and "Episode " in washed_full:
            no_ep = re.sub(r'(?i)Episode\s*\d+(?:\.\d+)?[\s\-\.\~\|]*', '', washed_full)
            no_ep = wash_title(no_ep)
            add_candidate("Without episode label", no_ep)

        if had_chapter_label:
            no_ch = re.sub(r'(?i)(?:\b|_)?(?:chapter|ch)[\.\-_\s]*\d+(?:\.\d+)?[\s\-\.\~\|]*', '', washed_full)
            no_ch = wash_title(no_ch)
            add_candidate("Without chapter label", no_ch)

        if had_season:
            no_season = re.sub(r'(?i)\(S\d+\)\s*', '', washed_full)
            no_season = wash_title(no_season)
            add_candidate("Without season tag", no_season)

            if had_episode_label:
                bare = re.sub(r'(?i)\(S\d+\)\s*', '', washed_full)
                bare = re.sub(r'(?i)Episode\s*\d+(?:\.\d+)?[\s\-\.\~\|]*', '', bare)
                bare = wash_title(bare)
                add_candidate("Bare title only", bare)

        if had_leading_prefix:
            def _strip_leading_prefix(text):
                stripped = re.sub(r'^0*\d+[\s\-_\.]+', '', text)
                return wash_title(stripped)

            for label, text in list(candidates):
                no_prefix = _strip_leading_prefix(text)
                if no_prefix != text:
                    if label == default_label:
                        add_candidate("Without leading number", no_prefix)
                    else:
                        add_candidate(f"{label}, without leading number", no_prefix)

    if had_season or had_episode_label or had_chapter_label or had_leading_prefix:
        add_candidate("Minimal (only number removed)", minimal_wash)

    if upload_type != "volume":
        add_candidate("Chapter N", f"Chapter {num:g}")
        add_candidate("Episode N", f"Episode {num:g}")

    if custom_extracted_title:
        candidates = [(l, t) for l, t in candidates if t != custom_extracted_title]
        candidates.insert(0, ("Custom regex extraction", custom_extracted_title))

    if not candidates:
        candidates = [(default_label, f"Chapter {num:g}")]

    shape_key = (f"season={had_season}|episode_label={had_episode_label}|"
                 f"chapter_label={had_chapter_label}|leading_prefix={had_leading_prefix}|"
                 f"custom={bool(custom_extracted_title)}")

    return num, candidates, raw_groups, shape_key, num_source, episode_label_num

ARCHIVE_IMAGE_EXTS = ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp', '.avif')

def validate_archive(filepath):
    try:
        with zipfile.ZipFile(filepath) as zf:
            namelist = zf.namelist()
            file_names = (n for n in namelist if not n.endswith('/'))
            has_any = False
            has_image = False
            for n in file_names:
                has_any = True
                if n.lower().endswith(ARCHIVE_IMAGE_EXTS):
                    has_image = True
                    break
            if not has_any:
                return "archive is empty"
            if not has_image:
                return "no image files inside"
    except zipfile.BadZipFile:
        return "not a valid ZIP/CBZ archive"
    except (OSError, EOFError) as e:
        return f"unreadable archive ({str(e)[:40]})"
    return None

def _correct_episode_drift(parsed):
    drift_detected = any(
        item.get("episode_label_num") is not None and item["episode_label_num"] != item["number"]
        for item in parsed
    )
    has_real_labels = any(item.get("episode_label_num") is not None for item in parsed)

    if not drift_detected or not has_real_labels:
        return

    # Prompt the user if a major numbering collision (like a Season reset) is found
    conflicts = [item for item in parsed if item.get("episode_label_num") is not None and item["episode_label_num"] != item["number"]]
    
    if conflicts:
        drifts = [item['number'] - item['episode_label_num'] for item in conflicts]
        distinct_drifts = sorted(set(round(d, 4) for d in drifts))

        console.print()
        console.rule("[bold yellow]Numbering Conflict Detected[/bold yellow]")
        print_info("Filename sequence and Episode labels disagree (this can happen after a season reset, inserted specials, or renumbering).")
        print_info(f"{len(conflicts)} file(s) affected.")
        if len(distinct_drifts) == 1:
            print_info(f"Drift is consistent: File Index is always {distinct_drifts[0]:+g} relative to Episode Label.")
        else:
            print_info(f"[yellow]Drift is NOT consistent — {len(distinct_drifts)} different drift amounts found ({distinct_drifts[0]:+g} to {distinct_drifts[-1]:+g}).[/yellow]")
            print_info("[yellow]A single choice below may not be correct for every file — consider reviewing individual titles afterward.[/yellow]")
        print_info(f"Example: '{conflicts[0]['filename']}'")
        print_info(f" -> File Index:    [magenta]{conflicts[0]['number']:g}[/magenta]")
        print_info(f" -> Episode Label: [cyan]{conflicts[0]['episode_label_num']:g}[/cyan]\n")
        
        example_file_index = conflicts[0]['number']
        example_episode_label = conflicts[0]['episode_label_num']

        choice = ask_select(
            "How should these be sorted on MangaDot?",
            choices=[
                questionary.Choice(title=f"Continuous (Use File Index -> Ch {example_file_index:g})", value="continuous"),
                questionary.Choice(title=f"Trust Labels (Use Label -> Ch {example_episode_label:g})", value="reset")
            ]
        )
        if choice == "continuous":
            return  # Bypass drift correction entirely; the chXXXX prefixes handle the exact order

    for item in parsed:
        item["original_num"] = item["number"]

    ordered = sorted(parsed, key=lambda x: x["original_num"])

    for item in ordered:
        if item.get("episode_label_num") is not None:
            item["number"] = item["episode_label_num"]

    i = 0
    while i < len(ordered):
        if ordered[i].get("episode_label_num") is None:
            start = i
            while i < len(ordered) and ordered[i].get("episode_label_num") is None:
                i += 1
            prev_val = ordered[start - 1]["number"] if start > 0 else 0.0
            block = ordered[start:i]
            n = len(block)
            if i < len(ordered) and ordered[i]["number"] > prev_val:
                next_val = ordered[i]["number"]
            else:
                next_val = prev_val + n + 1.0

            gap = next_val - prev_val

            if n == 1:
                block[0]["number"] = round(prev_val + gap / 2, 6)
            elif gap >= n + 1:
                for k, item in enumerate(block):
                    item["number"] = round(prev_val + (k + 1), 6)
            else:
                pad = 2 if n > 9 else 1
                base = int(prev_val)
                step = 1 / (10 ** pad)
                for k, item in enumerate(block):
                    frac = (k + 1) * step
                    proposed = round(base + frac, pad + 4)
                    # base is int(prev_val): when prev_val is itself fractional (e.g. 5.5),
                    # base + 0.1 = 5.1 would sort before it. Fall back in both directions.
                    if proposed <= prev_val or proposed >= next_val:
                        # Fall back to splitting the remaining gap evenly instead.
                        proposed = round(prev_val + gap * (k + 1) / (n + 1), 6)
                    item["number"] = proposed
        else:
            i += 1

    # Fix the desynced text titles
    for item in ordered:
        old_num = item["original_num"]
        new_num = item["number"]
        if old_num != new_num:
            updated_candidates = []
            for label, text in item["candidates"]:
                text = re.sub(rf'(?i)(Chapter|Episode)\s+{re.escape(format(old_num, "g"))}\b', rf'\g<1> {new_num:g}', text)
                updated_candidates.append((label, text))
            item["candidates"] = updated_candidates

def get_files_in_dir(directory, upload_type, chapter_naming="extract", custom_regex=None, strip_groups=False, validate=True, custom_renames=None, select_subset=False, picker_style="range"):
    valid_extensions = ('.cbz', '.zip')
    parsed = []

    if not directory or not os.path.isdir(directory):
        print_error(f"Invalid or missing directory: {directory}")
        return []

    try:
        with os.scandir(directory) as it:
            for entry in it:
                if not entry.is_file() or not entry.name.lower().endswith(valid_extensions):
                    continue

                filepath = entry.path
                filename = entry.name

                num, candidates, file_groups, shape_key, num_source, episode_label_num = parse_filename_details(
                    filename, upload_type, chapter_naming, custom_regex, strip_groups, custom_renames
                )

                if num is None:
                    print_warning(f"Could not detect {upload_type} number from '{filename}'. Skipping.")
                    continue

                parsed.append({
                    "entry": entry, "filepath": filepath, "filename": filename,
                    "number": num, "candidates": candidates, "groups": file_groups,
                    "shape_key": shape_key, "num_source": num_source,
                    "episode_label_num": episode_label_num,
                })
    except OSError as e:
        print_error(f"Error scanning directory {directory}: {e}")
        return []

    if upload_type == "chapter":
        _correct_episode_drift(parsed)

    parsed.sort(key=lambda x: x["number"])

    if select_subset and parsed:
        unit = "volume" if upload_type == "volume" else "chapter"
        console.print()
        print_info(f"Found {len(parsed)} {unit}(s) in this folder.")

        if picker_style == "checkbox":
            plan_choice = ask_select(f"Upload all {len(parsed)} {unit}(s)?", [
                questionary.Choice(title=f"Upload all {len(parsed)} file(s)", value="all"),
                questionary.Choice(title="Choose files to upload…", value="pick"),
                questionary.Choice(title="Cancel", value="cancel"),
            ], auto_number=False)
            if plan_choice == "cancel":
                print_info("Upload aborted by user.")
                sys.exit(0)
            if plan_choice == "pick":
                while True:
                    try:
                        picked = questionary.checkbox(
                            f"Select the {unit}(s) to upload:",
                            choices=[
                                questionary.Choice(
                                    title=item["filename"], value=item["filename"], checked=True,
                                ) for item in parsed
                            ],
                            qmark="?",
                        ).ask()
                    except KeyboardInterrupt:
                        picked = None
                    if picked is None:
                        print_warning("No selection made — exiting.")
                        sys.exit(0)
                    if not picked:
                        print_warning("No files selected — pick at least one, or cancel.")
                        continue
                    picked_set = set(picked)
                    parsed = [item for item in parsed if item["filename"] in picked_set]
                    print_success(f"Selected {len(parsed)} {unit}(s) to upload.\n")
                    break
        else:
            upload_all = ask_confirm(f"Upload all {len(parsed)} {unit}(s)?", default=True)
            if not upload_all:
                valid_numbers = [item["number"] for item in parsed]
                chosen_numbers = ask_number_range(
                    f"Which {unit}s do you want to upload? (e.g. '103-108,110,115-117')",
                    valid_numbers=valid_numbers
                )
                parsed = [item for item in parsed if item["number"] in chosen_numbers]
                print_success(f"Selected {len(parsed)} {unit}(s) to upload.\n")

    shape_key_counts = Counter(item["shape_key"] for item in parsed)

    shape_choices = {}
    range_choices = {}  # shape_key -> list of (number_set, chosen_label, cached-form for lookup)
    files_data = []

    def _pick_candidate_title(filename, candidates, match_count, scope_desc):
        """Runs the interactive multi-candidate picker once and returns (final_title, chosen_label)."""
        choices = [
            questionary.Choice(title=f"{label}: {text}", value=str(i))
            for i, (label, text) in enumerate(candidates)
        ]
        choices.append(questionary.Choice(title="Remove word/phrase (regex)...", value="__regex_remove__"))
        choices.append(questionary.Choice(title="Remove unnecessary leading zeros...", value="__strip_zeros__"))
        choices.append(questionary.Choice(title="Type my own...", value="__custom__"))
        console.print()
        while True:
            selection = ask_select(
                f"Select title for '{filename}' (applies to {scope_desc}):",
                choices=choices,
                auto_number=True
            )
            if selection == "__custom__":
                candidate_title = prompt(f"Enter custom title for '{filename}'", default=candidates[0][1]).strip() or candidates[0][1]
                candidate_label = None
            elif selection == "__regex_remove__":
                base_label, base_text = candidates[0]
                print_info(f"Base title: \"{base_text}\"")
                pattern_input = prompt("Enter word/phrase to remove (plain text, or a regex pattern)")
                if not pattern_input:
                    continue
                pattern = compile_removal_pattern(pattern_input)
                candidate_title = apply_removal_pattern(pattern, base_text)
                if candidate_title is None:
                    print_warning("Removing that would leave an empty title — try a narrower pattern.")
                    continue
                candidate_label = {"type": "regex_remove", "pattern": pattern}
            elif selection == "__strip_zeros__":
                base_label, base_text = candidates[0]
                candidate_title = strip_leading_zeros_in_title(base_text)
                if candidate_title == base_text:
                    print_info("No unnecessary leading zeros found in this title.")
                candidate_label = {"type": "strip_zeros"}
            else:
                candidate_label, candidate_title = candidates[int(selection)]

            if match_count > 1:
                confirmed = ask_confirm(
                    f"Use \"{candidate_title}\" as the title? This applies to {scope_desc}. Confirm?",
                    default=True
                )
            else:
                confirmed = ask_confirm(
                    f"Use \"{candidate_title}\" as the title for '{filename}'? Confirm?",
                    default=True
                )
            if confirmed:
                return candidate_title, candidate_label
            # Not confirmed: loop back and let the user pick again

    def _apply_cached(cached, candidates, num):
        if isinstance(cached, dict) and cached.get("type") == "regex_remove":
            base_label, base_text = candidates[0] if candidates else ("Full title (as detected)", f"Chapter {num:g}")
            return apply_removal_pattern(cached["pattern"], base_text) or base_text
        if isinstance(cached, dict) and cached.get("type") == "strip_zeros":
            base_label, base_text = candidates[0] if candidates else ("Full title (as detected)", f"Chapter {num:g}")
            return strip_leading_zeros_in_title(base_text)
        by_label = {l: t for l, t in candidates}
        if cached in by_label:
            return by_label[cached]
        elif candidates:
            return candidates[0][1]
        return f"Chapter {num:g}"

    for item in parsed:
        filename    = item["filename"]
        filepath    = item["filepath"]
        entry       = item["entry"]
        num         = item["number"]
        candidates  = item["candidates"]
        file_groups = item["groups"]
        shape_key   = item["shape_key"]

        matched_range_choice = None
        for number_set, chosen_label in range_choices.get(shape_key, []):
            if num in number_set:
                matched_range_choice = chosen_label
                break

        if matched_range_choice is not None:
            final_title = _apply_cached(matched_range_choice, candidates, num)
            chosen_label = matched_range_choice
        elif shape_key in shape_choices:
            cached = shape_choices[shape_key]
            final_title = _apply_cached(cached, candidates, num)
            chosen_label = cached
        elif candidates:
            chosen_label = None
            if len(candidates) == 1:
                label, text = candidates[0]
                console.print()
                confirmed = ask_confirm(f"'{filename}' -> {label}: \"{text}\". Use this for matching files?", default=True)
                if confirmed:
                    final_title = text
                    chosen_label = label
                else:
                    final_title = prompt(f"Enter title for '{filename}'", default=text).strip() or text
            else:
                match_count = shape_key_counts.get(shape_key, 1)
                scope = "all similarly-formatted files"
                if match_count > 1:
                    applies_to = ask_select(
                        f"Select title for '{filename}' applies to:",
                        choices=[
                            questionary.Choice(title="All similarly-formatted files", value="all"),
                            questionary.Choice(title="Choose your chapter range from similarly-formatted files", value="range"),
                        ],
                        auto_number=True
                    )
                    if applies_to == "range":
                        same_shape_numbers = [p["number"] for p in parsed if p["shape_key"] == shape_key]
                        chosen_numbers = ask_number_range(
                            "Which chapters should this title choice apply to?",
                            valid_numbers=same_shape_numbers
                        )
                        scope = f"{len(chosen_numbers)} chosen chapter(s)"
                        final_title, candidate_label = _pick_candidate_title(filename, candidates, len(chosen_numbers), scope)
                        range_choices.setdefault(shape_key, []).append((chosen_numbers, candidate_label))
                        chosen_label = None  # do not memoize to shape_choices — this was range-scoped only
                    else:
                        final_title, chosen_label = _pick_candidate_title(filename, candidates, match_count, scope)
                else:
                    final_title, chosen_label = _pick_candidate_title(filename, candidates, match_count, scope)
            if chosen_label is not None:
                shape_choices[shape_key] = chosen_label
        else:
            final_title = f"Chapter {num:g}"

        if validate:
            archive_err = validate_archive(filepath)
            if archive_err:
                print_warning(f"Skipping '{filename}': {archive_err}.")
                continue

        try:
            file_size = entry.stat().st_size
            if file_size == 0:
                print_warning(f"Skipping '{filename}': File is empty (0 bytes).")
                continue
        except OSError as e:
            print_warning(f"Skipping '{filename}': Could not read file size ({e}).")
            continue

        files_data.append({
            "filepath": filepath, "filename": filename,
            "norm_filepath": _norm_filepath(filepath),
            "number": num, "title": final_title, "size": file_size,
            "groups": file_groups, "shape_key": shape_key, "candidates": candidates,
        })

    files_data.sort(key=lambda x: x["number"])
    return files_data

def fmt_size(bytes_: int) -> str:
    if bytes_ == 0:
        return "0 B"
    gb = bytes_ / (1024 ** 3)
    if gb >= 1:
        return f"{gb:.2f} GB"
    mb = bytes_ / (1024 ** 2)
    if mb >= 1:
        return f"{mb:.2f} MB"
    kb = bytes_ / 1024
    if kb >= 1:
        return f"{kb:.2f} KB"
    return f"{bytes_} B"

def fmt_duration(seconds) -> str:
    seconds = int(seconds)
    h, rem  = divmod(seconds, 3600)
    m, s    = divmod(rem, 60)
    if h: return f"{h}h {m}m {s}s"
    if m: return f"{m}m {s}s"
    return f"{s}s"

def _pick_files_for_edit(files):
    """Ask for a number range or a filename search; returns the chosen files."""
    scope = ask_select("Apply to:", choices=[
        questionary.Choice(title="A chapter/number range (e.g. '103-108,110')", value="range"),
        questionary.Choice(title="A single file (search by filename)", value="single"),
        questionary.Choice(title="Cancel", value="cancel"),
    ])
    if scope == "cancel":
        return []
    if scope == "range":
        chosen = ask_number_range("Which numbers?", valid_numbers=[f["number"] for f in files])
        return [f for f in files if f["number"] in chosen]
    search = prompt("Type part of the filename to find it (e.g. 'Prologue' or 'ch0001')")
    matches = [f for f in files if search.lower() in f["filename"].lower()]
    if not matches:
        print_warning(f"No filename contains \"{search}\".")
        return []
    if len(matches) == 1:
        return matches
    choices = [questionary.Choice(title=f["filename"], value=idx) for idx, f in enumerate(matches)]
    choices.append(questionary.Choice(title="Cancel", value="__cancel__"))
    pick = ask_select(f"{len(matches)} files match — which one?", choices=choices)
    return [] if pick == "__cancel__" else [matches[pick]]

def _edit_file_overrides(files):
    """Per-file language / scanlator overrides (GUI parity): e.g. a batch where
    a few chapters are a different language, or credited to a different
    scanlator. Stored on the file dicts, so they survive pause/resume."""
    targets = _pick_files_for_edit(files)
    if not targets:
        return
    what = ask_select(f"For these {len(targets)} file(s):", choices=[
        questionary.Choice(title="Set a different language", value="language"),
        questionary.Choice(title="Credit to a scanlator name instead of the group", value="scanlator"),
        questionary.Choice(title="Clear their overrides", value="clear"),
        questionary.Choice(title="Cancel", value="cancel"),
    ])
    if what == "language":
        lang = ask_autocomplete(
            "Language code (type to filter, or press Tab to see all)",
            choices=[c for c, _ in LANGUAGES], meta_information={c: n for c, n in LANGUAGES},
        )
        for f in targets:
            f["language_override"] = lang
        print_success(f"{len(targets)} file(s) will upload as '{lang}'.")
    elif what == "scanlator":
        name = prompt("Scanlator name").strip()
        if name:
            for f in targets:
                f["scanlator_override"] = name
            print_success(f"{len(targets)} file(s) will be credited to scanlator '{name}'.")
    elif what == "clear":
        for f in targets:
            f.pop("language_override", None)
            f.pop("scanlator_override", None)
        print_success(f"Cleared overrides on {len(targets)} file(s).")

def review_and_edit_titles(files):
    while True:
        console.print()
        action = ask_select(
            "Everything look good, or want to adjust anything?",
            choices=[
                questionary.Choice(title="Proceed with upload", value="proceed"),
                questionary.Choice(title="Remove word/phrase from ALL titles...", value="global_remove"),
                questionary.Choice(title="Remove word/phrase from titles with specific range or single title...", value="ranged_remove"),
                questionary.Choice(title="Redo title for a specific group...", value="redo_group"),
                questionary.Choice(title="Change the number for a specific file...", value="edit_number"),
                questionary.Choice(title="Use a different language or scanlator for specific files...", value="overrides"),
            ]
        )

        if action == "proceed":
            return files

        elif action == "overrides":
            _edit_file_overrides(files)
            print_files_table(files, files[0].get("_upload_type", "chapter"), group_label=files[0].get("_group_label"))

        elif action == "edit_number":
            search = prompt("Type part of the filename to find it (e.g. 'Prologue' or 'ch0001')")
            if not search:
                continue
            matches = [f for f in files if search.lower() in f["filename"].lower()]
            if not matches:
                print_warning(f"No filename contains \"{search}\".")
                continue
            if len(matches) > 1:
                choices = [
                    questionary.Choice(title=f"{f['filename']}  (currently {f['number']:g})", value=idx)
                    for idx, f in enumerate(matches)
                ]
                choices.append(questionary.Choice(title="Cancel", value="__cancel__"))
                pick = ask_select(f"{len(matches)} files match — which one?", choices=choices)
                if pick == "__cancel__":
                    continue
                target = matches[pick]
            else:
                target = matches[0]

            console.print()
            print_info(f"'{target['filename']}' is currently number {target['number']:g}.")
            while True:
                new_num_input = prompt("Enter new number", default=f"{target['number']:g}").strip()
                try:
                    new_num = float(new_num_input)
                    break
                except ValueError:
                    print_error("Please enter a valid number (e.g. 0, 1.5, 12).")

            existing = [f for f in files if f is not target and f["number"] == new_num]
            if existing:
                print_warning(f"Number {new_num:g} is already used by: {', '.join(f['filename'] for f in existing)}")
                if not ask_confirm("Set it anyway and create a duplicate? (You can resolve it in the next step)", default=False):
                    continue

            target["number"] = new_num
            files.sort(key=lambda x: x["number"])
            print_success(f"'{target['filename']}' is now number {new_num:g}.")
            print_files_table(files, files[0].get("_upload_type", "chapter"), group_label=files[0].get("_group_label"))

        elif action == "global_remove":
            pattern_input = prompt("Enter word/phrase to remove from every title (plain text, or a regex pattern)")
            if not pattern_input:
                continue
            pattern = compile_removal_pattern(pattern_input)

            preview = []
            affected = 0
            for f in files:
                new_title = apply_removal_pattern(pattern, f["title"])
                if new_title is not None and new_title != f["title"]:
                    affected += 1
                    if len(preview) < 8:
                        preview.append((f["filename"], f["title"], new_title))

            if affected == 0:
                print_warning(f"No titles contain \"{pattern_input}\" — nothing to change.")
                continue

            console.print()
            print_info(f"This will change {affected} of {len(files)} title(s). Preview:")
            for fname, old_t, new_t in preview:
                console.print(f"  [dim]{fname}[/dim]")
                console.print(f"    [red]- {old_t}[/red]")
                console.print(f"    [green]+ {new_t}[/green]")
            if affected > len(preview):
                print_info(f"  ...and {affected - len(preview)} more.")

            console.print()
            if ask_confirm(f"Apply this removal to all {affected} affected title(s)?", default=True):
                for f in files:
                    new_title = apply_removal_pattern(pattern, f["title"])
                    if new_title is not None:
                        f["title"] = new_title
                print_success(f"Updated {affected} title(s).")
                print_files_table(files, files[0].get("_upload_type", "chapter"), group_label=files[0].get("_group_label"))
            # else: loop back to the menu without changes

        elif action == "ranged_remove":
            scope = ask_select(
                "Apply to:",
                choices=[
                    questionary.Choice(title="A chapter/number range (e.g. '103-108,110')", value="range"),
                    questionary.Choice(title="A single title (search by filename)", value="single"),
                ]
            )
            if scope == "range":
                valid_numbers = [f["number"] for f in files]
                chosen_numbers = ask_number_range("Which numbers should this apply to?", valid_numbers=valid_numbers)
                targets = [f for f in files if f["number"] in chosen_numbers]
            else:
                search = prompt("Type part of the filename to find it (e.g. 'Prologue' or 'ch0001')")
                if not search:
                    continue
                matches = [f for f in files if search.lower() in f["filename"].lower()]
                if not matches:
                    print_warning(f"No filename contains \"{search}\".")
                    continue
                if len(matches) > 1:
                    choices = [
                        questionary.Choice(title=f"{f['filename']}  (currently \"{f['title']}\")", value=idx)
                        for idx, f in enumerate(matches)
                    ]
                    choices.append(questionary.Choice(title="Cancel", value="__cancel__"))
                    pick = ask_select(f"{len(matches)} files match — which one?", choices=choices)
                    if pick == "__cancel__":
                        continue
                    targets = [matches[pick]]
                else:
                    targets = [matches[0]]

            if not targets:
                print_warning("No files matched — nothing to change.")
                continue

            pattern_input = prompt("Enter word/phrase to remove (plain text, or a regex pattern)")
            if not pattern_input:
                continue
            pattern = compile_removal_pattern(pattern_input)

            preview = []
            affected = 0
            for f in targets:
                new_title = apply_removal_pattern(pattern, f["title"])
                if new_title is not None and new_title != f["title"]:
                    affected += 1
                    if len(preview) < 8:
                        preview.append((f["filename"], f["title"], new_title))

            if affected == 0:
                print_warning(f"No selected titles contain \"{pattern_input}\" — nothing to change.")
                continue

            console.print()
            print_info(f"This will change {affected} of {len(targets)} selected title(s). Preview:")
            for fname, old_t, new_t in preview:
                console.print(f"  [dim]{fname}[/dim]")
                console.print(f"    [red]- {old_t}[/red]")
                console.print(f"    [green]+ {new_t}[/green]")
            if affected > len(preview):
                print_info(f"  ...and {affected - len(preview)} more.")

            console.print()
            if ask_confirm(f"Apply this removal to all {affected} affected title(s)?", default=True):
                for f in targets:
                    new_title = apply_removal_pattern(pattern, f["title"])
                    if new_title is not None:
                        f["title"] = new_title
                print_success(f"Updated {affected} title(s).")
                print_files_table(files, files[0].get("_upload_type", "chapter"), group_label=files[0].get("_group_label"))
            # else: loop back to the menu without changes

        elif action == "redo_group":
            groups = {}
            for f in files:
                key = f.get("shape_key", f["title"])
                groups.setdefault(key, []).append(f)

            group_list = sorted(groups.items(), key=lambda kv: -len(kv[1]))
            choices = []
            for key, group_files in group_list:
                sample_title = group_files[0]["title"]
                sample_name = group_files[0]["filename"]
                choices.append(questionary.Choice(
                    title=f"({len(group_files)} file(s)) \"{sample_title}\"  e.g. '{sample_name}'",
                    value=key
                ))
            choices.append(questionary.Choice(title="Cancel", value="__cancel__"))

            console.print()
            selection = ask_select("Which group do you want to redo the title for?", choices=choices)
            if selection == "__cancel__":
                continue

            group_files = groups[selection]
            sample = group_files[0]
            candidates = sample.get("candidates") or [("Full title (as detected)", sample["title"])]

            picker_choices = [
                questionary.Choice(title=f"{label}: {text}", value=str(i))
                for i, (label, text) in enumerate(candidates)
            ]
            picker_choices.append(questionary.Choice(title="Remove word/phrase (regex)...", value="__regex_remove__"))
            picker_choices.append(questionary.Choice(title="Remove unnecessary leading zeros...", value="__strip_zeros__"))
            picker_choices.append(questionary.Choice(title="Type my own...", value="__custom__"))

            console.print()
            while True:
                pick = ask_select(
                    f"Select new title for this group ({len(group_files)} file(s), e.g. '{sample['filename']}'):",
                    choices=picker_choices
                )
                if pick == "__custom__":
                    new_title = prompt("Enter custom title", default=sample["title"]).strip() or sample["title"]
                    break
                elif pick == "__regex_remove__":
                    pattern_input = prompt("Enter word/phrase to remove (plain text, or a regex pattern)")
                    if not pattern_input:
                        continue
                    pattern = compile_removal_pattern(pattern_input)
                    new_title = apply_removal_pattern(pattern, candidates[0][1])
                    if new_title is None:
                        print_warning("Removing that would leave an empty title — try a narrower pattern.")
                        continue
                    break
                elif pick == "__strip_zeros__":
                    new_title = strip_leading_zeros_in_title(candidates[0][1])
                    break
                else:
                    new_title = candidates[int(pick)][1]
                    break

            console.print()
            if ask_confirm(f"Use \"{new_title}\" for all {len(group_files)} file(s) in this group?", default=True):
                for f in group_files:
                    f_candidates = f.get("candidates") or [("Full title (as detected)", f["title"])]
                    if pick == "__custom__":
                        f["title"] = new_title
                    elif pick == "__regex_remove__":
                        f["title"] = apply_removal_pattern(pattern, f_candidates[0][1]) or f["title"]
                    elif pick == "__strip_zeros__":
                        f["title"] = strip_leading_zeros_in_title(f_candidates[0][1])
                    else:
                        f["title"] = f_candidates[min(int(pick), len(f_candidates) - 1)][1]
                print_success(f"Updated {len(group_files)} title(s).")
                print_files_table(files, files[0].get("_upload_type", "chapter"), group_label=files[0].get("_group_label"))

def print_files_table(files, upload_type, group_label=None):
    total_size = sum(f["size"] for f in files)
    print_success(f"Found {len(files)} file(s)  ({fmt_size(total_size)} total)\n")

    has_groups = any(f.get("groups") for f in files) or bool(group_label)
    has_overrides = any(f.get("language_override") or f.get("scanlator_override") for f in files)

    table = Table(box=box.ROUNDED, header_style="bold cyan", border_style="cyan")
    table.add_column("Filename", style="white", overflow="fold")
    table.add_column("Number", style="magenta", justify="right")
    table.add_column("Title", style="green", overflow="fold")
    if has_groups:
        table.add_column("Group", style="cyan", overflow="fold")
    if has_overrides:
        table.add_column("Override", style="bright_magenta", overflow="fold")
    table.add_column("Size", style="yellow", justify="right")

    for f in files:
        group_str = ", ".join(f["groups"]) if f.get("groups") else (group_label or "-")
        row = [f["filename"], str(f["number"]), f["title"] or "-"]
        if has_groups:
            row.append(group_str)
        if has_overrides:
            bits = []
            if f.get("language_override"):
                bits.append(f"lang {f['language_override']}")
            if f.get("scanlator_override"):
                bits.append(f"scanlator {f['scanlator_override']}")
            row.append(", ".join(bits) or "-")
        row.append(fmt_size(f["size"]))
        table.add_row(*row)

    unit = "volume" if upload_type == "volume" else "chapter"
    unit_plural = f"{len(files)} {unit}{'s' if len(files) != 1 else ''}"
    table.add_section()
    total_row = [Text(f"TOTAL  ({unit_plural})", style="bold"), "", ""]
    if has_groups:
        total_row.append("")
    if has_overrides:
        total_row.append("")
    total_row.append(Text(fmt_size(total_size), style="bold"))
    table.add_row(*total_row)

    console.print(table)
    print("")

def _check_missing(files, upload_type):
    numbers = [f["number"] for f in files]
    int_numbers = []
    for n in numbers:
        try:
            if n == int(n):
                int_numbers.append(int(n))
        except (ValueError, OverflowError):
            pass
    int_numbers = sorted(set(int_numbers))
    missing     = []
    if len(int_numbers) > 1:
        for i in range(len(int_numbers) - 1):
            if int_numbers[i + 1] - int_numbers[i] > 1: missing.extend(range(int_numbers[i] + 1, int_numbers[i + 1]))
    if missing:
        term = "chapters" if upload_type == "chapter" else "volumes"
        if len(missing) <= 15: print_warning(f"Missing {term} detected in sequence: {', '.join(map(str, missing))}")
        else: print_warning(f"Missing {term} detected: {len(missing)} {term} missing between {missing[0]} and {missing[-1]}.")
        print_warning("Please verify this is intentional before proceeding.\n")

def _check_duplicates(files, upload_type):
    term = "chapter" if upload_type == "chapter" else "volume"

    while True:
        by_number = {}
        for f in files:
            by_number.setdefault(f["number"], []).append(f)
        dups = {n: flist for n, flist in by_number.items() if len(flist) > 1}
        if not dups:
            return files

        print_warning(f"Duplicate {term} number(s) detected:")
        for n in sorted(dups):
            names = ", ".join(f["filename"] for f in dups[n])
            print_warning(f"  • {term.title()} {n:g}: {names}")
        console.print()

        action = ask_select(
            f"How do you want to handle these {len(dups)} duplicate number(s)?",
            choices=[
                questionary.Choice(title="Resolve them one by one (exclude or renumber)", value="resolve"),
                questionary.Choice(title="Proceed anyway (upload all, duplicates included)", value="proceed"),
            ]
        )
        if action == "proceed":
            print_warning("All listed files will be uploaded — duplicates included.\n")
            return files

        for n in sorted(dups):
            dup_files = [f for f in dups[n] if f in files]
            if len(dup_files) < 2:
                continue  # already resolved by a previous iteration
            console.print()
            print_info(f"{term.title()} {n:g} has {len(dup_files)} file(s):")
            choices = []
            for f in dup_files:
                choices.append(questionary.Choice(title=f"Keep '{f['filename']}' -> exclude the other(s)", value=("keep", f)))
            choices.append(questionary.Choice(title="Keep all — give them different numbers", value=("renumber", None)))
            choices.append(questionary.Choice(title="Keep all as-is (leave this duplicate)", value=("skip", None)))

            pick = ask_select(f"Resolve {term} {n:g}:", choices=choices)
            action_type, keep_file = pick

            if action_type == "keep":
                for f in dup_files:
                    if f is not keep_file:
                        files.remove(f)
                        print_info(f"Excluded '{f['filename']}'.")
            elif action_type == "renumber":
                for f in dup_files:
                    while True:
                        new_num_input = prompt(f"New number for '{f['filename']}' (currently {n:g})", default=f"{n:g}").strip()
                        try:
                            new_num = float(new_num_input)
                            break
                        except ValueError:
                            print_error("Please enter a valid number.")
                    f["number"] = new_num
            # "skip": leave as-is, will be re-reported if still duplicated after this pass

        files.sort(key=lambda x: x["number"])
        console.print()

def load_config():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as e:
        logging.debug("load_config: could not read %s (%s); starting with empty config.", CONFIG_PATH, e)
        return {}

def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except (OSError, TypeError, ValueError) as e:
        logging.debug("save_config: failed to write %s: %s", CONFIG_PATH, e)

def _remember_library(lib):
    if not lib:
        return
    lib = os.path.normpath(lib)
    cfg = load_config()
    if cfg.get("library") != lib:
        cfg["library"] = lib
        save_config(cfg)

def _remember_setting(key, value):
    """Generic settings-memory helper (mirrors _remember_library above, but
    for any scalar setting — language code, thread count, picker preference)."""
    if not value:
        return
    cfg = load_config()
    if cfg.get(key) != value:
        cfg[key] = value
        save_config(cfg)

def _remember_setting_force(key, value):
    """Like _remember_setting but also persists explicit False / 0 — needed
    for boolean flags such as proxy_no_verify where clearing the flag is
    meaningful and must not be treated as 'nothing to remember'."""
    cfg = load_config()
    if cfg.get(key) != value:
        cfg[key] = value
        save_config(cfg)

# ==============================================================================
# ⏸️  PAUSED UPLOAD STATE — crash-safe resume (CLI mirror of GUI's config.py)
# Persists enough of an in-flight batch to resume it after the script exits,
# crashes, or the terminal is closed. Only one paused upload is tracked.
# On resume files restart from zero; already-finished files are caught by
# the server's 409 Already-Exists dedup and marked instantly as done — so
# this gives true crash safety with a minimal, safe change to the worker.
# ==============================================================================

def load_paused_upload():
    """Return paused state dict or None (nothing paused / corrupt / wrong
    schema — all treated as 'no usable pause, do a fresh upload')."""
    with _paused_upload_lock:
        try:
            with open(PAUSED_UPLOAD_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError) as e:
            logging.debug("load_paused_upload: could not read %s (%s)", PAUSED_UPLOAD_PATH, e)
            return None
        if not isinstance(data, dict):
            return None
        if data.get("schema_version") != PAUSED_UPLOAD_SCHEMA_VERSION:
            logging.debug("load_paused_upload: schema mismatch (found %r, expected %r); discarding.",
                          data.get("schema_version"), PAUSED_UPLOAD_SCHEMA_VERSION)
            return None
        if not isinstance(data.get("files"), list):
            return None
        return data

def save_paused_upload(batch_config, files):
    """Persist batch_config + files atomically so a crash mid-write cannot
    corrupt the pause file. Files are full file-info dicts (filepath, size,
    number, title, groups, etc.) — all JSON-serializable."""
    # Strip any non-serializable DirEntry that get_files_in_dir may have left
    # before finalize (defensive — finalized entries already popped it).
    clean_files = []
    for f in files:
        cf = {k: v for k, v in f.items() if k != "entry"}
        clean_files.append(cf)
    data = {
        "schema_version": PAUSED_UPLOAD_SCHEMA_VERSION,
        "paused_at": time.time(),
        "batch_config": batch_config,
        "files": clean_files,
    }
    with _paused_upload_lock:
        try:
            fd, tmp = tempfile.mkstemp(dir=str(PAUSED_UPLOAD_PATH.parent),
                                       prefix=".mangadot_paused_", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(data, fh, indent=2, default=str)
                os.replace(tmp, PAUSED_UPLOAD_PATH)
            finally:
                if os.path.exists(tmp):
                    try: os.remove(tmp)
                    except OSError: pass
        except (OSError, TypeError, ValueError) as e:
            logging.warning("save_paused_upload: failed to write %s: %s", PAUSED_UPLOAD_PATH, e)

def clear_paused_upload():
    with _paused_upload_lock:
        try:
            os.remove(PAUSED_UPLOAD_PATH)
        except FileNotFoundError:
            pass
        except OSError as e:
            logging.debug("clear_paused_upload: failed to remove %s: %s", PAUSED_UPLOAD_PATH, e)

def _format_paused_age(paused_at):
    seconds = max(0, time.time() - paused_at)
    if seconds < 60:
        return "less than a minute ago"
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    hours = int(minutes // 60)
    if hours < 24:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = int(hours // 24)
    return f"{days} day{'s' if days != 1 else ''} ago"

# ==============================================================================
# 📚 UPLOAD HISTORY DB (~/.mangadot_uploader_db.json)
# Tracks which chapter/volume numbers have already been confirmed-uploaded to a
# given manga+type+language+group/scanlator target, so repeat runs on the same
# folder (e.g. a weekly re-upload) can skip files that already made it up
# without re-verifying them over the network.
# ==============================================================================

def load_db():
    try:
        with open(DB_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"version": 1, "uploaded": {}}
        data.setdefault("version", 1)
        if not isinstance(data.get("uploaded"), dict):
            data["uploaded"] = {}
        # Normalize every bucket to a compact sorted list of numbers, migrating
        # any legacy dict-shaped bucket in place. Persisted on the next save_db.
        uploaded = data["uploaded"]
        for k in list(uploaded.keys()):
            uploaded[k] = _normalize_uploaded_bucket(uploaded[k])
        return data
    except FileNotFoundError:
        return {"version": 1, "uploaded": {}}
    except (OSError, json.JSONDecodeError) as e:
        logging.debug("load_db: could not read %s (%s); starting with empty DB.", DB_PATH, e)
        return {"version": 1, "uploaded": {}}

def save_db(db):
    """Write the DB atomically (temp file + os.replace) so an interrupted write
    can never corrupt the accumulated upload history."""
    try:
        fd, tmp = tempfile.mkstemp(
            dir=str(DB_PATH.parent), prefix=".mangadot_db_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(db, f, indent=2)
            os.replace(tmp, DB_PATH)
        finally:
            if os.path.exists(tmp):
                try: os.remove(tmp)
                except OSError: pass
    except (OSError, TypeError, ValueError) as e:
        logging.debug("save_db: failed to write %s: %s", DB_PATH, e)

def _chapter_number_key(number):
    """Canonical string key for a chapter/volume number, matching how the
    server compares numbers: '340' / '342.5', trailing zeros dropped."""
    try:
        f = float(number)
    except (TypeError, ValueError):
        return str(number).strip()
    if f.is_integer():
        return str(int(f))
    return format(f, "g")

def _chapter_number_value(number):
    """JSON-friendly numeric form of a chapter number for compact storage: int
    when whole (340) else float (342.5); None if it can't be parsed."""
    try:
        f = float(number)
    except (TypeError, ValueError):
        return None
    return int(f) if f.is_integer() else f

def _uploaded_sort_key(v):
    try:
        return (0, float(v))
    except (TypeError, ValueError):
        return (1, 0.0)

def _normalize_uploaded_bucket(bucket):
    """Return an uploaded bucket as a de-duplicated, sorted list of chapter
    numbers, tolerating a legacy dict-shaped bucket by reading its keys."""
    if isinstance(bucket, dict):
        raw = list(bucket.keys())
    elif isinstance(bucket, list):
        raw = bucket
    else:
        return []
    seen, out = set(), []
    for x in raw:
        key = _chapter_number_key(x)
        if not key or key in seen:
            continue
        seen.add(key)
        val = _chapter_number_value(x)
        out.append(val if val is not None else key)
    out.sort(key=_uploaded_sort_key)
    return out

def _make_target_key(manga_id, upload_type, language, group_ids, scanlator_name):
    """Identity for a specific upload target: same manga + type + language +
    attribution. Scoping by attribution means a chapter uploaded under one
    group isn't treated as already-done under a different group/scanlator."""
    if group_ids:
        group_key = ",".join(str(g) for g in sorted(group_ids))
    elif scanlator_name:
        group_key = f"s:{scanlator_name.strip().lower()}"
    else:
        group_key = "none"
    return f"{manga_id}|{upload_type}|{language}|{group_key}"

def db_record_uploaded_files(manga_id, upload_type, language, group_ids, scanlator_name,
                              files, per_file_group_map=None, per_file_scanlator_map=None,
                              per_file_language_map=None):
    """Record uploaded files under the target each one was actually credited to."""
    per_file_group_map     = per_file_group_map or {}
    per_file_scanlator_map = per_file_scanlator_map or {}
    per_file_language_map  = per_file_language_map or {}
    by_target = {}
    for f in files:
        norm = f.get("norm_filepath") or _norm_filepath(f["filepath"])
        lang = f.get("language_override") or per_file_language_map.get(norm) or language
        scan = f.get("scanlator_override") or per_file_scanlator_map.get(norm)
        if scan:
            key = _make_target_key(manga_id, upload_type, lang, [], scan)
        else:
            key = _make_target_key(manga_id, upload_type, lang,
                                   per_file_group_map.get(norm) or group_ids, scanlator_name)
        by_target.setdefault(key, []).append(f)
    for key, group in by_target.items():
        db_record_uploaded(key, group)

def db_uploaded_numbers(target_key):
    db = load_db()  # load_db normalizes every bucket to a list of numbers
    bucket = db.get("uploaded", {}).get(target_key, [])
    return {_chapter_number_key(x) for x in bucket}

def db_record_uploaded(target_key, files):
    """Record the given file dicts (each with a 'number') as uploaded under
    target_key, stored compactly as a sorted list of chapter numbers. Merges
    into existing history rather than overwriting it."""
    if not files:
        return
    db = load_db()
    bucket = db.setdefault("uploaded", {}).setdefault(target_key, [])
    if not isinstance(bucket, list):
        bucket = _normalize_uploaded_bucket(bucket)
        db["uploaded"][target_key] = bucket
    existing = {_chapter_number_key(x) for x in bucket}
    for f in files:
        key = _chapter_number_key(f.get("number"))
        if not key or key in existing:
            continue
        existing.add(key)
        val = _chapter_number_value(f.get("number"))
        bucket.append(val if val is not None else key)
    bucket.sort(key=_uploaded_sort_key)
    save_db(db)

def fetch_uploads_page(session, page=1, limit=50, manga_id=None, upload_type=None, language=None, sort="number_desc"):
    """One page of the logged-in member's uploads (/api/uploads/mine).
    Raises SessionExpiredError on 401/403; returns {} on other failures."""
    params = {"page": page, "limit": limit, "sort": sort}
    if manga_id is not None:
        params["manga_id"] = manga_id
    if upload_type:
        params["type"] = upload_type
    if language:
        params["language"] = language
    try:
        res = session.get(f"{BASE_URL}/api/uploads/mine", params=params,
                          headers={"Referer": f"{BASE_URL}/upload"}, timeout=(10, 30))
        if res.status_code in (401, 403):
            raise SessionExpiredError()
        res.raise_for_status()
        data = res.json()
        return data if isinstance(data, dict) else {"uploads": data if isinstance(data, list) else []}
    except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
        logging.debug("fetch_uploads_page error: %s", e)
        return {}

def fetch_my_uploads(session, manga_id=None, upload_type=None, language=None, limit=100, max_pages=5):
    """All of the member's uploads matching the filters, following pagination
    (a single page used to hide older entries on busy titles). Includes
    uploads still awaiting moderation. Mirrors the GUI's net.fetch_my_uploads."""
    entries = []
    page = 1
    while page <= max_pages:
        data = fetch_uploads_page(session, page=page, limit=limit, manga_id=manga_id,
                                  upload_type=upload_type, language=language)
        if not isinstance(data, dict):
            break
        batch = data.get("uploads") or []
        entries.extend(batch)
        total_pages = (data.get("pagination") or {}).get("total_pages") or 1
        if page >= total_pages or not batch:
            break
        page += 1
    return entries

def fetch_remote_existing_numbers(session, manga_id, upload_type, language):
    """Numbers of chapters/volumes that already exist for this title + language:
    published ones (the volumes endpoint for volumes, the chapter list for
    chapters) plus the member's own pending/processing/approved uploads."""
    existing_numbers = set()
    num_field = "volume_number" if upload_type == "volume" else "chapter_number"

    # 1. Published releases. Volumes have their own endpoint — the chapter list
    #    does not reliably report published volumes, which let duplicates through.
    try:
        endpoint = (f"{BASE_URL}/api/manga/{manga_id}/volumes" if upload_type == "volume"
                    else f"{BASE_URL}/api/manga/{manga_id}/chapters/list")
        resp = session.get(
            endpoint,
            params={"lang": language},
            headers={"Referer": f"{BASE_URL}/manga/{manga_id}"},
            timeout=(10, 20)
        )
        if resp.status_code == 200:
            data = resp.json()
            items = data if isinstance(data, list) else (
                data.get("volumes") or data.get("chapters") or data.get("rows") or [])
            for item in items:
                if isinstance(item, dict) and item.get(num_field) is not None:
                    key = _chapter_number_key(item.get(num_field))
                    if key:
                        existing_numbers.add(key)
    except Exception as e:
        logging.debug("fetch_remote_existing_numbers published check failed: %s", e)

    # 2. Member's uploads queue (pending, processing, approved), all pages.
    try:
        for item in fetch_my_uploads(session, manga_id=manga_id, upload_type=upload_type,
                                     language=language, limit=100, max_pages=2):
            if isinstance(item, dict) and item.get("status") != "rejected" and item.get(num_field) is not None:
                key = _chapter_number_key(item.get(num_field))
                if key:
                    existing_numbers.add(key)
    except Exception as e:
        logging.debug("fetch_remote_existing_numbers uploads/mine failed: %s", e)

    return existing_numbers

def extract_first_image_from_archive(archive_path):
    """Extracts the first image filename and raw bytes from a cbz/zip archive using natural sort."""
    if not os.path.isfile(archive_path) or not zipfile.is_zipfile(archive_path):
        return None, None, None
    try:
        with zipfile.ZipFile(archive_path, "r") as zf:
            valid_exts = (".jpg", ".jpeg", ".png", ".webp")
            names = [
                n for n in zf.namelist()
                if not n.startswith("__MACOSX") and not os.path.basename(n).startswith(".")
                and n.lower().endswith(valid_exts)
            ]
            if not names:
                return None, None, None
            names.sort(key=natural_sort_key)
            first_name = names[0]
            data = zf.read(first_name)
            ext = os.path.splitext(first_name)[1].lower()
            mime = "image/jpeg" if ext in (".jpg", ".jpeg") else ("image/png" if ext == ".png" else "image/webp")
            return os.path.basename(first_name), data, mime
    except Exception as e:
        logging.debug("extract_first_image_from_archive failed on %s: %s", archive_path, e)
        return None, None, None

def upload_volume_cover(session, manga_id, volume_number, archive_path):
    """Extracts page 1 from the volume archive and uploads it as the volume cover."""
    fname, img_bytes, mime = extract_first_image_from_archive(archive_path)
    if not img_bytes:
        return False, "No valid image found in volume archive"

    try:
        vn_key = _chapter_number_key(volume_number)
    except Exception:
        vn_key = str(volume_number)

    url = f"{BASE_URL}/api/manga/{manga_id}/volumes/{vn_key}/cover"
    headers = {
        "Origin": BASE_URL,
        "Referer": f"{BASE_URL}/manga/{manga_id}/upload",
    }
    files = {"file": (fname, img_bytes, mime)}
    try:
        res = session.post(url, files=files, headers=headers, timeout=(15, 45))
        if res.status_code == 200:
            return True, None
        return False, f"HTTP {res.status_code}: {res.text[:120]}"
    except Exception as e:
        return False, str(e)

def _check_for_updates():
    """Once every 7 days, check PyPI for newer versions of our dependencies
    than the floors declared in REQUIRED_PACKAGES/OPTIMIZER_PACKAGES, and
    print a short FYI if any are behind. Purely informational:
      - never installs anything, never changes the PEP 723/REQUIRED floors
      - never blocks startup — any failure (offline, firewall, bad response,
        slow PyPI) is swallowed silently and the script proceeds as normal
      - on non-check days this does nothing at all (no network call)
    """
    cfg = load_config()
    last_checked = cfg.get("last_update_check")
    now = time.time()
    if isinstance(last_checked, (int, float)) and (now - last_checked) < 7 * 24 * 3600:
        return  # checked within the last week; skip silently

    try:
        all_pkgs = dict(REQUIRED_PACKAGES)
        all_pkgs.update(OPTIMIZER_PACKAGES)
        outdated = []
        for pkg, floor in all_pkgs.items():
            try:
                resp = requests.get(f"https://pypi.org/pypi/{pkg}/json", timeout=3)
                if resp.status_code != 200:
                    continue
                latest = resp.json().get("info", {}).get("version")
                if latest and _version_lt(floor, latest):
                    outdated.append((pkg, floor, latest))
            except Exception:
                continue  # one package failing shouldn't skip the rest

        if outdated:
            sep = "=" * 62
            print(sep)
            print("  ℹ️   Newer versions available (weekly check, informational only)")
            for pkg, floor, latest in outdated:
                print(f"      {pkg}: floor is {floor}, PyPI has {latest}")
            print("  This doesn't affect this run. To adopt a newer version, bump the")
            print("  floor in the '# dependencies =' block / REQUIRED_PACKAGES, or:")
            print(f"      uv add --script {_script_name()} <package>>=<version>")
            print(sep)
            print()
    except Exception:
        pass  # never let the update-check itself interfere with startup
    finally:
        # Record the check attempt regardless of outcome, so a flaky network
        # doesn't cause retries every single run.
        cfg["last_update_check"] = now
        save_config(cfg)

def _get_picker_style():
    """Ask (once) whether the user prefers the range-based picker (type e.g.
    '103-108,110') or the checkbox picker (tick individual files), remember
    the answer, and reuse it on future runs without asking again."""
    cfg = load_config()
    style = cfg.get("file_picker")
    if style in ("range", "checkbox"):
        return style
    style = ask_select("Which file picker do you prefer, when not uploading everything?", [
        questionary.Choice(title="Range syntax (e.g. '103-108,110,115-117')", value="range"),
        questionary.Choice(title="Checkbox list (tick individual files)", value="checkbox"),
    ])
    _remember_setting("file_picker", style)
    return style

def _count_archives(path):
    try:
        return sum(1 for f in os.listdir(path)
                   if f.lower().endswith(('.cbz', '.zip')) and os.path.isfile(os.path.join(path, f)))
    except OSError:
        return 0

def select_directory(library_dir=None):
    if library_dir and not os.path.isdir(library_dir):
        print_warning(f"Library folder '{library_dir}' not found — falling back to manual entry.")
        library_dir = None

    while True:
        if library_dir:
            root_count = _count_archives(library_dir)
            try:
                names = sorted(os.listdir(library_dir), key=natural_sort_key)
            except OSError:
                names = []
            subdirs = []
            for name in names:
                full = os.path.join(library_dir, name)
                if os.path.isdir(full):
                    count = _count_archives(full)
                    if count:
                        subdirs.append((name, full, count))

            if subdirs or root_count:
                choices = []
                if root_count:
                    choices.append(questionary.Choice(title=f"· (this folder) — {root_count} file(s)", value=library_dir))
                for name, full, count in subdirs:
                    choices.append(questionary.Choice(title=f"{name} — {count} file(s)", value=full))
                choices.append(questionary.Choice(title="📁 Enter a path manually", value="__manual__"))
                choices.append(questionary.Choice(title="🔄 Rescan", value="__rescan__"))

                pick = ask_select(f"Select a manga folder from [{library_dir}]:", choices)
                if pick == "__rescan__":
                    continue
                if pick != "__manual__":
                    _remember_library(library_dir)
                    return os.path.normpath(pick)
            else:
                print_warning(f"No subfolders containing .cbz/.zip files found in '{library_dir}'.")
                library_dir = None

        while True:
            directory = prompt("Enter the directory path containing your .cbz/.zip files",
                                default=DEFAULT_CHAPTERS_DIR if os.path.isdir(DEFAULT_CHAPTERS_DIR) else None)
            directory = os.path.normpath(directory.strip().strip('"\''))
            if os.path.isdir(directory):
                _remember_library(library_dir or os.path.dirname(os.path.abspath(directory)))
                return directory
            print_error("Directory does not exist. Please try again.")

# ==============================================================================
# 🏃 DRY RUN
# ==============================================================================

def run_dry_run(library_dir=None):
    console.print()
    console.rule("[bold magenta]MangaDot.net Batch Uploader — DRY RUN[/bold magenta]", style="green")
    console.print()

    directory = select_directory(library_dir)
    if not directory:
        print_error("No directory selected.")
        sys.exit(1)
        
    flush_input_buffer()

    upload_type = ask_select("Upload type?", [
        questionary.Choice(title="Chapter", value="chapter"),
        questionary.Choice(title="Volume", value="volume"),
    ])

    chapter_naming = "extract"
    custom_regex   = None
    custom_renames = None
    advanced_strip_groups = False
    if upload_type == "chapter":
        chapter_naming, custom_regex, custom_renames, advanced_strip_groups = _ask_chapter_naming()

    console.print()
    console.rule("[dim]Files[/dim]", style="green")
    console.print()

    print_info("Scanning directory for files...")
    files = get_files_in_dir(directory, upload_type, chapter_naming, custom_regex, strip_groups=advanced_strip_groups, custom_renames=custom_renames, select_subset=True, picker_style=_get_picker_style())
    if not files:
        print_error("No valid .cbz or .zip files found.")
        sys.exit(1)

    print_files_table(files, upload_type)
    _check_missing(files, upload_type)
    files = _check_duplicates(files, upload_type)

    print_success("Dry run complete — no files were uploaded.")
    console.print()
    input("Press Enter to exit... ")
    sys.exit(0)

# ==============================================================================
# 🗜️  CBZ OPTIMIZER  (--optimize-only / --optimize)
# ==============================================================================
# Re-compresses images inside .cbz/.zip archives before upload. STRICTLY
# LOSSLESS BY DEFAULT — pixel data is never altered unless --optimize-lossy
# is explicitly passed. Deliberately isolated from the upload pipeline:
# nothing in this section is imported or touched unless the user explicitly
# passes --optimize-only or --optimize, so a normal upload run pays zero
# cost for this feature (Pillow / mozjpeg-lossless-optimization are only
# imported lazily, inside _ensure_optimizer_deps()).
#
# Lossless mode (default):
#   - JPEG : Huffman-table / entropy-coding re-optimization via mozjpeg
#            (jpegtran-equivalent transform). Pixels are NEVER re-quantized
#            or re-encoded — decoding the output produces byte-identical
#            pixel data to the original. Typical savings: ~5-15%.
#   - PNG  : Pillow's optimize=True + max compress_level. PNG's DEFLATE
#            stream is inherently lossless; this only searches for a
#            better filter/compression strategy. Typical savings: 5-25%.
#   - WEBP : Pillow's lossless=True encoder. Typical savings varies widely.
#   - BMP  : Losslessly repacked into PNG (BMP is uncompressed, so this is
#            a pure size win with zero pixel change).
#
# Lossy mode (--optimize-lossy, opt-in only):
#   - JPEG : full re-encode at --optimize-jpeg-quality (default 85).
#   - PNG  : unchanged (PNG has no meaningful "lossy" mode in Pillow).
#   - WEBP : re-encode at --optimize-webp-quality (default 85).
#   This mode DOES alter pixel data and is never used unless the user
#   types --optimize-lossy on the command line.

OPTIMIZE_IMAGE_EXTS = ('.jpg', '.jpeg', '.png', '.webp', '.bmp')
_PILLOW_MODULE = None       # cached lazy import, set by _ensure_optimizer_deps()
_MOZJPEG_MODULE = None      # cached lazy import, set by _ensure_optimizer_deps()
_MOZJPEG_AVAILABLE = None   # tri-state: None=unchecked, True/False=checked

# --pingo: alternate optimizer backend that shells out to a local pingo
# binary (https://css-ig.net/pingo) instead of using mozjpeg/Pillow at all.
# Pingo ships official builds for Windows and Linux only — no macOS build
# exists. On unsupported platforms (or if the binary can't be found) this
# falls back to the normal mozjpeg/Pillow path, but ALWAYS prints a visible
# notice first: a silent fallback would mean the user believes they got a
# pingo pass when they actually got mozjpeg, which is exactly the kind of
# quiet behavior-swap this script avoids elsewhere (see _ensure_optimizer_deps).
_PINGO_BINARY_CACHE = None  # tri-state: None=unchecked, ""=checked-not-found, path=found

def _pingo_binary_name():
    return "pingo.exe" if platform.system() == "Windows" else "pingo"

def _find_pingo_binary():
    global _PINGO_BINARY_CACHE
    if _PINGO_BINARY_CACHE is not None:
        return _PINGO_BINARY_CACHE or None

    script_dir = Path(__file__).resolve().parent
    candidate = script_dir / _pingo_binary_name()
    if candidate.is_file():
        _PINGO_BINARY_CACHE = str(candidate)
    else:
        _PINGO_BINARY_CACHE = ""
    return _PINGO_BINARY_CACHE or None

def _pingo_supported_here():
    return platform.system() in ("Windows", "Linux")

def _ensure_pingo_ready():
    if not _pingo_supported_here():
        print_warning(
            f"--pingo was requested, but pingo has no official build for {platform.system()}. "
            "Falling back to the built-in mozjpeg/Pillow optimizer instead (still lossless by default)."
        )
        return None

    path = _find_pingo_binary()
    if path is None:
        print_warning(
            f"--pingo was requested, but '{_pingo_binary_name()}' wasn't found next to mangadot.py. "
            "Falling back to the built-in mozjpeg/Pillow optimizer instead (still lossless by default)."
        )
        return None

    return path

def _ensure_optimizer_deps(require_mozjpeg=False):
    global _PILLOW_MODULE, _MOZJPEG_MODULE, _MOZJPEG_AVAILABLE
    needs_check = _PILLOW_MODULE is None or (require_mozjpeg and _MOZJPEG_AVAILABLE is None)
    if needs_check:
        check_optimizer_dependencies(need_mozjpeg=require_mozjpeg)

    if _PILLOW_MODULE is None:
        try:
            from PIL import Image
            _PILLOW_MODULE = Image
        except ImportError:
            print_error("Pillow is required for --optimize / --optimize-only but isn't installed.")
            print_info("Install it with:  pip install Pillow")
            sys.exit(1)

    if _MOZJPEG_AVAILABLE is None:
        try:
            import mozjpeg_lossless_optimization as mz
            _MOZJPEG_MODULE = mz
            _MOZJPEG_AVAILABLE = True
        except ImportError:
            _MOZJPEG_AVAILABLE = False

    if require_mozjpeg and not _MOZJPEG_AVAILABLE:
        print_error("mozjpeg-lossless-optimization is required for lossless JPEG re-optimization.")
        print_info("Install it with:  pip install mozjpeg-lossless-optimization")
        print_info("(Or pass --optimize-lossy to allow lossy JPEG re-encoding instead — this DOES change pixel data.)")
        sys.exit(1)

    return _PILLOW_MODULE, _MOZJPEG_MODULE

def _optimize_image_bytes(Image, mozjpeg, name, data, lossy, jpeg_quality, png_level, webp_quality):
    import io
    ext = os.path.splitext(name)[1].lower()

    try:
        if ext in ('.jpg', '.jpeg'):
            if not lossy:
                new_bytes = mozjpeg.optimize(data)
            else:
                with Image.open(io.BytesIO(data)) as im:
                    im.load()
                    if im.mode not in ('RGB', 'L'):
                        im = im.convert('RGB')
                    out = io.BytesIO()
                    im.save(out, format='JPEG', quality=jpeg_quality,
                             optimize=True, progressive=True)
                    new_bytes = out.getvalue()

        elif ext == '.png':
            with Image.open(io.BytesIO(data)) as im:
                im.load()
                out = io.BytesIO()
                im.save(out, format='PNG', optimize=True, compress_level=png_level)
                new_bytes = out.getvalue()

        elif ext == '.webp':
            with Image.open(io.BytesIO(data)) as im:
                im.load()
                out = io.BytesIO()
                if not lossy:
                    im.save(out, format='WEBP', lossless=True, method=6, quality=100)
                else:
                    im.save(out, format='WEBP', quality=webp_quality, method=6)
                new_bytes = out.getvalue()

        elif ext == '.bmp':
            with Image.open(io.BytesIO(data)) as im:
                im.load()
                if im.mode not in ('RGB', 'RGBA', 'L'):
                    im = im.convert('RGB')
                out = io.BytesIO()
                im.save(out, format='PNG', optimize=True, compress_level=png_level)
                new_bytes = out.getvalue()

        else:
            return data, False

    except Exception:
        return data, False

    if len(new_bytes) < len(data):
        return new_bytes, True
    return data, False

def _resolve_optimized_output_path(input_path, replace):
    if replace:
        return input_path

    out_dir = input_path.parent / "optimized"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / input_path.name

def optimize_cbz_pingo(filepath, pingo_path, replace=False, lossy=False, jpeg_quality=85, webp_quality=85):
    input_path = Path(filepath)

    try:
        with zipfile.ZipFile(input_path, 'r') as zin:
            entries = zin.infolist()
            originals = {info.filename: zin.read(info.filename) for info in entries}
    except (zipfile.BadZipFile, OSError) as e:
        return {"filename": input_path.name, "error": str(e)}

    original_size = input_path.stat().st_size

    with tempfile.TemporaryDirectory(prefix="mangadot_pingo_") as tmp_dir:
        tmp_dir_path = Path(tmp_dir)
        image_files = []
        tmp_root = tmp_dir_path.resolve()
        for name, data in originals.items():
            if name.endswith('/'):
                continue
            dest = (tmp_dir_path / name).resolve()
            # A crafted archive member like '../../x' or 'C:/x' must not escape the temp dir.
            if dest != tmp_root and tmp_root not in dest.parents:
                return {"filename": input_path.name, "error": f"unsafe path inside archive: {name[:60]}"}
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            if os.path.splitext(name)[1].lower() in OPTIMIZE_IMAGE_EXTS:
                image_files.append(dest)

        if not image_files:
            return {"filename": input_path.name, "skipped": True,
                    "original_size": original_size, "optimized_size": original_size}

        cmd = [pingo_path]
        if lossy:
            cmd += [f"-jpeg={100 - jpeg_quality}", f"-webp={100 - webp_quality}"]
        else:
            cmd += ["-s8", "-lossless"]
        cmd += [str(p) for p in image_files]

        try:
            subprocess.run(
                cmd, capture_output=True, text=True, timeout=600, check=False
            )
        except (subprocess.TimeoutExpired, OSError) as e:
            return {"filename": input_path.name, "error": f"pingo failed to run: {e}"}

        new_entries = {}
        changed_any = False
        for name, data in originals.items():
            if name.endswith('/'):
                continue
            path_on_disk = (tmp_dir_path / name).resolve()
            try:
                new_data = path_on_disk.read_bytes()
            except OSError:
                new_data = data
            new_entries[name] = new_data
            if new_data != data:
                changed_any = True

        if not changed_any:
            return {"filename": input_path.name, "skipped": True,
                    "original_size": original_size, "optimized_size": original_size}

        tmp_fd, tmp_zip_path = tempfile.mkstemp(suffix='.cbz', dir=str(input_path.parent))
        os.close(tmp_fd)
        try:
            with zipfile.ZipFile(tmp_zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as zout:
                for name, data in new_entries.items():
                    zout.writestr(name, data)

            optimized_size = os.path.getsize(tmp_zip_path)

            if optimized_size >= original_size:
                os.remove(tmp_zip_path)
                return {"filename": input_path.name, "skipped": True,
                        "original_size": original_size, "optimized_size": original_size}

            output_path = _resolve_optimized_output_path(input_path, replace)
            os.replace(tmp_zip_path, output_path)

        except Exception as e:
            if os.path.exists(tmp_zip_path):
                os.remove(tmp_zip_path)
            return {"filename": input_path.name, "error": str(e)}

    return {
        "filename": input_path.name,
        "output_name": str(output_path.relative_to(input_path.parent)) if not replace else output_path.name,
        "original_size": original_size,
        "optimized_size": optimized_size,
    }

def optimize_cbz(filepath, lossy=False, jpeg_quality=85, png_level=9, webp_quality=85, replace=False):
    Image, mozjpeg = _ensure_optimizer_deps(require_mozjpeg=not lossy)
    input_path = Path(filepath)

    try:
        with zipfile.ZipFile(input_path, 'r') as zin:
            entries = zin.infolist()
            originals = {info.filename: zin.read(info.filename) for info in entries}
    except (zipfile.BadZipFile, OSError) as e:
        return {"filename": input_path.name, "error": str(e)}

    original_size = input_path.stat().st_size
    new_entries = {}
    changed_any = False

    for name, data in originals.items():
        if name.endswith('/'):
            continue
        ext = os.path.splitext(name)[1].lower()
        if ext in OPTIMIZE_IMAGE_EXTS:
            new_data, changed = _optimize_image_bytes(
                Image, mozjpeg, name, data, lossy, jpeg_quality, png_level, webp_quality
            )
            out_name = name
            if changed and ext == '.bmp':
                out_name = os.path.splitext(name)[0] + '.png'
            new_entries[out_name] = new_data
            changed_any = changed_any or changed
        else:
            new_entries[name] = data

    if not changed_any:
        return {"filename": input_path.name, "skipped": True,
                "original_size": original_size, "optimized_size": original_size}

    tmp_fd, tmp_path = tempfile.mkstemp(suffix='.cbz', dir=str(input_path.parent))
    os.close(tmp_fd)
    try:
        with zipfile.ZipFile(tmp_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as zout:
            for name, data in new_entries.items():
                zout.writestr(name, data)

        optimized_size = os.path.getsize(tmp_path)

        if optimized_size >= original_size:
            os.remove(tmp_path)
            return {"filename": input_path.name, "skipped": True,
                    "original_size": original_size, "optimized_size": original_size}

        output_path = _resolve_optimized_output_path(input_path, replace)
        os.replace(tmp_path, output_path)

    except Exception as e:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        return {"filename": input_path.name, "error": str(e)}

    return {
        "filename": input_path.name,
        "output_name": str(output_path.relative_to(input_path.parent)) if not replace else output_path.name,
        "original_size": original_size,
        "optimized_size": optimized_size,
    }

def run_optimize(directory, replace=False, lossy=False, jpeg_quality=85, png_level=9,
                  webp_quality=85, thread_count=4, then_upload=False, use_pingo=False):
    console.print()
    console.rule("[bold magenta]MangaDot CBZ Optimizer[/bold magenta]", style="green")
    console.print()

    pingo_path = None
    if use_pingo:
        pingo_path = _ensure_pingo_ready()
        if pingo_path:
            console.print()

    if not pingo_path:
        _ensure_optimizer_deps(require_mozjpeg=not lossy)  # fail fast before scanning

    backend_label = "PINGO" if pingo_path else "BUILT-IN (mozjpeg/Pillow)"
    console.print(f"[bold white on blue] BACKEND: {backend_label} [/bold white on blue]")
    if pingo_path:
        print_info(f"pingo binary: {pingo_path}")
    console.print()

    if lossy:
        print_warning(
            "LOSSY mode enabled (--optimize-lossy): JPEG/WEBP pixel data WILL be "
            "re-encoded and quality will be reduced. This cannot be undone once "
            "originals are overwritten."
        )
        console.print()

    valid_extensions = ('.cbz', '.zip')
    try:
        targets = sorted(
            (e.path for e in os.scandir(directory)
             if e.is_file() and e.name.lower().endswith(valid_extensions)),
            key=natural_sort_key
        )
    except OSError as e:
        print_error(f"Error scanning directory {directory}: {e}")
        if not then_upload:
            sys.exit(1)
        return

    if not targets:
        print_error("No .cbz or .zip files found in this directory.")
        if not then_upload:
            sys.exit(1)
        return

    if replace:
        print_warning(
            f"--optimize-replace will overwrite {len(targets)} original archive(s) "
            "in place. This cannot be undone."
        )
        if not ask_confirm(
            f"Really overwrite all {len(targets)} original(s) in place? "
            "(No = write to an 'optimized' subfolder instead)",
            default=False
        ):
            print_info("Keeping originals — writing to an 'optimized' subfolder instead.")
            replace = False
        console.print()

    mode_desc = "IN-PLACE (originals overwritten)" if replace else "SUBFOLDER (optimized/)"
    if pingo_path:
        quality_desc = f"lossy JPEG q{jpeg_quality}/WEBP q{webp_quality}" if lossy else "lossless"
    else:
        quality_desc = f"lossy JPEG q{jpeg_quality}/WEBP q{webp_quality}" if lossy else "lossless (pixel-identical)"
    console.print(f"[bold white on dark_green] MODE: {mode_desc} [/bold white on dark_green]")
    print_info(f"Found {len(targets)} archive(s) · {quality_desc} · {thread_count} thread(s)")
    console.print()

    results = []
    start = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=thread_count) as pool:
        if pingo_path:
            futures = {
                pool.submit(optimize_cbz_pingo, path, pingo_path, replace, lossy, jpeg_quality, webp_quality): path
                for path in targets
            }
        else:
            futures = {
                pool.submit(optimize_cbz, path, lossy, jpeg_quality, png_level, webp_quality, replace): path
                for path in targets
            }
        with console.status("[cyan]Optimizing archives...[/cyan]", spinner="dots") as status:
            done = 0
            for future in concurrent.futures.as_completed(futures):
                done += 1
                result = future.result()
                results.append(result)
                status.update(f"[cyan]Optimizing archives... ({done}/{len(targets)})[/cyan]")
    elapsed = time.time() - start

    table_title = f"Optimization Results — {backend_label} · {mode_desc}"
    table = Table(title=table_title, box=box.SIMPLE_HEAVY)
    table.add_column("File", overflow="fold")
    table.add_column("Original", justify="right")
    table.add_column("Optimized", justify="right")
    table.add_column("Saved", justify="right")
    table.add_column("Status", justify="center")

    total_original = 0
    total_optimized = 0
    error_count = 0
    skipped_count = 0
    carried_forward = []  # filenames copied into optimized/ untouched (skip/error), when then_upload

    for r in sorted(results, key=lambda x: natural_sort_key(x["filename"])):
        if r.get("error"):
            error_count += 1
            table.add_row(r["filename"], "-", "-", "-", "[red]error[/red]")
            continue

        orig = r["original_size"]
        opt = r["optimized_size"]
        total_original += orig
        total_optimized += opt

        if r.get("skipped"):
            skipped_count += 1
            table.add_row(r["filename"], fmt_size(orig), fmt_size(opt), "-", "[dim]no gain[/dim]")
        else:
            saved = orig - opt
            pct = (saved / orig * 100) if orig else 0
            table.add_row(
                r["filename"], fmt_size(orig), fmt_size(opt),
                f"-{fmt_size(saved)} ({pct:.1f}%)", "[green]optimized[/green]"
            )

    console.print(table)
    console.print()

    output_dir = directory
    if then_upload and not replace:
        optimized_dir = os.path.join(directory, "optimized")
        for r in results:
            if r.get("skipped") or r.get("error"):
                src = os.path.join(directory, r["filename"])
                dst = os.path.join(optimized_dir, r["filename"])
                if os.path.exists(src) and not os.path.exists(dst):
                    try:
                        os.makedirs(optimized_dir, exist_ok=True)
                        shutil.copy2(src, dst)
                        carried_forward.append(r["filename"])
                    except OSError as e:
                        print_warning(f"Could not copy '{r['filename']}' into optimized/ for upload: {e}")
        output_dir = optimized_dir
        if carried_forward:
            print_info(
                f"Copied {len(carried_forward)} skipped/errored file(s) into optimized/ "
                "unchanged, so the upload sees the complete set."
            )

    optimized_count = len(results) - error_count - skipped_count
    total_saved = total_original - total_optimized
    total_pct = (total_saved / total_original * 100) if total_original else 0

    print_info(
        f"{optimized_count} optimized · {skipped_count} skipped (no gain) · "
        f"{error_count} error(s) · {fmt_duration(elapsed)}"
    )
    if total_saved > 0:
        print_success(f"Total saved: {fmt_size(total_saved)} ({total_pct:.1f}% smaller)")
    console.print()

    if not then_upload:
        input("Press Enter to exit... ")
        sys.exit(0)

    return output_dir



# ==============================================================================
# 🔑 AUTH & API HELPERS
# ==============================================================================

def validate_session(session):
    try:
        res = session.get(f"{BASE_URL}/api/profile", timeout=(10, 30))
        if res.status_code == 200:
            data = res.json()
            profile = data.get("profile", {})
            name = profile.get("username") or profile.get("email")
            user_id = profile.get("id") or profile.get("user_id") or profile.get("uid")
            return name, user_id
    except requests.exceptions.RequestException as e:
        logging.debug("validate_session: network error: %s", e)
    except json.JSONDecodeError as e:
        logging.debug("validate_session: unexpected (non-JSON) response: %s", e)
    return None, None

def search_manga(query, session):
    try:
        res = session.get(f"{BASE_URL}/search.data", params={"search": query}, timeout=(10, 30))
        if res.status_code != 200: return []
        arr = res.json()
    except requests.exceptions.RequestException as e:
        print_warning(f"Network error while searching for manga: {e}")
        return []
    except json.JSONDecodeError as e:
        logging.debug("search_manga: bad JSON response: %s", e)
        print_warning("Search returned an unreadable response. The site API may have changed.")
        return []

    mangas = []
    if not isinstance(arr, list): return []

    raw_item_count = sum(1 for item in arr if isinstance(item, dict))
    for item in arr:
        if not isinstance(item, dict): continue
        decoded = {}
        for k, v in item.items():
            if k.startswith('_') and k[1:].isdigit():
                key_idx = int(k[1:])
                if (
                    key_idx < len(arr)
                    and isinstance(arr[key_idx], str)
                    and isinstance(v, int)
                    and 0 <= v < len(arr)
                ):
                    key_str = arr[key_idx]
                    val     = arr[v]
                    decoded[key_str] = val
            else:
                decoded[k] = v
        if "id" in decoded and "title" in decoded and isinstance(decoded["id"], int): mangas.append(decoded)

    if raw_item_count > 0 and not mangas:
        logging.warning("search_manga: API returned %d item(s) but none decoded successfully. "
                        "The search.data response schema may have changed.", raw_item_count)
        print_warning("Search returned results but could not be decoded. The site API may have changed.")

    seen = set()
    return [m for m in mangas if not (m["id"] in seen or seen.add(m["id"]))]

def search_groups(query, session):
    try:
        res = session.get(
            f"{BASE_URL}/api/groups/lookup",
            params={"q": query, "limit": 25},
            headers={"Referer": f"{BASE_URL}/"},
            timeout=(10, 30),
        )
        if res.status_code != 200: return []
        raw_groups = res.json().get("groups", [])
        cleaned = []
        for g in raw_groups:
            if isinstance(g, dict) and "id" in g:
                try:
                    g["id"] = int(g["id"])
                except (ValueError, TypeError):
                    pass
                cleaned.append(g)
        return cleaned
    except requests.exceptions.RequestException as e:
        print_warning(f"Network error while searching for groups: {e}")
        return []
    except json.JSONDecodeError as e:
        logging.debug("search_groups: bad JSON response: %s", e)
        print_warning("Group search returned an unreadable response. The site API may have changed.")
        return []

# ---------------------------------------------------------------------------
# MangaBaka -> MangaDot create flow (CLI mirror of GUI's net.py helpers)
# Direct create with no metadata editing; manual entry just prints the link.
# ---------------------------------------------------------------------------
MANGABAKA_API_BASE = "https://api.mangabaka.org"

def _mangabaka_primary_title(titles):
    if not isinstance(titles, list) or not titles:
        return ""
    for t in titles:
        if t.get("is_primary") and t.get("language") == "ja-Latn":
            return t.get("title", "")
    for t in titles:
        if t.get("is_primary"):
            return t.get("title", "")
    return titles[0].get("title", "")

def _mangabaka_thumbnail_url(cover):
    if not isinstance(cover, dict):
        return None
    for size_key in ("x150", "x250", "x350", "raw"):
        size = cover.get(size_key)
        if isinstance(size, dict):
            url = size.get("x1") or size.get("url")
            if url:
                return url
        elif isinstance(size, str) and size:
            return size
    return None

def search_mangabaka(query, limit=12):
    try:
        res = requests.get(
            f"{MANGABAKA_API_BASE}/v2/series/search",
            params={"q": query, "limit": limit},
            timeout=(10, 30),
        )
        if res.status_code != 200:
            error = f"MangaBaka returned HTTP {res.status_code}."
            logging.error(f"search_mangabaka: {error} (query={query!r})")
            return [], error
        payload = res.json()
    except requests.exceptions.RequestException as e:
        logging.error(f"Network error while searching MangaBaka: {e}")
        return [], "Couldn't reach MangaBaka."
    except json.JSONDecodeError as e:
        logging.error(f"MangaBaka search returned an unreadable response: {e}")
        return [], "MangaBaka sent back something unreadable."
    raw_results = payload.get("data")
    if not isinstance(raw_results, list):
        error = "MangaBaka's response wasn't in the expected shape."
        logging.error(f"search_mangabaka: {error} (query={query!r}, payload keys={list(payload.keys())})")
        return [], error
    results = []
    for item in raw_results:
        if not isinstance(item, dict) or "id" not in item:
            continue
        series_id = item["id"]
        results.append({
            "id": series_id,
            "title": _mangabaka_primary_title(item.get("titles")) or "Untitled",
            "status": item.get("status", ""),
            "cover_url": _mangabaka_thumbnail_url(item.get("cover")),
            "mangabaka_url": f"https://mangabaka.org/{series_id}",
        })
    return results, None

def _normalize_mangabaka_url(url: str) -> str:
    if not url:
        return ""
    url = url.split("?")[0].split("#")[0].rstrip("/")
    m = re.search(r"/manga/([^/]+)(?:/([^/]+))?", url)
    if m:
        manga_id = m.group(1)
        slug = m.group(2)
        if slug:
            return f"https://mangabaka.com/manga/{manga_id}/{slug}"
        return f"https://mangabaka.com/manga/{manga_id}"
    return url

def fetch_mangabaka_metadata(mangabaka_url, session):
    norm_url = _normalize_mangabaka_url(mangabaka_url)
    try:
        res = session.post(
            f"{BASE_URL}/api/manga/fetch-mangabaka",
            json={"url": norm_url},
            timeout=(10, 30),
        )
        try:
            payload = res.json()
        except json.JSONDecodeError as e:
            logging.error(f"fetch_mangabaka_metadata: unreadable response (HTTP {res.status_code}): {e}")
            return {"ok": False, "error": "MangaDot sent back something unreadable."}

        # 1. Successful fetch: MangaDot returns {"data": {...}} (success field omitted in new API)
        if res.status_code == 200:
            if isinstance(payload.get("data"), dict):
                return {"ok": True, "duplicate": False, "data": payload["data"]}
            if payload.get("success") and isinstance(payload.get("data"), dict):
                return {"ok": True, "duplicate": False, "data": payload["data"]}

        # 2. Duplicate detection: MangaDot returns 409 Conflict with RFC 7807 problem JSON:
        # {"code": "duplicate_manga", "existing": {"id": 123, "title": "..."}}
        if (
            res.status_code == 409
            or payload.get("code") == "duplicate_manga"
            or payload.get("detail") == "duplicate"
            or payload.get("error") == "duplicate"
        ):
            dup = payload.get("existing") or payload.get("duplicate") or {}
            if isinstance(dup, dict) and dup.get("id"):
                return {"ok": True, "duplicate": True, "id": dup.get("id"), "title": dup.get("title")}

        err_msg = payload.get("detail") or payload.get("error") or f"HTTP {res.status_code}"
        return {"ok": False, "error": str(err_msg)}

    except requests.exceptions.RequestException as e:
        logging.error(f"fetch_mangabaka_metadata: network error: {e}")
        return {"ok": False, "error": "Couldn't reach MangaDot."}

def create_manga_from_mangabaka(metadata, session):
    try:
        res = session.post(
            f"{BASE_URL}/api/manga/create-from-mangabaka",
            json=metadata,
            timeout=(10, 30),
        )
        try:
            payload = res.json()
        except json.JSONDecodeError as e:
            logging.error(f"create_manga_from_mangabaka: unreadable response (HTTP {res.status_code}): {e}")
            return {"ok": False, "error": "MangaDot sent back something unreadable."}
        if res.status_code in (200, 201):
            manga = payload.get("manga")
            if isinstance(manga, dict):
                return {"ok": True, "id": manga.get("id"), "title": manga.get("title")}
            if payload.get("success") and isinstance(payload.get("manga"), dict):
                manga = payload["manga"]
                return {"ok": True, "id": manga.get("id"), "title": manga.get("title")}
        return {"ok": False, "error": payload.get("detail") or payload.get("error") or f"HTTP {res.status_code}"}
    except requests.exceptions.RequestException as e:
        logging.error(f"create_manga_from_mangabaka: network error: {e}")
        return {"ok": False, "error": "Couldn't reach MangaDot."}

def _group_search_queries(name):
    queries = [name]
    if not re.search(r'\s', name):
        camel = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', name)
        if camel != name:
            queries.append(camel)
        queries.extend(name[:i] + ' ' + name[i:] for i in range(1, min(len(name), 7)))
    return queries

def detect_groups_from_filenames(directory, upload_type="chapter"):
    valid_ext = ('.cbz', '.zip')
    counter   = {}
    per_file  = {}

    try:
        filenames = [f for f in os.listdir(directory) if f.lower().endswith(valid_ext)]
    except OSError:
        return [], {}

    for filename in filenames:
        filepath = _norm_filepath(os.path.join(directory, filename))
        name  = re.sub(r'\.(cbz|zip)$', '', filename, flags=re.IGNORECASE)
        
        found, _ = _extract_parenthesis_groups(name) if upload_type == "volume" else _extract_bracket_groups(name)

        if found:
            per_file[filepath] = found
            key = frozenset(n.lower() for n in found)
            prev_count, prev_names = counter.get(key, (0, found))
            counter[key] = (prev_count + 1, prev_names)

    if not counter:
        return [], {}

    all_unique_names = list({name for _, names in counter.values() for name in names})
    return all_unique_names, per_file

def resolve_group_names(names, session):
    group_ids  = []
    unresolved = []

    for name in names:
        results    = []
        clean_name = name
        queries    = _group_search_queries(name)

        for q in queries:
            with console.status(f"[cyan]Searching for group '{q}'...[/cyan]", spinner="dots"):
                results = search_groups(q, session)
            if results:
                clean_name = q
                break

        if not results:
            print_warning(f"No groups found for '{name}'.")
            unresolved.append(name)
            continue

        exact = [g for g in results if g['name'].lower() in (name.lower(), clean_name.lower())]
        if len(exact) == 1:
            group_ids.append(exact[0]['id'])
            print_success(f"Auto-matched group: {exact[0]['name']} (ID: {exact[0]['id']})")
            continue

        choices = [questionary.Choice(title=f"{g['name']} (ID: {g['id']})", value=g) for g in results]
        choices.append(questionary.Choice(title="Skip this group", value="__skip__"))
        pick = ask_select(f"Multiple results for '{name}' — select one:", choices)
        if pick == "__skip__":
            unresolved.append(name)
        else:
            group_ids.append(pick['id'])
            print_success(f"Selected: {pick['name']} (ID: {pick['id']})")

    return group_ids, unresolved

class SessionExpiredError(Exception): pass
class BatchInitError(Exception): pass

def _read_cookie_db_safely(db_path, domains=None):
    """Reads a Gecko cookies.sqlite: rookiepy direct first (works when the
    browser is fully closed), then a SQLite Backup-API copy of the live DB.
    IMPORTANT: the source is opened mode=ro, never immutable=1 - immutable
    skips locking AND ignores pending -wal contents, so recently-created
    session cookies (which Firefox/Zen keep in WAL until checkpointed)
    would be silently missed."""
    try:
        result = rookiepy.firefox_based(db_path, domains=domains)
        logging.debug(
            "rookiepy direct read of %s succeeded, %d cookie(s) for domains=%s",
            db_path, len(result), domains,
        )
        return result
    except Exception as e:
        logging.debug("rookiepy direct read failed for %s: %s: %s", db_path, type(e).__name__, e)

    tmp_dir = tempfile.mkdtemp(prefix="mangadot_gecko_")
    try:
        tmp_db = os.path.join(tmp_dir, "cookies.sqlite")
        db_uri = Path(db_path).resolve().as_uri() + "?mode=ro"
        try:
            with sqlite3.connect(db_uri, uri=True, timeout=5) as src, \
                 sqlite3.connect(tmp_db) as dst:
                src.backup(dst)
        except sqlite3.Error as e:
            logging.debug("SQLite backup failed for %s: %s: %s", db_path, type(e).__name__, e)
            return []

        result = rookiepy.firefox_based(tmp_db, domains=domains)
        logging.debug(
            "Fallback (mode=ro backup) read of %s succeeded, %d cookie(s) for domains=%s",
            db_path, len(result), domains,
        )
        return result
    except Exception as e:
        logging.debug("Fallback read failed for %s: %s: %s", db_path, type(e).__name__, e)
        return []
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

def get_gecko_cookies(browser_name, domains=None):
    """Passive cookie read from any real Firefox/Zen profile on disk.
    Databases are tried newest-first so the active profile wins."""
    if sys.platform == 'win32':
        if browser_name == "firefox":
            profile_roots = [os.path.expandvars(r'%APPDATA%\Mozilla\Firefox\Profiles')]
        else:  # Zen
            profile_roots = [
                os.path.expandvars(r'%LOCALAPPDATA%\zen\Profiles'),
                os.path.expandvars(r'%APPDATA%\Zen\Profiles'),
                os.path.expandvars(r'%APPDATA%\zen\Profiles'),
                os.path.expandvars(r'%APPDATA%\zen-browser\Profiles'),
                os.path.expandvars(r'%APPDATA%\ZenBrowser\Profiles'),
                os.path.expandvars(r'%LOCALAPPDATA%\ZenBrowser\Profiles'),
            ]
    elif sys.platform == 'darwin':
        if browser_name == "firefox":
            profile_roots = [os.path.expanduser('~/Library/Application Support/Firefox/Profiles')]
        else:
            profile_roots = [
                os.path.expanduser('~/Library/Application Support/zen/Profiles'),
                os.path.expanduser('~/Library/Application Support/Zen/Profiles'),
            ]
    else:
        profile_roots = ([os.path.expanduser('~/.mozilla/firefox')] if browser_name == "firefox"
                         else [os.path.expanduser('~/.zen')])

    all_dbs = []
    for root in profile_roots:
        if not os.path.isdir(root):
            continue
        for entry in os.listdir(root):
            db_path = os.path.join(root, entry, 'cookies.sqlite')
            if os.path.isfile(db_path):
                all_dbs.append(db_path)

    # Newest first, so the profile the user actually uses gets tried first.
    all_dbs.sort(key=lambda x: os.path.getmtime(x) if os.path.exists(x) else 0, reverse=True)

    for db_path in all_dbs:
        cookies = _read_cookie_db_safely(db_path, domains=domains)
        if cookies:
            return cookies

    return []
# ==============================================================================
# 🔑 CDP-based cookie retrieval (Chromium browsers)
# ==============================================================================

CDP_REGISTRY_APP_NAMES = {
    "chrome":  "chrome.exe",
    "edge":    "msedge.exe",
    "brave":   "brave.exe",
    "vivaldi": "vivaldi.exe",
    "opera":   "opera.exe",
}

def _find_browser_via_registry(app_exe_name):
    if sys.platform != "win32":
        return None
    try:
        import winreg
    except ImportError:
        return None

    reg_paths = [
        (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{app_exe_name}"),
        (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\{app_exe_name}"),
        (winreg.HKEY_CURRENT_USER,  rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{app_exe_name}"),
    ]
    for hive, path in reg_paths:
        try:
            with winreg.OpenKey(hive, path) as key:
                value, _ = winreg.QueryValueEx(key, "")
                if value and os.path.isfile(value):
                    return value
        except FileNotFoundError:
            continue
        except OSError:
            continue
    return None

def _find_executable(browser_key, registry_app_names, executables_table):
    """Shared lookup for both the CDP (Chromium) and Gecko finders: Windows
    registry App Paths first, then the per-platform candidate list (PATH
    search on Linux, literal file check elsewhere)."""
    plat = sys.platform
    plat_key = "win32" if plat == "win32" else ("darwin" if plat == "darwin" else "linux")

    if plat_key == "win32":
        app_exe = registry_app_names.get(browser_key)
        if app_exe:
            found = _find_browser_via_registry(app_exe)
            if found:
                return found

    candidates = executables_table.get(browser_key, {}).get(plat_key, [])
    for candidate in candidates:
        expanded = os.path.expandvars(candidate)
        if plat_key == "linux":
            found = shutil.which(expanded)
            if found:
                return found
        else:
            if os.path.isfile(expanded):
                return expanded
    return None

def _find_browser_executable(browser_key):
    return _find_executable(browser_key, CDP_REGISTRY_APP_NAMES, CDP_BROWSER_EXECUTABLES)

def _find_gecko_executable(browser_key):
    return _find_executable(browser_key, GECKO_REGISTRY_APP_NAMES, GECKO_BROWSER_EXECUTABLES)

def _cdp_port_is_up(port, timeout=1.0):
    try:
        r = requests.get(f"http://127.0.0.1:{port}/json/version", timeout=timeout)
        return r.status_code == 200
    except requests.exceptions.RequestException:
        return False

def _cdp_wait_for_port(port, timeout=CDP_STARTUP_WAIT):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _cdp_port_is_up(port):
            return True
        time.sleep(0.5)
    return False

def _cdp_pid_file(browser_key):
    return os.path.join(_cdp_profile_dir_for(browser_key), ".cdp_launch.pid")

def _cdp_pid_matches_expected_exe(pid, expected_exe):
    if not expected_exe:
        return False
    expected_name = os.path.basename(expected_exe).lower()
    expected_name_stripped = re.sub(r'\.exe$', '', expected_name)

    try:
        if sys.platform == "win32":
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=5, check=False,
            )
            if result.returncode != 0 or not result.stdout.strip():
                return False
            first_field = result.stdout.strip().split(',')[0].strip('"')
            running_name = re.sub(r'\.exe$', '', first_field.lower())
            return running_name == expected_name_stripped

        elif sys.platform == "darwin":
            result = subprocess.run(
                ["ps", "-p", str(pid), "-o", "comm="],
                capture_output=True, text=True, timeout=5, check=False,
            )
            if result.returncode != 0 or not result.stdout.strip():
                return False
            running_path = result.stdout.strip()
            running_name = os.path.basename(running_path).lower()
            return running_name == expected_name or expected_name in running_path.lower()

        else: 
            proc_exe = f"/proc/{pid}/exe"
            if os.path.exists(proc_exe):
                try:
                    resolved = os.readlink(proc_exe)
                    return os.path.basename(resolved).lower() == expected_name
                except OSError:
                    pass  
            result = subprocess.run(
                ["ps", "-p", str(pid), "-o", "comm="],
                capture_output=True, text=True, timeout=5, check=False,
            )
            if result.returncode != 0 or not result.stdout.strip():
                return False
            running_name = os.path.basename(result.stdout.strip()).lower()
            return running_name == expected_name
    except (subprocess.SubprocessError, OSError, RuntimeError):
        # RuntimeError: subprocess.run can fail with "can't create new thread"
        # when one of these lookups runs from an atexit handler during
        # interpreter shutdown - nothing to do but give up quietly.
        return False

def _wait_for_process_exit(pid, timeout=0.5, poll_interval=0.05):
    """Polls whether `pid` is still alive, returning as soon as it exits or
    once `timeout` seconds have passed - used after SIGTERM so a browser gets
    a real chance to exit cleanly before escalating to SIGKILL."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            pass
        time.sleep(poll_interval)
    return False

def _gecko_pid_file(browser_key):
    return os.path.join(_gecko_debug_profile_dir_for(browser_key), ".gecko_launch.pid")

def _kill_stale_tracked_process(pid_file, expected_exe):
    """Shared body of _cdp_kill_stale_process/_gecko_kill_stale_process:
    reads the launch-time pid file, verifies the pid really is our browser
    (not a recycled pid), force-kills it, and removes the pid file."""
    if not os.path.isfile(pid_file):
        return
    try:
        with open(pid_file, "r", encoding="utf-8") as f:
            old_pid = int(f.read().strip())
    except (ValueError, OSError):
        return

    if not _cdp_pid_matches_expected_exe(old_pid, expected_exe):
        try:
            os.remove(pid_file)
        except OSError:
            pass
        return

    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/PID", str(old_pid), "/F", "/T"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
            )
        else:
            import signal
            try:
                os.kill(old_pid, signal.SIGTERM)
                _wait_for_process_exit(old_pid, timeout=0.5)
                os.kill(old_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    except (OSError, subprocess.SubprocessError, RuntimeError):
        pass
    finally:
        try:
            os.remove(pid_file)
        except OSError:
            pass

def _cdp_kill_stale_process(browser_key):
    _kill_stale_tracked_process(_cdp_pid_file(browser_key),
                                _find_browser_executable(browser_key))

def _gecko_kill_stale_process(browser_key):
    _kill_stale_tracked_process(_gecko_pid_file(browser_key),
                                _find_gecko_executable(browser_key))

def _kill_processes_by_profile_dir(profile_dir):
    """Kills every process whose command line references profile_dir,
    regardless of PID - the fallback for browsers that re-exec/hand off to
    a fresh child right after launch (common with a fresh --user-data-dir),
    leaving the launch-time pid pointing at a long-dead process. Matching on
    profile_dir keeps this safe: it is this app's own dedicated per-browser
    directory that only ever appears on a command line because THIS script
    passed it as --user-data-dir/-profile, so normal browsing windows can
    never match it."""
    try:
        if sys.platform == "win32":
            # wmic is deprecated but still present on Windows 10/11 as of
            # this writing; tasklist has no command-line filter. Falls back
            # to PowerShell's CIM cmdlet. The profile dir reaches PowerShell
            # through an ENV VAR rather than string interpolation - no
            # quoting scheme survives every possible path, but an env var
            # needs none at all: apostrophes/backslashes/spaces pass through
            # untouched and no crafted path can break out of the -like
            # comparison.
            pids = []
            if "'" not in profile_dir:
                # A WQL string literal cannot escape an apostrophe at all,
                # so paths containing ' skip straight to PowerShell.
                escaped = profile_dir.replace("\\", "\\\\")  # WQL LIKE treats \ as its escape char
                result = subprocess.run(
                    ["wmic", "process", "where",
                     f"CommandLine like '%{escaped}%'", "get", "ProcessId"],
                    capture_output=True, text=True, timeout=10, check=False,
                )
                if result.returncode == 0:
                    pids = [int(p) for p in re.findall(r'\d+', result.stdout)]
            if not pids:
                env = dict(os.environ)
                env["MANGADOT_PROFILE_DIR"] = profile_dir
                ps_cmd = (
                    "Get-CimInstance Win32_Process | "
                    "Where-Object { $_.CommandLine -like ('*' + $env:MANGADOT_PROFILE_DIR + '*') } | "
                    "Select-Object -ExpandProperty ProcessId"
                )
                result = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", ps_cmd],
                    capture_output=True, text=True, timeout=10, check=False, env=env,
                )
                pids = [int(p) for p in re.findall(r'\d+', result.stdout)]
            for pid in pids:
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/F", "/T"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
                )
        else:
            result = subprocess.run(
                ["pgrep", "-f", re.escape(profile_dir)],
                capture_output=True, text=True, timeout=10, check=False,
            )
            pids = [int(p) for p in result.stdout.split()]
            for pid in pids:
                try:
                    import signal
                    os.kill(pid, signal.SIGTERM)
                except ProcessLookupError:
                    continue
            for pid in pids:
                if _wait_for_process_exit(pid, timeout=0.5):
                    continue
                try:
                    import signal
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
    except (subprocess.SubprocessError, OSError, ValueError, RuntimeError) as e:
        logging.debug("_kill_processes_by_profile_dir(%r): %s", profile_dir, e)

def cleanup_all_cdp_processes():
    for browser in ["chrome", "edge", "brave", "vivaldi", "opera"]:
        _cdp_kill_stale_process(browser)
        _kill_processes_by_profile_dir(_cdp_profile_dir_for(browser))

def cleanup_all_gecko_debug_processes():
    for browser in ["zen", "firefox"]:
        _gecko_kill_stale_process(browser)
        _kill_processes_by_profile_dir(_gecko_debug_profile_dir_for(browser))

atexit.register(cleanup_all_cdp_processes)
atexit.register(cleanup_all_gecko_debug_processes)

def _cdp_launch_browser(browser_key, url):
    exe = _find_browser_executable(browser_key)
    if not exe:
        return None

    _cdp_kill_stale_process(browser_key)

    port = _cdp_port_for(browser_key)
    profile_dir = _cdp_profile_dir_for(browser_key)
    os.makedirs(profile_dir, exist_ok=True)
    args = [
        exe,
        f"--remote-debugging-port={port}",
        f"--remote-allow-origins=http://127.0.0.1:{port}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        url,
    ]
    try:
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if sys.platform == "win32" else 0
        proc = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        try:
            with open(_cdp_pid_file(browser_key), "w", encoding="utf-8") as f:
                f.write(str(proc.pid))
        except OSError:
            proc.terminate()
            return None
        return proc
    except (OSError, subprocess.SubprocessError):
        return None

def _cdp_get_targets(port):
    try:
        r = requests.get(f"http://127.0.0.1:{port}/json/list", timeout=5)
        r.raise_for_status()
        return r.json()
    except (requests.exceptions.RequestException, json.JSONDecodeError):
        return []

def _cdp_open_new_tab(port, url):
    try:
        r = requests.put(f"http://127.0.0.1:{port}/json/new?{url}", timeout=5)
        if r.status_code >= 400:
            r = requests.get(f"http://127.0.0.1:{port}/json/new?{url}", timeout=5)
        r.raise_for_status()
        return r.json()
    except (requests.exceptions.RequestException, json.JSONDecodeError):
        return None

def _cdp_get_all_cookies(port, timeout=10):
    targets = [t for t in _cdp_get_targets(port) if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
    if not targets:
        new_target = _cdp_open_new_tab(port, BASE_URL)
        if new_target and new_target.get("webSocketDebuggerUrl"):
            targets = [new_target]

    if not targets:
        return None

    ws_url = targets[0]["webSocketDebuggerUrl"]
    try:
        ws = websocket.create_connection(ws_url, timeout=timeout)
        try:
            ws.send(json.dumps({"id": 1, "method": "Network.getAllCookies"}))
            ws.settimeout(timeout)
            while True:
                raw = ws.recv()
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if msg.get("id") == 1:
                    return msg.get("result", {}).get("cookies", [])
        finally:
            ws.close()
    except (websocket.WebSocketException, OSError, TimeoutError) as e:
        logging.debug("_cdp_get_all_cookies: websocket connection to %s failed: %s", ws_url, e)
        return None

def _tracked_process_alive(pid_file):
    """Shared body of _cdp_tracked_process_alive/_gecko_tracked_process_alive."""
    if not os.path.isfile(pid_file):
        return False
    try:
        with open(pid_file, "r", encoding="utf-8") as f:
            pid = int(f.read().strip())
    except (ValueError, OSError):
        return False

    if sys.platform == "win32":
        try:
            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}"],
                capture_output=True, text=True, timeout=5, check=False,
            )
            return str(pid) in out.stdout
        except (subprocess.SubprocessError, OSError, RuntimeError):
            # RuntimeError: possible interpreter-shutdown race (atexit).
            return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, PermissionError):
            return False
        except OSError:
            return False

def _cdp_tracked_process_alive(browser_key):
    return _tracked_process_alive(_cdp_pid_file(browser_key))

def _gecko_tracked_process_alive(browser_key):
    return _tracked_process_alive(_gecko_pid_file(browser_key))

def get_cdp_cookies(browser_key, domains=None):
    port = _cdp_port_for(browser_key)
    port_up = _cdp_port_is_up(port)
    trusted = port_up and _cdp_tracked_process_alive(browser_key)

    if not trusted:
        launched_proc = _cdp_launch_browser(browser_key, BASE_URL)
        if launched_proc is None:
            print_error(f"Could not find or launch {browser_key.title()} for CDP mode.")
            print_info(f"If {browser_key.title()} is installed in a custom location, add its "
                       f"full path to the CDP_BROWSER_EXECUTABLES dict near the top of this script "
                       f"(under \"{browser_key}\" -> your OS).")
            return []

        print_info(f"Launched a dedicated {browser_key.title()} debug profile.")
        print_info("If this is the first run, log into MangaDot in that window, then come back here.")

        if not _cdp_wait_for_port(port):
            print_error("Timed out waiting for the browser's debug port to come up.")
            return []

        if not _cdp_open_new_tab(port, BASE_URL):
            print_warning(f"Couldn't confirm {browser_key.title()} navigated to MangaDot -- "
                           f"if the window looks blank, open {BASE_URL} in it manually.")

    raw_cookies = _cdp_get_all_cookies(port) or []

    domains = domains or []
    filtered = [
        {"name": c["name"], "value": c["value"], "domain": c["domain"]}
        for c in raw_cookies
        if not domains or any(c.get("domain", "").endswith(d.lstrip(".")) for d in domains)
    ]
    return filtered

# --- Dedicated debug-profile launch for Gecko browsers (Zen/Firefox) ------
# MangaDot's Cloudflare managed challenge needs a real browser engine; this
# gives Gecko browsers what CDP gives Chromium: a window WE launch with an
# isolated profile that can clear the challenge once, whose cookies.sqlite
# we then read like any other profile.

def _launch_gecko_debug_browser(browser_key, url):
    exe = _find_gecko_executable(browser_key)
    if not exe:
        return None

    _gecko_kill_stale_process(browser_key)

    profile_dir = _gecko_debug_profile_dir_for(browser_key)
    os.makedirs(profile_dir, exist_ok=True)
    args = [
        exe,
        "-profile", profile_dir,
        "-no-remote",
        "-new-instance",
        url,
    ]
    try:
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if sys.platform == "win32" else 0
        proc = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        try:
            with open(_gecko_pid_file(browser_key), "w", encoding="utf-8") as f:
                f.write(str(proc.pid))
        except OSError:
            proc.terminate()
            return None
        return proc
    except (OSError, subprocess.SubprocessError):
        return None

def get_gecko_debug_cookies(browser_key, domains=None):
    """Reads cookies from a dedicated debug profile this script launches and
    controls - not any of the person's real profiles - so a real Gecko engine
    can clear MangaDot's Cloudflare challenge once and we reuse the session."""
    profile_dir = _gecko_debug_profile_dir_for(browser_key)
    already_running = _gecko_tracked_process_alive(browser_key)

    if not already_running:
        launched_proc = _launch_gecko_debug_browser(browser_key, BASE_URL)
        if launched_proc is None:
            print_error(f"Could not find or launch {browser_key.title()} for the debug-profile login flow.")
            print_info(f"If {browser_key.title()} is installed in a custom location, add its full path "
                       f"to GECKO_BROWSER_EXECUTABLES near the top of this script.")
            return []
        print_info(f"Opened a dedicated {browser_key.title()} window for MangaDot sign-in.")
        print_info("Log into MangaDot in that window (solve the Cloudflare check if it appears), "
                   "then come back here.")

    db_path = os.path.join(profile_dir, "cookies.sqlite")
    deadline = time.time() + GECKO_DEBUG_STARTUP_WAIT
    cookies = []
    while time.time() < deadline:
        if os.path.isfile(db_path):
            cookies = _read_cookie_db_safely(db_path, domains=domains)
            if cookies:
                break
        time.sleep(1.0)

    return cookies

def authenticate_session(req_session, force_browser=None):
    supported_browsers = {
        "zen": lambda domains=None: get_gecko_cookies("zen", domains=domains),
        "chrome": rookiepy.chrome,
        # Firefox/Zen read passively off disk first (newest profile wins);
        # if Cloudflare or a locked DB gets in the way, the dedicated
        # "(debug)" variants below launch a real Gecko engine instead.
        "firefox": lambda domains=None: get_gecko_cookies("firefox", domains=domains),
        "brave": rookiepy.brave,
        "edge": rookiepy.edge,
        "opera": rookiepy.opera,
        "vivaldi": rookiepy.vivaldi,
    }

    cdp_browsers = {
        "chrome (cdp)":  lambda domains=None: get_cdp_cookies("chrome", domains=domains),
        "edge (cdp)":    lambda domains=None: get_cdp_cookies("edge", domains=domains),
        "brave (cdp)":   lambda domains=None: get_cdp_cookies("brave", domains=domains),
        "vivaldi (cdp)": lambda domains=None: get_cdp_cookies("vivaldi", domains=domains),
        "opera (cdp)":   lambda domains=None: get_cdp_cookies("opera", domains=domains),
    }

    gecko_debug_browsers = {
        "zen (debug)":     lambda domains=None: get_gecko_debug_cookies("zen", domains=domains),
        "firefox (debug)": lambda domains=None: get_gecko_debug_cookies("firefox", domains=domains),
    }

    all_browsers = {**supported_browsers, **cdp_browsers, **gecko_debug_browsers}
    browsers_to_try = {force_browser: all_browsers[force_browser]} if force_browser else supported_browsers

    if not force_browser:
        print_info("Scanning all installed browsers for an active MangaDot session...")

    for browser_name, get_cookies_fn in browsers_to_try.items():
        try:
            req_session.cookies.clear()
            ua_key = browser_name.replace(" (cdp)", "").replace(" (debug)", "")
            req_session.headers.update({"User-Agent": get_dynamic_user_agent(ua_key)})

            loud = force_browser or (browser_name == "zen")
            
            browser_cookies = get_cookies_fn(domains=["mangadot.net", ".mangadot.net"])
            if not browser_cookies:
                if loud:
                    print_warning(f"{browser_name.title()}: no MangaDot cookies found in this browser's storage.")
                else:
                    console.print(f"  [dim]· {browser_name.title()}: no session cookies found[/dim]")
                continue

            for cookie in browser_cookies: 
                req_session.cookies.set(cookie['name'], cookie['value'], domain=cookie['domain'])
    
            email, user_id = validate_session(req_session)
            if not email:
                # Maybe the cached UA is stale (browser updated): re-detect once and retry.
                fresh_ua = get_dynamic_user_agent(ua_key, force_refresh=True)
                if fresh_ua != req_session.headers.get("User-Agent"):
                    req_session.headers.update({"User-Agent": fresh_ua})
                    email, user_id = validate_session(req_session)
            if email:
                print_success(f"Successfully authenticated via {browser_name.title()}: [bold]{email}[/bold]")
                return browser_name, user_id
            elif loud:
                cookie_names = [c['name'] for c in browser_cookies]
                print_warning(f"{browser_name.title()}: found {len(browser_cookies)} cookie(s) ({', '.join(cookie_names)}), "
                              f"but the server didn't recognize the session as logged in.")
            else:
                console.print(f"  [dim]· {browser_name.title()}: found {len(browser_cookies)} cookie(s), session not recognized[/dim]")
        
        except Exception as e:
            safe_loud = force_browser or (browser_name == "zen")
            hint = ""
            if browser_name in CHROMIUM_BROWSERS:
                hint = (f" [dim]-- rookiepy reads Gecko browsers (Zen/Firefox) straight off disk, no issue there; "
                        f"Chromium browsers encrypt cookies at rest and usually block direct decryption -- "
                        f"try '{browser_name.title()} (Cdp)' instead.[/dim]")
            if safe_loud:
                print_warning(f"{browser_name.title()}: {type(e).__name__}: {_redact_home_path(e)}{hint}")
            else:
                console.print(f"  [dim]· {browser_name.title()}: {type(e).__name__}: {_redact_home_path(e)}[/dim]{hint}")
            continue 

    print_error("No valid MangaDot session found. Ensure your browser is FULLY CLOSED and you are logged in.")
    print_info("Zen/Firefox are read directly and should just work if you're logged in there; "
               "if Cloudflare blocks them, try 'Zen (Debug)' / 'Firefox (Debug)' (opens a real browser window). "
               "Chrome/Brave/Edge/Opera/Vivaldi usually can't be read directly (encrypted cookie store) — "
               "use their '(CDP)' option instead of the plain one.")
    
    browser_choices = [questionary.Choice(title=name.title(), value=name) for name in all_browsers.keys()]
    browser_choices.append(questionary.Choice(title="Quit script", value="__quit__"))

    choice = ask_select("Select a browser to retry manually:", browser_choices)
    if choice == "__quit__":
        print_info("Exiting script.")
        sys.exit(0)
        
    return authenticate_session(req_session, force_browser=choice)

# ==============================================================================
# 📤 TUS UPLOAD WORKER
# ==============================================================================

def _compute_retry_delay(response, attempt):
    jitter = random.uniform(0.5, 2.5)
    if response is not None:
        ra = response.headers.get("Retry-After")
        if ra:
            try:
                return max(0.0, min(float(ra), 120.0)) + jitter
            except (TypeError, ValueError):
                pass
        try:
            body = response.json()
            if isinstance(body, dict) and "retry_after" in body:
                return max(0.0, min(float(body["retry_after"]), 120.0)) + jitter
        except Exception:
            pass
    return min(RETRY_DELAY * (2 ** attempt), 60) + jitter

def _interruptible_sleep(delay, abort_event, slice_seconds=0.1):
    if delay <= 0:
        return not abort_event.is_set()
    remaining = delay
    while remaining > 0:
        if abort_event.is_set():
            return False
        step = min(slice_seconds, remaining)
        time.sleep(step)
        remaining -= step
    return not abort_event.is_set()

def _tus_offset(session, location):
    try:
        r = session.head(location, headers={"Tus-Resumable": "1.0.0"}, timeout=(10, 30))
        if r.status_code in (401, 403): raise SessionExpiredError()
        if r.status_code in (200, 204):
            off = r.headers.get("Upload-Offset")
            if off is not None:
                return int(off)
    except SessionExpiredError: raise
    except (requests.exceptions.RequestException, ValueError) as e:
        logging.debug("_tus_offset(%s): %s", location, e)
        return None
    return None

def _build_shared_upload_session(session):
    shared_session = requests.Session()
    shared_session.headers.update(session.headers)
    shared_session.cookies.update(session.cookies)
    if session.proxies:
        shared_session.proxies.update(session.proxies)
    shared_session.verify = session.verify
    if session.hooks.get('response'):
        shared_session.hooks['response'] = list(session.hooks['response'])

    shared_adapter = HTTPAdapter(max_retries=0, pool_connections=32, pool_maxsize=32)
    shared_session.mount("https://", shared_adapter)
    shared_session.mount("http://",  shared_adapter)
    return shared_session

class _ChunkStream(io.BytesIO):
    """A chunk payload that reports how many of its bytes have been read, so
    the progress bar moves while a 20 MB chunk is in flight instead of jumping
    once per chunk. Mirrors the GUI uploader's _ChunkStream."""
    def __init__(self, data: bytes, on_bytes_read=None):
        super().__init__(data)
        self._total = len(data)
        self._on_bytes = on_bytes_read
        self._read_so_far = 0

    def __len__(self):
        return self._total

    def read(self, size=-1):
        d = super().read(size)
        if d:
            self._read_so_far += len(d)
            if self._on_bytes:
                self._on_bytes(self._read_so_far)
        return d

class FileControl:
    """Pause/resume/cancel switch for one file, driven by the live terminal
    controls (see LiveControls). Checked by the worker at the same chunk
    boundaries as the batch-wide abort/pause events, so a chunk already in
    flight always finishes before a pause takes effect."""
    def __init__(self):
        self.pause_event  = threading.Event()
        self.cancel_event = threading.Event()

    def pause(self):
        if not self.cancel_event.is_set():
            self.pause_event.set()

    def resume(self):
        self.pause_event.clear()

    def cancel(self):
        self.cancel_event.set()
        self.pause_event.clear()

    def is_paused(self):
        return self.pause_event.is_set()

    def is_cancelled(self):
        return self.cancel_event.is_set()

def upload_file_tus_worker(session, renderer, file_info, manga_id, group_ids,
                           upload_type, batch_id, language, scanlator_name, abort_event,
                           verify_timeout=MAX_VERIFY_SECONDS, current_user_id=None,
                           is_group_upload=False, has_file_specific_group=True,
                           upload_session=None, skip_verification=True,
                           stitch_spreads=False, pause_event=None, resume_hint=None,
                           file_control=None, thread_count=None, on_offset=None):
    """Uploads one archive over TUS.

    pause_event / file_control: checked at every chunk boundary. A pause is
    not a failure: it returns {"paused": True, "upload_location", "offset",
    "fully_uploaded"} so the caller can continue this exact server-side
    upload later instead of starting over.

    resume_hint: {"upload_location", "offset", "fully_uploaded"}, already
    verified against the server with a HEAD request by the caller (see
    _verify_resume_hints). When given, no new TUS upload is created.

    on_offset(file_info, upload_location, offset): called each time the
    server confirms a new offset, so the caller can persist it and resume
    byte-exact after a crash, Ctrl+C, closed terminal or session expiry."""
    filename = file_info["filename"]
    filepath = file_info["filepath"]
    size     = file_info["size"]

    def _cancelled():
        return abort_event.is_set() or (file_control is not None and file_control.is_cancelled())

    def _cancel_error():
        return "Cancelled" if (file_control is not None and file_control.is_cancelled()) else "Aborted"

    def _paused():
        if pause_event is not None and pause_event.is_set():
            return True
        return file_control is not None and file_control.is_paused()

    def _paused_result(location, off, fully=False):
        return {"key": filename, "paused": True, "upload_location": location,
                "offset": off, "fully_uploaded": fully}

    owns_session = upload_session is None
    worker_session = upload_session if upload_session is not None else requests.Session()
    try:
        if owns_session:
            worker_session.headers.update(session.headers)
            worker_session.cookies.update(session.cookies)
            if session.proxies: worker_session.proxies.update(session.proxies)
            worker_session.verify = session.verify
            if session.hooks.get('response'): worker_session.hooks['response'] = list(session.hooks['response'])
            worker_adapter = HTTPAdapter(max_retries=0, pool_connections=10, pool_maxsize=25)
            worker_session.mount("https://", worker_adapter)
            worker_session.mount("http://",  worker_adapter)

        already_exists  = False
        upload_location = None

        if resume_hint and resume_hint.get("fully_uploaded"):
            # Every byte was already sent before the pause; only verification remained.
            offset = size
        elif resume_hint and resume_hint.get("upload_location"):
            upload_location = resume_hint["upload_location"]
            offset = max(0, min(int(resume_hint.get("offset") or 0), size))
            renderer.update_chapter_status(filename, "Resuming...", None, current=offset, total=size)
        else:
            tus_metadata = {
                "manga_id":       manga_id,
                "chapter_number": "0" if upload_type == "volume" else file_info["number"],
                "language":       language,
                "group_ids":      group_ids,
                "group_id":       group_ids[0] if group_ids else 0,
                "upload_type":    upload_type,
                "batch_id":       batch_id,
                "name":           filename,
                "type":           "application/zip",
                "filetype":       "application/zip",
                "filename":       filename,
            }
            raw_title = str(file_info.get("title") or "").strip()
            if upload_type == "volume":
                tus_metadata["volume_number"] = file_info["number"]
                if raw_title:
                    tus_metadata["volume_title"] = raw_title
            else:
                if not raw_title:
                    try:
                        raw_title = f"Chapter {float(file_info.get('number', 0)):g}"
                    except (TypeError, ValueError):
                        raw_title = f"Chapter {file_info.get('number', 0)}"
                tus_metadata["chapter_title"] = raw_title
            if scanlator_name:
                tus_metadata["scanlator_name"] = scanlator_name
            if stitch_spreads:
                tus_metadata["stitch_spreads"] = "1"

            headers = {
                "Tus-Resumable":   "1.0.0",
                "Upload-Length":   str(size),
                "Upload-Metadata": encode_tus_metadata(tus_metadata),
            }

            for attempt in range(MAX_RETRIES):
                if _cancelled(): return {"key": filename, "success": False, "error": _cancel_error()}
                if _paused(): return _paused_result(None, 0)
                try:
                    renderer.update_chapter_status(filename, "Creating upload...", None, current=0, total=size)
                    res = worker_session.post(TUS_ENDPOINT, headers=headers, timeout=(10, 30))
                    if res.status_code in (401, 403): raise SessionExpiredError()
                    if res.status_code == 409:
                        already_exists = True
                        break
                    if res.status_code in RETRYABLE_STATUSES and attempt < MAX_RETRIES - 1:
                        renderer.update_chapter_status(filename, f"Server busy (HTTP {res.status_code}), retrying...", None)
                        if not _interruptible_sleep(_compute_retry_delay(res, attempt), abort_event):
                            return {"key": filename, "success": False, "error": _cancel_error()}
                        continue
                    res.raise_for_status()
                    upload_location = res.headers.get("Location")
                    if not upload_location: raise ValueError("No Location header in TUS response")
                    upload_location = urljoin(TUS_ENDPOINT, upload_location)
                    break
                except SessionExpiredError: raise
                except (requests.exceptions.RequestException, ValueError) as e:
                    if attempt < MAX_RETRIES - 1:
                        renderer.update_chapter_status(filename, "Create Err... Retrying", None)
                        if not _interruptible_sleep(RETRY_DELAY, abort_event):
                            return {"key": filename, "success": False, "error": _cancel_error()}
                    else: return {"key": filename, "success": False, "error": f"Init failed: {str(e)[:30]}"}

            offset = size if already_exists else 0
            if upload_location and on_offset:
                on_offset(file_info, upload_location, 0)

        chunk_size = 20 * 1024 * 1024  # 20 MB native chunks matching site uploader

        try:
            with open(filepath, 'rb') as f:
                while offset < size:
                    if _cancelled(): return {"key": filename, "success": False, "error": _cancel_error()}
                    if _paused(): return _paused_result(upload_location, offset)

                    if f.tell() != offset:
                        f.seek(offset)

                    chunk = f.read(chunk_size)
                    if not chunk: break

                    chunk_done = False
                    resynced   = False
                    for patch_attempt in range(MAX_RETRIES):
                        try:
                            renderer.update_chapter_status(
                                filename, "Uploading...", None, current=offset, total=size
                            )
                            patch_headers = {
                                "Tus-Resumable": "1.0.0",
                                "Upload-Offset": str(offset),
                                "Content-Type":  "application/offset+octet-stream",
                            }
                            chunk_base = offset
                            last_report = [0.0]

                            def _on_chunk_bytes(n, _base=chunk_base, _last=last_report):
                                # Throttled: http.client reads the body in 8 KB blocks.
                                now = time.monotonic()
                                if now - _last[0] >= 0.1 or n >= len(chunk):
                                    _last[0] = now
                                    renderer.update_chapter_status(
                                        filename, "Uploading...", None, current=_base + n, total=size
                                    )

                            stream = _ChunkStream(chunk, on_bytes_read=_on_chunk_bytes)
                            patch_res = worker_session.patch(upload_location, headers=patch_headers, data=stream, timeout=60)

                            if patch_res.status_code in (401, 403): raise SessionExpiredError()
                            elif patch_res.status_code == 204:
                                server_off = patch_res.headers.get("Upload-Offset")
                                if server_off is not None:
                                    offset = int(server_off)
                                else:
                                    actual_off = _tus_offset(worker_session, upload_location)
                                    if actual_off is None:
                                        return {"key": filename, "success": False, "error": "Server dropped offset and HEAD failed"}
                                    offset = actual_off
                                if on_offset:
                                    on_offset(file_info, upload_location, offset)
                                chunk_done = True
                                break
                            elif patch_res.status_code in FATAL_SIZE_STATUSES:
                                return {"key": filename, "success": False, "error": f"HTTP {patch_res.status_code} (File Too Large/Bad Type)"}
                            elif patch_res.status_code == 409:
                                server_off = _tus_offset(worker_session, upload_location)
                                if server_off is not None and server_off != offset:
                                    offset   = server_off
                                    resynced = True
                                    break
                                if patch_attempt < MAX_RETRIES - 1:
                                    renderer.update_chapter_status(filename, f"Resyncing chunk... ({patch_attempt + 1})", None, current=offset, total=size)
                                    if not _interruptible_sleep(_compute_retry_delay(patch_res, patch_attempt), abort_event):
                                        return {"key": filename, "success": False, "error": _cancel_error()}
                                else: return {"key": filename, "success": False, "error": "HTTP 409 (Offset Conflict)"}
                            elif patch_res.status_code in RETRYABLE_STATUSES:
                                if patch_attempt < MAX_RETRIES - 1:
                                    renderer.update_chapter_status(filename, f"Retrying chunk (HTTP {patch_res.status_code}, attempt {patch_attempt + 1})...", None, current=offset, total=size)
                                    if not _interruptible_sleep(_compute_retry_delay(patch_res, patch_attempt), abort_event):
                                        return {"key": filename, "success": False, "error": _cancel_error()}
                                    server_off = _tus_offset(worker_session, upload_location)
                                    if server_off is not None and server_off > offset:
                                        offset   = server_off
                                        resynced = True
                                        break
                                else: return {"key": filename, "success": False, "error": f"HTTP {patch_res.status_code} (Max Retries)"}
                            else: return {"key": filename, "success": False, "error": f"HTTP {patch_res.status_code}"}
                        except SessionExpiredError: raise
                        except requests.exceptions.RequestException as e:
                            if patch_attempt < MAX_RETRIES - 1:
                                renderer.update_chapter_status(filename, f"Net Err, Retrying... (attempt {patch_attempt + 1})", None, current=offset, total=size)
                                if not _interruptible_sleep(_compute_retry_delay(None, patch_attempt), abort_event):
                                    return {"key": filename, "success": False, "error": _cancel_error()}
                                server_off = _tus_offset(worker_session, upload_location)
                                if server_off is not None and server_off > offset:
                                    offset   = server_off
                                    resynced = True
                                    break
                            else: return {"key": filename, "success": False, "error": f"Network Err: {str(e)[:30]}"}
                    if resynced:
                        if on_offset:
                            on_offset(file_info, upload_location, offset)
                        continue
                    if not chunk_done: return {"key": filename, "success": False, "error": "Chunk upload failed"}
        except SessionExpiredError: raise
        except OSError as e: return {"key": filename, "success": False, "error": str(e)[:30]}

        found        = False
        found_item   = None
        verify_start = time.time()

        if skip_verification or verify_timeout <= 0:
            label = "✅ Already Exists" if already_exists else "✅ Uploaded"
            renderer.update_chapter_status(filename, label, 1.0, current=size, total=size)
            return {"key": filename, "success": True, "already_exists": already_exists}

        if not group_ids and not scanlator_name:
            if is_group_upload and not has_file_specific_group:
                label = "⚠️ Uploaded (Unverified — no group)"
                renderer.update_chapter_status(filename, label, 1.0, current=size, total=size)
                return {
                    "key": filename,
                    "success": True,
                    "already_exists": already_exists,
                    "warning": "Uploaded without attribution verification: no resolved group/scanlator for this file."
                }
            label = "✅ Already Exists" if already_exists else "✅ Uploaded"
            renderer.update_chapter_status(filename, label, 1.0, current=size, total=size)
            return {"key": filename, "success": True, "already_exists": already_exists}

        while not found:
            if _cancelled(): return {"key": filename, "success": False, "error": _cancel_error()}
            if _paused(): return _paused_result(None, size, fully=True)

            elapsed_verify = int(time.time() - verify_start)
            if elapsed_verify >= verify_timeout:
                label = "✅ Already Exists" if already_exists else "✅ Uploaded (Pending Index)"
                renderer.update_chapter_status(filename, label, 1.0, current=size, total=size)
                return {
                    "key": filename,
                    "success": True,
                    "already_exists": already_exists,
                    "warning": None if already_exists else "Upload completed via TUS; awaiting server indexing in /api/uploads/mine."
                }

            renderer.update_chapter_status(filename, f"Verifying... ({elapsed_verify}s)", 1.0, current=size, total=size)
            with get_verify_sem(thread_count):
                try:
                    # /api/uploads/mine is authoritative even while awaiting moderation.
                    # Paginated and filtered by type/language so a busy title can't hide the file.
                    mine_items = fetch_my_uploads(
                        worker_session, manga_id=manga_id, upload_type=upload_type,
                        language=language, limit=50, max_pages=2,
                    )
                    for item in mine_items or []:
                        try:
                            if upload_type == "volume":
                                match = math.isclose(float(item.get("volume_number", -1)), float(file_info["number"]), abs_tol=0.001)
                            else:
                                match = math.isclose(float(item.get("chapter_number", -1)), float(file_info["number"]), abs_tol=0.001)
                        except (ValueError, TypeError): match = False

                        if match:
                            item_group_ids = []
                            if item.get("group_id"): item_group_ids.append(item["group_id"])
                            for g in item.get("groups", []) or []:
                                if isinstance(g, dict) and g.get("id"): item_group_ids.append(g["id"])
                                elif isinstance(g, int): item_group_ids.append(g)
                            item_scanlator = item.get("scanlator_name") or item.get("scanlator")

                            if group_ids and any(gid in item_group_ids for gid in group_ids):
                                found_item = item; found = True; break

                            if not group_ids and scanlator_name:
                                if isinstance(item_scanlator, str) and item_scanlator.strip().lower() == scanlator_name.strip().lower():
                                    found_item = item; found = True; break

                            if not group_ids and not scanlator_name:
                                found_item = item; found = True; break

                    if found: break
                except SessionExpiredError:
                    raise
                except (requests.exceptions.RequestException, json.JSONDecodeError, AttributeError) as e:
                    logging.debug("verify(%s): %s", filename, e)
            # Sleep outside the semaphore so waiting files don't hold a verify slot.
            if not _interruptible_sleep(2.0, abort_event):
                return {"key": filename, "success": False, "error": _cancel_error()}

        if already_exists:
            uploader_obj = found_item.get("uploader") if found_item else {}
            uploader_id  = (found_item.get("uploaded_by") or found_item.get("uploader_id") or found_item.get("user_id")
                            or (uploader_obj.get("id") if isinstance(uploader_obj, dict) else None)) if found_item else None
            if current_user_id is not None and uploader_id is not None and str(uploader_id) == str(current_user_id):
                label = "✅ Already Uploaded"
            else:
                label = "✅ Already Exists"
        else:
            label = "✅ Uploaded"
        renderer.update_chapter_status(filename, label, 1.0, current=size, total=size)
        return {"key": filename, "success": True, "already_exists": already_exists}
    finally:
        if owns_session:
            worker_session.close()

# ==============================================================================
# 🎮 LIVE TERMINAL CONTROLS (pause / resume / cancel while uploading)
# ==============================================================================

class LiveControls:
    """Reads single keystrokes while an upload batch runs, so the terminal gets
    the same pause/resume/cancel controls as the GUI's per-row menu:

      P          pause everything (in-flight files stop at the next chunk
                 boundary, progress is saved, then you choose resume or exit)
      :          start a command, then Enter:
                   p 3     pause file #3      (ranges work: p 4-6,9)
                   r 3     resume file #3     (r all = resume every paused file)
                   c 3     cancel file #3     (it is dropped from this run)

    Only active when stdin is a real terminal; otherwise it does nothing."""

    HELP = "[P] pause all & save   [:] command — p 3 pause #3 · r 3 resume · c 3 cancel · ranges ok (c 4-6)"

    def __init__(self):
        try:
            self.enabled = bool(sys.stdin) and sys.stdin.isatty()
        except (AttributeError, ValueError, OSError):
            self.enabled = False
        self._queue   = queue.Queue()
        self._lock    = threading.Lock()
        self._buffer  = None  # None = not typing a command
        self._message = ""
        self._stop    = threading.Event()
        self._thread  = None
        self._posix_saved = None

    # -- lifecycle ---------------------------------------------------------
    def start(self):
        if not self.enabled or self._thread is not None:
            return
        if sys.platform != "win32":
            try:
                import termios, tty
                fd = sys.stdin.fileno()
                self._posix_saved = termios.tcgetattr(fd)
                tty.setcbreak(fd)
            except Exception as e:
                logging.debug("LiveControls: could not enter cbreak mode (%s); controls disabled", e)
                self.enabled = False
                return
        else:
            flush_input_buffer()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="mangadot-live-controls", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
        if self._posix_saved is not None:
            try:
                import termios
                termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, self._posix_saved)
            except Exception:
                pass
            self._posix_saved = None
        with self._lock:
            self._buffer = None

    # -- input -------------------------------------------------------------
    def _read_key(self):
        if sys.platform == "win32":
            import msvcrt
            if msvcrt.kbhit():
                ch = msvcrt.getwch()
                if ch in ("\x00", "\xe0"):  # arrow/function key prefix: swallow the code too
                    msvcrt.getwch()
                    return None
                return ch
            time.sleep(0.05)
            return None
        import select
        try:
            ready, _, _ = select.select([sys.stdin], [], [], 0.05)
        except (OSError, ValueError):
            time.sleep(0.05)
            return None
        if ready:
            data = os.read(sys.stdin.fileno(), 1)
            return data.decode("utf-8", errors="ignore") or None
        return None

    def _run(self):
        while not self._stop.is_set():
            try:
                ch = self._read_key()
            except Exception as e:
                logging.debug("LiveControls: input error %s", e)
                return
            if ch:
                self._handle(ch)

    def _handle(self, ch):
        if ch == "\x03":  # Ctrl+C typed while we own the keyboard
            import _thread
            _thread.interrupt_main()
            return
        with self._lock:
            if self._buffer is None:
                if ch in ("p", "P"):
                    self._queue.put(("pause_all", None))
                    self._message = "Pausing everything at the next chunk boundary..."
                elif ch == ":":
                    self._buffer = ""
                return
            if ch in ("\r", "\n"):
                text, self._buffer = self._buffer, None
                self._parse(text)
            elif ch == "\x1b":
                self._buffer = None
            elif ch in ("\b", "\x7f"):
                self._buffer = self._buffer[:-1]
            elif ch.isprintable():
                self._buffer += ch

    def _parse(self, text):
        parts = text.strip().split(None, 1)
        if not parts:
            return
        verb = {"p": "pause", "pause": "pause", "r": "resume", "resume": "resume",
                "c": "cancel", "cancel": "cancel"}.get(parts[0].lower())
        arg = parts[1].strip() if len(parts) > 1 else ""
        if verb is None:
            self._message = f"Unknown command '{parts[0]}' — use p, r or c followed by file numbers."
            return
        if arg.lower() == "all":
            self._queue.put((verb, "all"))
            self._message = f"{verb.title()} all files."
            return
        nums, bad = parse_number_ranges(arg)
        nums = sorted(int(n) for n in nums if float(n).is_integer())
        if bad or not nums:
            self._message = f"Couldn't read file numbers in '{arg}' (example: {parts[0]} 3 or {parts[0]} 4-6)."
            return
        self._queue.put((verb, nums))
        self._message = f"{verb.title()}: #{', #'.join(map(str, nums))}"

    # -- consumer side -------------------------------------------------------
    def poll(self):
        out = []
        while True:
            try:
                out.append(self._queue.get_nowait())
            except queue.Empty:
                return out

    def set_message(self, message):
        with self._lock:
            self._message = message

    def footer(self):
        if not self.enabled:
            return None
        with self._lock:
            if self._buffer is not None:
                return Text.from_markup(f"[bold cyan]:[/bold cyan] {rich_escape(self._buffer)}▌  [dim](Enter to run · Esc to cancel)[/dim]")
            line = f"[dim]{rich_escape(self.HELP)}[/dim]"
            if self._message:
                line += f"\n[yellow]{rich_escape(self._message)}[/yellow]"
            return Text.from_markup(line)

# ==============================================================================
# 💾 RESUME TRACKING (byte-exact, crash-safe)
# ==============================================================================

class _ResumeTracker:
    """Keeps the on-disk paused-upload state in step with a running batch, so
    closing the terminal, a crash, Ctrl+C, a session expiry or a pause all
    leave behind an accurate resume point: finished and cancelled files are
    dropped, and in-flight files keep their TUS upload URL plus the last
    offset the server confirmed (the GUI's byte-exact resume)."""

    PERSIST_INTERVAL = 5.0
    HINT_KEYS = ("upload_location", "offset", "fully_uploaded")

    def __init__(self, batch_config, files):
        self.batch_config = batch_config
        self._lock  = threading.Lock()
        self._files = {}
        self._order = []
        self._hints = {}
        self._dirty = True
        self._last_persist = 0.0
        for f in files:
            name = f["filename"]
            self._order.append(name)
            self._files[name] = {k: v for k, v in f.items() if k not in self.HINT_KEYS}
            if f.get("fully_uploaded") or f.get("upload_location"):
                self._hints[name] = {
                    "upload_location": f.get("upload_location"),
                    "offset": int(f.get("offset") or 0),
                    "fully_uploaded": bool(f.get("fully_uploaded")),
                }

    def set_hint(self, filename, upload_location, offset, fully_uploaded=False):
        with self._lock:
            if filename not in self._files:
                return
            self._hints[filename] = {"upload_location": upload_location, "offset": int(offset or 0),
                                     "fully_uploaded": bool(fully_uploaded)}
            self._dirty = True

    def clear_hint(self, filename):
        with self._lock:
            if self._hints.pop(filename, None) is not None:
                self._dirty = True

    def hint_for(self, filename):
        with self._lock:
            h = self._hints.get(filename)
            return dict(h) if h else None

    def drop(self, filename):
        """The file is finished (uploaded, already on the server, or cancelled)."""
        with self._lock:
            if self._files.pop(filename, None) is not None:
                self._order = [n for n in self._order if n != filename]
                self._hints.pop(filename, None)
                self._dirty = True

    def remaining_files(self):
        with self._lock:
            out = []
            for name in self._order:
                f = dict(self._files[name])
                h = self._hints.get(name)
                if h:
                    f.update(h)
                out.append(f)
            return out

    def persist(self, force=False):
        with self._lock:
            if not self._dirty and not force:
                return
            if not force and time.monotonic() - self._last_persist < self.PERSIST_INTERVAL:
                return
            self._dirty = False
            self._last_persist = time.monotonic()
        remaining = self.remaining_files()
        if remaining:
            save_paused_upload(self.batch_config, remaining)
        else:
            clear_paused_upload()

def _verify_resume_hints(req_session, files, tracker):
    """Asks the server (HEAD) where each saved TUS upload really stands before
    resuming it — an upload session can expire, especially across a restart.
    Returns {filename: hint} for the files that can continue; files whose
    upload session is gone lose their hint and restart from byte 0, which is
    safe, whereas resuming a dead session would fail or misalign data.
    Mirrors the GUI's resume_paused_upload()."""
    hints, resumed, restarted = {}, [], []
    candidates = [(f, tracker.hint_for(f["filename"])) for f in files]
    candidates = [(f, h) for f, h in candidates if h]
    if not candidates:
        return hints
    shared = _build_shared_upload_session(req_session)
    try:
        with console.status("[cyan]Checking saved upload progress with the server...[/cyan]", spinner="dots"):
            for f, h in candidates:
                name = f["filename"]
                if h.get("fully_uploaded"):
                    hints[name] = h
                    resumed.append(name)
                    continue
                try:
                    server_off = _tus_offset(shared, h["upload_location"])
                except SessionExpiredError:
                    # Can't check right now; the batch will hit the expiry itself and
                    # re-run this check after you log in again. Hints are kept.
                    break
                if server_off is None:
                    tracker.clear_hint(name)
                    restarted.append(name)
                    continue
                h = {"upload_location": h["upload_location"],
                     "offset": min(server_off, int(f.get("size") or server_off)),
                     "fully_uploaded": False}
                tracker.set_hint(name, h["upload_location"], h["offset"])
                hints[name] = h
                resumed.append(name)
    finally:
        shared.close()
    if resumed:
        print_info(f"Continuing {len(resumed)} partly-uploaded file(s) from where they stopped.")
    if restarted:
        print_warning(f"{len(restarted)} file(s) had an expired upload session on the server and will restart from 0%.")
    return hints

# ==============================================================================
# 🔄 PROCESS UPLOADS
# ==============================================================================

_BATCH_COMPLETE_LOCK = threading.Lock()
_LAST_BATCH_COMPLETE_TIME = 0.0
_BATCH_COMPLETE_MIN_INTERVAL = 2.5

def _pace_batch_complete(abort_event=None) -> bool:
    global _LAST_BATCH_COMPLETE_TIME
    with _BATCH_COMPLETE_LOCK:
        now = time.time()
        elapsed = now - _LAST_BATCH_COMPLETE_TIME
        if elapsed < _BATCH_COMPLETE_MIN_INTERVAL:
            wait_time = _BATCH_COMPLETE_MIN_INTERVAL - elapsed
            if not _interruptible_sleep(wait_time, abort_event):
                return False
        _LAST_BATCH_COMPLETE_TIME = time.time()
        return True

def _send_batch_complete(batch_id, req_session, abort_event):
    """Decoupled background 'batch complete' housekeeping call, paced across
    workers so consecutive calls don't trip MangaDot's 429 limit."""
    def _worker(b_id, cookies_snap, headers_snap, proxies_snap, verify_opt, a_event):
        max_attempts = 5
        with requests.Session() as s:
            # cookies_snap is a RequestsCookieJar copy, NOT dict(): dict() raises
            # CookieConflictError when the browser has the same cookie name on
            # both mangadot.net and .mangadot.net.
            s.cookies.update(cookies_snap)
            s.headers.update(headers_snap)
            if proxies_snap:
                s.proxies.update(proxies_snap)
            s.verify = verify_opt
            for comp_attempt in range(max_attempts):
                try:
                    if not _pace_batch_complete(a_event):
                        return
                    comp_res = s.post(f"{BASE_URL}/api/uploads/batch/{b_id}/complete", timeout=(10, 30))
                    if comp_res.status_code in (401, 403):
                        return
                    if comp_res.status_code == 429 or comp_res.status_code in RETRYABLE_STATUSES:
                        delay = _compute_retry_delay(comp_res, comp_attempt)
                        if comp_res.status_code == 429:
                            delay = max(delay, 30.0)
                        if not _interruptible_sleep(delay, a_event):
                            return
                        continue
                    comp_res.raise_for_status()
                    logging.debug("Batch %s completion housekeeping succeeded.", b_id)
                    return
                except requests.exceptions.RequestException as e:
                    if comp_attempt < max_attempts - 1:
                        if not _interruptible_sleep(_compute_retry_delay(None, comp_attempt), a_event):
                            return
                    else:
                        logging.warning("Batch %s complete call failed after %d attempts: %s", b_id, max_attempts, e)

    threading.Thread(
        target=_worker,
        args=(
            batch_id,
            req_session.cookies.copy(),
            dict(req_session.headers),
            dict(req_session.proxies) if req_session.proxies else {},
            req_session.verify,
            abort_event,
        ),
        daemon=True,
    ).start()

def _init_batch(req_session, init_payload, abort_event):
    """POST batch/init with retries on 429/5xx/network errors (it used to fail
    the whole chunk of up to 100 files on a single rate-limit response).
    Returns (batch_id, None), (None, error_text) or raises SessionExpiredError."""
    last_err = "unknown error"
    for attempt in range(MAX_RETRIES):
        try:
            res = req_session.post(BATCH_INIT_ENDPOINT, json=init_payload, timeout=(10, 30))
            if res.status_code in (401, 403):
                raise SessionExpiredError()
            if res.status_code in RETRYABLE_STATUSES and attempt < MAX_RETRIES - 1:
                last_err = f"HTTP {res.status_code}"
                if not _interruptible_sleep(_compute_retry_delay(res, attempt), abort_event):
                    return None, "Aborted"
                continue
            res.raise_for_status()
            batch_data = res.json()
            batch_id = batch_data.get("batch_id")
            if not batch_id and isinstance(batch_data.get("data"), dict):
                batch_id = batch_data["data"].get("batch_id")
            if not batch_id:
                raise BatchInitError(f"Missing batch_id in response: {str(batch_data)[:200]}")
            return batch_id, None
        except SessionExpiredError:
            raise
        except (requests.exceptions.RequestException, json.JSONDecodeError, BatchInitError, KeyError, AttributeError) as e:
            last_err = str(e)
            if attempt < MAX_RETRIES - 1 and not isinstance(e, BatchInitError):
                if not _interruptible_sleep(_compute_retry_delay(None, attempt), abort_event):
                    return None, "Aborted"
                continue
            break
    return None, last_err

def _upload_volume_cover_with_retry(req_session, manga_id, f_info, attempts=3, delay=5.0):
    """The volume may not exist server-side the instant its archive finishes
    uploading (processing is asynchronous), so retry a 404 a few times."""
    err = None
    for attempt in range(attempts):
        ok, err = upload_volume_cover(req_session, manga_id, f_info.get("number"), f_info["filepath"])
        if ok:
            return True, None
        if not (err and err.startswith("HTTP 404")) or attempt == attempts - 1:
            break
        time.sleep(delay)
    return False, err

def process_uploads(files_to_upload, req_session, manga_id, group_ids,
                    upload_type, language, scanlator_name, thread_count,
                    per_file_group_map=None, verify_timeout=MAX_VERIFY_SECONDS, current_user_id=None,
                    is_group_upload=None, skip_verification=True,
                    stitch_spreads=False, auto_volume_cover=False,
                    per_file_scanlator_map=None, per_file_language_map=None,
                    resume_hints=None, pause_event=None, controls=None, tracker=None):
    """Uploads files_to_upload in batches of MAX_BATCH_SIZE.

    Returns (failed_chapters, session_expired, failure_reasons, paused), where
    paused maps filename -> resume hint for files stopped by a batch-wide pause
    (the P key or Ctrl+C) rather than by an error.

    per_file_scanlator_map / per_file_language_map (norm_filepath -> value), and
    the per-file 'scanlator_override' / 'language_override' fields, credit or
    file a single archive differently from the rest of the batch.
    resume_hints (filename -> hint) continue earlier TUS uploads byte-exact.
    controls is an optional LiveControls; tracker an optional _ResumeTracker."""
    per_file_group_map     = per_file_group_map or {}
    per_file_scanlator_map = per_file_scanlator_map or {}
    per_file_language_map  = per_file_language_map or {}
    resume_hints           = dict(resume_hints or {})
    pause_event            = pause_event if pause_event is not None else threading.Event()
    if is_group_upload is None:
        is_group_upload = bool(group_ids) or any(per_file_group_map.values())

    chunks     = [files_to_upload[i:i + MAX_BATCH_SIZE] for i in range(0, len(files_to_upload), MAX_BATCH_SIZE)]
    file_keys  = [f["filename"] for f in files_to_upload]
    row_number = {name: i + 1 for i, name in enumerate(file_keys)}
    by_number  = {i + 1: f for i, f in enumerate(files_to_upload)}
    file_controls = {name: FileControl() for name in file_keys}

    renderer = UIRenderer(file_keys, row_numbers=row_number,
                          footer_fn=(controls.footer if controls is not None else None))
    renderer.start()
    if controls is not None:
        controls.start()

    failed_chapters  = []
    failure_reasons  = {}
    paused           = {}
    finished         = set()
    session_expired  = False
    abort_event      = threading.Event()

    shared_upload_session = _build_shared_upload_session(req_session)

    def mark_failed(name, reason, status):
        renderer.update_chapter_status(name, status, 1.0)
        if name not in failed_chapters:
            failed_chapters.append(name)
        failure_reasons[name] = reason

    def mark_cancelled(name):
        mark_failed(name, "Cancelled", "❌ Cancelled")
        finished.add(name)
        if tracker is not None:
            tracker.drop(name)

    def current_hint(name):
        h = resume_hints.get(name)
        if h is None and tracker is not None:
            h = tracker.hint_for(name)
        return h

    def resolve_target(f):
        norm = f.get("norm_filepath") or _norm_filepath(f["filepath"])
        lang = f.get("language_override") or per_file_language_map.get(norm) or language
        scan_override = f.get("scanlator_override") or per_file_scanlator_map.get(norm)
        if scan_override:
            return [], False, scan_override, lang
        f_groups = per_file_group_map.get(norm)
        return (f_groups if f_groups else group_ids), bool(f_groups), scanlator_name, lang

    def on_offset(f_info, location, offset):
        if tracker is not None:
            tracker.set_hint(f_info["filename"], location, offset)

    def handle_commands(pending):
        if controls is None:
            return
        for verb, targets in controls.poll():
            if verb == "pause_all":
                pause_event.set()
                continue
            if targets == "all":
                names = [n for n in file_keys if n not in finished]
            else:
                names, unknown = [], []
                for n in targets:
                    f = by_number.get(n)
                    (names if f is not None else unknown).append(f["filename"] if f is not None else n)
                if unknown:
                    controls.set_message(f"No file numbered #{', #'.join(map(str, unknown))} in this run.")
            for name in names:
                if name in finished:
                    continue
                fc = file_controls[name]
                if verb == "pause":
                    fc.pause()
                    if any(p["filename"] == name for p in pending):
                        renderer.update_chapter_status(name, "Paused (waiting)", None)
                elif verb == "resume":
                    fc.resume()
                    if any(p["filename"] == name for p in pending):
                        renderer.update_chapter_status(name, "Queued", None)
                elif verb == "cancel":
                    fc.cancel()
                    for p in list(pending):
                        if p["filename"] == name:
                            pending.remove(p)
                            mark_cancelled(name)

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=thread_count) as executor:
            for chunk in chunks:
                if session_expired:
                    for f in chunk:
                        mark_failed(f["filename"], "Paused — session expired before upload", "⏸️ Paused (Session)")
                    continue
                if pause_event.is_set():
                    for f in chunk:
                        paused[f["filename"]] = current_hint(f["filename"])
                        renderer.update_chapter_status(f["filename"], "⏸️ Paused", None)
                    continue

                live_chunk = []
                for f in chunk:
                    if file_controls[f["filename"]].is_cancelled():
                        mark_cancelled(f["filename"])
                    else:
                        live_chunk.append(f)
                if not live_chunk:
                    continue

                chapters_payload = []
                chunk_group_ids = set(group_ids) if group_ids else set()
                for f in live_chunk:
                    c_title = (f.get("title") or "").strip()
                    if not c_title:
                        num = f.get("number", 0)
                        c_title = f"Chapter {int(num) if isinstance(num, (int, float)) and float(num).is_integer() else num}"
                    chapters_payload.append({
                        "chapter_number": f["number"] if upload_type == "chapter" else 0,
                        "volume_number": f["number"] if upload_type == "volume" else None,
                        "chapter_title": c_title,
                    })
                    f_groups, _, _, _ = resolve_target(f)
                    chunk_group_ids.update(f_groups or [])
                init_payload = {"manga_id": manga_id, "language": language, "group_ids": list(chunk_group_ids),
                                "type": upload_type, "scanlator_name": scanlator_name, "chapters": chapters_payload}
                try:
                    batch_id, init_err = _init_batch(req_session, init_payload, abort_event)
                except SessionExpiredError:
                    session_expired = True
                    abort_event.set()
                    for f in live_chunk:
                        mark_failed(f["filename"], "Paused — authentication expired", "⏸️ Paused (Auth)")
                    continue
                if not batch_id:
                    for f in live_chunk:
                        mark_failed(f["filename"], f"Batch init failed: {str(init_err)[:80]}", "❌ Batch Init Failed")
                    continue

                pending = list(live_chunk)
                for f in pending:
                    renderer.update_chapter_status(f["filename"], "Queued", None)
                futures = {}
                chunk_had_success = False
                covers_to_set = []

                def _submit_next():
                    while len(futures) < thread_count and not pause_event.is_set() and not abort_event.is_set():
                        nxt = None
                        for p in pending:
                            fc = file_controls[p["filename"]]
                            if fc.is_cancelled():
                                continue
                            if not fc.is_paused():
                                nxt = p
                                break
                        for p in [p for p in pending if file_controls[p["filename"]].is_cancelled()]:
                            pending.remove(p)
                            mark_cancelled(p["filename"])
                        if nxt is None:
                            return
                        pending.remove(nxt)
                        name = nxt["filename"]
                        f_groups, has_specific, f_scan, f_lang = resolve_target(nxt)
                        future = executor.submit(
                            upload_file_tus_worker, req_session, renderer, nxt, manga_id,
                            f_groups, upload_type, batch_id, f_lang, f_scan, abort_event,
                            verify_timeout, current_user_id,
                            is_group_upload, has_specific,
                            shared_upload_session, skip_verification,
                            stitch_spreads, pause_event, current_hint(name),
                            file_controls[name], thread_count, on_offset,
                        )
                        futures[future] = nxt

                def _handle_result(future):
                    nonlocal chunk_had_success, session_expired
                    f_info = futures.pop(future)
                    name = f_info["filename"]
                    fc = file_controls[name]
                    try:
                        result = future.result()
                    except SessionExpiredError:
                        session_expired = True
                        abort_event.set()
                        mark_failed(name, "Paused — authentication expired", "⏸️ Paused (Auth)")
                        return
                    except Exception as e:  # never let one file's crash take down the batch
                        logging.exception("worker crashed on %s", name)
                        mark_failed(name, f"Internal error: {type(e).__name__}: {str(e)[:60]}", f"❌ {type(e).__name__}")
                        return

                    if result.get("paused"):
                        hint = {"upload_location": result.get("upload_location"),
                                "offset": result.get("offset", 0),
                                "fully_uploaded": result.get("fully_uploaded", False)}
                        if not hint["upload_location"] and not hint["fully_uploaded"]:
                            hint = None
                        if hint is not None:
                            resume_hints[name] = hint
                            if tracker is not None:
                                tracker.set_hint(name, hint["upload_location"], hint["offset"], hint["fully_uploaded"])
                        if pause_event.is_set():
                            paused[name] = hint
                            renderer.update_chapter_status(name, "⏸️ Paused", None)
                        else:
                            # Paused on its own (":p N"): park it back in the queue; ":r N" picks it up again.
                            pending.insert(0, f_info)
                            renderer.update_chapter_status(name, "Paused — type ':r " + str(row_number[name]) + "' to resume", None)
                    elif result.get("success"):
                        chunk_had_success = True
                        finished.add(name)
                        if tracker is not None:
                            tracker.drop(name)
                        if result.get("warning"):
                            print_warning(f"'{name}': {result['warning']}")
                        if upload_type == "volume" and auto_volume_cover and not result.get("already_exists"):
                            covers_to_set.append(f_info)
                    else:
                        if fc.is_cancelled():
                            mark_cancelled(name)
                        else:
                            mark_failed(name, result.get("error", "Unknown error"), f"❌ {result.get('error', 'Error')}")

                try:
                    _submit_next()
                    while futures or (pending and not pause_event.is_set() and not abort_event.is_set()):
                        if futures:
                            done, _ = concurrent.futures.wait(
                                list(futures.keys()), timeout=0.25,
                                return_when=concurrent.futures.FIRST_COMPLETED,
                            )
                            for d in done:
                                _handle_result(d)
                        else:
                            # Only individually-paused files are left: wait for ':r N', ':c N' or P.
                            if controls is not None and controls.enabled:
                                controls.set_message(f"{len(pending)} paused file(s) waiting — ':r N' to resume, ':c N' to cancel, or P to stop and save.")
                            time.sleep(0.25)
                        handle_commands(pending)
                        if tracker is not None:
                            tracker.persist()
                        _submit_next()
                except KeyboardInterrupt:
                    # Graceful: in-flight files stop at the next chunk boundary. Their
                    # last confirmed offsets are already in the tracker for resume.
                    print_warning("Stopping — in-flight uploads pause at the next chunk boundary (this can take up to a minute)...")
                    pause_event.set()
                    abort_event.set()
                    for fut in futures:
                        fut.cancel()
                    raise

                for f in pending:
                    name = f["filename"]
                    if pause_event.is_set() or file_controls[name].is_paused():
                        paused[name] = current_hint(name)
                        renderer.update_chapter_status(name, "⏸️ Paused", None)
                    elif not file_controls[name].is_cancelled():
                        mark_failed(name, "Aborted", "❌ Aborted")

                if batch_id and not session_expired and chunk_had_success:
                    _send_batch_complete(batch_id, req_session, abort_event)

                for f_info in covers_to_set:
                    vol = _chapter_number_key(f_info.get("number"))
                    cover_ok, cover_err = _upload_volume_cover_with_retry(req_session, manga_id, f_info)
                    if cover_ok:
                        print_info(f"Auto-set volume cover for Vol. {vol}")
                    else:
                        print_warning(f"Couldn't auto-set the cover for Vol. {vol} ({cover_err}). "
                                      f"You can set it on the manga page instead.")
    except KeyboardInterrupt:
        abort_event.set()
        raise
    finally:
        if controls is not None:
            controls.stop()
        renderer.stop()
        shared_upload_session.close()
        if tracker is not None:
            tracker.persist(force=True)

    return failed_chapters, session_expired, failure_reasons, paused

# ==============================================================================
# 🎛️  INTERACTIVE SETUP HELPERS
# ==============================================================================

def _create_manga_from_mangabaka_interactive(session, initial_query):
    """Interactive MangaBaka -> MangaDot direct create (no metadata editing).
    Returns the new (or duplicate) manga ID on success, None otherwise."""
    query = initial_query.strip() if initial_query else ""
    while True:
        if not query:
            query = prompt("Search MangaBaka by title")
            if not query:
                return None
        with console.status(f"[cyan]Searching MangaBaka for '{query}'...[/cyan]", spinner="dots"):
            results, err = search_mangabaka(query)
        if err:
            print_warning(err)
            if not ask_confirm("Try a different search query?", default=True):
                return None
            query = prompt("Search MangaBaka by title")
            continue
        if not results:
            print_warning(f"No results on MangaBaka for '{query}'.")
            if not ask_confirm("Try a different search query?", default=True):
                return None
            query = prompt("Search MangaBaka by title")
            continue
        # Build picker
        choices = []
        for r in results:
            title = r.get("title", "Untitled")
            mid = r.get("id", "?")
            status = r.get("status", "")
            label = f"{title}  (MangaBaka ID: {mid})" + (f"  [{status}]" if status else "")
            choices.append(questionary.Choice(title=label, value=r))
        choices.append(questionary.Choice(title="🔍 Search again with a different query", value="__search_again__"))
        choices.append(questionary.Choice(title="Cancel", value="__cancel__"))
        pick = ask_select("Select a MangaBaka entry to create on MangaDot:", choices)
        if pick == "__cancel__":
            return None
        if pick == "__search_again__":
            query = prompt("Search MangaBaka by title")
            continue
        m_url = pick.get("mangabaka_url")
        if not m_url:
            print_error("Selected entry has no MangaBaka URL.")
            return None
        # Fetch metadata via MangaDot's proxy endpoint
        with console.status(f"[cyan]Fetching metadata for '{pick.get('title')}'...[/cyan]", spinner="dots"):
            meta = fetch_mangabaka_metadata(m_url, session)
        if meta.get("duplicate"):
            dup_id = meta.get("id")
            dup_title = meta.get("title") or pick.get("title")
            print_success(f"That title already exists on MangaDot: '{dup_title}' (ID: {dup_id}) — using it.")
            print_info(f"View it here: {BASE_URL}/manga/{dup_id}")
            return dup_id
        if not meta.get("ok"):
            print_error(f"Could not fetch MangaBaka entry: {meta.get('error', 'Unknown error')}")
            print_info(f"You can create it manually at: {BASE_URL}/add-manga")
            return None
        # Direct create — no metadata review/edit
        with console.status(f"[cyan]Creating '{pick.get('title')}' on MangaDot...[/cyan]", spinner="dots"):
            created = create_manga_from_mangabaka(meta.get("data"), session)
        if created.get("ok"):
            new_id = created.get("id")
            new_title = created.get("title") or pick.get("title")
            print_success(f"Created on MangaDot: '{new_title}' (ID: {new_id})")
            print_info(f"View it here: {BASE_URL}/manga/{new_id}")
            return new_id
        print_error(f"Failed to create on MangaDot: {created.get('error', 'Unknown error')}")
        print_info(f"You can create it manually at: {BASE_URL}/add-manga")
        return None

def _select_manga(req_session, guessed_title):
    manga_id = None
    while not manga_id:
        m_input = prompt("Search Manga by Title, or enter ID directly", default=guessed_title)

        try:
            candidate_id = int(m_input)
            with console.status(f"[cyan]Looking up manga ID {candidate_id}...[/cyan]", spinner="dots"):
                title, cover_url = fetch_manga_brief(candidate_id, req_session)
            if not title:
                print_warning(f"Could not find a manga with ID {candidate_id}. Please try again.")
                continue

            console.print(f"\n  [bold]Title:[/bold] {title}  [cyan](ID: {candidate_id})[/cyan]")
            if cover_url: show_cover(cover_url, req_session)
            else: print_warning("No cover art available for this entry.")

            if ask_confirm(f"Use '{title}'?", default=True):
                manga_id = candidate_id
                print_success(f"Selected Manga: {title} (ID: {manga_id})")
            else:
                guessed_title = None
            continue
        except ValueError:
            pass

        with console.status(f"[cyan]Searching MangaDot for '{m_input}'...[/cyan]", spinner="dots"):
            results = search_manga(m_input, req_session)

        if not results:
            print_warning(f"No matching manga titles found on MangaDot for '{m_input}'.")
            if ask_confirm("Fetch this entry from MangaBaka and create it on MangaDot directly (no editing)?", default=False):
                created_id = _create_manga_from_mangabaka_interactive(req_session, m_input)
                if created_id:
                    # Verify the newly created entry and confirm with user like the ID path does.
                    with console.status(f"[cyan]Looking up manga ID {created_id}...[/cyan]", spinner="dots"):
                        title, cover_url = fetch_manga_brief(created_id, req_session)
                    title = title or f"ID {created_id}"
                    console.print(f"\n  [bold]Title:[/bold] {title}  [cyan](ID: {created_id})[/cyan]")
                    if cover_url:
                        show_cover(cover_url, req_session)
                    if ask_confirm(f"Use '{title}'?", default=True):
                        manga_id = created_id
                        print_success(f"Selected Manga: {title} (ID: {manga_id})")
                    else:
                        guessed_title = None
                    continue
                # Creation failed or was cancelled — fall through to manual hint below.
            # Manual entry fallback — no metadata editing, just show the link.
            print_info(f"To create this entry manually, open: [cyan]{BASE_URL}/add-manga[/cyan] in your browser, "
                       f"create it, then come back here and enter its new ID.")
            guessed_title = None
            continue

        manga_choices = [questionary.Choice(title=f"{m['title']} (ID: {m['id']})", value=m) for m in results]
        manga_choices.append(questionary.Choice(title="🔍 Search again", value="__search_again__"))
        selection = ask_select("Select the matching manga:", manga_choices)

        if selection == "__search_again__":
            guessed_title = None
            continue

        candidate_title = selection["title"]
        cover_url = to_full_cover_url(selection.get("photo", ""))

        console.print(f"\n  [bold]Title:[/bold] {candidate_title}  [cyan](ID: {selection['id']})[/cyan]")
        if cover_url: show_cover(cover_url, req_session)
        else: print_warning("No cover art available for this entry.")

        if ask_confirm(f"Use '{candidate_title}'?", default=True):
            manga_id = selection["id"]
            print_success(f"Selected Manga: {candidate_title} (ID: {manga_id})")
        else:
            guessed_title = None

    return manga_id

def _search_group_interactive(req_session, prompt_text="Search Group by Name, or enter ID directly"):
    """Returns (group_id, group_name) or (None, None) if the user gives up."""
    while True:
        g_input = prompt(prompt_text)
        try:
            candidate_id = int(g_input)
            return candidate_id, f"ID: {candidate_id}"
        except ValueError:
            pass
        results = []
        for q in _group_search_queries(g_input):
            with console.status(f"[cyan]Searching for group '{q}'...[/cyan]", spinner="dots"):
                results = search_groups(q, req_session)
            if results:
                break
        if not results:
            print_warning("No groups found. Try another search.")
            continue
        choices = [questionary.Choice(title=f"{g.get('name', '?')} (ID: {g['id']})", value=g) for g in results]
        choices.append(questionary.Choice(title="🔍 Search again", value="__search_again__"))
        choices.append(questionary.Choice(title="Cancel", value="__cancel__"))
        selection = ask_select("Select a group:", choices)
        if selection == "__search_again__":
            continue
        if selection == "__cancel__":
            return None, None
        return selection["id"], selection.get("name") or f"ID: {selection['id']}"

def _credit_uncredited_files(directory, req_session, per_file_group_map, per_file_scanlator_map):
    """In a mixed-group batch every file is credited from its own [Group] tag.
    Files with no tag (or a tag that couldn't be resolved) used to be uploaded
    with no attribution at all. Ask how to credit them instead."""
    try:
        all_paths = [_norm_filepath(os.path.join(directory, n)) for n in os.listdir(directory)
                     if n.lower().endswith(('.cbz', '.zip')) and os.path.isfile(os.path.join(directory, n))]
    except OSError:
        return
    uncredited = sorted((p for p in all_paths if not per_file_group_map.get(p)), key=natural_sort_key)
    if not uncredited:
        return
    console.print()
    print_warning(f"{len(uncredited)} file(s) have no resolved group tag, e.g. '{os.path.basename(uncredited[0])}'.")
    choice = ask_select("How should these files be credited?", [
        questionary.Choice(title="Credit them to a group (search)", value="group"),
        questionary.Choice(title="Credit them to a scanlator name", value="scanlator"),
        questionary.Choice(title="Upload them without attribution", value="none"),
    ])
    if choice == "group":
        gid, gname = _search_group_interactive(req_session)
        if gid is not None:
            for path in uncredited:
                per_file_group_map[path] = [gid]
            print_success(f"{len(uncredited)} file(s) will be credited to {gname}.")
            return
        print_warning("No group chosen — these files will upload without attribution.")
    elif choice == "scanlator":
        name = prompt("Scanlator name for these files").strip()
        if name:
            for path in uncredited:
                per_file_scanlator_map[path] = name
            print_success(f"{len(uncredited)} file(s) will be credited to scanlator '{name}'.")

def _setup_group_config(directory, req_session, upload_type="chapter"):
    is_group             = ask_confirm("Upload as a Group?", default=True)
    group_ids            = []
    scanlator_name       = None
    per_file_group_map   = {}
    per_file_scanlator_map = {}
    selected_group_name  = None
    strip_bracket_groups = False

    if is_group:
        detected_names, per_file_names = detect_groups_from_filenames(directory, upload_type)
        unique_group_sets = set(frozenset(v) for v in per_file_names.values())
        is_mixed = len(unique_group_sets) > 1

        if detected_names:
            names_display = ", ".join(f"[cyan]{n}[/cyan]" for n in detected_names)
            if is_mixed:
                console.print("  [bold]Detected mixed groups across chapters.[/bold]")
                for gnames in sorted(unique_group_sets, key=lambda s: sorted(s)):
                    console.print(f"    · {'  +  '.join(sorted(gnames))}")
            else:
                console.print(f"  [bold]Detected group(s) from filenames:[/bold] {names_display}")

            use_detected = ask_confirm("Use detected group(s)?", default=True)
            if use_detected:
                if is_mixed:
                    all_unique_names = list({n for names in per_file_names.values() for n in names})
                    name_to_id = {}
                    for name in all_unique_names:
                        results    = []
                        clean_name = name
                        for q in _group_search_queries(name):
                            with console.status(f"[cyan]Resolving '{q}'...[/cyan]", spinner="dots"):
                                results = search_groups(q, req_session)
                            if results:
                                clean_name = q
                                break

                        exact = [g for g in results if g["name"].lower() in (name.lower(), clean_name.lower())]
                        if len(exact) == 1:
                            name_to_id[name] = exact[0]["id"]
                            print_success(f"Auto-matched: {exact[0]['name']} (ID: {exact[0]['id']})")
                        elif results:
                            choices = [questionary.Choice(title=f"{g['name']} (ID: {g['id']})", value=g) for g in results]
                            choices.append(questionary.Choice(title="Skip", value="__skip__"))
                            pick = ask_select(f"Multiple results for '{name}' — select one:", choices)
                            if pick != "__skip__":
                                name_to_id[name] = pick["id"]
                                print_success(f"Selected: {pick['name']} (ID: {pick['id']})")
                        
                        if name not in name_to_id:
                            print_warning(f"Could not resolve group tag: '{name}'")
                            while True:
                                fallback = prompt(f"Manually enter MangaDot Group ID for '{name}' (or type 'skip' to omit)").strip()
                                if fallback.lower() == 'skip':
                                    break
                                if fallback.isdigit():
                                    gid = int(fallback)
                                    name_to_id[name] = gid
                                    print_success(f"Manually mapped '{name}' -> Group ID: {gid}")
                                    break
                                print_error("Please enter a valid numeric ID.")

                    for filepath, fnames in per_file_names.items():
                        ids = [name_to_id[n] for n in fnames if n in name_to_id]
                        if ids:
                            per_file_group_map[_norm_filepath(filepath)] = ids

                    all_resolved = list(name_to_id.values())
                    if all_resolved:
                        group_ids = []
                        strip_bracket_groups = True
                    if not any(per_file_group_map.values()) and not group_ids:
                        print_warning("No groups could be resolved. Falling back to manual search.")
                    else:
                        _credit_uncredited_files(directory, req_session, per_file_group_map,
                                                 per_file_scanlator_map)
                else:
                    resolved_ids, unresolved = resolve_group_names(detected_names, req_session)
                    if resolved_ids:
                        group_ids = resolved_ids
                        selected_group_name = ", ".join(n for n in detected_names if n not in unresolved)
                        strip_bracket_groups = True
                    if unresolved:
                        print_warning(f"Could not resolve: {', '.join(unresolved)}. You can add them manually below.")
                        for name in unresolved:
                            while True:
                                fallback = prompt(f"Manually enter MangaDot Group ID for '{name}' (or type 'skip' to omit)").strip()
                                if fallback.lower() == 'skip':
                                    break
                                if fallback.isdigit():
                                    gid = int(fallback)
                                    group_ids.append(gid)
                                    print_success(f"Manually mapped '{name}' -> Group ID: {gid}")
                                    break
                                print_error("Please enter a valid numeric ID.")
                    if not group_ids:
                        print_warning("No groups could be resolved. Falling back to manual search.")

        while not group_ids and not any(per_file_group_map.values()):
            gid, gname = _search_group_interactive(req_session)
            if gid is None:
                continue
            group_ids = [gid]
            selected_group_name = gname
            print_success(f"Selected Group: {gname} (ID: {gid})")
    else:
        scanlator_name = prompt("Enter your individual Scanlator Name")

    return (is_group, group_ids, scanlator_name, per_file_group_map, selected_group_name,
            strip_bracket_groups, per_file_scanlator_map)

def _write_failed_log(manga_id, failed_chapters, failure_reasons):
    safe_id         = str(manga_id) if manga_id else "unknown"
    log_dir         = "logs"
    timestamp       = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    failed_log_name = os.path.join(log_dir, f"failed_manga_{safe_id}_{timestamp}.txt")
    try:
        os.makedirs(log_dir, exist_ok=True)
        with open(failed_log_name, "w", encoding="utf-8") as f:
            f.write(f"# Failed uploads for manga {safe_id} — {timestamp}\n")
            f.write(f"# {BASE_URL}/manga/{safe_id}\n")
            f.write("# <filename>\t<reason>\n\n")
            for chap in sorted(failed_chapters, key=natural_sort_key):
                f.write(f"{chap}\t{failure_reasons.get(chap, 'Unknown error')}\n")
        print_info(f"Failed list saved to [cyan]`{failed_log_name}`[/cyan].")
    except OSError as e:
        print_error(f"Could not write `{failed_log_name}`: {e}")

def _run_upload_loop(files, req_session, manga_id, group_ids, upload_type,
                     language, scanlator_name, thread_count, per_file_group_map,
                     current_browser, verify_timeout=MAX_VERIFY_SECONDS, current_user_id=None,
                     is_group_upload=None, selected_group_name=None, skip_verification=True,
                     stitch_spreads=False, auto_volume_cover=False,
                     per_file_scanlator_map=None, per_file_language_map=None):
    """Runs process_uploads until everything is done, the user stops, or the
    user declines a retry. The paused-upload file on disk is kept current the
    whole time (see _ResumeTracker), so a crash or closed terminal can always
    be resumed — byte-exact for files that were mid-transfer."""
    upload_start    = time.time()
    failed_chapters = []
    batch_config = {
        "manga_id": manga_id,
        "upload_type": upload_type,
        "language": language,
        "group_ids": group_ids or [],
        "scanlator_name": scanlator_name,
        "per_file_group_map": per_file_group_map or {},
        "per_file_scanlator_map": per_file_scanlator_map or {},
        "per_file_language_map": per_file_language_map or {},
        "thread_count": thread_count,
        "verify_timeout": verify_timeout,
        "current_user_id": current_user_id,
        "is_group_upload": is_group_upload,
        "selected_group_name": selected_group_name,
        "skip_verification": skip_verification,
        "stitch_spreads": stitch_spreads,
        "auto_volume_cover": auto_volume_cover,
    }
    tracker = _ResumeTracker(batch_config, files)
    tracker.persist(force=True)
    # Saved hint fields travel inside the tracker from here on.
    current_files_to_upload = [{k: v for k, v in f.items() if k not in _ResumeTracker.HINT_KEYS} for f in files]

    def _still_pending(names):
        return [f for f in current_files_to_upload if f["filename"] in names]

    try:
        while True:
            hints = _verify_resume_hints(req_session, current_files_to_upload, tracker)
            controls = LiveControls()
            if controls.enabled:
                print_info("While uploading: press [bold]P[/bold] to pause everything, or [bold]:[/bold] for per-file commands "
                           "(p 3 = pause #3, r 3 = resume, c 3 = cancel).")
            failed_chapters, session_expired, failure_reasons, paused = process_uploads(
                current_files_to_upload, req_session, manga_id, group_ids, upload_type,
                language, scanlator_name, thread_count,
                per_file_group_map=per_file_group_map,
                verify_timeout=verify_timeout,
                current_user_id=current_user_id,
                is_group_upload=is_group_upload,
                skip_verification=skip_verification,
                stitch_spreads=stitch_spreads,
                auto_volume_cover=auto_volume_cover,
                per_file_scanlator_map=per_file_scanlator_map,
                per_file_language_map=per_file_language_map,
                resume_hints=hints,
                controls=controls,
                tracker=tracker,
            )
            tracker.persist(force=True)

            if session_expired:
                console.print()
                console.rule("[bold red]Session Expired[/bold red]")
                print_warning("UPLOAD PAUSED: Session token expired or unauthorized.")
                print_warning(f"Progress saved — you can close the script and resume later "
                              f"({len(tracker.remaining_files())} file(s) pending).")
                print_warning("Refresh your login/Cloudflare check in your browser, then return here.")
                time.sleep(1.5)
                flush_input_buffer()
                choice = ask_select("Session expired — what now?", [
                    questionary.Choice(title="Re-authenticate now and continue", value="reauth"),
                    questionary.Choice(title="Pause & exit — resume next run", value="pause"),
                ])
                if choice == "pause":
                    print_info(f"Paused {len(tracker.remaining_files())} file(s) — run the script again to resume.")
                    sys.exit(0)
                current_browser, current_user_id = authenticate_session(req_session, current_browser)
                batch_config["current_user_id"] = current_user_id
                current_files_to_upload = _still_pending(set(failed_chapters) | set(paused))
                tracker.persist(force=True)
                console.print()
                console.rule("[dim]Resuming Upload[/dim]")
                console.print()
                print_info(f"Resuming upload for {len(current_files_to_upload)} failed/paused file(s)...")
                continue

            if paused:
                console.print()
                console.rule("[bold yellow]Upload Paused[/bold yellow]")
                print_info(f"{len(paused)} file(s) paused. Progress is saved — partly-uploaded files continue "
                           f"from where they stopped, even if you close the script now.")
                if failed_chapters:
                    print_warning(f"{len(failed_chapters)} file(s) also failed in this pass and will be retried on resume.")
                flush_input_buffer()
                choice = ask_select("What now?", [
                    questionary.Choice(title="Resume now", value="resume"),
                    questionary.Choice(title="Save & exit — resume next run", value="exit"),
                ])
                if choice == "exit":
                    print_info(f"Saved {len(tracker.remaining_files())} file(s) — run the script again to resume.")
                    sys.exit(0)
                retry_names = set(paused) | {n for n in failed_chapters if failure_reasons.get(n) != "Cancelled"}
                current_files_to_upload = _still_pending(retry_names)
                console.print()
                console.rule("[dim]Resuming Upload[/dim]")
                console.print()
                continue

            console.print()
            console.rule("[bold cyan]🎉 All operations complete[/bold cyan]", style="green")
            console.print()

            if not failed_chapters:
                print_success("All chapters were processed successfully!")
                clear_paused_upload()
                break

            print_error(f"{len(failed_chapters)} chapter(s) failed or were cancelled.")
            _write_failed_log(manga_id, failed_chapters, failure_reasons)

            retryable = [n for n in failed_chapters if failure_reasons.get(n) != "Cancelled"]
            if not retryable:
                clear_paused_upload()
                break
            if not ask_confirm(f"Retry ONLY the {len(retryable)} failed chapter(s)?", default=True):
                clear_paused_upload()
                break
            current_files_to_upload = _still_pending(set(retryable))
            tracker.persist(force=True)
            print_info(f"\nRetrying {len(current_files_to_upload)} failed chapter(s)...")
    except KeyboardInterrupt:
        console.print()
        print_warning("Upload interrupted by user (Ctrl+C).")
        tracker.persist(force=True)
        remaining = tracker.remaining_files()
        if not remaining:
            clear_paused_upload()
            sys.exit(0)
        if ask_confirm("Keep the saved progress so you can resume next run?", default=True):
            print_success(f"Saved {len(remaining)} file(s) — run the script again to resume.")
        else:
            clear_paused_upload()
            print_info("Discarded paused state.")
        sys.exit(0)

    return set(failed_chapters), time.time() - upload_start, current_browser

# ==============================================================================
# 🚀 MAIN
# ==============================================================================

def _check_proxy(proxy_url, verify=True):
    test_url = "https://mangadot.net"
    try:
        r = requests.get(
            test_url,
            proxies={"http": proxy_url, "https": proxy_url},
            timeout=10,
            headers={"User-Agent": DEFAULT_USER_AGENTS["chrome"]},
            allow_redirects=False,
            verify=verify,
        )
        if r.status_code == 407:
            return False, "Proxy returned 407 — credentials are wrong or missing."
        if r.status_code in (502, 503, 504) and "cf-ray" not in {k.lower() for k in r.headers}:
            return False, f"Proxy could not reach mangadot.net (HTTP {r.status_code} from the proxy)."
        # 2xx/3xx/4xx all mean the request went through the proxy and reached the site
        # (Cloudflare often answers plain HTTP clients with 403 or a redirect).
        return True, None
    except requests.exceptions.SSLError:
        return False, (
            "SSL error through proxy. The proxy may be intercepting TLS (MITM). "
            "If you trust this proxy, add '--proxy-no-verify' to skip SSL checks."
        )
    except requests.exceptions.ProxyError as e:
        return False, f"Proxy connection failed: {str(e)[:80]}"
    except requests.exceptions.ConnectionError as e:
        return False, f"Could not reach proxy: {str(e)[:80]}"
    except requests.exceptions.RequestException as e:
        return False, f"Proxy check error: {str(e)[:80]}"

def _positive_int(value):
    try:
        ivalue = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{value}' is not a valid integer")
    if ivalue <= 0:
        raise argparse.ArgumentTypeError(f"must be a positive integer, got {ivalue}")
    return ivalue

def build_arg_parser():
    parser = argparse.ArgumentParser(description="MangaDot Batch Uploader", formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Scan and parse chapter names without uploading.")
    parser.add_argument("--debug", action="store_true", help="Dump all HTTP traffic to api_requests.log.")
    parser.add_argument("--verify-timeout", type=_positive_int, default=MAX_VERIFY_SECONDS, metavar="SECONDS", help=f"How long to wait for validation confirmation (default: {MAX_VERIFY_SECONDS}s). Must be a positive integer.")
    parser.add_argument("--skip-verification", action="store_true", default=True, help="Skip post-upload verification polling (default: True, recommended because server post-processing is asynchronous).")
    parser.add_argument("--verify", dest="skip_verification", action="store_false", help="Enable post-upload verification polling.")
    parser.add_argument("--library", default=DEFAULT_LIBRARY_DIR or None, metavar="DIR", help="Parent folder of manga subfolders; pick one interactively instead of typing a path.")
    parser.add_argument("--proxy", default=None, help="Tunnel all HTTP/HTTPS requests through a specific proxy server.")
    parser.add_argument("--proxy-no-verify", action="store_true", default=None, help="Disable SSL certificate verification when using a proxy (use only if the proxy does TLS interception). Remembered across runs when explicitly passed.")
    parser.add_argument("--optimize-only", nargs="?", const="__prompt__", default=None, metavar="DIR",
                         help="Losslessly re-compress images inside every .cbz/.zip in DIR, then exit (no "
                              "login, no upload). Omit DIR to pick a folder interactively. Pixel data is "
                              "never altered unless --optimize-lossy is also passed. Requires Pillow "
                              "(pip install Pillow) and, for true lossless JPEG re-optimization, "
                              "mozjpeg-lossless-optimization (pip install mozjpeg-lossless-optimization).")
    parser.add_argument("--optimize", nargs="?", const="__prompt__", default=None, metavar="DIR",
                         help="Same as --optimize-only, but continues straight into the normal upload flow "
                              "on that folder afterward, so you can shrink and upload in one run.")
    parser.add_argument("--optimize-lossy", action="store_true", default=None,
                         help="Opt-in ONLY: allow lossy JPEG/WEBP re-encoding (pixel data changes, quality "
                              "reduced) for larger size savings. Without this flag, optimization is always "
                              "strictly lossless. Remembered across runs when explicitly passed.")
    parser.add_argument("--optimize-replace", action="store_true", default=None,
                         help="Overwrite originals in-place instead of writing to an 'optimized' subfolder "
                              "(the default). You'll be asked to confirm before any originals are "
                              "overwritten — declining falls back to the subfolder instead. Remembered across runs when explicitly passed.")
    parser.add_argument("--optimize-jpeg-quality", type=_positive_int, default=None, metavar="1-95",
                         help="JPEG quality when --optimize-lossy is used (default: 85). Ignored in the default lossless mode. Remembered across runs when explicitly passed.")
    parser.add_argument("--optimize-webp-quality", type=_positive_int, default=None, metavar="1-100",
                         help="WEBP quality when --optimize-lossy is used (default: 85). Ignored in the default lossless mode. Remembered across runs when explicitly passed.")
    parser.add_argument("--optimize-threads", type=_positive_int, default=None, metavar="N",
                         help="Parallel archives to optimize at once (default: 4). Remembered across runs when explicitly passed. Separate from the interactive upload thread-count prompt.")
    parser.add_argument("--pingo", action="store_true", default=None,
                         help="Modifier for --optimize/--optimize-only — has no effect on its own. "
                              "Use a local pingo binary (must sit next to mangadot.py) instead of the "
                              "built-in mozjpeg/Pillow optimizer — replaces that pipeline entirely for "
                              "this run. Remembered across runs when explicitly passed. Pingo has no official macOS build; on unsupported platforms or "
                              "if the binary isn't found, this falls back to mozjpeg/Pillow with a "
                              "visible notice rather than failing silently.")
    parser.add_argument("--refresh-uv-cache", action="store_true",
                         help="Clear uv's cached environment for this script and exit (only relevant "
                              "when running via 'uv run'). Forces the next run to re-resolve every "
                              "dependency in the PEP 723 block to its newest version satisfying the "
                              "declared floor. Handled before any other startup logic, so it works even "
                              "if dependencies aren't installed yet.")
    parser.add_argument("--stitch-spreads", dest="stitch_spreads", action="store_true", default=None,
                         help="Attach stitch_spreads to TUS metadata to automatically stitch two-page spreads on MangaDot.")
    parser.add_argument("--no-stitch-spreads", dest="stitch_spreads", action="store_false",
                         help="Disable automatic two-page spread stitching.")
    parser.add_argument("--volume-cover", dest="volume_cover", action="store_true", default=None,
                         help="Auto-extract page 1 from each volume archive and upload it as the volume cover.")
    parser.add_argument("--no-volume-cover", dest="volume_cover", action="store_false",
                         help="Do not automatically upload page 1 as the volume cover.")
    parser.add_argument("--skip-existing", dest="skip_existing", action="store_true", default=None,
                         help="Automatically skip chapters or volumes that already exist on MangaDot.")
    parser.add_argument("--no-skip-existing", dest="skip_existing", action="store_false",
                         help="Do not skip existing chapters or volumes.")
    return parser

def main():
    args = build_arg_parser().parse_args()
    verify_timeout = args.verify_timeout

    saved_config     = load_config()
    resolved_library = args.library or saved_config.get("library") or (DEFAULT_LIBRARY_DIR or None)

    # Persist proxy/optimizer preferences across runs (except --debug, per user choice).
    # Explicit CLI flags win over saved values; saved values win over built-in defaults.
    # Only an explicit flag triggers a write — this avoids spamming the config on every run.
    if args.proxy is not None:
        _remember_setting("proxy", args.proxy)
        resolved_proxy = args.proxy
    else:
        resolved_proxy = saved_config.get("proxy")
    # proxy_no_verify is a boolean — None means "not passed".
    if args.proxy_no_verify is not None:
        _remember_setting_force("proxy_no_verify", bool(args.proxy_no_verify))
        resolved_proxy_no_verify = bool(args.proxy_no_verify)
    else:
        resolved_proxy_no_verify = bool(saved_config.get("proxy_no_verify", False))
    # Optimizer preferences
    if args.optimize_lossy is not None:
        _remember_setting_force("optimize_lossy", bool(args.optimize_lossy))
    if args.optimize_replace is not None:
        _remember_setting_force("optimize_replace", bool(args.optimize_replace))
    if args.optimize_jpeg_quality is not None:
        _remember_setting("optimize_jpeg_quality", args.optimize_jpeg_quality)
    if args.optimize_webp_quality is not None:
        _remember_setting("optimize_webp_quality", args.optimize_webp_quality)
    if args.optimize_threads is not None:
        _remember_setting("optimize_threads", args.optimize_threads)
    if args.pingo is not None:
        _remember_setting_force("pingo", bool(args.pingo))
    # Resolve effective values for this run
    resolved_optimize_lossy = args.optimize_lossy if args.optimize_lossy is not None else bool(saved_config.get("optimize_lossy", False))
    resolved_optimize_replace = args.optimize_replace if args.optimize_replace is not None else bool(saved_config.get("optimize_replace", False))
    resolved_optimize_jpeg = args.optimize_jpeg_quality if args.optimize_jpeg_quality is not None else int(saved_config.get("optimize_jpeg_quality", 85))
    resolved_optimize_webp = args.optimize_webp_quality if args.optimize_webp_quality is not None else int(saved_config.get("optimize_webp_quality", 85))
    resolved_optimize_threads = args.optimize_threads if args.optimize_threads is not None else int(saved_config.get("optimize_threads", 4))
    resolved_pingo = args.pingo if args.pingo is not None else bool(saved_config.get("pingo", False))

    _check_for_updates()

    # resolved_proxy already computed above

    if args.dry_run: 
        run_dry_run(resolved_library)
        sys.exit(0)

    # --optimize-only: shrink images and exit. No auth, no session, no upload
    # code below this block is ever reached for this mode.
    if args.optimize_only is not None:
        target_dir = args.optimize_only
        if target_dir == "__prompt__":
            target_dir = select_directory(resolved_library)
        elif not os.path.isdir(target_dir):
            print_error(f"Directory does not exist: {target_dir}")
            sys.exit(1)
        run_optimize(
            target_dir,
            replace=resolved_optimize_replace,
            lossy=resolved_optimize_lossy,
            jpeg_quality=resolved_optimize_jpeg,
            webp_quality=resolved_optimize_webp,
            thread_count=resolved_optimize_threads,
            then_upload=False,
            use_pingo=resolved_pingo,
        )
        # run_optimize() calls sys.exit(0) itself once the summary is shown.

    # --optimize: shrink images first, then fall through into the normal
    # interactive upload flow below, pre-selecting the folder that actually
    # holds the optimized files (target_dir itself if --optimize-replace was
    # confirmed, or target_dir/optimized otherwise — run_optimize() reports
    # back which one so we never point the uploader at stale originals).
    preselected_dir = None
    # Carries the original source folder's name through to the title-guess
    # step below, since preselected_dir may end up pointing at <target>/optimized
    # — a name that makes a terrible manga-title guess. Kept separate from
    # preselected_dir on purpose: one is "where to scan files", the other is
    # "what to call this thing", and they diverge exactly when replace=False.
    preselected_title_source = None
    if args.optimize is not None:
        target_dir = args.optimize
        if target_dir == "__prompt__":
            target_dir = select_directory(resolved_library)
        elif not os.path.isdir(target_dir):
            print_error(f"Directory does not exist: {target_dir}")
            sys.exit(1)
        upload_dir = run_optimize(
            target_dir,
            replace=resolved_optimize_replace,
            lossy=resolved_optimize_lossy,
            jpeg_quality=resolved_optimize_jpeg,
            webp_quality=resolved_optimize_webp,
            thread_count=resolved_optimize_threads,
            then_upload=True,
            use_pingo=resolved_pingo,
        )
        if not upload_dir:
            print_error("Nothing was optimized, so there is nothing to upload from this folder.")
            sys.exit(1)
        upload_desc = "this same folder" if upload_dir == target_dir else "the 'optimized' subfolder"
        if not ask_confirm(f"Optimization done. Continue into upload for {upload_desc}?", default=True):
            print_info("Stopping here — nothing was uploaded.")
            sys.exit(0)
        preselected_dir = upload_dir
        preselected_title_source = Path(target_dir).name

    if args.debug:
        log_handler = logging.handlers.RotatingFileHandler(
            'api_requests.log', maxBytes=10*1024*1024, backupCount=3, encoding='utf-8'
        )
        logging.basicConfig(
            level=logging.DEBUG,
            format='%(asctime)s [%(levelname)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
            handlers=[log_handler]
        )
        console.print("[yellow][DEBUG] HTTP traffic logging active with circular rotation caps.[/yellow]")

    console.print()
    console.rule("[bold magenta]MangaDot.net Batch Uploader[/bold magenta]", style="green")
    console.print()

    req_session = requests.Session()
    if args.debug: req_session.hooks['response'].append(log_request_response)

    if resolved_proxy:
        proxy_no_verify = resolved_proxy_no_verify
        console.print(f"[yellow][PROXY] Routing all traffic through: {_redact_proxy_url(resolved_proxy)}[/yellow]")
        with console.status("[cyan]Checking proxy connectivity...[/cyan]", spinner="dots"):
            proxy_ok, proxy_err = _check_proxy(resolved_proxy, verify=not proxy_no_verify)
        if not proxy_ok:
            print_error(f"Proxy health check failed: {proxy_err}")
            if not ask_confirm("Continue anyway?", default=False):
                sys.exit(1)
        else:
            print_success("Proxy is reachable.")
        req_session.proxies = {"http": resolved_proxy, "https": resolved_proxy}
        if proxy_no_verify:
            req_session.verify = False
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            print_warning("SSL verification disabled — traffic is NOT verified end-to-end.")

    req_session.headers.update({"Origin": BASE_URL, "Referer": f"{BASE_URL}/"})
    no_retry_adapter = HTTPAdapter(max_retries=0)
    req_session.mount("https://", no_retry_adapter)
    req_session.mount("http://",  no_retry_adapter)

    current_browser, current_user_id = authenticate_session(req_session)
    # --- Text-only profile status line (#4) — cheap, no images, just level/rank/series ---
    try:
        with console.status("[dim]Fetching profile info...[/dim]", spinner="dots"):
            # Reuse the GUI's fetch_profile_stats scrapers if available; fall back to validate_session already did.
            # We do a lightweight profile fetch here for the status line.
            prof_res = req_session.get(f"{BASE_URL}/api/profile", timeout=(5, 15))
            if prof_res.status_code == 200:
                prof_data = prof_res.json().get("profile", {}) if isinstance(prof_res.json().get("profile"), dict) else prof_res.json()
                _uname = prof_data.get("username") or prof_data.get("email") or current_browser
                _lvl = prof_data.get("level")
                _series = None
                # Try to scrape series/chapters counts from /user/<name> like GUI does (best-effort, silent on fail).
                try:
                    _user_html = req_session.get(f"{BASE_URL}/user/{_uname}", timeout=(5, 15)).text if _uname else ""
                    import re as _re
                    _m_series = _re.search(r'<span class="pf-num[^"]*">([\d,]+)</span>\s*(?:<!--\s*-->)?\s*series', _user_html)
                    if _m_series:
                        _series = int(_m_series.group(1).replace(",", ""))
                except Exception:
                    pass
                _status_parts = [f"[bold]{_uname}[/bold]"]
                if _lvl is not None:
                    _status_parts.append(f"Lv {_lvl}")
                if _series is not None:
                    _status_parts.append(f"{_series} series")
                console.print(f"  [dim]👤 Logged in as[/dim] {' · '.join(_status_parts)}  [dim]({current_browser})[/dim]")
    except Exception:
        pass  # status line is cosmetic — never block startup

    # --- Crash-safe resume (#2): offer to resume a previously paused batch ---
    try:
        paused_state = load_paused_upload()
    except Exception:
        paused_state = None
    if paused_state and not args.dry_run and args.optimize is None and args.optimize_only is None:
        bc = paused_state.get("batch_config", {}) or {}
        paused_files = paused_state.get("files", []) or []
        paused_at = paused_state.get("paused_at")
        age_str = _format_paused_age(paused_at) if paused_at else "an unknown time ago"
        console.print()
        console.rule("[bold yellow]Paused upload found[/bold yellow]")
        print_info(f"Found a paused upload from {age_str}: [bold]{len(paused_files)}[/bold] file(s), "
                   f"manga ID [cyan]{bc.get('manga_id', '?')}[/cyan], {bc.get('upload_type', 'chapter')}, "
                   f"language [cyan]{bc.get('language', '?')}[/cyan].")
        if paused_files:
            _preview = ", ".join(f.get("filename", "?") for f in paused_files[:3])
            if len(paused_files) > 3:
                _preview += f" +{len(paused_files)-3} more"
            console.print(f"  [dim]{_preview}[/dim]")
        _resume_now = ask_confirm("Resume this paused upload now? (No = discard it and start fresh)", default=True)
        if _resume_now:
            # Filter files that no longer exist on disk.
            _valid = []
            _missing = 0
            for _f in paused_files:
                _fp = _f.get("filepath") or ""
                if _fp and os.path.isfile(_fp):
                    _valid.append(_f)
                else:
                    _missing += 1
            if _missing:
                print_warning(f"{_missing} file(s) no longer found on disk and will be skipped.")
            if not _valid:
                print_warning("No paused files remain on disk — discarding paused state.")
                clear_paused_upload()
            else:
                _manga_id = bc.get("manga_id")
                _upload_type = bc.get("upload_type", "chapter")
                _language = bc.get("language", "en")
                _group_ids = bc.get("group_ids", []) or []
                _scanlator_name = bc.get("scanlator_name")
                _per_file_group_map = bc.get("per_file_group_map", {}) or {}
                _per_file_scanlator_map = bc.get("per_file_scanlator_map", {}) or {}
                _per_file_language_map = bc.get("per_file_language_map", {}) or {}
                _thread_count = bc.get("thread_count", 5)
                _verify_timeout = bc.get("verify_timeout", MAX_VERIFY_SECONDS)
                _skip_verification = bc.get("skip_verification", args.skip_verification)
                _is_group_upload = bc.get("is_group_upload")
                _group_label = bc.get("selected_group_name") or (", ".join(map(str, _group_ids)) if _group_ids else (_scanlator_name or "-"))
                req_session.headers.update({"Referer": f"{BASE_URL}/manga/{_manga_id}/upload"})
                console.print()
                print_info(f"Resuming {len(_valid)} file(s) for manga {_manga_id}...")
                try:
                    print_files_table(_valid, _upload_type, group_label=_group_label)
                except Exception:
                    pass
                if not ask_confirm("Proceed with this resumed upload?", default=True):
                    clear_paused_upload()
                    print_info("Discarded paused upload.")
                else:
                    _final_failed, _upload_elapsed, _current_browser = _run_upload_loop(
                        _valid, req_session, _manga_id, _group_ids, _upload_type,
                        _language, _scanlator_name, _thread_count, _per_file_group_map,
                        current_browser, _verify_timeout, current_user_id, _is_group_upload,
                        selected_group_name=_group_label, skip_verification=_skip_verification,
                        stitch_spreads=bc.get("stitch_spreads", False),
                        auto_volume_cover=bc.get("auto_volume_cover", False),
                        per_file_scanlator_map=_per_file_scanlator_map,
                        per_file_language_map=_per_file_language_map,
                    )
                    # Record successful uploads for DB history, then show summary and exit.
                    _uploaded = [f for f in _valid if f["filename"] not in _final_failed]
                    if _uploaded:
                        try:
                            db_record_uploaded_files(_manga_id, _upload_type, _language, _group_ids, _scanlator_name,
                                                     _uploaded, _per_file_group_map, _per_file_scanlator_map,
                                                     _per_file_language_map)
                        except Exception as e:
                            logging.debug("resume: could not record upload history: %s", e)
                    _manga_url = f"{BASE_URL}/manga/{_manga_id}"
                    console.print()
                    console.rule("[dim]Summary[/dim]", style="green")
                    console.print()
                    if _uploaded:
                        _uploaded_bytes = sum(f.get("size", 0) for f in _uploaded)
                        _avg = _uploaded_bytes / _upload_elapsed if _upload_elapsed > 0 else 0
                        print_info(f"Uploaded [bold]{len(_uploaded)}[/bold] file(s) · {fmt_size(_uploaded_bytes)} in {fmt_duration(_upload_elapsed)} · avg {fmt_size(_avg)}/s")
                    if _final_failed:
                        print_error(f"{len(_final_failed)} file(s) still failed.")
                    else:
                        print_success("All resumed chapters were processed successfully!")
                    print_info(f"View your manga here: {_manga_url}")
                    console.print()
                    input("Press Enter to exit... ")
                    sys.exit(0)
        else:
            clear_paused_upload()
            print_info("Discarded paused upload — starting fresh.")

    console.print()
    console.rule("[dim]Setup[/dim]", style="green")
    console.print()

    if preselected_dir:
        directory = preselected_dir
        print_info(f"Using just-optimized folder: [cyan]{directory}[/cyan]")
    else:
        library_dir = resolved_library
        if library_dir and not args.library and library_dir == saved_config.get("library"):
            print_info(f"Using remembered library folder: [cyan]{library_dir}[/cyan]")
        directory = select_directory(library_dir)
    flush_input_buffer()

    guessed_title = preselected_title_source or (Path(directory).name if directory else "")
    manga_id = _select_manga(req_session, guessed_title)

    req_session.headers.update({"Referer": f"{BASE_URL}/manga/{manga_id}/upload"})

    upload_type = ask_select("Upload type?", [
        questionary.Choice(title="Chapter", value="chapter"),
        questionary.Choice(title="Volume", value="volume"),
    ])

    auto_volume_cover = False
    if upload_type == "volume":
        if getattr(args, "volume_cover", None) is not None:
            auto_volume_cover = bool(args.volume_cover)
        else:
            auto_volume_cover = ask_confirm("Auto-set first page as volume cover?", default=True)

    chapter_naming = "extract"
    custom_regex   = None
    custom_renames = None
    advanced_strip_groups = False
    if upload_type == "chapter":
        chapter_naming, custom_regex, custom_renames, advanced_strip_groups = _ask_chapter_naming()

    guessed_lang_code = _guess_language_from_path(directory)
    remembered_lang   = str(saved_config.get("language") or "en")
    default_lang_code = guessed_lang_code or remembered_lang

    # Single field: type to filter (autocomplete), or press Tab with nothing
    # typed to reveal the full list of all languages to pick from — no
    # separate dropdown mode needed, questionary/prompt_toolkit does this
    # natively for any autocomplete field with a completer attached.
    lang_codes = [code for code, _name in LANGUAGES]
    lang_meta  = {code: name for code, name in LANGUAGES}
    language = ask_autocomplete(
        "Language code (type to filter, or press Tab to see all)",
        choices=lang_codes,
        default=default_lang_code,
        meta_information=lang_meta,
    )
    _remember_setting("language", language)

    if getattr(args, "stitch_spreads", None) is not None:
        stitch_spreads = bool(args.stitch_spreads)
    else:
        saved_stitch = bool(saved_config.get("stitch_spreads", False))
        stitch_spreads = ask_confirm("Stitch double-page spreads on MangaDot?", default=saved_stitch)
    _remember_setting_force("stitch_spreads", stitch_spreads)

    (is_group, group_ids, scanlator_name, per_file_group_map, selected_group_name,
     strip_bracket_groups, per_file_scanlator_map) = _setup_group_config(directory, req_session, upload_type)
    strip_bracket_groups = strip_bracket_groups or advanced_strip_groups
    
    print_warning(
    "Recommended: 5 to 10 threads. But sure, slap it to 30 if you want.\n"
    "Cloudflare's banhammer is feeling lonely today, and I'm sure the admins\n"
    "won't mind you trying to single-handedly melt their infrastructure."
    )
    saved_threads = saved_config.get("threads")
    default_threads = str(saved_threads) if isinstance(saved_threads, int) and 1 <= saved_threads <= 30 else "5"
    while True:
        try:
            thread_count = int(prompt("Number of parallel uploads (1-30)", default=default_threads))
            if 1 <= thread_count <= 30: break
            print_error("Please enter a number between 1 and 30.")
        except ValueError: print_error("Invalid input.")
    _remember_setting("threads", thread_count)

    console.print()
    console.rule("[dim]Files[/dim]", style="green")
    console.print()

    print_info("Scanning directory for files...")
    files = get_files_in_dir(directory, upload_type, chapter_naming, custom_regex, strip_groups=strip_bracket_groups, custom_renames=custom_renames, select_subset=True, picker_style=_get_picker_style())
    if not files:
        print_error("No valid .cbz or .zip files found.")
        sys.exit(1)

    if not strip_bracket_groups:
        for f in files:
            f["groups"] = []

    for f in files:
        f["_upload_type"] = upload_type
        f["_group_label"] = selected_group_name

    target_key = _make_target_key(manga_id, upload_type, language, group_ids, scanlator_name)
    already_uploaded = set(db_uploaded_numbers(target_key))
    with console.status("[dim]Checking MangaDot for existing releases...[/dim]", spinner="dots"):
        remote_uploaded = fetch_remote_existing_numbers(req_session, manga_id, upload_type, language)
    already_uploaded.update(remote_uploaded)

    if already_uploaded:
        skip_candidates = [f for f in files if _chapter_number_key(f["number"]) in already_uploaded]
        if skip_candidates:
            console.print()
            print_info(
                f"[cyan]{len(skip_candidates)}[/cyan] of {len(files)} file(s) match numbers already published or "
                f"pending on MangaDot (or recorded from a previous run)."
            )
            if getattr(args, "skip_existing", None) is not None:
                skip_them = bool(args.skip_existing)
            else:
                skip_them = ask_confirm(
                    f"Skip these {len(skip_candidates)} already-uploaded file(s)?", default=True
                )
            if skip_them:
                skip_names = {f["filename"] for f in skip_candidates}
                files = [f for f in files if f["filename"] not in skip_names]
                if not files:
                    print_success("Nothing left to upload - everything in this batch already exists on MangaDot.")
                    sys.exit(0)
                print_info(f"Skipped {len(skip_names)}; [bold]{len(files)}[/bold] file(s) remain to upload.")

    print_files_table(files, upload_type, group_label=selected_group_name)
    _check_missing(files, upload_type)
    files = _check_duplicates(files, upload_type)

    files = review_and_edit_titles(files)

    confirm = ask_confirm("Proceed with upload?", default=True)
    if not confirm:
        print_info("Upload aborted by user.")
        sys.exit(0)

    console.print()
    console.rule("[dim]Upload[/dim]", style="green")
    console.print()

    final_failed, upload_elapsed, current_browser = _run_upload_loop(
        files, req_session, manga_id, group_ids, upload_type,
        language, scanlator_name, thread_count, per_file_group_map, current_browser,
        verify_timeout=verify_timeout, current_user_id=current_user_id,
        is_group_upload=is_group, selected_group_name=selected_group_name,
        skip_verification=args.skip_verification,
        stitch_spreads=stitch_spreads, auto_volume_cover=auto_volume_cover,
        per_file_scanlator_map=per_file_scanlator_map,
    )

    manga_url = f"{BASE_URL}/manga/{manga_id}"
    console.print()
    console.rule("[dim]Summary[/dim]", style="green")
    console.print()

    uploaded_files = [f for f in files if f["filename"] not in final_failed]
    uploaded_bytes = sum(f["size"] for f in uploaded_files)

    # Record confirmed uploads so future runs on this same target can skip them.
    if uploaded_files:
        db_record_uploaded_files(manga_id, upload_type, language, group_ids, scanlator_name,
                                 uploaded_files, per_file_group_map, per_file_scanlator_map)

    if uploaded_files:
        avg = uploaded_bytes / upload_elapsed if upload_elapsed > 0 else 0
        print_info(
            f"Uploaded [bold]{len(uploaded_files)}[/bold] file(s) · "
            f"{fmt_size(uploaded_bytes)} in {fmt_duration(upload_elapsed)} · "
            f"avg {fmt_size(avg)}/s"
        )
    console.print()
            
    try:
        with console.status("[cyan]Fetching upload confirmation details...[/cyan]", spinner="dots"):
            api_res = req_session.get(f"{BASE_URL}/api/manga/{manga_id}", timeout=15)

        if api_res.status_code == 200:
            manga_data = api_res.json().get("manga", {})

            def unpack_str(val, default=""):
                if isinstance(val, dict):
                    return str(val.get("en") or (next(iter(val.values())) if val else default))
                return str(val) if val is not None else default

            title      = unpack_str(manga_data.get("title"), "Unknown Title")
            status     = unpack_str(manga_data.get("status"), "N/A")
            raw_desc   = unpack_str(manga_data.get("description"), "No description available.")
            photo      = manga_data.get("photo", "")

            _stripped  = re.sub(r'<[^>]*>', '', raw_desc) if raw_desc else ""
            clean_desc = (_stripped[:200] + "...") if len(_stripped) > 200 else (_stripped if _stripped else "N/A")

            raw_alts = manga_data.get("alt_titles", [])
            cleaned_alt_titles = []
            if isinstance(raw_alts, list):
                cleaned_alt_titles = [unpack_str(a) for a in raw_alts if a]
            elif raw_alts:
                cleaned_alt_titles = [unpack_str(raw_alts)]

            raw_genres = manga_data.get("genres", [])
            genre_names = []
            if isinstance(raw_genres, list):
                for g in raw_genres:
                    val = unpack_str(g.get("name") or g.get("title") or g if isinstance(g, dict) else g)
                    if val and val not in genre_names:
                        genre_names.append(val)

            mangabaka_id = (
                manga_data.get("mangabaka_id") or
                manga_data.get("baka_id") or
                manga_data.get("mangaupdates_id") or
                (manga_data.get("external_links") or {}).get("mangabaka") or
                (manga_data.get("external_links") or {}).get("baka")
            )
            mangabaka_url = f"https://mangabaka.org/{mangabaka_id}" if mangabaka_id else None

            cover_url      = to_full_cover_url(photo)
            total_uploaded = len(files) - len(final_failed)

            top_lines = [
                f"[bold #5CE1E6]Title:[/bold #5CE1E6]          {rich_escape(title)}"
            ]
            if cleaned_alt_titles and cleaned_alt_titles[0]:
                top_lines.append(f"[bold #5CE1E6]Alt Title:[/bold #5CE1E6]      {rich_escape(cleaned_alt_titles[0])}")

            if cover_url:
                top_lines.append(f"[bold #5CE1E6]Cover Art:[/bold #5CE1E6]      [#FFBF00]{cover_url}[/#FFBF00]")

            top_text = Text.from_markup("\n".join(top_lines))

            bottom_lines = []

            bottom_lines.append(f"[bold #5CE1E6]Status:[/bold #5CE1E6]         [bold green]{str(status).upper()}[/bold green]")

            if genre_names:
                genres_str = "  ".join(f"[dim][[/dim][cyan]{rich_escape(g)}[/cyan][dim]][/dim]" for g in genre_names)
                bottom_lines.append(f"[bold #5CE1E6]Genres:[/bold #5CE1E6]         {genres_str}")

            group_str = (
                f"[bold #5CE1E6]Release Group:[/bold #5CE1E6]  [yellow]{rich_escape(str(selected_group_name or 'Multiple / Auto-Detected'))}[/yellow]"
                if is_group else
                f"[bold #5CE1E6]Scanlator:[/bold #5CE1E6]      [yellow]{rich_escape(str(scanlator_name))}[/yellow]"
            )
            bottom_lines.extend([
                f"[bold #5CE1E6]Uploaded Items:[/bold #5CE1E6] [magenta]{total_uploaded}[/magenta] / {len(files)} {upload_type}(s) successfully processed",
                group_str,
                "",
                "[bold #5CE1E6]Synopsis:[/bold #5CE1E6]",
                f"[dim]{rich_escape(clean_desc)}[/dim]",
                "",
                f"[bold #5CE1E6]MangaDot:[/bold #5CE1E6]       [#FFBF00]{manga_url}[/#FFBF00]"
            ])

            if mangabaka_url:
                bottom_lines.append(f"[bold #5CE1E6]MangaBaka:[/bold #5CE1E6]      [#FFBF00]{mangabaka_url}[/#FFBF00]")
            bottom_text = Text.from_markup("\n".join(bottom_lines))

            print()
            console.print(Rule("[bold #FF1493]🎉 UPLOAD CONFIRMED ON MANGADOT[/bold #FF1493]", style="green"))
            print()

            console.print(top_text)
            print()

            if cover_url:
                _render_cover(cover_url, req_session, silent=True)
                print()

            console.print(bottom_text)
            console.print(Rule(style="green"))

        else: print_info(f"View your manga here: {manga_url}\n")
    except Exception as e:
        logging.debug("Post-upload summary rendering failed: %s: %s", type(e).__name__, e)
        print_warning(f"Could not fetch metadata: {e}")
        print_info(f"View your manga here: {manga_url}\n")

    console.print()
    input("Press Enter to exit... ")

if __name__ == "__main__":
    try: main()
    except KeyboardInterrupt:
        console.print("\n\n[yellow]⚠️  Script interrupted by user.[/yellow]")
        sys.exit(0)