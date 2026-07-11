# MangaDot.net Batch Uploader version 1.3.0 [https://mangadot.net]
# [Interactive UI, Synchronized Color Theme & High-Fidelity Inline Art Update applied]
# [v1.2.4: Audit fix pass — custom regex, ghost-chapter verification gap, volume
#  titles, stale-PID kill safety, connection pooling, interruptible retries,
#  natural sort negatives, verify-timeout validation, dead import, path norm]
# [v1.3.0: Auto-detect title now always shows a picker with dynamically-built,
#  labeled candidates (full/without-episode-label/without-season/bare/minimal),
#  memoized per detected filename "shape" across the batch]

"""
==============================================================================
🚀 MANGADOT BATCH UPLOADER - ADVANCED FEATURES & USAGE
==============================================================================

WHAT THIS SCRIPT DOES:
  A multi-threaded batch uploader for .cbz/.zip files to MangaDot.net. 
  It extracts active browser cookies (Chrome, Firefox, Edge, Brave, Opera, Vivaldi)
  and dynamically spoofs your exact User-Agent to natively bypass Cloudflare. 
  Uploads are handled via the resumable TUS protocol in 5MB chunks with optional proxy tunneling.

ADVANCED NAMING & UI:
  - Bracket Detection: Automatically detects and assigns release groups from [Bracket] tags.
  - Mixed-Group Batching: Seamlessly uploads and assigns multiple release groups in a single run.
  - Custom Regex: Use 'Pattern -> Replace' syntax to quickly rename files, or '()' to extract titles.
  - Terminal Dashboard: Renders high-fidelity cover art directly in the terminal (requires 'chafa').

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
==============================================================================
"""
import os
import re
import sys
import json
import base64
import time
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
from collections import deque
from pathlib import Path

# ==============================================================================
# ⚙️  DEPENDENCY CHECK
# ==============================================================================

REQUIRED_PACKAGES = {
    "requests":         "2.28.0",
    "rookiepy":         "0.5.0",
    "questionary":      "2.0.0",
    "rich":             "13.0.0",
    "websocket-client": "1.6.0",
}

def _parse_version_tuple(version_str):
    match = re.match(r'(\d+(?:\.\d+)*)', str(version_str))
    if not match:
        return (0,)
    return tuple(map(int, match.group(1).split('.')))

def _version_lt(installed, required):
    """True if installed < required, zero-padding to equal length so that
    e.g. '2.28' is not treated as older than '2.28.0'."""
    a = _parse_version_tuple(installed)
    b = _parse_version_tuple(required)
    length = max(len(a), len(b))
    a += (0,) * (length - len(a))
    b += (0,) * (length - len(b))
    return a < b

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
        except Exception:
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
        print(f"\n  🔧 Auto-installing missing/outdated packages: {' '.join(to_install)}...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade"] + to_install)
            print("  ✅ All dependencies verified and updated.\n")
            ok = True
        except subprocess.CalledProcessError:
            print("  ❌ Auto-install failed. You'll need to run pip manually.")
            print(f"    pip install --upgrade {' '.join(to_install)}\n")

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

if not check_dependencies():
    sys.exit(1)

try:
    import requests
    from requests.adapters import HTTPAdapter
    import rookiepy
    import questionary
    import websocket  # provided by the 'websocket-client' package

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
except Exception as _import_err:
    print(f"An unexpected error occurred during import: {_import_err}")
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
_VERIFY_CONCURRENCY  = 3
RETRYABLE_STATUSES   = [429, 500, 502, 503, 504, 524]
FATAL_SIZE_STATUSES  = [413, 415]


# ==============================================================================
# 🔑 CDP (Chrome DevTools Protocol) fallback for Chromium browsers
# ==============================================================================

# Since Chrome 136, remote debugging is refused against a browser's default
# profile (see https://developer.chrome.com/blog/remote-debugging-port).
# The supported pattern is a dedicated, non-default profile directory launched
# with debugging enabled; the script then asks the browser for its own
# cookies over the debugger protocol it explicitly exposes for this purpose.
# No cookie-store decryption or key extraction is involved.
# ------------------------------------------------------------------------------
CDP_BASE_PORT = 9222
CDP_PORT_OFFSETS = {"chrome": 0, "edge": 1, "brave": 2, "vivaldi": 3, "opera": 4}

def _cdp_port_for(browser_key):
    return CDP_BASE_PORT + CDP_PORT_OFFSETS.get(browser_key, 99)

def _cdp_profile_dir_for(browser_key):
    """Each browser gets its own subfolder -- a Chromium profile directory
    isn't portable across different browser vendors, so sharing one between
    e.g. Vivaldi and Brave would corrupt/confuse both."""
    return os.path.join(CDP_PROFILE_ROOT, browser_key)

