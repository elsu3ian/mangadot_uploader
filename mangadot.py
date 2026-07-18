# MangaDot.net Batch Uploader version 1.3.0 [https://mangadot.net]
# [Interactive UI, Synchronized Color Theme & High-Fidelity Inline Art Update applied]
# [v1.2.4: Audit fix pass — custom regex, ghost-chapter verification gap, volume
#  titles, stale-PID kill safety, connection pooling, interruptible retries,
#  natural sort negatives, verify-timeout validation, dead import, path norm]
# [v1.3.0: Auto-detect title now always shows a picker with dynamically-built,
#  labeled candidates (full/without-episode-label/without-season/bare/minimal),
#  memoized per detected filename "shape" across the batch. Core architecture
#  patch: pagination for Ghost Chapter verifier, dynamic decimal interpolation,
#  TUS HEAD fallback, natural sort hyphen fix, and thread pool thrashing eliminated]

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
import sqlite3
from collections import deque, Counter
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
    a = _parse_version_tuple(installed)
    b = _parse_version_tuple(required)
    length = max(len(a), len(b))
    a += (0,) * (length - len(a))
    b += (0,) * (length - len(b))
    return a < b

def _in_virtualenv():
    """True if running inside a venv/virtualenv/conda env, where auto-installing
    packages only affects this isolated environment rather than the user's
    system-wide Python."""
    return (
        hasattr(sys, "real_prefix")
        or sys.base_prefix != sys.prefix
        or bool(os.environ.get("CONDA_DEFAULT_ENV"))
    )

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
            # Malformed package metadata (rare, but importlib.metadata can choke
            # on broken/partial installs) - treat it like "missing" so the user
            # gets a chance to reinstall it cleanly, instead of silently skipping.
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

        if not _in_virtualenv():
            print("\n  ℹ️   You're not inside a virtual environment - installing now would")
            print("      affect your system-wide Python packages.")
            print(f"\n      requirements.txt is included next to this script. You can instead run:")
            print(f"        python -m venv .venv")
            print(f"        .venv\\Scripts\\activate      (Windows)   OR   source .venv/bin/activate  (macOS/Linux)")
            print(f"        pip install -r requirements.txt\n")
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
            print(f"    Try running this manually:")
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
_VERIFY_CONCURRENCY  = 3
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

def _default_cdp_profile_dir():
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser(r"~\AppData\Local")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "MangaDotUploader", "cdp_profile")

CDP_PROFILE_ROOT = _default_cdp_profile_dir()
CDP_STARTUP_WAIT = 20  

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
        # ValueError covers plistlib's InvalidFileException (a ValueError subclass)
        # for a corrupt/unexpected Info.plist.
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

def get_dynamic_user_agent(browser):
    with _UA_CACHE_LOCK:
        if browser in _UA_CACHE: return _UA_CACHE[browser]
        config = load_config()
        cached_uas = config.get("cached_user_agents", {})
        if browser in cached_uas:
            _UA_CACHE[browser] = cached_uas[browser]
            return cached_uas[browser]

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
            cached_uas[browser] = ua
            fresh_config["cached_user_agents"] = cached_uas
            save_config(fresh_config)
        except OSError as e:
            # Best-effort cache write; a failure here just means we re-detect
            # the UA next run instead of using the cache. Not fatal.
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
    """Replace the current user's home directory (and thus their OS username)
    with a placeholder before showing exception text on-screen or in logs.
    Many rookiepy/sqlite3/file-I/O exceptions embed the full cookie DB path,
    which on Windows/macOS/Linux typically includes the OS username."""
    text = str(text)
    if _HOME_DIR_STR and _HOME_DIR_STR in text:
        text = text.replace(_HOME_DIR_STR, "~")
    return text

def _redact_proxy_url(proxy_url):
    """Mask any user:pass@ credentials embedded in a proxy URL before it's
    ever printed to the console (or would end up in a debug log/screenshot)."""
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

            self.live.refresh()

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

def parse_number_ranges(text, valid_numbers=None):
    """Parse flexible range input like '103-108,110,115-117' into a set of numbers.
    Accepts ints or floats (chapter numbers can be e.g. 100.5 for extras).
    If valid_numbers is given (an iterable of the numbers actually present),
    results are filtered to that set and unmatched tokens are reported.
    Returns (matched_set, unmatched_tokens)."""
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
    """Prompt for a range string against a known set of valid numbers, retrying on
    bad/empty input. If allow_all is True, blank input returns None (meaning 'all')."""
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
    """Ask the chapter naming format question. Returns
    (chapter_naming, custom_regex, custom_renames, advanced_strip_groups)."""
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
    """Return a Latin-normalized copy of text for regex matching purposes only.
    This is a 1-to-1 character substitution (no insertions/deletions), so
    character positions/indices stay identical to the original string -
    match spans found against the normalized text are valid against the
    original text too."""
    return text.translate(_HOMOGLYPH_TABLE)

