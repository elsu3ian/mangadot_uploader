# MangaDot.net Batch Uploader version 1.2.8 [https://mangadot.net]
# [Interactive UI & Cover Art Update applied]

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
import tempfile
import shutil
import zipfile
from pathlib import Path

try:
    import ctypes
except ImportError:
    ctypes = None

# ==============================================================================
# ⚙️  DEPENDENCY CHECK
# ==============================================================================

REQUIRED_PACKAGES = {
    "requests":    "2.28.0",
    "rookiepy":    "0.5.0",
    "colorama":    "0.4.6",
    "questionary": "2.0.0",
    "rich":        "13.0.0",
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

    # --- Pip packages ---
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
        print(f"\n  Fix:")
        print(f"    pip install --upgrade {' '.join(to_install)}")
        print()

    # --- System tool: chafa (optional but warn clearly) ---
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

# ---------------------------------------------------------------------------
# Third-Party Framework Imports
# ---------------------------------------------------------------------------
if not check_dependencies():
    sys.exit(1)

try:
    import requests
    from requests.adapters import HTTPAdapter
    import rookiepy
    import questionary
    from colorama import init as colorama_init, Fore, Style
    colorama_init(autoreset=True)
    
    from rich.console import Console, Group
    from rich.live import Live
    from rich.markup import escape as rich_escape
    from rich.rule import Rule
    from rich.table import Table
    from rich.text import Text
    from rich.panel import Panel
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
RETRYABLE_STATUSES   = [429, 500, 502, 503, 504, 524]
FATAL_SIZE_STATUSES  = [413, 415]
MAX_VERIFY_SECONDS   = 60
DEFAULT_CHAPTERS_DIR = "chapters"
DEFAULT_LIBRARY_DIR  = ""   # parent folder whose subfolders are offered as a picker; "" disables
CONFIG_PATH          = Path.home() / ".mangadot_uploader.json"   # remembers settings between runs

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
            out = subprocess.run([cmd, "--version"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5)
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
            BarColumn(bar_width=None),
            TaskProgressColumn(),
            TextColumn("[cyan]{task.completed:.0f}/{task.total:.0f} chapters[/cyan]"),
            console=console,
            expand=True,
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
        self.finished_order = []

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
                if "✅" in status:
                    self.completed_chapters += 1
                    self.overall_progress.update(self.overall_task, completed=self.completed_chapters)
                if chap_key not in self.finished_order:
                    self.finished_order.append(chap_key)
                    self._trim_finished()

            self.live.refresh()

    def _trim_finished(self):
        while len(self.finished_order) > self.MAX_VISIBLE_FINISHED:
            oldest = self.finished_order.pop(0)
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

def ask_select(message, choices, default=None):
    try:
        answer = questionary.select(message, choices=choices, default=default, qmark="?").ask()
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
    return ask_select(message, choices)

def to_full_cover_url(photo):
    if not photo: return None
    return photo if photo.startswith("http") else f"{BASE_URL}{photo}"

def fetch_manga_brief(manga_id, session):
    try:
        res = session.get(f"{BASE_URL}/api/manga/{manga_id}", timeout=15)
        if res.status_code == 200:
            data = res.json().get("manga", {})
            title = data.get("title")
            if title: return title, to_full_cover_url(data.get("photo", ""))
    except Exception: pass
    return None, None

def get_cover_ansi(image_url: str, session: requests.Session):
    if shutil.which('chafa') is None:
        return None

    try:
        resp = session.get(image_url, timeout=10)
        resp.raise_for_status()
        tmp = tempfile.NamedTemporaryFile(suffix='.jpg', delete=False)
        tmp.write(resp.content)
        tmp.close()
        try:
            chafa_result = subprocess.run(['chafa', '--size=20x30', tmp.name], capture_output=True, text=True, encoding='utf-8', errors='replace')
            if chafa_result.returncode == 0:
                return chafa_result.stdout
        finally:
            os.unlink(tmp.name)
    except Exception:
        return None
    return None

def natural_sort_key(s):
    return [float(text) if re.match(r'^-?\d+(?:\.\d+)?$', text) else text.lower()
            for text in re.split(r'(-?\d+(?:\.\d+)?)', str(s))]

def encode_tus_metadata(meta_dict):
    pairs = []
    for k, v in meta_dict.items():
        if v is None: continue
        if isinstance(v, list):
            val_str = json.dumps(v)
        elif isinstance(v, float) and v.is_integer():
            # Send whole numbers as "5" rather than "5.0"
            val_str = str(int(v))
        else:
            val_str = str(v)
        encoded_val = base64.b64encode(val_str.encode('utf-8')).decode('utf-8')
        pairs.append(f"{k} {encoded_val}")
    return ",".join(pairs)

def parse_filename_details(filename, upload_type="chapter", chapter_naming="extract", custom_regex=None, strip_groups=False):
    """Returns (number, title, group_names).
    group_names: list of group name strings found in [Bracket] tags (always extracted).
    strip_groups: if True, remove bracket tags from the title; if False, keep them."""
    _bracket_re = re.compile(r'\[([A-Za-z][^\]]*?)\]')
    name_without_ext = re.sub(r'\.(cbz|zip)$', '', filename, flags=re.IGNORECASE)

    # Always extract bracket tags so detection works, but only strip from title when accepted
    raw_groups    = []
    name_no_group = name_without_ext
    for m in _bracket_re.finditer(name_without_ext):
        content = m.group(1).strip()
        if re.match(r'^[\d\s\-\.]+$', content): continue   # skip purely numeric
        if re.match(r'^\d{3,4}p$', content, re.IGNORECASE): continue  # skip resolution tags
        names = [n.strip() for n in content.split(',') if n.strip()]
        raw_groups.extend(names)
        if strip_groups:
            name_no_group = name_no_group.replace(m.group(0), '')
    name_no_group = name_no_group.strip(' -_') if strip_groups else name_without_ext

    # Require the keyword to start at a word boundary or after an underscore so it
    # doesn't match mid-word (e.g. the "c" in "Arc 3" or "Disc 2"). The digits may
    # follow immediately ("c5"), so no trailing boundary is used.
    if upload_type == "volume":
        match = re.search(r'(?:\b|_)(?:volume|vol|v)\.?\s*(\d+(?:\.\d+)?)', name_no_group, re.IGNORECASE)
    else:
        match = re.search(r'(?:\b|_)(?:chapter|ch|c)\.?\s*(\d+(?:\.\d+)?)', name_no_group, re.IGNORECASE)

    num = float(match.group(1)) if match else None
    if num is None:
        match = re.search(r'(\d+(?:\.\d+)?)', name_no_group)
        num = float(match.group(1)) if match else None

    if num is None: return None, None, raw_groups
    if upload_type == "volume": return num, f"Vol. {num:.2f}", raw_groups

    if chapter_naming == "custom" and custom_regex:
        try:
            if "->" in custom_regex:
                find_pat, replace_pat = custom_regex.split("->", 1)
                title = re.sub(find_pat.strip(), replace_pat.strip(), name_no_group).strip()
                return num, title, raw_groups
            else:
                c_match = re.search(custom_regex, name_no_group)
                if c_match:
                    title = c_match.group(1).strip() if c_match.groups() else c_match.group(0).strip()
                    return num, title, raw_groups
                else: print_warning(f"Custom regex did not match '{filename}'. Falling back to Auto-detect.")
        except re.error as e: print_warning(f"Invalid regex '{custom_regex}' ({e}). Falling back to Auto-detect.")

    if chapter_naming == "preset": return num, f"Chapter {num:g}", raw_groups

    title = None
    parts = name_no_group.split(' - ', 1)
    if len(parts) > 1:
        split_idx     = name_no_group.find(' - ')
        part0_has_num = match.start() < split_idx if match else False
        if part0_has_num: title = parts[1].strip()
        else:
            title = parts[0].strip()
            if match:
                remaining = parts[1].replace(match.group(0), '').strip(' -_')
                if remaining: title = f"{title} - {remaining}"
    else:
        if match: title = name_no_group.replace(match.group(0), '').strip(' -_') or None
    return num, title, raw_groups

ARCHIVE_IMAGE_EXTS = ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp', '.avif')

def validate_archive(filepath):
    """Lightweight integrity check for a .cbz/.zip. Returns None if the archive
    looks valid, otherwise a short human-readable reason. Only reads the central
    directory (fast) — it does not CRC-check every entry."""
    try:
        if not zipfile.is_zipfile(filepath):
            return "not a valid ZIP/CBZ archive"
        with zipfile.ZipFile(filepath) as zf:
            names = [n for n in zf.namelist() if not n.endswith('/')]
            if not names:
                return "archive is empty"
            if not any(n.lower().endswith(ARCHIVE_IMAGE_EXTS) for n in names):
                return "no image files inside"
    except Exception as e:
        return f"unreadable archive ({str(e)[:40]})"
    return None

def get_files_in_dir(directory, upload_type, chapter_naming="extract", custom_regex=None, strip_groups=False, validate=True):
    valid_extensions = ('.cbz', '.zip')
    files_data = []
    for filename in os.listdir(directory):
        if not filename.lower().endswith(valid_extensions): continue
        filepath = os.path.join(directory, filename)
        if not os.path.isfile(filepath): continue
        num, title, file_groups = parse_filename_details(filename, upload_type, chapter_naming, custom_regex, strip_groups=strip_groups)
        if num is None:
            print_warning(f"Could not detect {upload_type} number from '{filename}'. Skipping.")
            continue
        if validate:
            archive_err = validate_archive(filepath)
            if archive_err:
                print_warning(f"Skipping '{filename}': {archive_err}.")
                continue
        files_data.append({
            "filepath": filepath, "filename": filename,
            "number": num, "title": title, "size": os.path.getsize(filepath),
            "groups": file_groups,   # group name strings extracted from [Bracket] tags
        })
    files_data.sort(key=lambda x: x["number"])
    return files_data

def fmt_size(bytes_: int) -> str:
    """Format a byte count as MB or GB depending on magnitude."""
    gb = bytes_ / (1024 ** 3)
    if gb >= 1:
        return f"{gb:.2f} GB"
    return f"{bytes_ / (1024 ** 2):.2f} MB"

def fmt_duration(seconds) -> str:
    """Format a duration in seconds as a compact h/m/s string."""
    seconds = int(seconds)
    h, rem  = divmod(seconds, 3600)
    m, s    = divmod(rem, 60)
    if h: return f"{h}h {m}m {s}s"
    if m: return f"{m}m {s}s"
    return f"{s}s"

def print_files_table(files, upload_type, group_label=None):
    """group_label: optional string shown in the Group column for every row when
    the group was set manually (and files therefore have no bracket-detected groups)."""
    total_size = sum(f["size"] for f in files)
    print_success(f"Found {len(files)} file(s)  ({fmt_size(total_size)} total)\n")

    # Show Group column when files have bracket-detected groups OR a manual label was given
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
    """Load the persisted settings file. Returns {} on any problem."""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def save_config(cfg):
    """Persist settings to the config file. Failures are non-fatal."""
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass

def _remember_library(lib):
    """Save the library folder so the next run can default to it."""
    if not lib:
        return
    lib = os.path.normpath(lib)
    cfg = load_config()
    if cfg.get("library") != lib:
        cfg["library"] = lib
        save_config(cfg)

def _count_archives(path):
    """Count .cbz/.zip files directly inside a folder (non-recursive)."""
    try:
        return sum(1 for f in os.listdir(path)
                   if f.lower().endswith(('.cbz', '.zip')) and os.path.isfile(os.path.join(path, f)))
    except OSError:
        return 0

def select_directory(library_dir=None):
    """Resolve the folder of .cbz/.zip files to work with.

    When library_dir is a valid parent folder, its immediate subfolders that
    contain archives are offered as a questionary picker (with file counts).
    A manual-path entry is always available as a fallback. Returns a validated,
    normalized directory path."""
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
                library_dir = None  # stop re-scanning an empty library

        directory = prompt("Enter the directory path containing your .cbz/.zip files",
                            default=DEFAULT_CHAPTERS_DIR if os.path.isdir(DEFAULT_CHAPTERS_DIR) else None)
        directory = os.path.normpath(directory.strip().strip('"\''))
        if os.path.isdir(directory):
            # Remember the parent as a library so the picker works next time.
            _remember_library(library_dir or os.path.dirname(os.path.abspath(directory)))
            return directory
        print_error("Directory does not exist. Please try again.")

# ==============================================================================
# 🏃 DRY RUN
# ==============================================================================

def run_dry_run(library_dir=None):
    console.print()
    console.rule("[bold magenta]MangaDot.net Batch Uploader — DRY RUN[/bold magenta]")
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
            custom_regex = prompt("Enter your regex pattern")

    console.print()
    console.rule("[dim]Files[/dim]")
    console.print()
    print_info("Scanning directory for files...")
    # Dry run has no group-acceptance step, so bracket tags are never stripped here.
    files = get_files_in_dir(directory, upload_type, chapter_naming, custom_regex, strip_groups=False)
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
            else: 
                decoded[k] = v
        if "id" in decoded and "title" in decoded and isinstance(decoded["id"], int): mangas.append(decoded)
    seen = set()
    return [m for m in mangas if not (m["id"] in seen or seen.add(m["id"]))]

def search_groups(query, session):
    try:
        res = session.get(f"{BASE_URL}/api/groups?q={query}&limit=25", timeout=(10, 30))
        if res.status_code != 200: return []
        return res.json().get("groups", [])
    except Exception: return []

def detect_groups_from_filenames(directory):
    """Scan filenames for [GroupName] or [Group1, Group2] bracket tags.

    Returns:
        common_names  - list of group name strings that appear most often
                        (used when the whole batch shares one group).
        per_file_map  - dict of {filename: [group_name, ...]} for every file
                        that has a bracket tag, enabling mixed-group batches.
    """
    valid_ext  = ('.cbz', '.zip')
    bracket_re = re.compile(r'\[([A-Za-z][^\]]*?)\]')
    counter    = {}  # frozenset of lowered names -> (count, original_names_list)
    per_file   = {}  # filename -> [name, ...]

    try:
        filenames = [f for f in os.listdir(directory) if f.lower().endswith(valid_ext)]
    except OSError:
        return [], {}

    for filename in filenames:
        name  = re.sub(r'\.(cbz|zip)$', '', filename, flags=re.IGNORECASE)
        found = []
        for m in bracket_re.finditer(name):
            tag = m.group(1).strip()
            if re.match(r'^[\d\s\-\.]+$', tag): continue
            if re.match(r'^\d{3,4}p$', tag, re.IGNORECASE): continue
            names = [n.strip() for n in tag.split(',') if n.strip()]
            found.extend(names)
        if found:
            per_file[filename] = found
            key = frozenset(n.lower() for n in found)
            prev_count, prev_names = counter.get(key, (0, found))
            counter[key] = (prev_count + 1, prev_names)

    if not counter:
        return [], {}

    _, best_names = max(counter.values(), key=lambda x: x[0])
    return best_names, per_file

def resolve_group_names(names, session):
    """Given a list of group name strings, search the API for each and return
    confirmed group IDs. Prompts the user to pick when results are ambiguous.
    Returns (group_ids, unresolved_names)."""
    group_ids  = []
    unresolved = []

    for name in names:
        with console.status(f"[cyan]Searching for group '{name}'...[/cyan]", spinner="dots"):
            results = search_groups(name, session)

        if not results:
            print_warning(f"No groups found for '{name}'.")
            unresolved.append(name)
            continue

        # exact name match (case-insensitive) -> auto-select without prompting
        exact = [g for g in results if g['name'].lower() == name.lower()]
        if len(exact) == 1:
            group_ids.append(exact[0]['id'])
            print_success(f"Auto-matched group: {exact[0]['name']} (ID: {exact[0]['id']})")
            continue

        # ambiguous - let user pick
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
                with console.status(f"[cyan]Extracting cookies from {current_browser.title()}...[/cyan]", spinner="dots"):
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
            with console.status("[cyan]Validating session with Mangadot...[/cyan]", spinner="dots"):
                email = validate_session(req_session)
            if email:
                print_success(f"Successfully authenticated as: [bold]{email}[/bold]")
                return current_browser
            else:
                print_warning("Cookies extracted but session validation failed (unauthorized or expired).")
                print_warning("Ensure you have passed the Cloudflare check and are logged in on your browser.")
        print_info("\nAuthentication failed. Please select an option to retry:")
        
        browser_choices = []
        for key, (name, _) in supported_browsers.items():
            label = f"{name.title()}" + (" (active)" if name == current_browser else "")
            browser_choices.append(questionary.Choice(title=label, value=name))
        browser_choices.append(questionary.Choice(title="Quit script", value="__quit__"))

        choice = ask_select("Select a browser to retry with:", browser_choices, default=current_browser)
        if choice == "__quit__":
            print_info("Exiting script.")
            sys.exit(0)
        current_browser = choice

# ==============================================================================
# 📤 TUS UPLOAD WORKER
# ==============================================================================

def _compute_retry_delay(response, attempt):
    """Honor a server 'Retry-After' header when present, else exponential backoff
    (RETRY_DELAY, 2x, 4x, ...) capped at 60s."""
    if response is not None:
        ra = response.headers.get("Retry-After")
        if ra:
            try:
                return max(0.0, min(float(ra), 120.0))
            except (TypeError, ValueError):
                pass
    return min(RETRY_DELAY * (2 ** attempt), 60)

def _tus_offset(session, location):
    """HEAD a TUS upload to read the server's current Upload-Offset, so a stalled
    transfer can resume instead of re-sending from the start. Returns an int
    offset, or None if it could not be determined."""
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

def upload_file_tus_worker(session, renderer, file_info, manga_id, group_ids,
                           upload_type, batch_id, language, scanlator_name, abort_event):
    filename = file_info["filename"]
    filepath = file_info["filepath"]
    size     = file_info["size"]

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
    if scanlator_name:  
        tus_metadata["scanlator_name"] = scanlator_name

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

    try:
        with open(filepath, 'rb') as f:
            while offset < size:
                if abort_event.is_set(): return {"key": filename, "success": False, "error": "Aborted"}

                if f.tell() != offset:
                    f.seek(offset)

                chunk = f.read(chunk_size)
                if not chunk: break

                chunk_done = False
                resynced   = False  # server offset jumped ahead; recompute chunk
                for patch_attempt in range(MAX_RETRIES):
                    try:
                        renderer.update_chapter_status(
                            filename, "Uploading...", offset / size,
                            current=offset, total=size
                        )
                        # Build headers per attempt so Upload-Offset tracks any resync.
                        patch_headers = {
                            "Tus-Resumable": "1.0.0",
                            "Upload-Offset": str(offset),
                            "Content-Type":  "application/offset+octet-stream",
                        }
                        patch_res = worker_session.patch(upload_location, headers=patch_headers, data=chunk, timeout=60)

                        if patch_res.status_code in (401, 403): raise SessionExpiredError()
                        elif patch_res.status_code == 204:
                            # Trust the server's reported offset when given.
                            server_off = patch_res.headers.get("Upload-Offset")
                            offset     = int(server_off) if server_off is not None else offset + len(chunk)
                            chunk_done = True
                            break
                        elif patch_res.status_code in FATAL_SIZE_STATUSES:
                            return {"key": filename, "success": False, "error": f"HTTP {patch_res.status_code} (File Too Large/Bad Type)"}
                        elif patch_res.status_code == 409:
                            # Offset conflict: a prior attempt likely landed despite an
                            # error. Resync to the server's true offset and continue.
                            server_off = _tus_offset(worker_session, upload_location)
                            if server_off is not None and server_off != offset:
                                offset   = server_off
                                resynced = True
                                break
                            if patch_attempt < MAX_RETRIES - 1:
                                renderer.update_chapter_status(filename, f"Resyncing chunk... ({patch_attempt + 1})", offset / size, current=offset, total=size)
                                time.sleep(_compute_retry_delay(patch_res, patch_attempt))
                            else: return {"key": filename, "success": False, "error": "HTTP 409 (Offset Conflict)"}
                        elif patch_res.status_code in RETRYABLE_STATUSES:
                            if patch_attempt < MAX_RETRIES - 1:
                                renderer.update_chapter_status(filename, f"Retrying chunk... ({patch_attempt + 1})", offset / size, current=offset, total=size)
                                time.sleep(_compute_retry_delay(patch_res, patch_attempt))
                            else: return {"key": filename, "success": False, "error": f"HTTP {patch_res.status_code} (Max Retries)"}
                        else: return {"key": filename, "success": False, "error": f"HTTP {patch_res.status_code}"}
                    except SessionExpiredError: raise
                    except Exception as e:
                        if patch_attempt < MAX_RETRIES - 1:
                            renderer.update_chapter_status(filename, f"Net Err, Retrying... ({patch_attempt + 1})", offset / size, current=offset, total=size)
                            time.sleep(_compute_retry_delay(None, patch_attempt))
                            # The chunk may have partially landed; resume from the
                            # server's confirmed offset rather than re-sending blindly.
                            server_off = _tus_offset(worker_session, upload_location)
                            if server_off is not None and server_off > offset:
                                offset   = server_off
                                resynced = True
                                break
                        else: return {"key": filename, "success": False, "error": f"Network Err: {str(e)[:30]}"}
                if resynced:
                    continue  # outer loop reseeks and reads the next chunk at new offset
                if not chunk_done: return {"key": filename, "success": False, "error": "Chunk upload failed"}
    except SessionExpiredError: raise
    except Exception as e: return {"key": filename, "success": False, "error": str(e)[:30]}

    base_check_url = f"{BASE_URL}/api/manga/{manga_id}/volumes" if upload_type == "volume" else f"{BASE_URL}/api/manga/{manga_id}/chapters/list"
    found        = False
    verify_start = time.time()
    # Number-only fallback: if the right chapter/volume number shows up but the
    # server response carries no group/scanlator identity we can match against,
    # accept it after a couple of polls rather than failing a real upload.
    number_only_polls = 0
    NUMBER_ONLY_THRESHOLD = 2

    while not found:
        if abort_event.is_set(): return {"key": filename, "success": False, "error": "Aborted"}
        elapsed_verify = int(time.time() - verify_start)
        if elapsed_verify >= MAX_VERIFY_SECONDS: return {"key": filename, "success": False, "error": "Verification timeout reached."}
        renderer.update_chapter_status(filename, f"Verifying... ({elapsed_verify}s)", 1.0, current=size, total=size, speed=0.0, eta=0.0)
        time.sleep(RETRY_DELAY)
        try:
            fetch_check = worker_session.get(f"{base_check_url}?_t={int(time.time())}", timeout=10)

            if fetch_check.status_code in (401, 403): raise SessionExpiredError()
            if fetch_check.status_code != 200: continue

            items_list = fetch_check.json()
            if isinstance(items_list, dict): items_list = items_list.get("volumes", items_list.get("chapters", []))
            if not isinstance(items_list, list): continue

            number_match_no_identity = False
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

                    if group_ids and any(gid in item_group_ids for gid in group_ids): found = True; break

                    if not group_ids and scanlator_name:
                        if item_scanlator == scanlator_name:
                            found = True; break

                    # Number matched, but the item has no identity info to compare
                    # (no group ids and no scanlator name) — candidate for fallback.
                    if not item_group_ids and not item_scanlator:
                        number_match_no_identity = True

            if not found and number_match_no_identity:
                number_only_polls += 1
                if number_only_polls >= NUMBER_ONLY_THRESHOLD:
                    logging.warning("Verifying '%s' by number only — server returned no group/scanlator identity to match.", filename)
                    found = True
        except SessionExpiredError: raise
        except Exception: continue

    renderer.update_chapter_status(filename, "✅ Uploaded", 1.0, current=size, total=size, speed=0.0, eta=0.0)
    return {"key": filename, "success": True}

# ==============================================================================
# 🔄 PROCESS UPLOADS
# ==============================================================================

def process_uploads(files_to_upload, req_session, manga_id, group_ids,
                    upload_type, language, scanlator_name, thread_count,
                    per_file_group_map=None):
    """per_file_group_map: optional dict of {filename: [group_id, ...]} for mixed-group
    batches where different chapters belong to different groups."""
    per_file_group_map = per_file_group_map or {}
    chunks    = [files_to_upload[i:i + MAX_BATCH_SIZE] for i in range(0, len(files_to_upload), MAX_BATCH_SIZE)]
    file_keys = [f["filename"] for f in files_to_upload]
    renderer  = UIRenderer(file_keys)
    renderer.start()

    failed_chapters  = []
    failure_reasons  = {}   # filename -> reason string, for the failed-upload log
    session_expired  = False
    abort_event      = threading.Event()

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
            # For the batch init we use the shared group_ids; per-file overrides are applied in the worker
            init_payload = {"manga_id": manga_id, "language": language, "group_ids": group_ids, "type": upload_type, "scanlator_name": scanlator_name, "chapters": chapters_payload}
            batch_id = None
            try:
                res = req_session.post(BATCH_INIT_ENDPOINT, json=init_payload, timeout=(10, 45))
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
            except SessionExpiredError:
                session_expired = True
                abort_event.set()
                for f in chunk:
                    mark_failed(f["filename"], "Paused — authentication expired", "⏸️ Paused (Auth)")
                continue
            except Exception as e:
                for f in chunk:
                    mark_failed(f["filename"], f"Batch init failed: {str(e)[:80]}", "❌ Batch Init Failed")
                continue

            with concurrent.futures.ThreadPoolExecutor(max_workers=thread_count) as executor:
                futures = {executor.submit(
                    upload_file_tus_worker, req_session, renderer, f, manga_id,
                    per_file_group_map.get(f["filename"], group_ids),  # per-file override or batch default
                    upload_type, batch_id, language, scanlator_name, abort_event
                ): f for f in chunk}
                for future in concurrent.futures.as_completed(futures):
                    f_info = futures[future]
                    try:
                        result = future.result()
                        if not result['success']:
                            mark_failed(result['key'], result.get('error', 'Unknown error'), f"❌ {result['error']}")
                    except SessionExpiredError:
                        session_expired = True
                        abort_event.set()
                        mark_failed(f_info["filename"], "Paused — authentication expired", "⏸️ Paused (Auth)")

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
                        if comp_attempt < MAX_RETRIES - 1: time.sleep(_compute_retry_delay(None, comp_attempt))
                        else: logging.warning(f"Batch {batch_id} complete call failed after {MAX_RETRIES} attempts: {e}")
    except KeyboardInterrupt:
        # Signal workers to stop promptly so Ctrl+C doesn't hang on in-flight chunks.
        abort_event.set()
        raise
    finally:
        renderer.stop()

    return failed_chapters, session_expired, failure_reasons

# ==============================================================================
# 🚀 MAIN
# ==============================================================================

def build_arg_parser():
    parser = argparse.ArgumentParser(description="MangaDot Batch Uploader", formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Scan and parse chapter names without uploading.")
    parser.add_argument("--debug", action="store_true", help="Dump all HTTP traffic to api_requests.log.")
    parser.add_argument("--verify-timeout", type=int, default=MAX_VERIFY_SECONDS, metavar="SECONDS", help=f"How long to wait for validation confirmation (default: {MAX_VERIFY_SECONDS}s).")
    parser.add_argument("--library", default=DEFAULT_LIBRARY_DIR or None, metavar="DIR", help="Parent folder of manga subfolders; pick one interactively instead of typing a path.")
    return parser

def main():
    global MAX_VERIFY_SECONDS
    args = build_arg_parser().parse_args()
    MAX_VERIFY_SECONDS = args.verify_timeout

    # Resolve the library folder: explicit flag > remembered config > built-in default.
    saved_config     = load_config()
    resolved_library = args.library or saved_config.get("library") or (DEFAULT_LIBRARY_DIR or None)

    if args.dry_run: run_dry_run(resolved_library)

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
        print(f"{Colors.WARNING}[DEBUG] HTTP traffic logging active with circular rotation caps.{Colors.RESET}")

    console.print()
    console.rule("[bold magenta]MangaDot.net Batch Uploader[/bold magenta]")
    console.print()

    req_session = requests.Session()
    if args.debug: req_session.hooks['response'].append(log_request_response)
    req_session.headers.update({"Origin": BASE_URL, "Referer": f"{BASE_URL}/"})
    no_retry_adapter = HTTPAdapter(max_retries=0)
    req_session.mount("https://", no_retry_adapter)
    req_session.mount("http://",  no_retry_adapter)

    current_browser = authenticate_session(req_session, "firefox")
    
    console.print()
    console.rule("[dim]Setup[/dim]")
    console.print()

    library_dir = resolved_library
    if library_dir and not args.library and library_dir == saved_config.get("library"):
        print_info(f"Using remembered library folder: [cyan]{library_dir}[/cyan]")
    directory = select_directory(library_dir)
    flush_input_buffer()

    guessed_title = Path(directory).name if directory else ""

    manga_id = None
    while not manga_id:
        m_input = prompt("Search Manga by Title, or enter ID directly", default=guessed_title)
        
        if m_input.isdigit():
            candidate_id = int(m_input)
            with console.status(f"[cyan]Looking up manga ID {candidate_id}...[/cyan]", spinner="dots"):
                title, cover_url = fetch_manga_brief(candidate_id, req_session)
            if not title:
                print_warning(f"Could not find a manga with ID {candidate_id}. Please try again.")
                continue

            console.print(f"\n  [bold]Title:[/bold] {title}  [cyan](ID: {candidate_id})[/cyan]")
            if cover_url:
                c_ansi = get_cover_ansi(cover_url, req_session)
                if c_ansi:
                    console.print(Text.from_ansi(c_ansi))
            else: print_warning("No cover art available for this entry.")

            if ask_confirm(f"Use '{title}'?", default=True):
                manga_id = candidate_id
                print_success(f"Selected Manga: {title} (ID: {manga_id})")
            else:
                guessed_title = None
            continue

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
        if cover_url:
            c_ansi = get_cover_ansi(cover_url, req_session)
            if c_ansi:
                console.print(Text.from_ansi(c_ansi))
        else: print_warning("No cover art available for this entry.")

        if ask_confirm(f"Use '{candidate_title}'?", default=True):
            manga_id = selection["id"]
            print_success(f"Selected Manga: {candidate_title} (ID: {manga_id})")
        else:
            guessed_title = None

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
            print_info("Regex Tip: Use 'Pattern' -> 'Replace' for your regex of choice.")
            custom_regex = prompt("Enter your regex pattern")

    language = prompt("Language code", default="en")

    is_group = ask_confirm("Upload as a Group?", default=True)
    group_ids      = []
    scanlator_name = None

    per_file_group_map  = {}  # filename -> [group_id, ...] for mixed-group batches
    selected_group_name = None  # display name for the Group column in the file table
    strip_bracket_groups = False  # only strip [brackets] from titles when auto-groups accepted

    if is_group:
        # --- Auto-detect groups from filenames ---
        detected_names, per_file_names = detect_groups_from_filenames(directory)

        # Check whether different files have different groups (mixed batch)
        unique_group_sets = set(frozenset(v) for v in per_file_names.values())
        is_mixed = len(unique_group_sets) > 1

        if detected_names:
            names_display = ", ".join(f"[cyan]{n}[/cyan]" for n in detected_names)
            if is_mixed:
                console.print(f"  [bold]Detected mixed groups across chapters.[/bold]")
                # Show a compact summary of unique group combinations
                for gnames in sorted(unique_group_sets, key=lambda s: sorted(s)):
                    console.print(f"    · {'  +  '.join(sorted(gnames))}")
            else:
                console.print(f"  [bold]Detected group(s) from filenames:[/bold] {names_display}")

            use_detected = ask_confirm("Use detected group(s)?", default=True)
            if use_detected:
                if is_mixed:
                    # Resolve every unique group name to an ID, building a name->id dict
                    all_unique_names = list({n for names in per_file_names.values() for n in names})
                    name_to_id = {}
                    for name in all_unique_names:
                        with console.status(f"[cyan]Resolving '{name}'...[/cyan]", spinner="dots"):
                            res = search_groups(name, req_session)
                        exact = [g for g in res if g["name"].lower() == name.lower()]
                        if len(exact) == 1:
                            name_to_id[name] = exact[0]["id"]
                            print_success(f"Auto-matched: {exact[0]['name']} (ID: {exact[0]['id']})")
                        elif res:
                            choices = [questionary.Choice(title=f"{g['name']} (ID: {g['id']})", value=g) for g in res]
                            choices.append(questionary.Choice(title="Skip", value="__skip__"))
                            pick = ask_select(f"Multiple results for '{name}' — select one:", choices)
                            if pick != "__skip__":
                                name_to_id[name] = pick["id"]
                                print_success(f"Selected: {pick['name']} (ID: {pick['id']})")
                        else:
                            print_warning(f"Could not resolve '{name}'.")

                    for filename, fnames in per_file_names.items():
                        ids = [name_to_id[n] for n in fnames if n in name_to_id]
                        if ids:
                            per_file_group_map[filename] = ids

                    # group_ids stays empty — per_file_group_map drives per-chapter assignment
                    all_resolved = list(name_to_id.values())
                    if all_resolved:
                        group_ids = all_resolved  # fallback for files not in the map
                        strip_bracket_groups = True
                    if not per_file_group_map and not group_ids:
                        print_warning("No groups could be resolved. Falling back to manual search.")
                else:
                    resolved_ids, unresolved = resolve_group_names(detected_names, req_session)
                    if resolved_ids:
                        group_ids = resolved_ids
                        selected_group_name = ", ".join(detected_names)
                        strip_bracket_groups = True
                    if unresolved:
                        print_warning(f"Could not resolve: {', '.join(unresolved)}. You can add them manually below.")
                    if not group_ids:
                        print_warning("No groups could be resolved. Falling back to manual search.")

        # --- Manual search (fallback or if auto-detect was declined/failed) ---
        while not group_ids:
            g_input = prompt("Search Group by Name, or enter ID directly")
            if g_input.isdigit():
                group_ids = [int(g_input)]
                selected_group_name = f"ID: {g_input}"
                break

            with console.status(f"[cyan]Searching for group '{g_input}'...[/cyan]", spinner="dots"):
                results = search_groups(g_input, req_session)

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
    else: scanlator_name = prompt("Enter your individual Scanlator Name")

    while True:
        try:
            thread_count = int(prompt("Number of parallel uploads (1-10)", default="3"))
            if 1 <= thread_count <= 10: break
            print_error("Please enter a number between 1 and 10.")
        except ValueError: print_error("Invalid input.")

    console.print()
    console.rule("[dim]Files[/dim]")
    console.print()
    
    print_info("Scanning directory for files...")
    files = get_files_in_dir(directory, upload_type, chapter_naming, custom_regex, strip_groups=strip_bracket_groups)
    if not files:
        print_error("No valid .cbz or .zip files found.")
        sys.exit(1)

    # If auto-groups were not accepted, clear per-file groups so the table shows
    # selected_group_name uniformly instead of the raw bracket-detected names
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

    current_files_to_upload = files

    console.print()
    console.rule("[dim]Upload[/dim]")
    console.print()

    upload_start = time.time()
    while True:
        failed_chapters, session_expired, failure_reasons = process_uploads(
            current_files_to_upload, req_session, manga_id, group_ids, upload_type, language, scanlator_name, thread_count,
            per_file_group_map=per_file_group_map
        )
        
        if session_expired:
            console.print()
            console.rule("[bold red]Session Expired[/bold red]")
            print_warning("UPLOAD PAUSED: Session token expired or unauthorized.")
            print_warning("Refresh your login/Cloudflare check in your browser, then return here.")
            
            time.sleep(1.5)
            flush_input_buffer()
            
            input("\nPress Enter to re-authenticate and resume... ")
            current_browser = authenticate_session(req_session, current_browser)
            current_files_to_upload = [f for f in current_files_to_upload if f["filename"] in failed_chapters]
            
            console.print()
            console.rule("[dim]Resuming Upload[/dim]")
            console.print()
            print_info(f"Resuming upload for {len(current_files_to_upload)} failed/paused chapter(s)...")
            continue

        console.print()
        console.rule("[bold cyan]🎉 All operations complete[/bold cyan]")
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
                f.write("# <filename>\\t<reason>\n\n")
                for chap in sorted(failed_chapters, key=natural_sort_key):
                    reason = failure_reasons.get(chap, "Unknown error")
                    f.write(f"{chap}\t{reason}\n")
            print_info(f"Failed list saved to [cyan]`{failed_log_name}`[/cyan].")
        except Exception as e:
            print_error(f"Could not write `{failed_log_name}`: {e}")
            break

        retry_choice = ask_confirm("Retry ONLY the failed chapters?", default=True)
        if not retry_choice: break
        current_files_to_upload = [f for f in current_files_to_upload if f["filename"] in failed_chapters]
        print_info(f"\nRetrying {len(current_files_to_upload)} failed chapter(s)...")

    manga_url = f"{BASE_URL}/manga/{manga_id}"
    console.print()
    console.rule("[dim]Summary[/dim]")
    console.print()

    # Post-run stats: time elapsed, bytes successfully uploaded, average speed.
    upload_elapsed = time.time() - upload_start
    final_failed   = set(failed_chapters)
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
            manga_data  = api_res.json().get("manga", {})
            title       = manga_data.get("title", "Unknown Title")
            alt_titles  = manga_data.get("alt_titles", [])
            status      = manga_data.get("status", "N/A")
            description = manga_data.get("description", "No description available.")
            photo       = manga_data.get("photo", "")
            clean_desc  = (re.sub(r'<[^>]*>', '', description)[:200] + "...") if description else "N/A"

            # Tags — try several common field names
            raw_tags = (
                manga_data.get("tags") or
                manga_data.get("genres") or
                manga_data.get("categories") or
                []
            )
            if isinstance(raw_tags, list):
                tag_names = [
                    (t.get("name") or t.get("title") or t) if isinstance(t, dict) else str(t)
                    for t in raw_tags
                ]
            else:
                tag_names = []

            # MangaBaka link — try common field names
            mangabaka_id = (
                manga_data.get("mangabaka_id") or
                manga_data.get("baka_id") or
                manga_data.get("mangaupdates_id") or
                (manga_data.get("external_links") or {}).get("mangabaka") or
                (manga_data.get("external_links") or {}).get("baka")
            )
            mangabaka_url = f"https://mangabaka.org/{mangabaka_id}" if mangabaka_id else None

            cover_url = to_full_cover_url(photo)

            # Calculate total successful uploads
            total_uploaded = len(files) - len(failed_chapters)

            info_lines = [f"[bold]Title:[/bold] {rich_escape(title)}"]

            if alt_titles:
                alt_display = alt_titles[0] if isinstance(alt_titles, list) else alt_titles
                info_lines.append(f"[bold]Alt Title:[/bold] {rich_escape(str(alt_display))}")

            info_lines.append(f"[bold]Status:[/bold] {rich_escape(str(status).upper())}")

            if tag_names:
                tags_str = "  ".join(f"[dim][[/dim][cyan]{rich_escape(t)}[/cyan][dim]][/dim]" for t in tag_names)
                info_lines.append(f"[bold]Tags:[/bold] {tags_str}")

            group_str = f"[bold]Release Group:[/bold] [yellow]{rich_escape(str(selected_group_name or 'Multiple / Auto-Detected'))}[/yellow]" if is_group else f"[bold]Scanlator:[/bold] [yellow]{rich_escape(str(scanlator_name))}[/yellow]"

            info_lines.extend([
                "",
                f"[bold]Uploaded Items:[/bold] [magenta]{total_uploaded}[/magenta] / {len(files)} {upload_type}(s) successfully processed",
                group_str,
                "",
                "[bold]Synopsis:[/bold]",
                rich_escape(clean_desc),
                "",
                f"[bold green]MangaDot:[/bold green]  {manga_url}"
            ])

            if cover_url:
                info_lines.append(f"[bold green]Cover Art:[/bold green] {cover_url}")
            if mangabaka_url:
                info_lines.append(f"[bold green]MangaBaka:[/bold green] {mangabaka_url}")

            info_text = Text.from_markup("\n".join(info_lines))

            # Build a 2-column layout to mimic the website
            summary_grid = Table.grid(padding=(0, 3))
            summary_grid.add_column(justify="center")          # Left column: Image
            summary_grid.add_column(justify="left", ratio=1)   # Right column: Text

            cover_ansi = get_cover_ansi(cover_url, req_session) if cover_url else None

            # Inject the ANSI art if it exists, otherwise just show text
            if cover_ansi:
                summary_grid.add_row(Text.from_ansi(cover_ansi), info_text)
            else:
                summary_grid.add_row(info_text)

            console.print(Panel(
                summary_grid,
                title="🎉 UPLOAD CONFIRMED ON MANGADOT",
                border_style="green",
                box=box.ROUNDED,
                padding=(1, 2)
            ))
            
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