def _default_cdp_profile_dir():
    """Lives outside the script's own folder on purpose -- the script folder
    may be inside a Git repo (as it is for some users), and this directory
    will contain a live, logged-in session cookie once used. Keeping it in
    the OS's local-app-data area keeps it well away from anything that
    might get committed or pushed."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser(r"~\AppData\Local")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "MangaDotUploader", "cdp_profile")

CDP_PROFILE_ROOT = _default_cdp_profile_dir()
CDP_STARTUP_WAIT = 20  # seconds to wait for the debug port to come up

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
MAX_VERIFY_SECONDS   = 60
DEFAULT_CHAPTERS_DIR = "chapters"
DEFAULT_LIBRARY_DIR  = ""
CONFIG_PATH          = Path.home() / ".mangadot_uploader.json"

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
def get_verify_sem():
    global _VERIFY_SEM
    if _VERIFY_SEM is None:
        with _VERIFY_SEM_LOCK:
            if _VERIFY_SEM is None:
                _VERIFY_SEM = threading.Semaphore(_VERIFY_CONCURRENCY)
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
    except Exception: pass
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
    except Exception: return None
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
    except Exception: return None

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
    except Exception: return None
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

def get_dynamic_user_agent(browser):
    with _UA_CACHE_LOCK:
        if browser in _UA_CACHE: return _UA_CACHE[browser]
        config = load_config()
        cached_uas = config.get("cached_user_agents", {})
        if browser in cached_uas:
            _UA_CACHE[browser] = cached_uas[browser]
            return cached_uas[browser]

    # --- Lock released: slow OS / network work happens here ---
    version = None
    try:
        if sys.platform == 'win32':    version = _read_windows_registry(browser)
        elif sys.platform == 'darwin': version = _read_mac_plist(browser)
        else:                          version = _read_linux_version(browser)
    except Exception: version = None

    if not version and browser in ("chrome", "edge", "firefox"):
        try:
            version = _fetch_web_version(browser, timeout=5)
        except Exception:
            version = None

    chromium_version = _get_chromium_version_for_browser(browser)
    ua = _build_user_agent(browser, version, chromium_version)

    # --- Reacquire lock to write results back to the cache ---
    with _UA_CACHE_LOCK:
        _UA_CACHE[browser] = ua
        try:
            fresh_config = load_config()
            cached_uas = fresh_config.get("cached_user_agents", {})
            cached_uas[browser] = ua
            fresh_config["cached_user_agents"] = cached_uas
            save_config(fresh_config)
        except Exception:
            pass

    return ua

def restore_terminal():
    try:
        sys.stdout.write("\033[?7h")
        sys.stdout.flush()
    except Exception: pass

atexit.register(restore_terminal)

# ==============================================================================
# 🐛  DEBUG LOGGING
# ==============================================================================

_SENSITIVE_HEADERS = frozenset({"cookie", "authorization", "x-auth-token", "x-session-token"})

_STRIP_ANSI_RE = re.compile(r'\033\[[0-9;?]*[A-Za-z]')
def strip_ansi(text):
    return _STRIP_ANSI_RE.sub('', str(text))

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
        except Exception: logging.debug("--- REQUEST BODY (Size: Unknown) ---")
    logging.debug("--- RESPONSE STATUS: %s %s ---", response.status_code, response.reason)
    logging.debug("--- RESPONSE HEADERS ---")
    for k, v in response.headers.items(): logging.debug(strip_ansi(f"{k}: {v}"))
    logging.debug("--- RESPONSE BODY ---")
    try:
        resp_text = response.text
        logging.debug(strip_ansi(f"{resp_text[:1000]}... (truncated)" if len(resp_text) > 1000 else resp_text))
    except Exception: logging.debug("<Binary or Unreadable Response>")
    logging.debug("=" * 63 + "\n")

# ==============================================================================
# 🖥️ UI RENDERER
# ==============================================================================

class UIRenderer:
    FINAL_MARKERS = ("✅", "❌", "⏸️")
    MAX_VISIBLE_FINISHED = 15

    def __init__(self, chapter_keys):
        self.lock = threading.Lock()
        self.sorted_keys = chapter_keys
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

        self.live = Live(
            Group(self.overall_progress, Rule(style="dim cyan"), self.chapter_progress),
            console=console, refresh_per_second=8, transient=False,
        )

    def _label(self, filename, status):
        name = rich_escape(filename if len(filename) <= 40 else filename[:37] + "...")
        if "✅" in status: color = "green"
        elif "❌" in status: color = "red"
        elif "⏸️" in status: color = "yellow"
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
                if "✅" in status and chap_key not in self._was_done:
                    self._was_done.add(chap_key)
                    self.completed_chapters += 1
                    self.overall_progress.update(self.overall_task, completed=self.completed_chapters)
                if chap_key not in self.finished_order:
                    self.finished_order.append(chap_key)
                    self._trim_finished()

            self.live.refresh()

    def _trim_finished(self):
        while len(self.finished_order) > self.MAX_VISIBLE_FINISHED:
            oldest = self.finished_order.popleft()
            task_id = self.chapter_tasks.pop(oldest, None)
            if task_id is not None:
                try: self.chapter_progress.remove_task(task_id)
                except Exception: pass

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
        except Exception: pass

def prompt(text, default=None, required=True):
    while True:
        prompt_text = f"{text} [{default}]: " if default else f"{text}: "
        user_input  = input(prompt_text).strip()
        if not user_input and default is not None: return default
        if required and not user_input:
            print_warning("This field is required.")
            continue
        return user_input

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
    except Exception: pass
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
    except Exception as e:
        if not silent:
            print_warning(f"Could not display cover art: {e}")
            print_info(f"Cover: {image_url}")

def show_cover(image_url: str, session: requests.Session):
    _render_cover(image_url, session, silent=False)

def _norm_filepath(path):
    """Canonical normalization for using a filepath as a dict key (e.g. in
    per_file_group_map). Must be applied identically everywhere a filepath
    is used as a key -- both normpath (collapses redundant separators like
    'dir//file' or 'dir/./file' to a consistent form) and normcase
    (case-folds on case-insensitive filesystems) are needed, and applying
    only one of the two at some call sites but both at others is exactly
    what causes lookup misses between differently-constructed paths that
    point at the same file."""
    return os.path.normcase(os.path.normpath(path))

def natural_sort_key(s):
    # Encode each numeric run as a sortable string. Zero-padding the numeric
    # text directly (e.g. f"{float(text):015.4f}") breaks for negative
    # numbers: the '-' sign ends up glued to the front of the zero-padded
    # digits, so plain string comparison compares magnitudes as if they were
    # positive (e.g. "-5" -> "-000000005.0000" sorts AFTER "-100" ->
    # "-000000100.0000", the opposite of numeric order). To fix this we
    # split sign from magnitude: a single leading sort-order character
    # ('0' for negative, '1' for non-negative) puts all negatives before all
    # non-negatives, and for negatives we invert the padded magnitude
    # (subtract from a large constant) so that more-negative values compare
    # as "smaller" strings, restoring correct ascending numeric order
    # end-to-end for both positive and negative numbers.
    def encode(text):
        value = float(text)
        if value < 0:
            inverted = 10 ** 12 + value  # value is negative, so this subtracts its magnitude
            return f"0{inverted:015.4f}"
        return f"1{value:015.4f}"

    return [encode(text) if re.match(r'^-?\d+(?:\.\d+)?$', text) else text.lower()
            for text in re.split(r'(-?\d+(?:\.\d+)?)', str(s))]

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
    """
    Parses the raw string typed into the 'Custom regex' prompt into a
    (renames, extractor) pair:
      - renames: list of (pattern, replacement) tuples for 'Find -> Replace'
        syntax, applied to the filename before number/title extraction.
      - extractor: a compiled regex with a capture group, used to pull the
        title directly out of the filename, or None if not applicable.
    Multiple 'Find -> Replace' rules can be chained with ';;'.
    A bare pattern containing a capture group (no '->') is treated as a
    title extractor instead of a rename.
    """
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
                    # Validate the REPLACEMENT half too, not just the
                    # pattern. re.sub's replacement string only understands
                    # backreferences (\1, \g<name>) and a few literal
                    # escapes -- NOT general regex escapes like \s, \d, \w.
                    # Someone typing "_ -> \s" (meaning "underscore becomes
                    # a space") is a completely reasonable thing to type,
                    # but \s is invalid on the replacement side and used to
                    # raise re.error deep inside parse_filename_details,
                    # crashing the entire batch scan. Catch it here instead,
                    # at input time, with a clear warning.
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
                # Defense in depth: parse_custom_regex_input already
                # validates rules at input time, but custom_renames can
                # also reach this function directly from other callers --
                # one bad rule (e.g. an invalid backreference) should skip
                # itself, not take down parsing for every file in the batch.
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
    num_came_from_episode_label = False
    # Tracks which extraction path actually supplied `num`, so callers that
    # aggregate a whole batch (see get_files_in_dir's drift-correction pass)
    # can tell a real "Episode N" / "Chapter N" label apart from a number
    # that was only ever a blind last-number-in-the-string guess. This
    # matters because a bare sequential file prefix like "ch0015" satisfies
    # the chapter/volume pattern just as well as a genuine "Ch. 15" label
    # does -- regex alone can't distinguish "ch" as a real chapter marker
    # from "ch" as the first two letters of a counter -- so num_source is
    # deliberately coarse ("labeled" vs "fallback") rather than trying to
    # guess intent here. The batch-level drift check is what actually
    # resolves the ambiguity, by comparing this against sibling files.
    num_source = None  # "chapter_or_volume_label" | "episode_label" | "fallback"

    # Patch 1: Split regex to enforce strict boundaries on single-letter flags ('v' and 'c')
    if upload_type == "volume":
        num_pattern = r'(?i)(?:(?:\b|_)?(?:volume|vol)|(?:\b|_)v)[\.\-_\s]*(\d+(?:\.\d+)?)'
    else:
        num_pattern = r'(?i)(?:(?:\b|_)?(?:chapter|ch)|(?:\b|_)c)[\.\-_\s]*(\d+(?:\.\d+)?)'

    match = re.search(num_pattern, name_clean)
    if match:
        num = float(match.group(1))
        num_source = "chapter_or_volume_label"
        name_clean = name_clean[:match.start()] + name_clean[match.end():]
    else:
        if upload_type == "chapter":
            ep_match = re.search(r'(?i)(?:\b|_)?(?:episode|ep)[\.\-_\s]*(\d+(?:\.\d+)?)', name_clean)
            if ep_match:
                num = float(ep_match.group(1))
                num_came_from_episode_label = True
                num_source = "episode_label"
                name_clean = name_clean[:ep_match.start()] + name_clean[ep_match.end():]
        
        if num is None:
            # A leading numeric prefix at the very start of the filename
            # (e.g. "0071 - Season 1 Afterword", "0069 - Title") is almost
            # always the intended chapter/episode counter in scanslation-
            # style naming -- checked BEFORE the generic last-number
            # fallback below, because that generic fallback grabs the LAST
            # number in the string, and a bare "Season 1" phrase (with no
            # actual Ep./Ch. label anywhere) would otherwise win over the
            # real leading counter -- e.g. "0071 - Season 1 Afterword"
            # would wrongly resolve to chapter 1 instead of chapter 71.
            leading_prefix_match = re.match(r'^0*(\d+)(?:\.\d+)?[\s\-_\.]+', name_clean)
            if leading_prefix_match:
                num = float(leading_prefix_match.group(1))
                num_source = "fallback"
                name_clean = name_clean[:leading_prefix_match.start()] + name_clean[leading_prefix_match.end():]

        if num is None:
            # Patch 2: Smarter Fallback. Skip years and grab the LAST number in the string
            all_nums = [(m.group(1), m) for m in re.finditer(r'(?<!\d)(\d+(?:\.\d+)?)(?!\d)', name_clean)]
            if all_nums:
                # Filter out obvious release years (1900-2099)
                valid_nums = [n for n in all_nums if not (len(n[0]) == 4 and n[0].startswith(('19', '20')))]
                target = valid_nums[-1] if valid_nums else all_nums[-1]
                num = float(target[0])
                num_source = "fallback"
                name_clean = name_clean[:target[1].start()] + name_clean[target[1].end():]

    if num is None:
        return None, [], raw_groups, None, None, None

    # The actual numeric value of a literal "Episode N" label in the
    # filename, if one exists -- regardless of whether it ended up being
    # the source of `num` or was passed over because a "ch0001"-style
    # sequential prefix won the number-extraction match first. This is what
    # lets get_files_in_dir's drift-correction pass compare "the number
    # we're about to sort/upload by" against "the number the story itself
    # actually uses" for the same file. Computed for both extract and
    # preset chapter-naming modes (the drift bug affects sort order either
    # way), but not for volumes, where this concept doesn't apply.
    episode_label_num = None
    if upload_type == "chapter":
        if num_came_from_episode_label:
            episode_label_num = num
        else:
            _ep_num_match = re.search(r'(?i)(?:\b|_)?(?:episode|ep)[\.\-_\s]*(\d+(?:\.\d+)?)', name_clean)
            if _ep_num_match:
                episode_label_num = float(_ep_num_match.group(1))

    if upload_type == "volume":
        return num, [("Vol. N.NN", f"Vol. {num:.2f}")], raw_groups, "volume", num_source, None
    if chapter_naming == "preset":
        return num, [("Chapter N", f"Chapter {num:g}")], raw_groups, "preset", num_source, episode_label_num

    had_season = bool(re.search(r'(?i)[\(\[\s]*s(?:eason)?[\.\-_\s]*\d+[\)\]\s]*', name_clean))
    # Either an "Episode N" label is still literally present elsewhere in the
    # string (e.g. it wasn't the number-extraction source), or it WAS the
    # source of `num` above and got removed already -- both cases mean the
    # filename genuinely had an episode label worth offering as a strip-able
    # candidate.
    had_episode_label = episode_label_num is not None
    # Same idea, but for a LEFTOVER "Ch./Chapter N" label -- e.g.
    # "ch0001 - Ch. 001 - Her Secret.cbz" has the number extracted from the
    # first "ch0001", leaving a second, untouched "Ch. 001 -" label sitting
    # in the title text. That leftover label is just as strippable as an
    # episode label, so it needs the same detection + candidate treatment.
    had_chapter_label = (not num_came_from_episode_label and upload_type != "volume" and
                          bool(re.search(r'(?i)(?:\b|_)?(?:chapter|ch)[\.\-_\s]*\d+(?:\.\d+)?', name_clean)))
    # A LEFTOVER leading zero-padded numeric prefix -- e.g.
    # "0069 - Ep. 69 - The Second Plan.cbz" gets its number from the
    # "Ep. 69" label, leaving the redundant leading "0069 -" sequential
    # counter still sitting untouched at the front of name_clean. Detected
    # independently of whichever path actually supplied `num`, since this
    # can leak through regardless of source (episode label, chapter label,
    # or fallback) -- it's just a separate, redundant counter baked into
    # the filename itself, extremely common in scanslation naming
    # (NNNN - Ep. NN - Title).
    had_leading_prefix = bool(re.match(r'^0*\d+[\s\-_\.]+', name_clean))

    def wash_title(s):
        s = s.replace('_', ' ')
        s = re.sub(r'\s+[\.\~\|]+', ' - ', s)
        s = re.sub(r'\bv\d+\b', '', s, flags=re.IGNORECASE)
        s = re.sub(r'^[\s\-\.\~\|]+|[\s\-\.\~\|]+$', '', s)
        s = re.sub(r'\s{2,}', ' ', s)
        s = re.sub(r'\s+-\s+', ' - ', s)
        return s.strip()

    # Capture the minimal wash (only the chapter/episode number removed,
    # nothing else rewritten) BEFORE the season/episode normalization below
    # mutates name_clean -- this is the genuine "untouched" fallback option,
    # distinct from the normalized "Episode N" / "(S1)" rewrites.
    minimal_wash = wash_title(name_clean)

    # Season-tag normalization. Two separate passes are needed:
    #
    # 1. Bracketed form -- "(Season 1 Finale)" / "(Season 2 Premiere)" /
    #    "(S1)". Must consume the WHOLE parenthetical, including any
    #    trailing words sharing the same bracket, not just "Season 1"
    #    itself -- otherwise the real closing paren is left behind as a
    #    dangling orphan (e.g. "(S1) Finale)"). Trailing words ("Finale",
    #    "Premiere") are kept as their own separate text outside the
    #    (S1) tag rather than folded into it, since they're naturally part
    #    of the title, not the season marker.
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

    # 2. Unbracketed form -- bare "Season 1 Afterword" with no parens at
    #    all. Needs its own pass since the bracketed regex above requires
    #    an actual closing bracket to match. The negative lookbehind on
    #    "(" stops this from re-matching the "(S1)" text the bracketed
    #    substitution just produced -- without it, "(S1)" immediately
    #    matches again as an "unbracketed" Season 1 and gets wrapped a
    #    second time into "((S1))".
    name_clean = re.sub(
        r'(?i)(?<!\()(?:\b|_)s(?:eason)?[\.\-_\s]*(\d+)\b',
        lambda m: f" (S{int(m.group(1))}) ",
        name_clean
    )
    name_clean = re.sub(r'(?i)(?:\b|_)?(?:episode|ep)[\.\-_\s]*(\d+(?:\.\d+)?)', lambda m: f" Episode {float(m.group(1)):g} ", name_clean)

    # Build a small set of distinct, meaningful candidates. Each is
    # (label, text) -- label describes the shape so the picker reads clearly,
    # text is the actual title that would be used. Candidates are deduped by
    # text: whichever label got there first wins, since a raw wash_title()
    # of the full untouched name is always offered too as a universal
    # fallback in case every detected pattern guessed wrong.
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

        # Title with the "Episode N" label stripped out, if one was present.
        if had_episode_label and "Episode " in washed_full:
            no_ep = re.sub(r'(?i)Episode\s*\d+(?:\.\d+)?[\s\-\.\~\|]*', '', washed_full)
            no_ep = wash_title(no_ep)
            add_candidate("Without episode label", no_ep)

        # Title with a leftover "Ch./Chapter N" label stripped out, if one
        # is still sitting in the text (e.g. "Ch. 001 - Her Secret" after
        # the actual chapter number was already pulled from elsewhere in
        # the filename). Same idea as the episode-label strip above, just
        # for the chapter-label case, since previously only episode/season
        # labels got this treatment and a leftover chapter label was never
        # recognized as strippable at all.
        if had_chapter_label:
            no_ch = re.sub(r'(?i)(?:\b|_)?(?:chapter|ch)[\.\-_\s]*\d+(?:\.\d+)?[\s\-\.\~\|]*', '', washed_full)
            no_ch = wash_title(no_ch)
            add_candidate("Without chapter label", no_ch)

        # Title with the season tag also stripped, on top of the above.
        if had_season:
            no_season = re.sub(r'(?i)\(S\d+\)\s*', '', washed_full)
            no_season = wash_title(no_season)
            add_candidate("Without season tag", no_season)

            if had_episode_label:
                bare = re.sub(r'(?i)\(S\d+\)\s*', '', washed_full)
                bare = re.sub(r'(?i)Episode\s*\d+(?:\.\d+)?[\s\-\.\~\|]*', '', bare)
                bare = wash_title(bare)
                add_candidate("Bare title only", bare)

        # Title with a redundant leading numeric prefix (e.g. "0069 -")
        # also stripped, on top of whichever other labels were already
        # removed above. This isn't mutually exclusive with the
        # episode/chapter/season stripping -- a real file can have both a
        # leading prefix AND an episode label at once (the common
        # "NNNN - Ep. NN - Title" scanslation pattern), so this strips the
        # leading prefix from every candidate text built so far rather
        # than only from washed_full, ensuring the combination is offered
        # too, not just the leading-prefix-only version.
        if had_leading_prefix:
            def _strip_leading_prefix(text):
                stripped = re.sub(r'^0*\d+[\s\-_\.]+', '', text)
                return wash_title(stripped)

            # Snapshot current candidates before adding prefix-stripped
            # variants, so we don't strip our own freshly-added entries.
            for label, text in list(candidates):
                no_prefix = _strip_leading_prefix(text)
                if no_prefix != text:
                    if label == default_label:
                        add_candidate("Without leading number", no_prefix)
                    else:
                        add_candidate(f"{label}, without leading number", no_prefix)

    # Always offer the completely untouched (only number/groups stripped,
    # nothing else rewritten -- e.g. keeps 'S01' or 'Ep 001' verbatim as
    # typed rather than normalizing them) wash as a universal fallback, in
    # case none of the detected/normalized patterns above match what the
    # person actually wants.
    if had_season or had_episode_label or had_chapter_label or had_leading_prefix:
        add_candidate("Minimal (only number removed)", minimal_wash)

    # Universal fallbacks, always offered for every chapter file regardless
    # of what was detected in the filename -- per explicit request, "Chapter
    # N" and "Episode N" should always be pickable options, not just a
    # last-resort when washed_full is empty.
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
    except Exception as e:
        return f"unreadable archive ({str(e)[:40]})"
    return None

def _correct_episode_drift(parsed):
    """
    Fixes a specific, real numbering bug: some batches name files with a
    sequential file-slot counter ("ch0001", "ch0002", ...) alongside the
    actual in-story episode number ("Episode 001", "Episode 002", ...).
    Normally these two numbers move in lockstep and it doesn't matter which
    one parse_filename_details picked. But when a batch contains a
    placeholder file with no real episode of its own -- a "Hiatus" chapter,
    for example -- upstream renaming tools sometimes still burn a ch000N
    slot on it without a matching Episode NNN. From that point on, every
    later file's ch000N counter is permanently offset from its true
    Episode NNN by however many placeholders came before it. Since
    ch000N (matched via the chapter/volume label pattern) is preferred
    over Episode N during extraction, every file after the first
    placeholder would otherwise sort and upload at the wrong chapter
    position.

    This can't be caught per-file -- "ch0025" looks like a perfectly valid
    chapter number in isolation. It only shows up as a batch-relative
    disagreement between two numbering systems for the same file, so the
    correction has to run once, across the whole parsed batch, before
    final numbers are committed.

    Rule (confirmed against a real drifted batch before implementing):
      - A file with a real "Episode N" label anywhere in its filename is
        trustworthy -- always use that label's number, never the ch000N
        counter, even when they happen to agree.
      - A file with NO episode label at all (a placeholder like "Hiatus")
        is the anomaly. It gets slotted in as (previous real episode
        number) + 0.5, so it lands immediately after the episode it
        actually follows in reading order.
      - If the anomaly is the very first file in the batch (nothing real
        precedes it), it's treated as a prologue and assigned 0.
      - Every file after an anomaly reverts to using its own real episode
        label number -- the correction doesn't propagate an offset
        forward, since only the placeholder itself was ever wrong.

    Mutates each dict in `parsed` in place, overwriting "number" with the
    corrected value where applicable. Files without any num_source
    ambiguity (e.g. already sourced correctly) are left untouched.
    """
    if not parsed:
        return

    # Only activate when the batch actually shows the drift signature: a
    # file whose num was sourced from a bare ch000N-style counter (matched
    # via the chapter/volume label pattern) that ALSO carries its own real
    # "Episode N" label with a DIFFERENT value. That's the one situation
    # that can only mean a sequential file-slot counter has drifted away
    # from the true episode numbering.
    #
    # Without this guard, an ordinary manga that's simply numbered
    # "ch0001 - Title", "ch0002 - Title", ... with no episode labels
    # anywhere would have every single file misread as a numberless
    # "anomaly" (since episode_label_num is None for all of them) and get
    # mangled into 0, 0.1, 0.2, ... This guard keeps the correction
    # strictly opt-in per batch, based on actual evidence of drift rather
    # than the mere absence of episode labels.
    drift_detected = any(
        item.get("num_source") == "chapter_or_volume_label"
        and item.get("episode_label_num") is not None
        and item["episode_label_num"] != item["number"]
        for item in parsed
    )
    if not drift_detected:
        return

    # ch000N-style counters are still monotonically increasing even when
    # drifted -- drift only offsets numbers, it never reorders files -- so
    # sorting by the raw (possibly drifted) number is a safe stand-in for
    # true reading order here, and matches how the batch is scanned/sorted
    # everywhere else in the script.
    ordered = sorted(parsed, key=lambda x: x["number"])

    # Every number a REAL episode label already claims, collected up front.
    # A placeholder's derived number (N.5, N.6, ...) must never land on one
    # of these -- e.g. if the batch separately contains a genuine
    # standalone "Episode 14.5" chapter, an auto-derived placeholder that
    # would also want "14.5" (because it happens to fall right after
    # episode 14 too) has to be pushed to 14.6 instead, or it would
    # silently collide with -- and in the title picker/upload step,
    # effectively overwrite the sort position of -- the real chapter.
    real_numbers = {
        item["episode_label_num"]
        for item in parsed
        if item.get("episode_label_num") is not None
    }

    def _next_free_slot(base):
        # base is the real integer/decimal to build off of (e.g. 14 for
        # the first placeholder after episode 14). Tries base+0.5, then
        # base+0.6, base+0.7, ... until it finds a value no real episode
        # label already owns.
        candidate = round(base + 0.5, 4)
        step = 1
        while candidate in real_numbers:
            step += 1
            candidate = round(base + 0.5 + (step - 1) * 0.1, 4)
        return candidate

    last_real_number = None   # last genuine episode-labeled number seen
    last_assigned = None      # last number assigned to ANY file (real or placeholder)
    saw_real_number = False   # whether any real-labeled file has appeared yet

    for item in ordered:
        episode_label_num = item.get("episode_label_num")

        if episode_label_num is not None:
            # Real label present -- always trust it over a ch000N counter,
            # correcting drift even if this exact file's numbers happened
            # to still agree (keeps every file consistently sourced from
            # the same signal rather than a mix of the two).
            item["number"] = episode_label_num
            last_real_number = episode_label_num
            last_assigned = episode_label_num
            saw_real_number = True
        else:
            # No real label at all -- this file itself is the anomaly
            # (e.g. a placeholder like "Hiatus"). Slot it in right after
            # whatever real episode last preceded it, skipping past any
            # slot a real episode label already claims.
            if not saw_real_number:
                if last_assigned is None:
                    item["number"] = 0.0 if 0.0 not in real_numbers else _next_free_slot(-0.5)
                else:
                    candidate = round(last_assigned + 0.1, 4)
                    while candidate in real_numbers:
                        candidate = round(candidate + 0.1, 4)
                    item["number"] = candidate
            elif last_assigned == last_real_number:
                # First placeholder since the last real episode -- the
                # normal N.5 "insert between two known integers" case,
                # pushed forward if a real .5 (or .6, .7...) chapter has
                # already claimed that exact slot.
                item["number"] = _next_free_slot(last_real_number)
            else:
                # A SECOND (or later) consecutive placeholder with no real
                # episode number in between. Using +0.5 again would repeat
                # the previous placeholder's number; using +1.0 would risk
                # colliding with the next real episode's integer. Extend
                # the decimal instead -- 14.5, 14.6, 14.7, ... -- so each
                # stays uniquely sortable between the same two real
                # episodes without touching the next real integer, again
                # skipping past anything a real label already claims.
                candidate = round(last_assigned + 0.1, 4)
                while candidate in real_numbers:
                    candidate = round(candidate + 0.1, 4)
                item["number"] = candidate
            last_assigned = item["number"]

def get_files_in_dir(directory, upload_type, chapter_naming="extract", custom_regex=None, strip_groups=False, validate=True, custom_renames=None):
    valid_extensions = ('.cbz', '.zip')
    parsed = []

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

    # Process in chapter/volume order so the title picker is asked in a
    # predictable, natural sequence rather than filesystem/scandir order.
    parsed.sort(key=lambda x: x["number"])

    # shape_key -> chosen title text, memoized across the whole batch. The
    # first file of a given shape prompts; every later file with the same
    # shape reuses that answer automatically. A shape that hasn't been seen
    # before (even if it only differs in, say, having a season tag when
    # earlier files didn't) prompts again.
    shape_choices = {}
    files_data = []

    for item in parsed:
        filename    = item["filename"]
        filepath    = item["filepath"]
        entry       = item["entry"]
        num         = item["number"]
        candidates  = item["candidates"]
        file_groups = item["groups"]
        shape_key   = item["shape_key"]

        if shape_key in shape_choices:
            chosen_label = shape_choices[shape_key]
            # Memoize by LABEL, not literal text -- e.g. once "Title only"
            # is picked for file 1 ("Her Secret"), file 2 should also get
            # ITS OWN "Title only" candidate text ("Her Depth and My
            # Bottom"), not fall back to file 1's literal string (which
            # won't exist in file 2's candidate list) or to candidates[0]
            # (a totally different label/shape, e.g. "Full title").
            by_label = {l: t for l, t in candidates}
            if chosen_label in by_label:
                final_title = by_label[chosen_label]
            elif candidates:
                # This file's candidate set doesn't even offer the
                # previously-chosen label -- genuinely no equivalent
                # option, so fall back to this file's own top candidate.
                final_title = candidates[0][1]
            else:
                final_title = f"Chapter {num:g}"
        elif candidates:
            chosen_label = None
            if len(candidates) == 1:
                # Still confirm every time, per your preference -- but with
                # only one real option there's nothing to choose between, so
                # show it as a single-choice confirmation instead of a bare
                # picker with one row.
                label, text = candidates[0]
                console.print()
                confirmed = ask_confirm(f"'{filename}' -> title will be [bold]\"{text}\"[/bold] ({label}). Use this for matching files?", default=True)
                if confirmed:
                    final_title = text
                    chosen_label = label
                else:
                    final_title = prompt(f"Enter title for '{filename}'", default=text).strip() or text
                    # A hand-typed title has no matching label -- don't
                    # memoize a label for it, so later files of this shape
                    # get re-prompted rather than silently reusing text
                    # that was specific to this one file.
            else:
                # value carries an index into `candidates` (as a string) so
                # the label can be recovered after selection -- using the
                # literal title text as the value loses which label/shape
                # was actually chosen, which is what broke memoization
                # across files with different per-file title text.
                choices = [
                    questionary.Choice(title=f"{text}  [dim]({label})[/dim]", value=str(i))
                    for i, (label, text) in enumerate(candidates)
                ]
                choices.append(questionary.Choice(title="Type my own...", value="__custom__"))
                console.print()
                selection = ask_select(
                    f"Select title for '{filename}' (applies to all similarly-formatted files):",
                    choices=choices,
                    auto_number=True
                )
                if selection == "__custom__":
                    final_title = prompt(f"Enter custom title for '{filename}'", default=candidates[0][1]).strip() or candidates[0][1]
                else:
                    chosen_label, final_title = candidates[int(selection)]
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
            "groups": file_groups,
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

def print_files_table(files, upload_type, group_label=None):
    total_size = sum(f["size"] for f in files)
    print_success(f"Found {len(files)} file(s)  ({fmt_size(total_size)} total)\n")

    has_groups = any(f.get("groups") for f in files) or bool(group_label)

    table = Table(box=box.ROUNDED, header_style="bold cyan", border_style="cyan", row_styles=["", "dim"])
    table.add_column("Filename", style="white", overflow="fold")
    table.add_column("Number", style="magenta", justify="right")
    table.add_column("Title", style="green", overflow="fold")
    if has_groups:
        table.add_column("Group", style="cyan", overflow="fold")
    table.add_column("Size", style="yellow", justify="right")

    for f in files:
        group_str = ", ".join(f["groups"]) if f.get("groups") else (group_label or "-")
        row = [f["filename"], str(f["number"]), f["title"] or "-"]
        if has_groups:
            row.append(group_str)
        row.append(fmt_size(f["size"]))
        table.add_row(*row)

    unit = "volume" if upload_type == "volume" else "chapter"
    unit_plural = f"{len(files)} {unit}{'s' if len(files) != 1 else ''}"
    table.add_section()
    total_row = [Text(f"TOTAL  ({unit_plural})", style="bold"), "", ""]
    if has_groups:
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
    by_number = {}
    for f in files:
        by_number.setdefault(f["number"], []).append(f["filename"])
    dups = {n: names for n, names in by_number.items() if len(names) > 1}
    if dups:
        term = "chapter" if upload_type == "chapter" else "volume"
        print_warning(f"Duplicate {term} number(s) detected:")
        for n in sorted(dups):
            print_warning(f"  • {term.title()} {n:g}: {', '.join(dups[n])}")
        print_warning("All listed files will be uploaded — remove duplicates if unintended.\n")

def load_config():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        logging.debug("save_config: failed to write %s: %s", CONFIG_PATH, e)

def _remember_library(lib):
    if not lib:
        return
    lib = os.path.normpath(lib)
    cfg = load_config()
    if cfg.get("library") != lib:
        cfg["library"] = lib
        save_config(cfg)

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
    flush_input_buffer()

    upload_type = ask_select("Upload type?", [
        questionary.Choice(title="Chapter", value="chapter"),
        questionary.Choice(title="Volume", value="volume"),
    ])

    chapter_naming = "extract"
    custom_regex   = None
    if upload_type == "chapter":
        chapter_naming = ask_select("Chapter naming format?", [
            questionary.Choice(title="Force 'Chapter X'", value="preset"),
            questionary.Choice(title="Auto-detect title", value="extract"),
            questionary.Choice(title="Custom regex", value="custom"),
        ])
        if chapter_naming == "custom":
            print_info("Regex Tip: Use a capture group () to extract a title, or 'Find -> Replace' to rename.")
            custom_regex_input = prompt("Enter your regex pattern")
            custom_renames, custom_regex = parse_custom_regex_input(custom_regex_input)
        else:
            custom_renames = None
    else:
        custom_renames = None

    console.print()
    console.rule("[dim]Files[/dim]", style="green")
    console.print()

    print_info("Scanning directory for files...")
    files = get_files_in_dir(directory, upload_type, chapter_naming, custom_regex, strip_groups=False, custom_renames=custom_renames)
    if not files:
        print_error("No valid .cbz or .zip files found.")
        sys.exit(1)

    print_files_table(files, upload_type)
    _check_missing(files, upload_type)
    _check_duplicates(files, upload_type)

    print_success("Dry run complete — no files were uploaded.")
    console.print()
    input("Press Enter to exit... ")
    sys.exit(0)

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
            # Confirmed via live API: id is the profile's user ID.
            user_id = profile.get("id") or profile.get("user_id") or profile.get("uid")
            return name, user_id
    except Exception: pass
    return None, None

def search_manga(query, session):
    try:
        res = session.get(f"{BASE_URL}/search.data", params={"search": query}, timeout=(10, 30))
        if res.status_code != 200: return []
        arr = res.json()
    except Exception: return []

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
        res = session.get(f"{BASE_URL}/api/groups", params={"q": query, "limit": 25}, timeout=(10, 30))
        if res.status_code != 200: return []
        return res.json().get("groups", [])
    except Exception: return []

def _group_search_queries(name):
    """Build an ordered list of search queries to try for a group name."""
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

def _read_cookie_db_with_fallback(db_path, domains=None):
    """Tries the DB in place first (works fine if the browser is closed).
    If that fails -- typically because the browser has it open and locked --
    copies it (plus its -wal/-shm sidecar files, since SQLite in WAL mode
    keeps recent writes there rather than in the main file) to a temp
    location and reads the copy instead. This is standard practice for
    reading a live SQLite database (the same idea backup tools and forensic
    utilities use) -- it doesn't touch encryption or the browser process,
    just works around the OS file lock."""
    try:
        return rookiepy.firefox_based(db_path, domains=domains)
    except Exception:
        pass

    tmp_dir = tempfile.mkdtemp(prefix="mangadot_zen_cookies_")
    try:
        tmp_db = os.path.join(tmp_dir, "cookies.sqlite")
        shutil.copy2(db_path, tmp_db)
        for sidecar_ext in ("-wal", "-shm"):
            sidecar_src = db_path + sidecar_ext
            if os.path.isfile(sidecar_src):
                shutil.copy2(sidecar_src, tmp_db + sidecar_ext)

        return rookiepy.firefox_based(tmp_db, domains=domains)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

def get_zen_cookies(domains=None):
    """rookiepy.firefox() only auto-detects the standard Firefox install
    location and has no parameter to redirect it elsewhere, so it can't be
    pointed at Zen. Instead this finds Zen's actual cookies.sqlite file and
    reads it via rookiepy.firefox_based(db_path, domains), the lower-level
    function that accepts an explicit database path."""
    if sys.platform == 'win32':
        profile_roots = [
            os.path.expandvars(r'%LOCALAPPDATA%\zen\Profiles'),
            os.path.expandvars(r'%APPDATA%\Zen\Profiles'),
            os.path.expandvars(r'%APPDATA%\zen\Profiles'),
        ]
    elif sys.platform == 'darwin':
        profile_roots = [
            os.path.expanduser('~/Library/Application Support/zen/Profiles'),
            os.path.expanduser('~/Library/Application Support/Zen/Profiles'),
        ]
    else:
        profile_roots = [os.path.expanduser('~/.zen')]

    for root in profile_roots:
        if not os.path.isdir(root):
            continue
        # Prefer a profile folder name containing 'default' (case-insensitive),
        # matching Firefox/Zen's own convention for the main profile.
        entries = sorted(os.listdir(root))
        default_entries = [e for e in entries if 'default' in e.lower()]
        ordered = default_entries + [e for e in entries if e not in default_entries]

        for entry in ordered:
            db_path = os.path.join(root, entry, 'cookies.sqlite')
            if os.path.isfile(db_path):
                return _read_cookie_db_with_fallback(db_path, domains=domains)

    return []
# ==============================================================================
# 🔑 CDP-based cookie retrieval (Chromium browsers)
# ==============================================================================

# This talks to the browser's own DevTools debugging endpoint, which the
# browser opts into explicitly via --remote-debugging-port. It is the same
# mechanism automation tools like Playwright/Selenium use. Cookies are
# returned by the browser itself over Network.getAllCookies -- there is no
# decryption of the on-disk cookie store and no bypass of App-Bound
# Encryption involved.
# ------------------------------------------------------------------------------

CDP_REGISTRY_APP_NAMES = {
    "chrome":  "chrome.exe",
    "edge":    "msedge.exe",
    "brave":   "brave.exe",
    "vivaldi": "vivaldi.exe",
    "opera":   "opera.exe",
}

def _find_browser_via_registry(app_exe_name):
    """Checks the Windows 'App Paths' registry keys, which installers
    register with the actual install location regardless of drive letter.
    This is the same mechanism Windows itself uses to resolve `chrome.exe`
    when you run it from the Start menu or `Win+R`."""
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

def _find_browser_executable(browser_key):
    plat = sys.platform
    plat_key = "win32" if plat == "win32" else ("darwin" if plat == "darwin" else "linux")

    # Registry lookup first -- finds installs on any drive/custom path.
    if plat_key == "win32":
        app_exe = CDP_REGISTRY_APP_NAMES.get(browser_key)
        if app_exe:
            found = _find_browser_via_registry(app_exe)
            if found:
                return found

    # Fall back to hardcoded common install paths.
    candidates = CDP_BROWSER_EXECUTABLES.get(browser_key, {}).get(plat_key, [])
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

def _cdp_port_is_up(port, timeout=1.0):
    try:
        r = requests.get(f"http://127.0.0.1:{port}/json/version", timeout=timeout)
        return r.status_code == 200
    except Exception:
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
    """Best-effort check that `pid` is still the process we launched (i.e. its
    running executable matches `expected_exe`), before we kill it. PIDs get
    recycled by the OS, so without this check a stale/incorrect PID entry
    could point at a completely unrelated process by the time cleanup runs.
    Returns True only when we can positively confirm a match; returns False
    for "doesn't match" AND for "couldn't determine" -- i.e. we only kill
    when we're reasonably sure, erring on the side of *not* killing."""
    if not expected_exe:
        return False
    expected_name = os.path.basename(expected_exe).lower()
    # Normalize away the .app/Contents/MacOS wrapper naming and .exe suffix
    # so comparisons are robust to how each platform reports process names.
    expected_name_stripped = re.sub(r'\.exe$', '', expected_name)

    try:
        if sys.platform == "win32":
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=5, check=False,
            )
            if result.returncode != 0 or not result.stdout.strip():
                return False
            # CSV format: "imagename.exe","pid","session","session#","mem"
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

        else:  # linux / other POSIX
            proc_exe = f"/proc/{pid}/exe"
            if os.path.exists(proc_exe):
                try:
                    resolved = os.readlink(proc_exe)
                    return os.path.basename(resolved).lower() == expected_name
                except OSError:
                    pass  # fall through to `ps` fallback below (e.g. permission denied)
            result = subprocess.run(
                ["ps", "-p", str(pid), "-o", "comm="],
                capture_output=True, text=True, timeout=5, check=False,
            )
            if result.returncode != 0 or not result.stdout.strip():
                return False
            running_name = os.path.basename(result.stdout.strip()).lower()
            return running_name == expected_name
    except Exception:
        return False