def strip_leading_zeros_in_title(text):
    """Strip unnecessary leading zeros from standalone numbers in title text.
    e.g. 'Episode 001' -> 'Episode 1', 'Ch. 113 - Stalker (01)' -> 'Ch. 113 - Stalker (1)'.
    Uses word boundaries so it won't touch things like 'S002' (no boundary between S and 0)."""
    return re.sub(r'\b0+(\d+)\b', r'\1', text)

def compile_removal_pattern(pattern_input):
    """Compile a user-entered word/phrase into a regex pattern for removal.
    Plain text (e.g. '(Official)') is treated literally so parens/brackets the user
    typed as ordinary text don't get interpreted as regex groups. Only treated as a
    real regex if it contains metacharacters unlikely to appear as plain text:
    \\d \\w \\s * + ? | ^ $ {n,m} etc."""
    looks_like_regex = bool(re.search(r'\\[dwsSDWbB]|[*+?^$|]|\{\d*,?\d*\}', pattern_input))
    if looks_like_regex:
        try:
            re.compile(pattern_input)
            return pattern_input
        except re.error:
            return re.escape(pattern_input)
    return re.escape(pattern_input)

def apply_removal_pattern(pattern, text):
    """Apply a compiled removal pattern to text, cleaning up leftover empty
    parens/brackets and extra whitespace. Returns None if the result would be empty."""
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
        num_pattern = r'(?i)(?:(?:\b|_)?(?:chapter|ch|episode|ep)|(?:\b|_)c)[\.\-_\s]*(\d+(?:\.\d+)?)'

    matches = list(re.finditer(num_pattern, normalize_homoglyphs(name_clean)))
    
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
        digits_str = matches[0].group(1)
        has_explicit_label = bool(re.search(r'(?i)chapter|ch\b|episode|ep\b', matched_str))
        # The file's own auto-generated sequence prefix always looks like a bare
        # 'ch' immediately followed by digits with no separator (e.g. 'ch1000',
        # 'ch0057') - lowercase, no dot/space, and not the word 'chapter'. Real
        # chapter/episode labels almost always have a separator ('Ch. 001',
        # 'Chapter 11') or use 'episode'/'ep'. This is more reliable than
        # checking for zero-padding, which breaks once the sequence number
        # reaches 4+ digits without a leading zero (e.g. 'ch1000').
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
        # Compute the drift (file_index - episode_label) for every conflict so the
        # user can see whether this is one clean, consistent reset (safe to resolve
        # with a single choice) or several different drift amounts (which a single
        # Continuous/Trust-Labels choice can't correctly handle for the whole batch).
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
                # No next labeled item (trailing run at the end of the list, or
                # the file list started with unlabeled items) - leave enough
                # room for the whole block to count up sequentially rather than
                # collapsing everything into a 1.0-wide gap.
                next_val = prev_val + n + 1.0

            gap = next_val - prev_val

            if n == 1:
                block[0]["number"] = round(prev_val + gap / 2, 6)
            elif gap >= n + 1:
                # There's enough room to continue sequential whole numbers
                # (prev_val + 1, prev_val + 2, ...) without reaching next_val.
                # This is the right treatment for a long run of unlabeled files
                # that are really just sequential chapters without an explicit
                # "Chapter N" label in the filename - not a small cluster of
                # specials squeezed between two labeled chapters, which is what
                # the decimal (.1/.2/.3...) scheme below is for.
                for k, item in enumerate(block):
                    item["number"] = round(prev_val + (k + 1), 6)
            else:
                # Multiple unlabeled items in this gap: number them prev.1, prev.2, prev.3...
                # in file order, but only as many decimal places as needed to fit
                # strictly within the available gap without colliding with next_val.
                pad = 2 if n > 9 else 1
                base = int(prev_val)
                step = 1 / (10 ** pad)
                for k, item in enumerate(block):
                    frac = (k + 1) * step
                    proposed = round(base + frac, pad + 4)
                    # Guard against overshooting into or past the next real label
                    # (can happen if prev_val's fractional part is already close
                    # to next_val, e.g. prev=9.9, next=10.0).
                    if proposed >= next_val:
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
                text = re.sub(rf'(?i)(Chapter|Episode)\s+{old_num:g}\b', rf'\g<1> {new_num:g}', text)
                updated_candidates.append((label, text))
            item["candidates"] = updated_candidates

