# MangaDot.net Batch Uploader version 1.1.5 [https://mangadot.net]

"""
==============================================================================
🚀 MANGADOT BATCH UPLOADER - ADVANCED FEATURES & USAGE
==============================================================================

WHAT THIS SCRIPT DOES:
  A multi-threaded batch uploader for .cbz/.zip files to MangaDot.net. 
  It extracts active browser cookies (Chrome, Firefox, Edge, Brave, Opera, Vivaldi) 
  to natively bypass Cloudflare and authenticate sessions. Uploads 
  are handled via the resumable TUS protocol in 5MB chunks.

COMMAND LINE FLAGS:
  python mangadot_basic.py --dry-run   : Scans directory, parses names, and flags missing chapters without uploading.
  python mangadot_basic.py --debug     : Dumps all HTTP traffic to 'api_requests.log' utilizing circular file rotation caps.

ADVANCED NAMING (Custom Regex):
  - Extraction Mode: Use a capture group '()' to extract the chapter title directly from the filename.
  - Rename Mode: Use 'FindPattern -> ReplacePattern' syntax to quickly rename files during the parsing phase.

SMART PROTECTIONS:
  - Auto-Session Recovery: If your token expires mid-batch, the script pauses, allowing you to refresh the browser instead of crashing.
  - Missing Chapter Detection: Automatically scans the file sequence and flags numerical gaps before starting the upload.
  - Ghost Chapter Prevention: Verifies the server successfully mapped the upload to your specific Scanlator Name or Group ID.
  - Failure State Recovery: Saves failed uploads to a timestamped 'failed_manga_[id].txt' log and allows immediate isolated retries.
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
import unicodedata
import atexit
import math
from pathlib import Path

# Low-3 Fix: Move ctypes import to top-level to eliminate frame-by-frame overhead
try:
    import ctypes
except ImportError:
    ctypes = None

# ==============================================================================
# ⚙️  DEPENDENCY CHECK
# ==============================================================================

# Low-1 & Low-4 Fix: Added rich to constraints; removed urllib3 to prevent false dependency blocks
REQUIRED_PACKAGES = {
    "requests":  "2.34.2",
    "rookiepy":  "0.5.6",
    "colorama":  "0.4.6",
    "rich":      "13.7.0"
}

def _parse_version_tuple(version_str):
    match = re.match(r'(\d+(?:\.\d+)*)', str(version_str))
    if not match:
        return (0,)
    return tuple(map(int, match.group(1).split('.')))

def check_dependencies():
    missing_or_outdated = []

    for pkg, min_version in REQUIRED_PACKAGES.items():
        try:
            installed_version = importlib.metadata.version(pkg)
            installed_tuple   = _parse_version_tuple(installed_version)
            min_tuple         = _parse_version_tuple(min_version)
            if installed_tuple < min_tuple:
                missing_or_outdated.append((pkg, min_version, installed_version))
        except importlib.metadata.PackageNotFoundError:
            missing_or_outdated.append((pkg, min_version, None))
        except Exception as exc:
            # Fix-F: Log actual metadata read exception instead of masking it
            logging.debug("Unexpected error while checking package '%s': %s", pkg, exc)
            missing_or_outdated.append((pkg, min_version, None))

    if missing_or_outdated:
        print("=" * 60)
        print(" ⚠️  DEPENDENCY CHECK FAILED")
        print("=" * 60)
        print("\nThe following required packages are missing or outdated:\n")
        for pkg, req_ver, inst_ver in missing_or_outdated:
            if inst_ver is None:
                print(f"  - {pkg}: (Not installed, requires >= {req_ver})")
            else:
                print(f"  - {pkg}: (Installed {inst_ver}, requires >= {req_ver})")
        print("\n" + "=" * 60)
        print(" HOW TO FIX THIS:")
        print("  pip install --upgrade requests rookiepy colorama rich\n")
        return False
    return True

# ---------------------------------------------------------------------------
# Third-Party Framework Imports
# ---------------------------------------------------------------------------
try:
    import requests
    from requests.adapters import HTTPAdapter
    import rookiepy
    from colorama import init as colorama_init, Fore, Style
    colorama_init(autoreset=True)
    
    from rich.console import Console, Group
    from rich.table import Table
    from rich.text import Text
    from rich.live import Live
    from rich.markup import escape as rich_escape
    
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
RETRYABLE_STATUSES   = [429, 500, 502, 503, 504, 524]
FATAL_SIZE_STATUSES  = [413, 415]
MAX_VERIFY_SECONDS   = 60
DEFAULT_CHAPTERS_DIR = "chapters"

# Fix-G: Colors values use colorama constants exclusively (No raw string mixtures)
class Colors:
    HEADER  = Fore.MAGENTA
    OKCYAN  = Fore.CYAN
    OKGREEN = Fore.GREEN
    WARNING = Fore.YELLOW
    FAIL    = Fore.RED
    RESET   = Style.RESET_ALL
    BOLD    = Style.BRIGHT

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
    if machine in ('arm64', 'aarch64'): return 'ARM64' # Fix-D: Support ARM64 architecture string injection
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
            out = subprocess.run([cmd, "--version"], capture_output=True, text=True, timeout=5)
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
            out = subprocess.run([cmd, "--version"], capture_output=True, text=True, timeout=5)
            if out.returncode == 0 and out.stdout:
                m = re.search(r'Chromium[/ ](\d+\.\d+\.\d+(?:\.\d+)?)', out.stdout, re.IGNORECASE)
                if m: return _clean_version(m.group(1))
        except (OSError, subprocess.SubprocessError): continue
    return _fetch_web_version("chrome")

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
    if browser in _UA_CACHE: return _UA_CACHE[browser]
    with _UA_CACHE_LOCK:
        if browser in _UA_CACHE: return _UA_CACHE[browser]
        version = None
        try:
            if sys.platform == 'win32':   version = _read_windows_registry(browser)
            elif sys.platform == 'darwin': version = _read_mac_plist(browser)
            else:                          version = _read_linux_version(browser)
        except Exception: version = None
        if not version and browser in ("chrome", "edge", "firefox"): version = _fetch_web_version(browser)
        chromium_version = _get_chromium_version_for_browser(browser)
        ua = _build_user_agent(browser, version, chromium_version)
        _UA_CACHE[browser] = ua
        return ua

def restore_terminal():
    # Critical-3 Fix: Safe pipe unmounting wrapper prevents secondary crash loops on unhandled exit blocks
    try:
        sys.stdout.write("\033[?7h")
        sys.stdout.flush()
    except Exception: pass

atexit.register(restore_terminal)

# ==============================================================================
# 🐛  DEBUG LOGGING
# ==============================================================================

_SENSITIVE_HEADERS = frozenset({"cookie", "authorization", "x-auth-token", "x-session-token"})

def log_request_response(response, *args, **kwargs):
    req = response.request
    
    # High-3 Fix: Sanitization regex filter scrubs raw ANSI layout tracking metadata completely from drive log traces
    # Fix-9: Broadened pattern from SGR-only (\033\[[0-9;]*m) to all ANSI escape sequences (\033\[[0-9;?]*[A-Za-z])
    # so cursor movement, mode-set codes (e.g. \033[?7h from restore_terminal) are also stripped
    def strip_ansi(text):
        return re.sub(r'\033\[[0-9;?]*[A-Za-z]', '', str(text))

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

def _visual_width(text):
    """Estimate terminal display width, accounting for wide chars and emojis."""
    ansi_stripped = re.sub(r'\033\[[0-9;]*m', '', text)
    chars  = list(ansi_stripped)
    width  = 0
    i      = 0
    n      = len(chars)
    while i < n:
        cp      = ord(chars[i])
        next_cp = ord(chars[i + 1]) if i + 1 < n else 0
        if next_cp == 0xFE0F: # Fix-H: Consume sequence lookaheads correctly
            width += 2
            i     += 2   
            continue
        if cp == 0xFE0E:
            i += 1
            continue
        if cp > 0xFFFF:
            width += 2
            i     += 1
            continue
        eaw = unicodedata.east_asian_width(chars[i])
        width += 2 if eaw in ('F', 'W') else 1
        i     += 1
    return width

class UIRenderer:
    def __init__(self, chapter_keys):
        self.lock              = threading.Lock()
        self.sorted_keys       = chapter_keys
        self.total_chapters    = len(chapter_keys)
        self.completed_chapters = 0   
        self.finished_chapters  = 0   
        self.status = {key: {
            "status": "Queued",
            "progress": 0.0,
            "current": 0,
            "total": 0,
            "speed": 0.0,
            "eta": 0.0,
            "done": False,   
        } for key in chapter_keys}
        self.page_size       = 25
        self.view_start_index = 0
        self.live = None

    def _render(self):
        # Low-3 Fix: Relocated ctypes check to absolute layout frame gate entry context paths
        if ctypes:
            try:
                hwnd = ctypes.windll.kernel32.GetConsoleWindow()
                if hwnd and ctypes.windll.user32.IsIconic(hwnd): return
            except Exception: pass

        # Fix-6: Snapshot all shared mutable state under the lock before any rendering work.
        # _render() is intentionally called outside the lock (Medium-2 Fix) to avoid blocking
        # upload workers, but reading self.status / counters / indices without synchronisation
        # produces torn reads at high thread counts. A short lock window just to copy the data
        # is the correct tradeoff: workers are never blocked during the actual stdout write.
        with self.lock:
            view_start          = self.view_start_index
            finished_count      = self.finished_chapters
            completed_count     = self.completed_chapters
            total               = self.total_chapters
            chapters_to_display = self.sorted_keys[view_start:view_start + self.page_size]
            status_snapshot     = {k: dict(self.status[k]) for k in chapters_to_display}

        overall_pct = (finished_count / total * 100) if total > 0 else 0
        bar_fill    = int(overall_pct / 2.5)
        overall_bar = f"[{'#' * bar_fill:<40}]"

        header_text = Text.from_markup(
            f"[bold cyan]--- Uploading ({completed_count}/{total}) "
            f"{overall_bar} {overall_pct:3.0f}% ---[/bold cyan]"
        )

        table = Table(box=None, show_header=False, padding=(0, 1))
        table.add_column("Filename", width=32, style="white", overflow="ellipsis")
        table.add_column("Status", width=25)
        table.add_column("ProgressBar", width=22)
        table.add_column("Percentage", width=6, justify="right")
        table.add_column("Metrics", style="dim")

        for key in chapters_to_display:
            info        = status_snapshot[key]
            status_text = info["status"]
            progress    = info["progress"]

            if "✅" in status_text: status_color, bar_color = "green", "green"
            elif "❌" in status_text: status_color, bar_color = "red", "red"
            elif "⏸️" in status_text: status_color, bar_color = "yellow", "yellow"
            else:
                status_color = "yellow" if progress > 0 else "white"
                bar_color    = "yellow"

            filled_len = int(progress * 20)
            bar_str    = f"[{'#' * filled_len:<20}]"
            
            padded_status = f"[{status_color}]{rich_escape(status_text)}[/{status_color}]"
            padded_bar    = f"[{bar_color}]{rich_escape(bar_str)}[/{bar_color}]"
            padded_pct    = f"{progress * 100:3.0f}%"

            curr_mb     = info["current"] / 1048576
            tot_mb      = info["total"]   / 1048576
            speed       = info["speed"]
            eta_seconds = info["eta"]

            speed_str = f"{speed / 1048576:>5.2f} MB/s" if speed > 1048576 else f"{speed / 1024:>5.2f} KB/s"

            if eta_seconds > 0:
                m, s = divmod(int(eta_seconds), 60)
                h, m = divmod(m, 60)
                eta_str = f"{h:02d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"
            else: eta_str = "--:--"

            stats_str = ""
            if info["total"] > 0:
                if progress >= 1.0: stats_str = f"({tot_mb:>6.1f} MB)"
                elif progress > 0.0: stats_str = f"({curr_mb:>6.1f}MB / {tot_mb:>6.1f}MB) | {speed_str} | ETA: {eta_str:>5}"

            table.add_row(key, padded_status, padded_bar, padded_pct, stats_str)

        if self.live and self.live.is_started:
            self.live.update(Group(header_text, table))

    def update_chapter_status(self, chap_key, status, progress=None, current=None,
                               total=None, speed=None, eta=None):
        with self.lock:
            if chap_key not in self.status: return
            info = self.status[chap_key]
            was_done = info["done"]

            info["status"] = status
            if progress is not None: info["progress"] = progress
            if current  is not None: info["current"]  = current
            if total    is not None: info["total"]     = total
            if speed    is not None: info["speed"]     = speed
            if eta      is not None: info["eta"]       = eta

            is_success  = "✅" in status
            is_fail     = "❌" in status
            is_terminal = is_success or is_fail

            if is_terminal and not was_done:
                info["done"] = True
                self.finished_chapters += 1        
                if is_success: self.completed_chapters += 1   
                self._check_and_scroll_view()

        # Medium-2 Fix: Dropped mutex acquisition state entirely before rendering stdout writes to eliminate background worker block stalls
        self._render()

    def _check_and_scroll_view(self):
        end_index    = min(self.view_start_index + self.page_size, self.total_chapters)
        visible_keys = self.sorted_keys[self.view_start_index:end_index]
        if all(self.status[k]["done"] for k in visible_keys):
            next_pending = next((i for i, k in enumerate(self.sorted_keys) if not self.status[k]["done"]), -1)
            if next_pending != -1: self.view_start_index = next_pending
            else: self.view_start_index = max(0, self.total_chapters - self.page_size)

    def start(self):
        # Critical-3 Fix: Managed rich.Live tree lifecycle handles window wrapping natively, bypassing primitive manual reset strategies
        self.live = Live(Group(), console=console, refresh_per_second=8, transient=False)
        self.live.start()
        self._render()

    def stop(self):
        if self.live: self.live.stop()

# ==============================================================================
# 🔧 HELPER FUNCTIONS
# ==============================================================================

def print_success(msg): print(f"{Colors.OKGREEN}[+]{Colors.RESET} {msg}")
def print_info(msg):    print(f"{Colors.OKCYAN}[*]{Colors.RESET} {msg}")
def print_warning(msg): print(f"{Colors.WARNING}[!]{Colors.RESET} {msg}")
def print_error(msg):   print(f"{Colors.FAIL}[-]{Colors.RESET} {msg}")

def flush_input_buffer():
    try:
        import msvcrt
        while msvcrt.kbhit(): msvcrt.getch()
    except ImportError:
        # Medium-5 Fix: Explicitly probe standard input stream using isatty() descriptors to avoid execution drops on server shells
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

def natural_sort_key(s):
    return [float(text) if re.match(r'^-?\d+(?:\.\d+)?$', text) else text.lower()
            for text in re.split(r'(-?\d+(?:\.\d+)?)', str(s))]

def encode_tus_metadata(meta_dict):
    pairs = []
    for k, v in meta_dict.items():
        if v is None: continue
        val_str     = json.dumps(v) if isinstance(v, list) else str(v)
        encoded_val = base64.b64encode(val_str.encode('utf-8')).decode('utf-8')
        pairs.append(f"{k} {encoded_val}")
    return ",".join(pairs)

def parse_filename_details(filename, upload_type="chapter", chapter_naming="extract", custom_regex=None):
    name_without_ext = re.sub(r'\.(cbz|zip)$', '', filename, flags=re.IGNORECASE)
    if upload_type == "volume":
        match = re.search(r'(?:volume|vol\.?|v)\s*(\d+(?:\.\d+)?)', name_without_ext, re.IGNORECASE)
    else:
        match = re.search(r'(?:chapter|ch\.?|c)\s*(\d+(?:\.\d+)?)', name_without_ext, re.IGNORECASE)

    num = float(match.group(1)) if match else None
    if num is None:
        match = re.search(r'(\d+(?:\.\d+)?)', name_without_ext)
        num = float(match.group(1)) if match else None

    if num is None: return None, None
    if upload_type == "volume": return num, f"Vol. {num:g}" # Low-2 Fix: Normalized tracking metrics to :g display parity rules

    if chapter_naming == "custom" and custom_regex:
        try:
            if "->" in custom_regex:
                find_pat, replace_pat = custom_regex.split("->", 1)
                title = re.sub(find_pat.strip(), replace_pat.strip(), name_without_ext).strip()
                return num, title
            else:
                c_match = re.search(custom_regex, name_without_ext)
                if c_match:
                    title = c_match.group(1).strip() if c_match.groups() else c_match.group(0).strip()
                    return num, title
                else: print_warning(f"Custom regex did not match '{filename}'. Falling back to Auto-detect.")
        except re.error as e: print_warning(f"Invalid regex '{custom_regex}' ({e}). Falling back to Auto-detect.")

    if chapter_naming == "preset": return num, f"Chapter {num:g}"

    title = None
    parts = name_without_ext.split(' - ', 1)
    if len(parts) > 1:
        split_idx    = name_without_ext.find(' - ')
        part0_has_num = match.start() < split_idx if match else False
        if part0_has_num: title = parts[1].strip()
        else:
            title = parts[0].strip()
            if match:
                remaining = parts[1].replace(match.group(0), '').strip(' -_')
                if remaining: title = f"{title} - {remaining}"
    else:
        if match: title = name_without_ext.replace(match.group(0), '').strip(' -_') or None
    return num, title

def get_files_in_dir(directory, upload_type, chapter_naming="extract", custom_regex=None):
    valid_extensions = ('.cbz', '.zip')
    files_data = []
    for filename in os.listdir(directory):
        if not filename.lower().endswith(valid_extensions): continue
        filepath = os.path.join(directory, filename)
        if not os.path.isfile(filepath): continue
        num, title = parse_filename_details(filename, upload_type, chapter_naming, custom_regex)
        if num is None:
            print_warning(f"Could not detect {upload_type} number from '{filename}'. Skipping.")
            continue
        files_data.append({
            "filepath": filepath, "filename": filename,
            "number": num, "title": title, "size": os.path.getsize(filepath)
        })
    files_data.sort(key=lambda x: x["number"])
    return files_data

def print_files_table(files, upload_type):
    total_size = sum(f["size"] for f in files)
    print_success(f"Found {len(files)} file(s)  ({total_size / 1048576:.1f} MB total)\n")
    col_file = max(max((len(f["filename"]) for f in files), default=8), 8)
    header   = f"  {'Filename':<{col_file}}  {'Number':<10}  {'Title':<30}  {'Size':>10}"
    print(f"{Colors.OKCYAN}{header}{Colors.RESET}")
    print(f"  {'-' * col_file}  {'-' * 10}  {'-' * 30}  {'-' * 10}")
    for f in files:
        print(f"  {f['filename']:<{col_file}}  {str(f['number']):<10}  "
              f"{(f['title'] or '-'):<30}  {f['size'] / 1048576:>9.2f} MB")
    print("")

def _check_missing(files, upload_type):
    numbers     = [f["number"] for f in files]
    int_numbers = []
    for n in numbers:
        try:
            # Fix-5: Guard against nan/inf edge cases from malformed filenames parsed via float()
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

# ==============================================================================
# 🏃 DRY RUN
# ==============================================================================

def run_dry_run():
    print(f"{Colors.HEADER}{Colors.BOLD}")
    print("========================================")
    print("   MangaDot.net Batch Uploader          ")
    print("   *** DRY RUN MODE (no upload) *** ")
    print("========================================")
    print(f"{Colors.RESET}")

    while True:
        prompt_txt = "Enter the directory path containing your .cbz/.zip files"
        directory  = prompt(prompt_txt, default=DEFAULT_CHAPTERS_DIR if os.path.isdir(DEFAULT_CHAPTERS_DIR) else None)
        directory  = directory.strip().rstrip('\\').strip('"\'')
        if os.path.isdir(directory): break
        print_error("Directory does not exist. Please try again.")
    flush_input_buffer()

    upload_type_choice = prompt("Upload type? (1) Chapter  (2) Volume", default="1")
    upload_type        = "volume" if upload_type_choice == "2" else "chapter"

    chapter_naming = "extract"
    custom_regex   = None
    if upload_type == "chapter":
        naming_choice = prompt("Chapter naming? (1) Auto-detect  (2) Force 'Chapter X'  (3) Custom regex", default="2")
        if naming_choice == "2": chapter_naming = "preset"
        elif naming_choice == "3":
            chapter_naming = "custom"
            print_info("Regex Tip: Use a capture group () to extract a title, or 'Find -> Replace' to rename.")
            custom_regex = prompt("Enter your regex pattern")

    print("\n" + "-" * 40 + "\n")
    print_info("Scanning directory for files...")
    files = get_files_in_dir(directory, upload_type, chapter_naming, custom_regex)
    if not files:
        print_error("No valid .cbz or .zip files found.")
        sys.exit(1)

    print_files_table(files, upload_type)
    _check_missing(files, upload_type)

    print(f"{Colors.OKGREEN}[Dry run complete — no files were uploaded.]{Colors.RESET}")
    input(f"\n{Colors.WARNING}Press Enter to exit...{Colors.RESET}")
    sys.exit(0)

# ==============================================================================
# 🔑 AUTH & API HELPERS
# ==============================================================================

def validate_session(session):
    try:
        res = session.get(f"{BASE_URL}/api/profile", timeout=(10, 30))
        if res.status_code == 200:
            data = res.json()
            if "profile" in data and "email" in data["profile"]: return data['profile']['email']
    except Exception: pass
    return None

def search_manga(query, session):
    try:
        res = session.get(f"{BASE_URL}/search.data?search={query}", timeout=(10, 30))
        if res.status_code != 200: return []
        arr = res.json()
    except Exception: return []

    mangas = []
    # Medium-3 Fix: Explicit structure shape validation stops empty lists from throwing silent crashes
    if not isinstance(arr, list): return []
    
    for item in arr:
        if not isinstance(item, dict): continue
        decoded = {}
        for k, v in item.items():
            if k.startswith('_') and k[1:].isdigit():
                key_idx = int(k[1:])
                if key_idx < len(arr) and isinstance(v, int) and v < len(arr):
                    key_str = arr[key_idx]
                    val     = arr[v]
                    decoded[key_str] = val
            else: decoded[k] = v
        if "id" in decoded and "title" in decoded and isinstance(decoded["id"], int): mangas.append(decoded)
    seen = set()
    return [m for m in mangas if not (m["id"] in seen or seen.add(m["id"]))]

def search_groups(query, session):
    try:
        res = session.get(f"{BASE_URL}/api/groups?q={query}&limit=25", timeout=(10, 30))
        if res.status_code != 200: return []
        return res.json().get("groups", [])
    except Exception: return []

class SessionExpiredError(Exception): pass

def authenticate_session(req_session, current_browser="firefox"):
    supported_browsers = {
        "1": ("chrome",  rookiepy.chrome),
        "2": ("firefox", rookiepy.firefox),
        "3": ("brave",   rookiepy.brave),
        "4": ("edge",    rookiepy.edge),
        "5": ("opera",   rookiepy.opera),
        "6": ("vivaldi", rookiepy.vivaldi),
    }
    while True:
        print_info(f"Attempting to extract cookies from {current_browser.title()}...")
        req_session.headers.update({"User-Agent": get_dynamic_user_agent(current_browser)})
        extracted_successfully = False
        try:
            req_session.cookies.clear()
            get_cookies_fn = next((fn for name, fn in supported_browsers.values() if name == current_browser), None)
            if get_cookies_fn:
                browser_cookies = get_cookies_fn(domains=["mangadot.net", ".mangadot.net"])
                if browser_cookies:
                    for cookie in browser_cookies: req_session.cookies.set(cookie['name'], cookie['value'], domain=cookie['domain'])
                    extracted_successfully = True
                else: print_warning(f"No Mangadot.net cookies found in {current_browser.title()}.")
            else: print_error("Internal Error: browser mapping not found.")
        except Exception as e:
            print_warning(f"Failed to extract cookies from {current_browser.title()}: {e}")
            print_warning(f"Make sure {current_browser.title()} is fully CLOSED before running this script.")
        if extracted_successfully:
            print_info("Validating session with Mangadot...")
            email = validate_session(req_session)
            if email:
                print_success(f"Successfully authenticated as: {email}")
                return current_browser
            else:
                print_warning("Cookies extracted but session validation failed (unauthorized or expired).")
                print_warning("Ensure you have passed the Cloudflare check and are logged in on your browser.")
        print_info("\nAuthentication failed. Please select an option to retry:")
        for key, (name, _) in supported_browsers.items():
            active_marker = f" {Colors.OKCYAN}(active){Colors.RESET}" if name == current_browser else ""
            print(f"  [{key}] {name.title()}{active_marker}")
        print("  [q] Quit script")
        choice = prompt("Select an option", default="2").lower()
        if choice == 'q':
            print_info("Exiting script.")
            sys.exit(0)
        elif choice in supported_browsers: current_browser = supported_browsers[choice][0]
        else:
            print_error("Invalid selection. Defaulting back to Firefox.")
            current_browser = "firefox"

# ==============================================================================
# 📤 TUS UPLOAD WORKER
# ==============================================================================

def upload_file_tus_worker(session, renderer, file_info, manga_id, group_ids,
                            upload_type, batch_id, language, scanlator_name, abort_event):
    filename = file_info["filename"]
    filepath = file_info["filepath"]
    size     = file_info["size"]

    # Critical-1 Fix: Isolated RequestsCookieJar assigned to thread allocations blocks race conditions cleanly
    worker_session = requests.Session()
    worker_session.headers.update(session.headers)
    worker_session.cookies.update(session.cookies)
    if session.hooks.get('response'): worker_session.hooks['response'] = session.hooks['response']
    worker_session.mount("https://", session.adapters.get("https://"))
    worker_session.mount("http://",  session.adapters.get("http://"))

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
    if scanlator_name:            tus_metadata["scanlator_name"] = scanlator_name

    encoded_metadata = encode_tus_metadata(tus_metadata)
    headers = {
        "Tus-Resumable":   "1.0.0",
        "Upload-Length":   str(size),
        "Upload-Metadata": encoded_metadata,
    }

    for attempt in range(MAX_RETRIES):
        if abort_event.is_set(): return {"key": filename, "success": False, "error": "Aborted"}
        try:
            renderer.update_chapter_status(filename, "Creating upload...", 0.0)
            res = worker_session.post(TUS_ENDPOINT, headers=headers, timeout=(10, 30))
            if res.status_code in (401, 403): raise SessionExpiredError()
            if res.status_code == 409:
                renderer.update_chapter_status(filename, "✅ Already Exists", 1.0, current=size, total=size)
                return {"key": filename, "success": True}
            res.raise_for_status()
            upload_location = res.headers.get("Location")
            if not upload_location: raise ValueError("No Location header in TUS response")
            break
        except SessionExpiredError: raise
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                renderer.update_chapter_status(filename, "Create Err... Retrying", 0.0)
                time.sleep(RETRY_DELAY)
            else: return {"key": filename, "success": False, "error": f"Init failed: {str(e)[:30]}"}

    chunk_size = 5 * 1024 * 1024
    offset     = 0
    last_speed = 0.0
    eta        = 0.0

    try:
        with open(filepath, 'rb') as f:
            while offset < size:
                if abort_event.is_set(): return {"key": filename, "success": False, "error": "Aborted"}
                
                # High-2 Fix: Prevent file pointer drift without running O(n²) redundant file seek loops
                if f.tell() != offset:
                    f.seek(offset)
                    
                chunk = f.read(chunk_size)
                if not chunk: break

                patch_headers = {
                    "Tus-Resumable": "1.0.0",
                    "Upload-Offset": str(offset),
                    "Content-Type":  "application/offset+octet-stream",
                }

                chunk_done = False
                for patch_attempt in range(MAX_RETRIES):
                    try:
                        renderer.update_chapter_status(
                            filename, "Uploading...", offset / size,
                            current=offset, total=size, speed=last_speed, eta=eta
                        )
                        t0        = time.time()
                        patch_res = worker_session.patch(upload_location, headers=patch_headers, data=chunk, timeout=60)
                        elapsed   = time.time() - t0

                        if patch_res.status_code in (401, 403): raise SessionExpiredError()
                        elif patch_res.status_code == 204:
                            last_speed = len(chunk) / elapsed if elapsed > 0.001 else 0
                            offset    += len(chunk)
                            eta        = (size - offset) / last_speed if last_speed > 0 else 0
                            chunk_done = True
                            break
                        elif patch_res.status_code in FATAL_SIZE_STATUSES:
                            return {"key": filename, "success": False, "error": f"HTTP {patch_res.status_code} (File Too Large/Bad Type)"}
                        elif patch_res.status_code in RETRYABLE_STATUSES:
                            if patch_attempt < MAX_RETRIES - 1:
                                renderer.update_chapter_status(filename, f"Retrying chunk... ({patch_attempt + 1})", offset / size, current=offset, total=size)
                                time.sleep(RETRY_DELAY)
                            else: return {"key": filename, "success": False, "error": f"HTTP {patch_res.status_code} (Max Retries)"}
                        else: return {"key": filename, "success": False, "error": f"HTTP {patch_res.status_code}"}
                    except SessionExpiredError: raise
                    except Exception as e:
                        if patch_attempt < MAX_RETRIES - 1:
                            renderer.update_chapter_status(filename, f"Net Err, Retrying... ({patch_attempt + 1})", offset / size, current=offset, total=size)
                            time.sleep(RETRY_DELAY)
                        else: return {"key": filename, "success": False, "error": f"Network Err: {str(e)[:30]}"}
                if not chunk_done: return {"key": filename, "success": False, "error": "Chunk upload failed"}
    except SessionExpiredError: raise
    except Exception as e: return {"key": filename, "success": False, "error": str(e)[:30]}

    base_check_url = f"{BASE_URL}/api/manga/{manga_id}/volumes" if upload_type == "volume" else f"{BASE_URL}/api/manga/{manga_id}/chapters/list"
    found        = False
    verify_start = time.time()

    while not found:
        if abort_event.is_set(): return {"key": filename, "success": False, "error": "Aborted"}
        elapsed_verify = int(time.time() - verify_start)
        if elapsed_verify >= MAX_VERIFY_SECONDS: return {"key": filename, "success": False, "error": "Verification timeout reached."}
        renderer.update_chapter_status(filename, f"Verifying... ({elapsed_verify}s)", 1.0, current=size, total=size, speed=0.0, eta=0.0)
        time.sleep(RETRY_DELAY)
        try:
            fetch_check = worker_session.get(f"{base_check_url}?_t={int(time.time())}", timeout=10)
            
            # Critical-2 Fix: Prioritize verification auth validation states to break out of routine hangs
            if fetch_check.status_code in (401, 403): raise SessionExpiredError()
            if fetch_check.status_code != 200: continue
            
            items_list = fetch_check.json()
            if isinstance(items_list, dict): items_list = items_list.get("volumes", items_list.get("chapters", []))
            if not isinstance(items_list, list): continue
            
            for item in items_list:
                try:
                    # Medium-1 Fix: Replaced volatile raw comparison operators with math.isclose absolute delta tolerance structures
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
                    
                    if group_ids and any(gid in item_group_ids for gid in group_ids): found = True; break
                    
                    # Medium-4 Fix: Add verification fallback paths when processing individual scanlator credentials without active group IDs
                    # Fix-3: Removed erroneous unconditional else-branch that set found=True even when scanlator name did NOT match,
                    # defeating Ghost Chapter Prevention for standalone scanlators entirely
                    if not group_ids and scanlator_name:
                        if item.get("scanlator_name") == scanlator_name or item.get("scanlator") == scanlator_name:
                            found = True; break
        except SessionExpiredError: raise
        except Exception: continue

    renderer.update_chapter_status(filename, "✅ Uploaded", 1.0, current=size, total=size, speed=0.0, eta=0.0)
    return {"key": filename, "success": True}

# ==============================================================================
# 🔄 PROCESS UPLOADS
# ==============================================================================

def process_uploads(files_to_upload, req_session, manga_id, group_ids,
                    upload_type, language, scanlator_name, thread_count):
    chunks    = [files_to_upload[i:i + MAX_BATCH_SIZE] for i in range(0, len(files_to_upload), MAX_BATCH_SIZE)]
    file_keys = [f["filename"] for f in files_to_upload]
    renderer  = UIRenderer(file_keys)
    renderer.start()

    failed_chapters  = []
    session_expired  = False
    
    # High-1 Fix: Instantiated Event objects safely inside orchestrator context lifetimes to prevent retry state leakage
    abort_event      = threading.Event()

    for chunk in chunks:
        if session_expired:
            for f in chunk:
                if f["filename"] not in failed_chapters:
                    renderer.update_chapter_status(f["filename"], "⏸️ Paused (Session)", 0.0)
                    failed_chapters.append(f["filename"])
            continue

        chapters_payload = [{"chapter_number": f["number"] if upload_type == "chapter" else 0, "volume_number": f["number"] if upload_type == "volume" else None, "chapter_title": f["title"]} for f in chunk]
        init_payload = {"manga_id": manga_id, "language": language, "group_ids": group_ids, "type": upload_type, "scanlator_name": scanlator_name, "chapters": chapters_payload}
        batch_id = None
        try:
            # High-4 Fix: Split generic timeout metrics down to granular connect/read components to avoid UI freeze intervals
            res = req_session.post(BATCH_INIT_ENDPOINT, json=init_payload, timeout=(10, 45))
            if res.status_code in (401, 403):
                session_expired = True
                abort_event.set()
                for f in chunk:
                    renderer.update_chapter_status(f["filename"], "⏸️ Paused (Auth)", 0.0)
                    failed_chapters.append(f["filename"])
                continue
            res.raise_for_status()
            batch_data = res.json()
            if not batch_data.get("success"): raise Exception(str(batch_data))
            batch_id = batch_data["batch_id"]
        except SessionExpiredError:
            # Fix-4: Explicit SessionExpiredError catch before broad Exception so session recovery
            # is never silently swallowed and misreported as a generic batch init failure
            session_expired = True
            abort_event.set()
            for f in chunk:
                renderer.update_chapter_status(f["filename"], "⏸️ Paused (Auth)", 0.0)
                if f["filename"] not in failed_chapters:
                    failed_chapters.append(f["filename"])
            continue
        except Exception:
            for f in chunk:
                renderer.update_chapter_status(f["filename"], "❌ Batch Init Failed", 1.0)
                failed_chapters.append(f["filename"])
            continue

        with concurrent.futures.ThreadPoolExecutor(max_workers=thread_count) as executor:
            futures = {executor.submit(upload_file_tus_worker, req_session, renderer, f, manga_id, group_ids, upload_type, batch_id, language, scanlator_name, abort_event): f for f in chunk}
            for future in concurrent.futures.as_completed(futures):
                f_info = futures[future]
                try:
                    result = future.result()
                    if not result['success']:
                        renderer.update_chapter_status(result['key'], f"❌ {result['error']}", 1.0)
                        if result['key'] not in failed_chapters: failed_chapters.append(result['key'])
                except SessionExpiredError:
                    session_expired = True
                    abort_event.set()
                    renderer.update_chapter_status(f_info["filename"], "⏸️ Paused (Auth)", 1.0)
                    if f_info["filename"] not in failed_chapters: failed_chapters.append(f_info["filename"])

        if batch_id and not session_expired:
            for comp_attempt in range(MAX_RETRIES):
                try:
                    comp_res = req_session.post(f"{BASE_URL}/api/uploads/batch/{batch_id}/complete", timeout=(10, 30))
                    if comp_res.status_code in (401, 403):
                        session_expired = True
                        break
                    comp_res.raise_for_status()
                    break  
                except Exception as e:
                    if comp_attempt < MAX_RETRIES - 1: time.sleep(RETRY_DELAY)
                    else: logging.warning(f"Batch {batch_id} complete call failed after {MAX_RETRIES} attempts: {e}")

    renderer.stop()
    return failed_chapters, session_expired

# ==============================================================================
# 🚀 MAIN
# ==============================================================================

def build_arg_parser():
    parser = argparse.ArgumentParser(description="MangaDot Batch Uploader", formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Scan and parse chapter names without uploading.")
    parser.add_argument("--debug", action="store_true", help="Dump all HTTP traffic to api_requests.log.")
    parser.add_argument("--verify-timeout", type=int, default=MAX_VERIFY_SECONDS, metavar="SECONDS", help=f"How long to wait for validation confirmation (default: {MAX_VERIFY_SECONDS}s).")
    return parser

def main():
    global MAX_VERIFY_SECONDS
    if not check_dependencies(): sys.exit(1)
    args = build_arg_parser().parse_args()
    MAX_VERIFY_SECONDS = args.verify_timeout

    if args.dry_run: run_dry_run()

    if args.debug:
        # Low-5 Fix: Dropped unbound basic configuration logs to integrate sizing max caps via RotatingFileHandlers
        log_handler = logging.handlers.RotatingFileHandler(
            'api_requests.log', maxBytes=10*1024*1024, backupCount=3, encoding='utf-8'
        )
        logging.basicConfig(
            level=logging.DEBUG,
            format='%(asctime)s [%(levelname)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
            handlers=[log_handler]
        )
        print(f"{Colors.WARNING}[DEBUG] HTTP traffic logging active with circular rotation caps.{Colors.RESET}")

    print(f"{Colors.HEADER}{Colors.BOLD}")
    print("========================================")
    print("      MangaDot.net Batch Uploader       ")
    print("========================================")
    print(f"{Colors.RESET}")

    req_session = requests.Session()
    if args.debug: req_session.hooks['response'].append(log_request_response)
    req_session.headers.update({"Origin": BASE_URL, "Referer": f"{BASE_URL}/"})
    no_retry_adapter = HTTPAdapter(max_retries=0)
    req_session.mount("https://", no_retry_adapter)
    req_session.mount("http://",  no_retry_adapter)

    current_browser = authenticate_session(req_session, "firefox")
    print("\n" + "-" * 40 + "\n")

    while True:
        prompt_txt = "Enter the directory path containing your .cbz/.zip files"
        directory  = prompt(prompt_txt, default=DEFAULT_CHAPTERS_DIR if os.path.isdir(DEFAULT_CHAPTERS_DIR) else None)
        directory  = directory.strip().rstrip('\\').strip('"\'')
        if os.path.isdir(directory): break
        print_error("Directory does not exist. Please try again.")
    flush_input_buffer()

    guessed_title = Path(directory).name if directory else ""

    manga_id = None
    while not manga_id:
        m_input = prompt("Search Manga by Title, or enter ID directly", default=guessed_title)
        if m_input.isdigit():
            manga_id = int(m_input)
            break
        print_info(f"Searching MangaDot for: '{m_input}'...")
        results = search_manga(m_input, req_session)
        if not results:
            print_warning("No matching manga found. Try another search query.")
            guessed_title = None
            continue
        for i, m in enumerate(results): print(f"  [{i + 1}] {m['title']} (ID: {m['id']})")
        sel = prompt(f"Select 1-{len(results)} (or 's' to search again)", default="1")
        if sel.lower() == 's':
            guessed_title = None
            continue
        try:
            sel_idx  = int(sel) - 1
            manga_id = results[sel_idx]['id']
            print_success(f"Selected: {results[sel_idx]['title']} (ID: {manga_id})")
        except (ValueError, IndexError): print_error("Invalid selection.")

    req_session.headers.update({"Referer": f"{BASE_URL}/manga/{manga_id}/upload"})

    upload_type_choice = prompt("Upload type? (1) Chapter  (2) Volume", default="1")
    upload_type        = "volume" if upload_type_choice == "2" else "chapter"

    chapter_naming = "extract"
    custom_regex   = None
    if upload_type == "chapter":
        naming_choice = prompt("Chapter naming? (1) Auto-detect  (2) Force 'Chapter X'  (3) Custom regex", default="2")
        if naming_choice == "2": chapter_naming = "preset"
        elif naming_choice == "3":
            chapter_naming = "custom"
            print_info("Regex Tip: Use a capture group () to extract a title, or 'Find -> Replace' to rename.")
            custom_regex = prompt("Enter your regex pattern")

    language = prompt("Language code", default="en")

    is_group     = prompt("Upload as a Group? (y/n)", default="y").lower().startswith('y')
    group_ids    = []
    scanlator_name = None

    if is_group:
        while not group_ids:
            g_input = prompt("Search Group by Name, or enter ID directly")
            if g_input.isdigit():
                group_ids = [int(g_input)]
                break
            results = search_groups(g_input, req_session)
            if not results:
                print_warning("No groups found. Try another search.")
                continue
            for i, g in enumerate(results): print(f"  [{i + 1}] {g['name']} (ID: {g['id']})")
            sel = prompt(f"Select 1-{len(results)} (or 's' to search again)", default="1")
            if sel.lower() == 's': continue
            try:
                sel_idx   = int(sel) - 1
                group_ids = [results[sel_idx]['id']]
                print_success(f"Selected Group: {results[sel_idx]['name']} (ID: {group_ids[0]})")
            except (ValueError, IndexError): print_error("Invalid selection.")
    else: scanlator_name = prompt("Enter your individual Scanlator Name")

    while True:
        try:
            thread_count = int(prompt("Number of parallel uploads (1-10)", default="3"))
            if 1 <= thread_count <= 10: break
            print_error("Please enter a number between 1 and 10.")
        except ValueError: print_error("Invalid input.")

    print("\n" + "-" * 40 + "\n")
    print_info("Scanning directory for files...")
    files = get_files_in_dir(directory, upload_type, chapter_naming, custom_regex)
    if not files:
        print_error("No valid .cbz or .zip files found.")
        sys.exit(1)

    print_files_table(files, upload_type)
    _check_missing(files, upload_type)

    confirm = prompt("Proceed with upload? (y/n)", default="y").lower()
    if not confirm.startswith('y'):
        print_info("Upload aborted by user.")
        sys.exit(0)

    current_files_to_upload = files

    while True:
        failed_chapters, session_expired = process_uploads(
            current_files_to_upload, req_session, manga_id, group_ids, upload_type, language, scanlator_name, thread_count
        )
        if session_expired:
            print(f"\n{Colors.FAIL}⚠️  UPLOAD PAUSED: Session expired or unauthorized.{Colors.RESET}")
            print(f"{Colors.WARNING}Refresh your login/Cloudflare check in your browser, then return here.{Colors.RESET}")
            time.sleep(1.5)
            flush_input_buffer()
            input(f"{Colors.OKCYAN}Press Enter to re-authenticate and resume...{Colors.RESET}")
            current_browser = authenticate_session(req_session, current_browser)
            current_files_to_upload = [f for f in current_files_to_upload if f["filename"] in failed_chapters]
            print_info(f"\nResuming upload for {len(current_files_to_upload)} failed/paused chapter(s)...")
            continue

        print(f"{Colors.OKCYAN}--- 🎉 All operations complete. ---{Colors.RESET}")
        if not failed_chapters:
            print(f"{Colors.OKGREEN}✅ All chapters were processed successfully!{Colors.RESET}")
            break

        print(f"{Colors.FAIL}⚠️  {len(failed_chapters)} chapter(s) failed after all retries.{Colors.RESET}")
        safe_id         = str(manga_id) if manga_id else "unknown"
        failed_log_name = f"failed_manga_{safe_id}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        try:
            with open(failed_log_name, "w", encoding="utf-8") as f:
                for chap in sorted(failed_chapters, key=natural_sort_key): f.write(f"{chap}\n")
            print(f"Failed list saved to {Colors.OKCYAN}`{failed_log_name}`{Colors.RESET}.")
        except Exception as e:
            print(f"{Colors.FAIL}Could not write `{failed_log_name}`: {e}{Colors.RESET}")
            break

        retry_choice = prompt("Retry ONLY the failed chapters? (y/n)", default="y").lower()
        if not retry_choice.startswith('y'): break
        current_files_to_upload = [f for f in current_files_to_upload if f["filename"] in failed_chapters]
        print_info(f"\nRetrying {len(current_files_to_upload)} failed chapter(s)...")

    manga_url = f"{BASE_URL}/manga/{manga_id}"
    print(f"\n{Colors.OKCYAN}[*]{Colors.RESET} Fetching upload confirmation details...")
    try:
        api_res = req_session.get(f"{BASE_URL}/api/manga/{manga_id}", timeout=15)
        if api_res.status_code == 200:
            manga_data  = api_res.json().get("manga", {})
            title       = manga_data.get("title", "Unknown Title")
            alt_titles  = manga_data.get("alt_titles", [])
            status      = manga_data.get("status", "N/A")
            description = manga_data.get("description", "")
            photo       = manga_data.get("photo", "")
            clean_desc  = (re.sub(r'<[^>]*>', '', description)[:150] + "...") if description else "N/A"

            print("\n" + "=" * 50)
            print(f"{Colors.HEADER}{Colors.BOLD}🎉 UPLOAD CONFIRMED ON MANGADOT{Colors.RESET}")
            print("=" * 50)
            print(f"  {Colors.BOLD}Title:{Colors.RESET}       {title}")
            if alt_titles: print(f"  {Colors.BOLD}Alt Title:{Colors.RESET}   {alt_titles[0] if isinstance(alt_titles, list) else alt_titles}")
            print(f"  {Colors.BOLD}Status:{Colors.RESET}      {status.upper()}")
            print(f"  {Colors.BOLD}Synopsis:{Colors.RESET}    {clean_desc}")
            if photo:
                cover_url = photo if photo.startswith("http") else f"{BASE_URL}{photo}"
                print(f"  {Colors.BOLD}Cover Art:{Colors.RESET}   {cover_url}")
            print("-" * 50)
            print(f"  {Colors.OKGREEN}{Colors.BOLD}Direct Link:{Colors.RESET} {manga_url}")
            print("=" * 50 + "\n")
        else: print(f"\n{Colors.OKCYAN}[*]{Colors.RESET} View your manga here: {manga_url}\n")
    except Exception as e:
        print_warning(f"Could not fetch metadata: {e}")
        print(f"\n{Colors.OKCYAN}[*]{Colors.RESET} View your manga here: {manga_url}\n")

    input(f"{Colors.WARNING}Press Enter to exit...{Colors.RESET}")

if __name__ == "__main__":
    try: main()
    except KeyboardInterrupt:
        print("\n\n" + Colors.WARNING + "[!] Script interrupted by user." + Colors.RESET)
        sys.exit(0)