def _cdp_kill_stale_process(browser_key):
    """If a previous CDP launch of this specific browser is still alive (e.g.
    it kept running in the background after its window was closed), kill it
    so the next launch is guaranteed to pick up current command-line flags.
    Without this, subprocess.Popen on some platforms/browsers can silently
    hand off to the already-running process instead of starting a fresh one."""
    pid_file = _cdp_pid_file(browser_key)
    if not os.path.isfile(pid_file):
        return
    try:
        with open(pid_file, "r", encoding="utf-8") as f:
            old_pid = int(f.read().strip())
    except (ValueError, OSError):
        return

    # Verify this PID is still actually our browser before killing it -- PIDs
    # get recycled, so without this check we could kill an unrelated process
    # that happens to have inherited the same PID since our last run.
    expected_exe = _find_browser_executable(browser_key)
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
                time.sleep(0.5)
                os.kill(old_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass  # already dead
    except Exception:
        pass 
    finally:
        try:
            os.remove(pid_file)
        except OSError:
            pass

def _cleanup_all_cdp_processes():
    for browser in ["chrome", "edge", "brave", "vivaldi", "opera"]:
        _cdp_kill_stale_process(browser)
atexit.register(_cleanup_all_cdp_processes)        

def _cdp_launch_browser(browser_key, url):
    """Launch a Chromium browser with remote debugging enabled, pointed at a
    dedicated (non-default) profile directory unique to this browser. Chrome
    136+ refuses the debug port against the default profile, so a separate
    profile is required -- you'll need to log into MangaDot once inside this
    dedicated window."""
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
            pass
        return proc
    except Exception:
        return None

def _cdp_get_targets(port):
    try:
        r = requests.get(f"http://127.0.0.1:{port}/json/list", timeout=5)
        r.raise_for_status()
        return r.json()
    except Exception:
        return []

def _cdp_open_new_tab(port, url):
    try:
        # PUT is the documented method for /json/new in modern Chrome; older
        # versions also accepted GET, so fall back if PUT is rejected.
        r = requests.put(f"http://127.0.0.1:{port}/json/new?{url}", timeout=5)
        if r.status_code >= 400:
            r = requests.get(f"http://127.0.0.1:{port}/json/new?{url}", timeout=5)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None

def _cdp_get_all_cookies(port, timeout=10):
    """Connects to a page-level DevTools target and issues Network.getAllCookies,
    which returns cookies across the whole browser (not just that one tab)."""
    targets = [t for t in _cdp_get_targets(port) if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
    if not targets:
        new_target = _cdp_open_new_tab(port, BASE_URL)
        if new_target and new_target.get("webSocketDebuggerUrl"):
            targets = [new_target]

    if not targets:
        return None

    ws_url = targets[0]["webSocketDebuggerUrl"]
    ws = websocket.create_connection(ws_url, timeout=timeout)
    try:
        ws.send(json.dumps({"id": 1, "method": "Network.getAllCookies"}))
        ws.settimeout(timeout)
        while True:
            raw = ws.recv()
            msg = json.loads(raw)
            if msg.get("id") == 1:
                return msg.get("result", {}).get("cookies", [])
    finally:
        ws.close()

def _cdp_tracked_process_alive(browser_key):
    """True only if the PID we last launched for this specific browser via
    _cdp_launch_browser is still running -- i.e. we know it was started with
    current command-line flags. A port simply being 'up' isn't enough
    evidence, since a stale process from before a flag change (like
    --remote-allow-origins) can still be listening and would otherwise get
    silently reused -- or worse, a different browser's live process could be
    mistaken for this one if ports/profiles were shared."""
    pid_file = _cdp_pid_file(browser_key)
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
        except Exception:
            return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, PermissionError):
            return False
        except Exception:
            return False

def get_cdp_cookies(browser_key, domains=None):
    """Returns cookies for `browser_key` via CDP, launching a dedicated debug
    profile (own port, own user-data-dir) if one isn't already running for
    this specific browser. Returns a list of dicts shaped like rookiepy's
    output: {'name', 'value', 'domain'}."""
    port = _cdp_port_for(browser_key)
    port_up = _cdp_port_is_up(port)
    trusted = port_up and _cdp_tracked_process_alive(browser_key)

    if not trusted:
        launched_proc = _cdp_launch_browser(browser_key, BASE_URL)
        if launched_proc is None:
            print_error(f"Could not find or launch {browser_key.title()} for CDP mode.")
            print_info(f"If {browser_key.title()} is installed in a custom location, "
                       f"tell Claude the exact path to its .exe and it can be added directly.")
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

def authenticate_session(req_session, force_browser=None):
    # Gecko-based (Zen/Firefox) store cookies in a plain, unencrypted SQLite
    # file on disk -- rookiepy reads that directly, no issue. Chromium-based
    # browsers encrypt cookies at rest (App-Bound Encryption on Windows) and
    # usually block direct decryption by external processes; their CDP
    # counterparts exist specifically to route around that.
    CHROMIUM_BROWSERS = {"chrome", "brave", "edge", "opera", "vivaldi"}

    supported_browsers = {
        "zen": get_zen_cookies,
        "chrome": rookiepy.chrome,
        "firefox": rookiepy.firefox,
        "brave": rookiepy.brave,
        "edge": rookiepy.edge,
        "opera": rookiepy.opera,
        "vivaldi": rookiepy.vivaldi,
    }

    # CDP fallbacks -- these use a dedicated debug profile per browser, so
    # they're only tried explicitly (via the manual retry menu), not in the
    # automatic first pass, since they may need a one-time login.
    cdp_browsers = {
        "chrome (cdp)":  lambda domains=None: get_cdp_cookies("chrome", domains=domains),
        "edge (cdp)":    lambda domains=None: get_cdp_cookies("edge", domains=domains),
        "brave (cdp)":   lambda domains=None: get_cdp_cookies("brave", domains=domains),
        "vivaldi (cdp)": lambda domains=None: get_cdp_cookies("vivaldi", domains=domains),
        "opera (cdp)":   lambda domains=None: get_cdp_cookies("opera", domains=domains),
    }

    all_browsers = {**supported_browsers, **cdp_browsers}
    browsers_to_try = {force_browser: all_browsers[force_browser]} if force_browser else supported_browsers

    if not force_browser:
        print_info("Scanning all installed browsers for an active MangaDot session...")

    for browser_name, get_cookies_fn in browsers_to_try.items():
        try:
            req_session.cookies.clear()
            ua_key = browser_name.replace(" (cdp)", "")
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
                print_warning(f"{browser_name.title()}: {type(e).__name__}: {e}{hint}")
            else:
                console.print(f"  [dim]· {browser_name.title()}: {type(e).__name__}: {e}[/dim]{hint}")
            continue 

    print_error("No valid MangaDot session found. Ensure your browser is FULLY CLOSED and you are logged in.")
    print_info("Zen/Firefox are read directly and should just work if you're logged in there. "
               "Chrome/Brave/Edge/Opera/Vivaldi usually can't be read directly (encrypted cookie store) -- "
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
    if response is not None:
        ra = response.headers.get("Retry-After")
        if ra:
            try:
                return max(0.0, min(float(ra), 120.0))
            except (TypeError, ValueError):
                pass
    return min(RETRY_DELAY * (2 ** attempt), 60)

def _interruptible_sleep(delay, abort_event, slice_seconds=0.1):
    """Sleep for `delay` seconds, but in short slices so an abort (e.g. from
    Ctrl+C) is noticed almost immediately instead of only after the full
    delay elapses. Returns True if the sleep completed normally, False if it
    was cut short because abort_event got set. Retry backoffs here can be up
    to 60s (exponential) or 120s (server Retry-After), and since a Python
    thread can't be force-killed, without this a worker mid-sleep on a bad
    retry window could hold up the whole script's exit for up to two minutes."""
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
    except Exception:
        return None
    return None

def _build_shared_upload_session(session):
    """Build one requests.Session, configured with the same auth/cookies/proxy
    as the main session, that persists across the whole batch and is shared
    by every worker thread. requests.Session objects (and the connection pool
    on their mounted HTTPAdapter) are thread-safe for concurrent requests, so
    a single shared session here lets uploads across files/threads actually
    reuse pooled TCP+TLS connections instead of each file paying for a fresh
    handshake."""
    shared_session = requests.Session()
    shared_session.headers.update(session.headers)
    shared_session.cookies.update(session.cookies)
    if session.proxies:
        shared_session.proxies.update(session.proxies)
    shared_session.verify = session.verify
    if session.hooks.get('response'):
        shared_session.hooks['response'] = list(session.hooks['response'])

    # Sized for the full batch: pool_maxsize should comfortably cover the
    # configured thread count (1-30) so worker threads aren't fighting each
    # other for pooled connections.
    shared_adapter = HTTPAdapter(max_retries=0, pool_connections=32, pool_maxsize=32)
    shared_session.mount("https://", shared_adapter)
    shared_session.mount("http://",  shared_adapter)
    return shared_session

def upload_file_tus_worker(session, renderer, file_info, manga_id, group_ids,
                           upload_type, batch_id, language, scanlator_name, abort_event,
                           verify_timeout=MAX_VERIFY_SECONDS, current_user_id=None,
                           is_group_upload=False, has_file_specific_group=True,
                           upload_session=None):
    filename = file_info["filename"]
    filepath = file_info["filepath"]
    size     = file_info["size"]

    # upload_session is a shared, pre-configured session that persists across
    # the whole batch (see _build_shared_upload_session / process_uploads),
    # so connections are pooled across files and threads instead of each file
    # paying for a fresh TCP+TLS handshake. Falling back to a private session
    # keeps this function usable standalone (e.g. in tests) if none is passed.
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
        if upload_type == "volume":   tus_metadata["volume_number"]  = file_info["number"]
        if file_info.get("title"):    tus_metadata["chapter_title"]  = file_info["title"]
        if scanlator_name:
            tus_metadata["scanlator_name"] = scanlator_name

        encoded_metadata = encode_tus_metadata(tus_metadata)
        headers = {
            "Tus-Resumable":   "1.0.0",
            "Upload-Length":   str(size),
            "Upload-Metadata": encoded_metadata,
        }

        already_exists = False
        for attempt in range(MAX_RETRIES):
            if abort_event.is_set(): return {"key": filename, "success": False, "error": "Aborted"}
            try:
                renderer.update_chapter_status(filename, "Creating upload...", 0.0)
                res = worker_session.post(TUS_ENDPOINT, headers=headers, timeout=(10, 30))
                if res.status_code in (401, 403): raise SessionExpiredError()
                if res.status_code == 409:
                    # Don't return success yet — the chapter already exists server-side,
                    # but it may belong to a different group/scanlator. Fall through to
                    # the same Ghost-Chapter verification block used by normal uploads.
                    already_exists = True
                    break
                res.raise_for_status()
                upload_location = res.headers.get("Location")
                if not upload_location: raise ValueError("No Location header in TUS response")
                break
            except SessionExpiredError: raise
            except Exception as e:
                if attempt < MAX_RETRIES - 1:
                    renderer.update_chapter_status(filename, "Create Err... Retrying", 0.0)
                    if not _interruptible_sleep(RETRY_DELAY, abort_event):
                        return {"key": filename, "success": False, "error": "Aborted"}
                else: return {"key": filename, "success": False, "error": f"Init failed: {str(e)[:30]}"}

        chunk_size = 5 * 1024 * 1024
        offset     = size if already_exists else 0

        try:
            with open(filepath, 'rb') as f:
                while offset < size:
                    if abort_event.is_set(): return {"key": filename, "success": False, "error": "Aborted"}

                    if f.tell() != offset:
                        f.seek(offset)

                    chunk = f.read(chunk_size)
                    if not chunk: break

                    chunk_done = False
                    resynced   = False
                    for patch_attempt in range(MAX_RETRIES):
                        try:
                            renderer.update_chapter_status(
                                filename, "Uploading...", offset / size,
                                current=offset, total=size
                            )
                            patch_headers = {
                                "Tus-Resumable": "1.0.0",
                                "Upload-Offset": str(offset),
                                "Content-Type":  "application/offset+octet-stream",
                            }
                            patch_res = worker_session.patch(upload_location, headers=patch_headers, data=chunk, timeout=60)

                            if patch_res.status_code in (401, 403): raise SessionExpiredError()
                            elif patch_res.status_code == 204:
                                server_off = patch_res.headers.get("Upload-Offset")
                                offset     = int(server_off) if server_off is not None else offset + len(chunk)
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
                                    renderer.update_chapter_status(filename, f"Resyncing chunk... ({patch_attempt + 1})", offset / size, current=offset, total=size)
                                    if not _interruptible_sleep(_compute_retry_delay(patch_res, patch_attempt), abort_event):
                                        return {"key": filename, "success": False, "error": "Aborted"}
                                else: return {"key": filename, "success": False, "error": "HTTP 409 (Offset Conflict)"}
                            elif patch_res.status_code in RETRYABLE_STATUSES:
                                if patch_attempt < MAX_RETRIES - 1:
                                    renderer.update_chapter_status(filename, f"Retrying chunk... ({patch_attempt + 1})", offset / size, current=offset, total=size)
                                    if not _interruptible_sleep(_compute_retry_delay(patch_res, patch_attempt), abort_event):
                                        return {"key": filename, "success": False, "error": "Aborted"}
                                else: return {"key": filename, "success": False, "error": f"HTTP {patch_res.status_code} (Max Retries)"}
                            else: return {"key": filename, "success": False, "error": f"HTTP {patch_res.status_code}"}
                        except SessionExpiredError: raise
                        except Exception as e:
                            if patch_attempt < MAX_RETRIES - 1:
                                renderer.update_chapter_status(filename, f"Net Err, Retrying... ({patch_attempt + 1})", offset / size, current=offset, total=size)
                                if not _interruptible_sleep(_compute_retry_delay(None, patch_attempt), abort_event):
                                    return {"key": filename, "success": False, "error": "Aborted"}
                                server_off = _tus_offset(worker_session, upload_location)
                                if server_off is not None and server_off > offset:
                                    offset   = server_off
                                    resynced = True
                                    break
                            else: return {"key": filename, "success": False, "error": f"Network Err: {str(e)[:30]}"}
                    if resynced:
                        continue
                    if not chunk_done: return {"key": filename, "success": False, "error": "Chunk upload failed"}
        except SessionExpiredError: raise
        except Exception as e: return {"key": filename, "success": False, "error": str(e)[:30]}

        base_check_url = f"{BASE_URL}/api/manga/{manga_id}/volumes" if upload_type == "volume" else f"{BASE_URL}/api/manga/{manga_id}/chapters/list"
        found        = False
        found_item   = None
        verify_start = time.time()

        if not group_ids and not scanlator_name:
            if is_group_upload and not has_file_specific_group:
                # This is a group upload overall, but this specific file had no
                # [Group] tag that could be resolved (or its tag failed to
                # resolve). There is nothing to verify server-side ingestion
                # against, so — unlike a genuine individual/ungrouped upload —
                # we must NOT silently report success. Surface this clearly so
                # it isn't mistaken for a verified upload.
                label = "⚠️ Uploaded (Unverified — no group)"
                renderer.update_chapter_status(filename, label, 1.0, current=size, total=size, speed=0.0, eta=0.0)
                return {
                    "key": filename,
                    "success": True,
                    "warning": "Uploaded without attribution verification: no resolved group/scanlator for this file."
                }
            # Genuine individual (non-group) upload — nothing to verify uploader-attribution against.
            label = "✅ Already Exists" if already_exists else "✅ Uploaded"
            renderer.update_chapter_status(filename, label, 1.0, current=size, total=size, speed=0.0, eta=0.0)
            return {"key": filename, "success": True}

        while not found:
            if abort_event.is_set(): return {"key": filename, "success": False, "error": "Aborted"}
            elapsed_verify = int(time.time() - verify_start)
            if elapsed_verify >= verify_timeout: return {"key": filename, "success": False, "error": "Verification timeout reached."}
            renderer.update_chapter_status(filename, f"Verifying... ({elapsed_verify}s)", 1.0, current=size, total=size, speed=0.0, eta=0.0)
            if not _interruptible_sleep(RETRY_DELAY, abort_event):
                return {"key": filename, "success": False, "error": "Aborted"}
            
            with get_verify_sem():
                try:
                    fetch_check = worker_session.get(f"{base_check_url}?_t={int(time.time())}", timeout=10)

                    if fetch_check.status_code in (401, 403): raise SessionExpiredError()
                    if fetch_check.status_code != 200: continue

                    items_list = fetch_check.json()
                    if isinstance(items_list, dict): items_list = items_list.get("volumes", items_list.get("chapters", []))
                    if not isinstance(items_list, list): continue

                    for item in items_list:
                        try:
                            if upload_type == "volume":
                                match = math.isclose(float(item.get("volume_number", -1)), float(file_info["number"]), abs_tol=0.001)
                            else:
                                match = math.isclose(float(item.get("chapter_number", -1)), float(file_info["number"]), abs_tol=0.001)
                        except (ValueError, TypeError): match = False

                        if match:
                            item_group_ids = []
                            if item.get("group_id"): item_group_ids.append(item["group_id"])
                            for g in item.get("groups", []):
                                if isinstance(g, dict) and g.get("id"): item_group_ids.append(g["id"])
                                elif isinstance(g, int): item_group_ids.append(g)
                            item_scanlator = item.get("scanlator_name") or item.get("scanlator")

                            if group_ids and any(gid in item_group_ids for gid in group_ids):
                                found_item = item; found = True; break

                            if not group_ids and scanlator_name:
                                if isinstance(item_scanlator, str) and item_scanlator.strip().lower() == scanlator_name.strip().lower():
                                    found_item = item; found = True; break

                except SessionExpiredError:
                    raise
                except Exception:
                    continue

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
        renderer.update_chapter_status(filename, label, 1.0, current=size, total=size, speed=0.0, eta=0.0)
        return {"key": filename, "success": True}
    finally:
        # Only close sessions this call created itself. The shared batch
        # session (passed in via upload_session) must stay open -- it's
        # reused by every other worker thread/file for the rest of the batch.
        if owns_session:
            worker_session.close()

# ==============================================================================
# 🔄 PROCESS UPLOADS
# ==============================================================================

def process_uploads(files_to_upload, req_session, manga_id, group_ids,
                    upload_type, language, scanlator_name, thread_count,
                    per_file_group_map=None, verify_timeout=MAX_VERIFY_SECONDS, current_user_id=None,
                    is_group_upload=None):
    per_file_group_map = per_file_group_map or {}
    # is_group_upload tells the workers whether this batch is a "group" upload
    # overall (so a file with no resolvable group/scanlator is an attribution
    # gap that must be flagged) versus a genuine individual/ungrouped upload
    # (where having no group_ids/scanlator is expected and fine).
    # If not explicitly provided, infer it defensively: treat as a group
    # upload whenever any group information exists anywhere in the batch.
    if is_group_upload is None:
        is_group_upload = bool(group_ids) or any(per_file_group_map.values())
    chunks    = [files_to_upload[i:i + MAX_BATCH_SIZE] for i in range(0, len(files_to_upload), MAX_BATCH_SIZE)]
    file_keys = [f["filename"] for f in files_to_upload]
    renderer  = UIRenderer(file_keys)
    renderer.start()

    failed_chapters  = []
    failure_reasons  = {}
    session_expired  = False
    abort_event      = threading.Event()

    # One shared session, reused by every worker thread across every chunk of
    # this batch, so upload connections are actually pooled instead of each
    # file paying for a fresh TCP+TLS handshake (requests.Session is safe for
    # concurrent use across threads).
    shared_upload_session = _build_shared_upload_session(req_session)

    def mark_failed(name, reason, status):
        renderer.update_chapter_status(name, status, 1.0)
        if name not in failed_chapters:
            failed_chapters.append(name)
        failure_reasons[name] = reason

    try:
        for chunk in chunks:
            if session_expired:
                for f in chunk:
                    mark_failed(f["filename"], "Paused — session expired before upload", "⏸️ Paused (Session)")
                continue

            chapters_payload = [{"chapter_number": f["number"] if upload_type == "chapter" else 0, "volume_number": f["number"] if upload_type == "volume" else None, "chapter_title": f["title"]} for f in chunk]

            chunk_group_ids = set(group_ids) if group_ids else set()
            for f in chunk:
                f_groups = per_file_group_map.get(f.get("norm_filepath") or _norm_filepath(f["filepath"]))
                if f_groups:
                    chunk_group_ids.update(f_groups)
            init_payload = {"manga_id": manga_id, "language": language, "group_ids": list(chunk_group_ids), "type": upload_type, "scanlator_name": scanlator_name, "chapters": chapters_payload}
            batch_id = None
            try:
                res = req_session.post(BATCH_INIT_ENDPOINT, json=init_payload, timeout=(10, 30))
                if res.status_code in (401, 403):
                    session_expired = True
                    abort_event.set()
                    for f in chunk:
                        mark_failed(f["filename"], "Paused — authentication expired", "⏸️ Paused (Auth)")
                    continue
                res.raise_for_status()
                batch_data = res.json()
                if not batch_data.get("success"): raise Exception(str(batch_data))
                batch_id = batch_data["batch_id"]
            except Exception as e:
                for f in chunk:
                    mark_failed(f["filename"], f"Batch init failed: {str(e)[:80]}", "❌ Batch Init Failed")
                continue

            with concurrent.futures.ThreadPoolExecutor(max_workers=thread_count) as executor:
                futures = {}
                for f in chunk:
                    norm_path = f.get("norm_filepath") or _norm_filepath(f["filepath"])
                    file_specific_groups = per_file_group_map.get(norm_path)
                    has_file_specific_group = bool(file_specific_groups)
                    resolved_group_ids = file_specific_groups if file_specific_groups else group_ids
                    future = executor.submit(
                        upload_file_tus_worker, req_session, renderer, f, manga_id,
                        resolved_group_ids,
                        upload_type, batch_id, language, scanlator_name, abort_event,
                        verify_timeout, current_user_id,
                        is_group_upload, has_file_specific_group,
                        shared_upload_session
                    )
                    futures[future] = f
                chunk_had_success = False
                try:
                    for future in concurrent.futures.as_completed(futures):
                        f_info = futures[future]
                        try:
                            result = future.result()
                            if result['success']:
                                chunk_had_success = True
                                if result.get('warning'):
                                    print_warning(f"'{f_info['filename']}': {result['warning']}")
                            else:
                                mark_failed(result['key'], result.get('error', 'Unknown error'), f"❌ {result['error']}")
                        except SessionExpiredError:
                            session_expired = True
                            abort_event.set()
                            mark_failed(f_info["filename"], "Paused — authentication expired", "⏸️ Paused (Auth)")
                except KeyboardInterrupt:
                    print_warning("Stopping after in-flight uploads finish... (This might take a minute)")
                    abort_event.set()
                    for f in futures:
                        f.cancel()
                    raise

            if batch_id and not session_expired and chunk_had_success:
                for comp_attempt in range(MAX_RETRIES):
                    try:
                        comp_res = req_session.post(f"{BASE_URL}/api/uploads/batch/{batch_id}/complete", timeout=(10, 30))
                        if comp_res.status_code in (401, 403):
                            session_expired = True
                            break
                        comp_res.raise_for_status()
                        break
                    except Exception as e:
                        if comp_attempt < MAX_RETRIES - 1:
                            if not _interruptible_sleep(_compute_retry_delay(None, comp_attempt), abort_event):
                                break
                        else: logging.warning(f"Batch {batch_id} complete call failed after {MAX_RETRIES} attempts: {e}")
    except KeyboardInterrupt:
        abort_event.set()
        raise
    finally:
        renderer.stop()
        shared_upload_session.close()

    return failed_chapters, session_expired, failure_reasons

# ==============================================================================
# 🎛️  INTERACTIVE SETUP HELPERS
# ==============================================================================

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
            print_warning("No matching manga titles found on MangaDot. Try another search query.")
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

def _setup_group_config(directory, req_session, upload_type="chapter"):
    is_group             = ask_confirm("Upload as a Group?", default=True)
    group_ids            = []
    scanlator_name       = None
    per_file_group_map   = {}
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
            g_input = prompt("Search Group by Name, or enter ID directly")
            try:
                candidate_id = int(g_input)
                group_ids = [candidate_id]
                selected_group_name = f"ID: {candidate_id}"
                break
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

            group_choices = [questionary.Choice(title=f"{g['name']} (ID: {g['id']})", value=g) for g in results]
            group_choices.append(questionary.Choice(title="🔍 Search again", value="__search_again__"))
            selection = ask_select("Select a group:", group_choices)

            if selection == "__search_again__": continue
            group_id  = selection['id']
            group_ids = [group_id]
            selected_group_name = selection['name']
            print_success(f"Selected Group: {selection['name']} (ID: {group_id})")
    else:
        scanlator_name = prompt("Enter your individual Scanlator Name")

    return is_group, group_ids, scanlator_name, per_file_group_map, selected_group_name, strip_bracket_groups

def _run_upload_loop(files, req_session, manga_id, group_ids, upload_type,
                     language, scanlator_name, thread_count, per_file_group_map,
                     current_browser, verify_timeout=MAX_VERIFY_SECONDS, current_user_id=None,
                     is_group_upload=None):
    current_files_to_upload = files
    upload_start    = time.time()
    failed_chapters = []
    failure_reasons = {}

    while True:
        failed_chapters, session_expired, failure_reasons = process_uploads(
            current_files_to_upload, req_session, manga_id, group_ids, upload_type,
            language, scanlator_name, thread_count,
            per_file_group_map=per_file_group_map,
            verify_timeout=verify_timeout,
            current_user_id=current_user_id,
            is_group_upload=is_group_upload
        )

        if session_expired:
            console.print()
            console.rule("[bold red]Session Expired[/bold red]")
            print_warning("UPLOAD PAUSED: Session token expired or unauthorized.")
            print_warning("Refresh your login/Cloudflare check in your browser, then return here.")

            time.sleep(1.5)
            flush_input_buffer()

            input("\nPress Enter to re-authenticate and resume... ")
            current_browser, current_user_id = authenticate_session(req_session, current_browser)
            failed_set = set(failed_chapters)
            current_files_to_upload = [f for f in current_files_to_upload if f["filename"] in failed_set]

            console.print()
            console.rule("[dim]Resuming Upload[/dim]")
            console.print()
            print_info(f"Resuming upload for {len(current_files_to_upload)} failed/paused chapter(s)...")
            continue

        console.print()
        console.rule("[bold cyan]🎉 All operations complete[/bold cyan]", style="green")
        console.print()

        if not failed_chapters:
            print_success("All chapters were processed successfully!")
            break

        print_error(f"{len(failed_chapters)} chapter(s) failed after all retries.")
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
                    reason = failure_reasons.get(chap, "Unknown error")
                    f.write(f"{chap}\t{reason}\n")
            print_info(f"Failed list saved to [cyan]`{failed_log_name}`[/cyan].")
        except Exception as e:
            print_error(f"Could not write `{failed_log_name}`: {e}")
            break

        retry_choice = ask_confirm("Retry ONLY the failed chapters?", default=True)
        if not retry_choice: break
        failed_set = set(failed_chapters)
        current_files_to_upload = [f for f in current_files_to_upload if f["filename"] in failed_set]
        print_info(f"\nRetrying {len(current_files_to_upload)} failed chapter(s)...")

    return set(failed_chapters), time.time() - upload_start, current_browser

# ==============================================================================
# 🚀 MAIN
# ==============================================================================

def _check_proxy(proxy_url, verify=True):
    test_url = "https://www.google.com/generate_204"
    try:
        r = requests.get(
            test_url,
            proxies={"http": proxy_url, "https": proxy_url},
            timeout=10,
            headers={"User-Agent": DEFAULT_USER_AGENTS["chrome"]},
            allow_redirects=False,
            verify=verify,
        )
        if r.status_code == 204:
            return True, None
        elif r.status_code == 407:
            return False, "Proxy returned 407 — credentials are wrong or missing."
        else:
            return False, f"Proxy failed. Unexpected status: HTTP {r.status_code}"
    except requests.exceptions.SSLError:
        return False, (
            "SSL error through proxy. The proxy may be intercepting TLS (MITM). "
            "If you trust this proxy, add '--proxy-no-verify' to skip SSL checks."
        )
    except requests.exceptions.ProxyError as e:
        return False, f"Proxy connection failed: {str(e)[:80]}"
    except requests.exceptions.ConnectionError as e:
        return False, f"Could not reach proxy: {str(e)[:80]}"
    except Exception as e:
        return False, f"Proxy check error: {str(e)[:80]}"

def _positive_int(value):
    """argparse type= validator for arguments that must be a positive
    integer (e.g. --verify-timeout). Without this, a value like 0 or a
    negative number passes argparse silently and only causes a confusing
    failure much later -- e.g. --verify-timeout 0 makes the very first
    'elapsed >= verify_timeout' check in the verification loop already
    true, so every upload immediately reports "Verification timeout
    reached" instead of a clear "invalid argument" error up front."""
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
    parser.add_argument("--library", default=DEFAULT_LIBRARY_DIR or None, metavar="DIR", help="Parent folder of manga subfolders; pick one interactively instead of typing a path.")
    parser.add_argument("--proxy", default=None, help="Tunnel all HTTP/HTTPS requests through a specific proxy server.")
    parser.add_argument("--proxy-no-verify", action="store_true", help="Disable SSL certificate verification when using a proxy (use only if the proxy does TLS interception).")
    return parser

def main():
    args = build_arg_parser().parse_args()
    verify_timeout = args.verify_timeout

    saved_config     = load_config()
    resolved_library = args.library or saved_config.get("library") or (DEFAULT_LIBRARY_DIR or None)

    resolved_proxy = args.proxy

    if args.dry_run: 
        run_dry_run(resolved_library)
        sys.exit(0)

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
        proxy_no_verify = args.proxy_no_verify
        console.print(f"[yellow][PROXY] Routing all traffic through: {resolved_proxy}[/yellow]")
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

    console.print()
    console.rule("[dim]Setup[/dim]", style="green")
    console.print()

    library_dir = resolved_library
    if library_dir and not args.library and library_dir == saved_config.get("library"):
        print_info(f"Using remembered library folder: [cyan]{library_dir}[/cyan]")
    directory = select_directory(library_dir)
    flush_input_buffer()

    guessed_title = Path(directory).name if directory else ""
    manga_id = _select_manga(req_session, guessed_title)

    req_session.headers.update({"Referer": f"{BASE_URL}/manga/{manga_id}/upload"})

    upload_type = ask_select("Upload type?", [
        questionary.Choice(title="Chapter", value="chapter"),
        questionary.Choice(title="Volume", value="volume"),
    ])

    chapter_naming = "extract"
    custom_regex   = None
    if upload_type == "chapter":
        chapter_naming = ask_select("Chapter naming format?", [
            questionary.Choice(title="Force 'Chapter X'", value="preset"),
            questionary.Choice(title="Auto-detect title", value="extract"),
            questionary.Choice(title="Custom regex", value="custom"),
        ])
        if chapter_naming == "custom":
            print_info("Regex Tip: Use a capture group () to extract a title, or 'Find -> Replace' to rename.")
            custom_regex_input = prompt("Enter your regex pattern")
            custom_renames, custom_regex = parse_custom_regex_input(custom_regex_input)
        else:
            custom_renames = None
    else:
        custom_renames = None

    language = prompt("Language code", default="en")

    is_group, group_ids, scanlator_name, per_file_group_map, selected_group_name, strip_bracket_groups = \
    _setup_group_config(directory, req_session, upload_type)
    
    print_warning(
    "Recommended: 5 to 10 threads. But sure, slap it to 30 if you want.\n"
    "Cloudflare's banhammer is feeling lonely today, and I'm sure the admins\n"
    "won't mind you trying to single-handedly melt their infrastructure."
    )
    while True:
        try:
            thread_count = int(prompt("Number of parallel uploads (1-30)", default="5"))
            if 1 <= thread_count <= 30: break
            print_error("Please enter a number between 1 and 30.")
        except ValueError: print_error("Invalid input.")

    console.print()
    console.rule("[dim]Files[/dim]", style="green")
    console.print()

    print_info("Scanning directory for files...")
    files = get_files_in_dir(directory, upload_type, chapter_naming, custom_regex, strip_groups=strip_bracket_groups, custom_renames=custom_renames)
    if not files:
        print_error("No valid .cbz or .zip files found.")
        sys.exit(1)

    if not strip_bracket_groups:
        for f in files:
            f["groups"] = []

    print_files_table(files, upload_type, group_label=selected_group_name)
    _check_missing(files, upload_type)
    _check_duplicates(files, upload_type)

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
        is_group_upload=is_group
    )

    manga_url = f"{BASE_URL}/manga/{manga_id}"
    console.print()
    console.rule("[dim]Summary[/dim]", style="green")
    console.print()

    uploaded_files = [f for f in files if f["filename"] not in final_failed]
    uploaded_bytes = sum(f["size"] for f in uploaded_files)
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
        print_warning(f"Could not fetch metadata: {e}")
        print_info(f"View your manga here: {manga_url}\n")

    console.print()
    input("Press Enter to exit... ")

if __name__ == "__main__":
    try: main()
    except KeyboardInterrupt:
        console.print("\n\n[yellow]⚠️  Script interrupted by user.[/yellow]")
        sys.exit(0)