def get_files_in_dir(directory, upload_type, chapter_naming="extract", custom_regex=None, strip_groups=False, validate=True, custom_renames=None, select_subset=False):
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

        # A range-scoped decision for this shape takes priority over the whole-shape cache,
        # since it was made specifically for this file's number.
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

def review_and_edit_titles(files):
    """Post-scan review pass: let the user apply a global find/replace across
    all titles (with a live preview before committing), redo the title for
    a specific group of files, or override the computed number for a
    specific file, before finally proceeding to upload."""
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
            ]
        )

        if action == "proceed":
            return files

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
            # Group files by their current title-derivation shape so the user can
            # pick a group of similarly-formatted files and redo the choice for all of them.
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
                    new_title = prompt(f"Enter custom title", default=sample["title"]).strip() or sample["title"]
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
                    # Re-derive per-file so files with different base text in the same
                    # shape still get an appropriately-transformed title, not one fixed string.
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

    table = Table(box=box.ROUNDED, header_style="bold cyan", border_style="cyan")
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
    """Detect duplicate chapter/volume numbers and let the user resolve them:
    exclude a file, give it a new number, or proceed anyway. Returns the
    (possibly modified) files list. Loops until the user is done resolving
    or chooses to proceed with duplicates intact."""
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
    files = get_files_in_dir(directory, upload_type, chapter_naming, custom_regex, strip_groups=advanced_strip_groups, custom_renames=custom_renames, select_subset=True)
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
        res = session.get(f"{BASE_URL}/api/groups", params={"q": query, "limit": 25}, timeout=(10, 30))
        if res.status_code != 200: return []
        return res.json().get("groups", [])
    except requests.exceptions.RequestException as e:
        print_warning(f"Network error while searching for groups: {e}")
        return []
    except json.JSONDecodeError as e:
        logging.debug("search_groups: bad JSON response: %s", e)
        print_warning("Group search returned an unreadable response. The site API may have changed.")
        return []

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

def _read_cookie_db_with_fallback(db_path, domains=None):
    try:
        return rookiepy.firefox_based(db_path, domains=domains)
    except (OSError, sqlite3.Error) as e:
        logging.debug("_read_cookie_db_with_fallback: direct read failed for %s (%s); trying a copy.", db_path, e)

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
        entries = sorted(os.listdir(root))
        default_entries = [e for e in entries if 'default' in e.lower()]
        ordered = default_entries + [e for e in entries if e not in default_entries]

        for entry in ordered:
            db_path = os.path.join(root, entry, 'cookies.sqlite')
            if os.path.isfile(db_path):
                cookies = _read_cookie_db_with_fallback(db_path, domains=domains)
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

def _find_browser_executable(browser_key):
    plat = sys.platform
    plat_key = "win32" if plat == "win32" else ("darwin" if plat == "darwin" else "linux")

    if plat_key == "win32":
        app_exe = CDP_REGISTRY_APP_NAMES.get(browser_key)
        if app_exe:
            found = _find_browser_via_registry(app_exe)
            if found:
                return found

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
    except (subprocess.SubprocessError, OSError):
        return False

def _cdp_kill_stale_process(browser_key):
    pid_file = _cdp_pid_file(browser_key)
    if not os.path.isfile(pid_file):
        return
    try:
        with open(pid_file, "r", encoding="utf-8") as f:
            old_pid = int(f.read().strip())
    except (ValueError, OSError):
        return

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
                pass  
    except (OSError, subprocess.SubprocessError):
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

def _cdp_tracked_process_alive(browser_key):
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
        except (subprocess.SubprocessError, OSError):
            return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, PermissionError):
            return False
        except OSError:
            return False

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

def authenticate_session(req_session, force_browser=None):
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
                print_warning(f"{browser_name.title()}: {type(e).__name__}: {_redact_home_path(e)}{hint}")
            else:
                console.print(f"  [dim]· {browser_name.title()}: {type(e).__name__}: {_redact_home_path(e)}[/dim]{hint}")
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

def upload_file_tus_worker(session, renderer, file_info, manga_id, group_ids,
                           upload_type, batch_id, language, scanlator_name, abort_event,
                           verify_timeout=MAX_VERIFY_SECONDS, current_user_id=None,
                           is_group_upload=False, has_file_specific_group=True,
                           upload_session=None):
    filename = file_info["filename"]
    filepath = file_info["filepath"]
    size     = file_info["size"]

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
                    already_exists = True
                    break
                res.raise_for_status()
                upload_location = res.headers.get("Location")
                if not upload_location: raise ValueError("No Location header in TUS response")
                break
            except SessionExpiredError: raise
            except (requests.exceptions.RequestException, ValueError) as e:
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
                                if server_off is not None:
                                    offset = int(server_off)
                                else:
                                    actual_off = _tus_offset(worker_session, upload_location)
                                    if actual_off is None:
                                        return {"key": filename, "success": False, "error": "Server dropped offset and HEAD failed"}
                                    offset = actual_off
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
                        except requests.exceptions.RequestException as e:
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
        except OSError as e: return {"key": filename, "success": False, "error": str(e)[:30]}

        base_check_url = f"{BASE_URL}/api/manga/{manga_id}/volumes" if upload_type == "volume" else f"{BASE_URL}/api/manga/{manga_id}/chapters/list"
        found        = False
        found_item   = None
        verify_start = time.time()
        total_semaphore_wait = 0

        if not group_ids and not scanlator_name:
            if is_group_upload and not has_file_specific_group:
                label = "⚠️ Uploaded (Unverified — no group)"
                renderer.update_chapter_status(filename, label, 1.0, current=size, total=size, speed=0.0, eta=0.0)
                return {
                    "key": filename,
                    "success": True,
                    "warning": "Uploaded without attribution verification: no resolved group/scanlator for this file."
                }
            label = "✅ Already Exists" if already_exists else "✅ Uploaded"
            renderer.update_chapter_status(filename, label, 1.0, current=size, total=size, speed=0.0, eta=0.0)
            return {"key": filename, "success": True}

        while not found:
            if abort_event.is_set(): return {"key": filename, "success": False, "error": "Aborted"}
            
            elapsed_verify = int(time.time() - verify_start - total_semaphore_wait)
            if elapsed_verify >= verify_timeout: return {"key": filename, "success": False, "error": "Verification timeout reached."}
            
            renderer.update_chapter_status(filename, f"Verifying... ({elapsed_verify}s)", 1.0, current=size, total=size, speed=0.0, eta=0.0)
            if not _interruptible_sleep(RETRY_DELAY, abort_event):
                return {"key": filename, "success": False, "error": "Aborted"}
            
            wait_start = time.time()
            with get_verify_sem():
                total_semaphore_wait += (time.time() - wait_start)
                try:
                    page = 1
                    while True:
                        fetch_check = worker_session.get(f"{base_check_url}?page={page}&limit=100&_t={int(time.time())}", timeout=10)

                        if fetch_check.status_code in (401, 403): raise SessionExpiredError()
                        if fetch_check.status_code != 200: break

                        items_list = fetch_check.json()
                        if isinstance(items_list, dict): items_list = items_list.get("volumes", items_list.get("chapters", []))
                        if not isinstance(items_list, list) or not items_list: 
                            break

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
                        
                        if found: break
                        page += 1

                except SessionExpiredError:
                    raise
                except (requests.exceptions.RequestException, json.JSONDecodeError):
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

    shared_upload_session = _build_shared_upload_session(req_session)

    def mark_failed(name, reason, status):
        renderer.update_chapter_status(name, status, 1.0)
        if name not in failed_chapters:
            failed_chapters.append(name)
        failure_reasons[name] = reason

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=thread_count) as executor:
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
                    if not batch_data.get("success"): raise BatchInitError(str(batch_data)[:200])
                    batch_id = batch_data["batch_id"]
                except (requests.exceptions.RequestException, json.JSONDecodeError, BatchInitError, KeyError) as e:
                    for f in chunk:
                        mark_failed(f["filename"], f"Batch init failed: {str(e)[:80]}", "❌ Batch Init Failed")
                    continue

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
                        except requests.exceptions.RequestException as e:
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
        except OSError as e:
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
    custom_renames = None
    advanced_strip_groups = False
    if upload_type == "chapter":
        chapter_naming, custom_regex, custom_renames, advanced_strip_groups = _ask_chapter_naming()

    language = prompt("Language code", default="en")

    is_group, group_ids, scanlator_name, per_file_group_map, selected_group_name, strip_bracket_groups = \
    _setup_group_config(directory, req_session, upload_type)
    strip_bracket_groups = strip_bracket_groups or advanced_strip_groups
    
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
    files = get_files_in_dir(directory, upload_type, chapter_naming, custom_regex, strip_groups=strip_bracket_groups, custom_renames=custom_renames, select_subset=True)
    if not files:
        print_error("No valid .cbz or .zip files found.")
        sys.exit(1)

    if not strip_bracket_groups:
        for f in files:
            f["groups"] = []

    for f in files:
        f["_upload_type"] = upload_type
        f["_group_label"] = selected_group_name

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