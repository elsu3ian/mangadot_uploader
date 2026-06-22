#From Protearsdropper and Elsu version 0.0.1 by Protearsdropper, Elsu, Moon, and others
import os
import re
import sys
import json
import base64
import time
import threading
import concurrent.futures
import argparse
import importlib.metadata
import subprocess
import platform
from pathlib import Path

# ==============================================================================
# ⚙️ DEPENDENCY CHECK & CONFIGURATION
# ==============================================================================

REQUIRED_PACKAGES = {
    "requests": "2.34.2",
    "urllib3": "2.7.0",
    "rookiepy": "0.5.6",
    "colorama": "0.4.6"
}

def check_dependencies():
    missing_or_outdated = []
    
    for pkg, min_version in REQUIRED_PACKAGES.items():
        try:
            installed_version = importlib.metadata.version(pkg)
            installed_tuple = tuple(map(int, installed_version.split('.')))
            min_tuple = tuple(map(int, min_version.split('.')))
            
            if installed_tuple < min_tuple:
                missing_or_outdated.append((pkg, min_version, installed_version))
        except importlib.metadata.PackageNotFoundError:
            missing_or_outdated.append((pkg, min_version, None))
        except Exception:
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
        print(" HOW TO FIX THIS (Choose one method below):")
        print("=" * 60)
        print("\nMethod 1: Upgrade everything automatically (Recommended)")
        print("  Open your Command Prompt (Windows) or Terminal (Mac/Linux) and run:")
        print('  pip install --upgrade requests urllib3 rookiepy colorama')
        
        print("\nMethod 2: If 'pip' doesn't work, try:")
        print("  python -m pip install --upgrade requests urllib3 rookiepy colorama")
        
        print("\nMethod 3: If you have multiple Python versions, try:")
        print("  py -m pip install --upgrade requests urllib3 rookiepy colorama")
        print("\n" + "=" * 60 + "\n")
        sys.exit(1)

check_dependencies()

try:
    import requests
    from requests.adapters import HTTPAdapter
    import rookiepy
    from colorama import init, Fore, Style
    init(autoreset=True)  # Enable ANSI colors for Windows
except Exception as e:
    print(f"An unexpected error occurred during import: {e}")
    sys.exit(1)

# ==============================================================================
# ⚙️ CONFIGURATION - CODE BEGINS BELOW
# ==============================================================================

BASE_URL = "https://mangadot.net"
TUS_ENDPOINT = f"{BASE_URL}/api/tus/"
BATCH_INIT_ENDPOINT = f"{BASE_URL}/api/uploads/batch/init"

MAX_BATCH_SIZE = 100
MAX_RETRIES = 3
RETRY_DELAY = 5
RETRYABLE_STATUSES = [500, 502, 503, 504, 524]
DEFAULT_CHAPTERS_DIR = "chapters"

DEFAULT_USER_AGENTS = {
    "chrome":   "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
    "firefox":  "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0",
    "brave":    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
    "edge":     "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36 Edg/137.0.0.0",
    "opera":    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36 OPR/122.0.0.0",
    "vivaldi":  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36 Vivaldi/7.4.3684.38",
}

_WEB_VERSION_APIS = {
    "chrome":  "https://versionhistory.googleapis.com/v1/chrome/platforms/win/channels/stable/versions?pageSize=1",
    "firefox": "https://product-details.mozilla.org/1.0/firefox_versions.json",
}

_UA_CACHE = {}


def _clean_version(raw):
    """Extract the first dotted version number from any string."""
    if not raw:
        return None
    m = re.search(r'(\d+(?:\.\d+)*)', str(raw))
    return m.group(1) if m else None


def _detect_windows_arch():
    """Return the architecture token used in Windows User-Agents."""
    machine = platform.machine().lower()
    if machine in ('amd64', 'x86_64'):
        return 'Win64; x64'
    return ''


def _detect_macos_ver():
    """Return an underscore-joined macOS version, e.g. '14_4_1' or '10_15_7'."""
    try:
        ver = platform.mac_ver()[0]
        if ver and ver != '':
            parts = ver.split('.')
            if len(parts) >= 2:
                base = f"{parts[0]}_{parts[1]}"
                if len(parts) >= 3 and parts[2]:
                    base += f"_{parts[2]}"
                return base
    except Exception:
        pass
    return "10_15_7"


def _read_windows_registry(browser):
    """Return installed browser version from the Windows registry, or None."""
    try:
        import winreg
        paths = {
            "chrome":  [(winreg.HKEY_CURRENT_USER, r"SOFTWARE\Google\Chrome\BLBeacon", "version"),
                        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Google\Chrome\BLBeacon", "version")],
            "edge":    [(winreg.HKEY_CURRENT_USER,
                          r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{56EB18F8-B008-4CBD-B6D2-8C97FE7E7558}", "pv"),
                        (winreg.HKEY_LOCAL_MACHINE,
                          r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{56EB18F8-B008-4CBD-B6D2-8C97FE7E7558}", "pv")],
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
                    if v:
                        return v
            except OSError:
                continue
    except Exception:
        return None
    return None


def _read_mac_plist(browser):
    """Return installed browser version from a macOS .app Info.plist, or None."""
    try:
        import plistlib
        paths = {
            "chrome":  "/Applications/Google Chrome.app/Contents/Info.plist",
            "edge":    "/Applications/Microsoft Edge.app/Contents/Info.plist",
            "brave":   "/Applications/Brave Browser.app/Contents/Info.plist",
            "firefox": "/Applications/Firefox.app/Contents/Info.plist",
            "opera":   "/Applications/Opera.app/Contents/Info.plist",
            "vivaldi": "/Applications/Vivaldi.app/Contents/Info.plist",
        }
        path = paths.get(browser)
        if not path or not os.path.exists(path):
            return None
        with open(path, 'rb') as f:
            plist = plistlib.load(f)
            raw = plist.get('KSVersion') or plist.get('CFBundleShortVersionString')
            return _clean_version(raw)
    except Exception:
        return None


def _read_linux_version(browser):
    """Return installed browser version by running `<binary> --version` on Linux."""
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
            out = subprocess.run(
                [cmd, "--version"],
                capture_output=True, text=True, timeout=5,
            )
            if out.returncode == 0 and out.stdout:
                return _clean_version(out.stdout)
        except (OSError, subprocess.SubprocessError):
            continue
    return None


def _fetch_web_version(browser, timeout=5):
    """Fetch the latest stable version from the official vendor API."""
    try:
        if browser == "firefox":
            r = requests.get(_WEB_VERSION_APIS["firefox"], timeout=timeout)
            if r.status_code == 200:
                return _clean_version(r.json().get("LATEST_FIREFOX_VERSION"))
        elif browser in ("chrome", "edge"):
            r = requests.get(_WEB_VERSION_APIS["chrome"], timeout=timeout)
            if r.status_code == 200:
                data = r.json()
                versions = data.get("versions") or []
                if versions:
                    return _clean_version(versions[0].get("version"))
    except Exception:
        return None
    return None

def _build_user_agent(browser, version):
    """Build a platform-aware User-Agent string from browser + version."""
    if not version:
        return DEFAULT_USER_AGENTS.get(browser, DEFAULT_USER_AGENTS["firefox"])

    major = version.split('.')[0]

    if sys.platform == 'win32':
        arch = _detect_windows_arch()
        nt = "Windows NT 10.0"
        arch_clause = f"{nt}; {arch}" if arch else nt
        if browser == "firefox":
            return f"Mozilla/5.0 ({arch_clause}; rv:{major}.0) Gecko/20100101 Firefox/{major}.0"
        if browser == "edge":
            return (f"Mozilla/5.0 ({arch_clause}) AppleWebKit/537.36 (KHTML, like Gecko) "
                    f"Chrome/{major}.0.0.0 Safari/537.36 Edg/{major}.0.0.0")
        if browser == "opera":
            return (f"Mozilla/5.0 ({arch_clause}) AppleWebKit/537.36 (KHTML, like Gecko) "
                    f"Chrome/{major}.0.0.0 Safari/537.36 OPR/{major}.0.0.0")
        if browser == "vivaldi":
            return (f"Mozilla/5.0 ({arch_clause}) AppleWebKit/537.36 (KHTML, like Gecko) "
                    f"Chrome/{major}.0.0.0 Safari/537.36 Vivaldi/{major}.0.0.0")
        return (f"Mozilla/5.0 ({arch_clause}) AppleWebKit/537.36 (KHTML, like Gecko) "
                f"Chrome/{major}.0.0.0 Safari/537.36")

    if sys.platform == 'darwin':
        mac_ver = _detect_macos_ver()
        if browser == "firefox":
            return (f"Mozilla/5.0 (Macintosh; Intel Mac OS X {mac_ver}; rv:{major}.0) "
                    f"Gecko/20100101 Firefox/{major}.0")
        if browser == "edge":
            return (f"Mozilla/5.0 (Macintosh; Intel Mac OS X {mac_ver}) AppleWebKit/537.36 "
                    f"(KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36 Edg/{major}.0.0.0")
        if browser == "opera":
            return (f"Mozilla/5.0 (Macintosh; Intel Mac OS X {mac_ver}) AppleWebKit/537.36 "
                    f"(KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36 OPR/{major}.0.0.0")
        if browser == "vivaldi":
            return (f"Mozilla/5.0 (Macintosh; Intel Mac OS X {mac_ver}) AppleWebKit/537.36 "
                    f"(KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36 Vivaldi/{major}.0.0.0")
        return (f"Mozilla/5.0 (Macintosh; Intel Mac OS X {mac_ver}) AppleWebKit/537.36 "
                f"(KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36")

    if browser == "firefox":
        return (f"Mozilla/5.0 (X11; Linux x86_64; rv:{major}.0) "
                f"Gecko/20100101 Firefox/{major}.0")
    if browser == "edge":
        return (f"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                f"Chrome/{major}.0.0.0 Safari/537.36 Edg/{major}.0.0.0")
    if browser == "opera":
        return (f"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                f"Chrome/{major}.0.0.0 Safari/537.36 OPR/{major}.0.0.0")
    if browser == "vivaldi":
        return (f"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                f"Chrome/{major}.0.0.0 Safari/537.36 Vivaldi/{major}.0.0.0")
    return (f"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/{major}.0.0.0 Safari/537.36")


def get_dynamic_user_agent(browser):
    """Return a User-Agent that matches the locally installed browser version."""
    if browser in _UA_CACHE:
        return _UA_CACHE[browser]

    version = None
    try:
        if sys.platform == 'win32':
            version = _read_windows_registry(browser)
        elif sys.platform == 'darwin':
            version = _read_mac_plist(browser)
        else:
            version = _read_linux_version(browser)
    except Exception:
        version = None

    if not version and browser in ("chrome", "edge", "firefox"):
        version = _fetch_web_version(browser)

    ua = _build_user_agent(browser, version)
    _UA_CACHE[browser] = ua
    return ua

class Colors:
    HEADER = '\033[95m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    RESET = Style.RESET_ALL
    BOLD = '\033[1m'

# --- UI Renderer ---
class UIRenderer:
    def __init__(self, chapter_keys):
        self.lock = threading.Lock()
        self.sorted_keys = chapter_keys
        self.total_chapters = len(chapter_keys)
        self.completed_chapters = 0
        self.status = {key: {"status": "Queued", "progress": 0.0} for key in chapter_keys}
        self.height = 0
        self.page_size = 25
        self.view_start_index = 0

    def _render(self):
        if self.height > 0:
            sys.stdout.write(f"\033[{self.height}A")
            
        overall_progress = self.completed_chapters / self.total_chapters if self.total_chapters > 0 else 0
        overall_bar = f"[{'#' * int(overall_progress * 40):<40}]"
        sys.stdout.write(f"{Colors.OKCYAN}--- Uploading ({self.completed_chapters}/{self.total_chapters}) {overall_bar} {overall_progress*100:3.0f}% ---\033[K\n")
        
        end_index = min(self.view_start_index + self.page_size, self.total_chapters)
        chapters_to_display = self.sorted_keys[self.view_start_index:end_index]
        
        for key in chapters_to_display:
            info = self.status[key]
            status_text, progress = info["status"], info["progress"]
            
            visual_len = len(status_text)
            if "✅" in status_text or "❌" in status_text:
                visual_len += 1
                
            padding = 25 - visual_len
            if padding < 0: padding = 0
            padded_status = f"{status_text}{' ' * padding}"
            
            bar_color = Colors.OKGREEN if progress == 1.0 and ("✅" in status_text) else (Colors.FAIL if "❌" in status_text else Colors.WARNING)
            bar = f"[{bar_color}{'#' * int(progress * 20):<20}{Colors.RESET}]"
            status_color = Colors.OKGREEN if "✅" in status_text else (Colors.FAIL if "❌" in status_text else "")
            
            line = f"  {key:<30.30}: {status_color}{padded_status}{Colors.RESET} {bar} {progress*100:3.0f}%"
            sys.stdout.write(f"{line}\033[K\n")
            
        self.height = 1 + len(chapters_to_display)
        sys.stdout.flush()

    def update_chapter_status(self, chap_key, status, progress=None):
        with self.lock:
            if chap_key not in self.status: return
            self.status[chap_key]["status"] = status
            if progress is not None:
                self.status[chap_key]["progress"] = progress
            if self.status[chap_key]["progress"] >= 1.0 and "✅" in status:
                self.completed_chapters += 1
                self._check_and_scroll_view()
            self._render()

    def _check_and_scroll_view(self):
        end_index = min(self.view_start_index + self.page_size, self.total_chapters)
        visible_keys = self.sorted_keys[self.view_start_index:end_index]
        if all(self.status[key]["progress"] == 1.0 for key in visible_keys):
            next_incomplete_index = next((i for i, k in enumerate(self.sorted_keys) if self.status[k]["progress"] < 1.0), -1)
            if next_incomplete_index != -1:
                self.view_start_index = next_incomplete_index
            else:
                self.view_start_index = max(0, self.total_chapters - self.page_size)

    def start(self):
        self.height = 1 + min(self.total_chapters, self.page_size)
        sys.stdout.write("\n" * self.height)
        with self.lock:
            self._render()

# --- Helper Functions ---
def print_success(msg): print(f"{Colors.OKGREEN}[+]{Colors.RESET} {msg}")
def print_info(msg): print(f"{Colors.OKCYAN}[*]{Colors.RESET} {msg}")
def print_warning(msg): print(f"{Colors.WARNING}[!]{Colors.RESET} {msg}")
def print_error(msg): print(f"{Colors.FAIL}[-]{Colors.RESET} {msg}")

def flush_input_buffer():
    """Cross-platform utility to clean stray threads and leftover newline entries out of standard input."""
    try:
        import msvcrt
        while msvcrt.kbhit():
            msvcrt.getch()
    except ImportError:
        import termios
        try:
            termios.tcflush(sys.stdin, termios.TCIFLUSH)
        except Exception:
            pass

def prompt(text, default=None, required=True):
    while True:
        prompt_text = f"{text} [{default}]: " if default else f"{text}: "
        user_input = input(prompt_text).strip()
        if not user_input and default is not None: return default
        if required and not user_input:
            print_warning("This field is required.")
            continue
        return user_input

def natural_sort_key(s): 
    return [float(text) if re.match(r'^-?\d+(?:\.\d+)?$', text) else text.lower() for text in re.split(r'(-?\d+(?:\.\d+)?)', str(s))]

def encode_tus_metadata(meta_dict):
    pairs = []
    for k, v in meta_dict.items():
        if v is None: continue
        val_str = json.dumps(v) if isinstance(v, list) else str(v)
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

    if num is None:
        return None, None

    if upload_type == "volume" and num is not None:
        title = f"Vol. {num:.2f}"
        return num, title

    if chapter_naming == "custom" and custom_regex:
        try:
            c_match = re.search(custom_regex, name_without_ext)
            if c_match:
                title = c_match.group(1).strip() if c_match.groups() else c_match.group(0).strip()
                return num, title
            else:
                print_warning(f"Custom regex did not match '{filename}'. Falling back to Auto-detect.")
        except re.error as e:
            print_warning(f"Invalid regex '{custom_regex}' ({e}). Falling back to Auto-detect.")

    if chapter_naming == "preset" and num is not None:
        return num, f"Chapter {num:g}"

    title = None
    parts = name_without_ext.split(' - ', 1)
    
    if len(parts) > 1:
        split_idx = name_without_ext.find(' - ')
        part0_has_num = match.start() < split_idx if match else False
            
        if part0_has_num:
            title = parts[1].strip()
        else:
            title = parts[0].strip()
            if match:
                remaining = parts[1].replace(match.group(0), '').strip(' -_')
                if remaining:
                    title = f"{title} - {remaining}"
    else:
        if match:
            title = name_without_ext.replace(match.group(0), '').strip(' -_')
            if not title: 
                title = None
        else:
            title = None

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
            "filepath": filepath,
            "filename": filename,
            "number": num,
            "title": title,
            "size": os.path.getsize(filepath)
        })
        
    files_data.sort(key=lambda x: x["number"])
    return files_data

def validate_session(session):
    res = session.get(f"{BASE_URL}/api/profile", timeout=30)
    if res.status_code == 200:
        data = res.json()
        if "profile" in data and "email" in data["profile"]:
            return data['profile']['email']
    return None

def search_manga(query, session):
    url = f"{BASE_URL}/search.data?search={query}"
    res = session.get(url, timeout=30)
    if res.status_code != 200: return []
    try: arr = res.json()
    except: return []
        
    mangas = []
    for item in arr:
        if isinstance(item, dict):
            decoded = {}
            for k, v in item.items():
                if k.startswith('_') and k[1:].isdigit():
                    key_idx = int(k[1:])
                    if key_idx < len(arr):
                        key_str = arr[key_idx]
                        val = arr[v] if isinstance(v, int) and v < len(arr) else v
                        decoded[key_str] = val
                else: decoded[k] = v
            
            if "id" in decoded and "title" in decoded and isinstance(decoded["id"], int):
                if "photo" in decoded or "status" in decoded: mangas.append(decoded)
                    
    seen = set()
    return [m for m in mangas if not (m["id"] in seen or seen.add(m["id"]))]

def search_groups(query, session):
    res = session.get(f"{BASE_URL}/api/groups?q={query}&limit=25", timeout=30)
    if res.status_code != 200: return []
    try: return res.json().get("groups", [])
    except: return []

# --- Worker Function for TUS ---
def upload_file_tus_worker(session, renderer, file_info, manga_id, group_ids, upload_type, batch_id, language, scanlator_name):
    filename = file_info["filename"]
    filepath = file_info["filepath"]
    size = file_info["size"]
    
    tus_metadata = {
        "manga_id": manga_id,
        "chapter_number": "0" if upload_type == "volume" else file_info["number"],
        "language": language,
        "group_ids": group_ids,
        "group_id": group_ids[0] if group_ids else 0,
        "upload_type": upload_type,
        "batch_id": batch_id,
        "name": filename,
        "type": "application/zip",
        "filetype": "application/zip",
        "filename": filename
    }
    
    if upload_type == "volume": tus_metadata["volume_number"] = file_info["number"]
    if file_info.get("title"): tus_metadata["chapter_title"] = file_info["title"]
    if scanlator_name: tus_metadata["scanlator_name"] = scanlator_name

    encoded_metadata = encode_tus_metadata(tus_metadata)
    headers = {"Tus-Resumable": "1.0.0", "Upload-Length": str(size), "Upload-Metadata": encoded_metadata}

    for attempt in range(MAX_RETRIES):
        try:
            renderer.update_chapter_status(filename, "Creating upload...", 0.0)
            res = session.post(TUS_ENDPOINT, headers=headers, timeout=30)
            res.raise_for_status()
            upload_location = res.headers.get("Location")
            if not upload_location: raise ValueError("No Location header")
            break
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                renderer.update_chapter_status(filename, f"Create Err... Retrying", 0.0)
                time.sleep(RETRY_DELAY)
            else:
                return {"key": filename, "success": False, "error": f"Init failed: {str(e)[:30]}"}

    chunk_size = int(20 * 1024 * 1024)
    offset = 0
    
    try:
        with open(filepath, 'rb') as f:
            while offset < size:
                f.seek(offset)
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                
                patch_headers = {
                    "Tus-Resumable": "1.0.0",
                    "Upload-Offset": str(offset),
                    "Content-Type": "application/offset+octet-stream",
                }
                
                try:
                    renderer.update_chapter_status(filename, "Uploading...", offset/size)
                    patch_res = session.patch(upload_location, headers=patch_headers, data=chunk, timeout=60)
                    
                    if patch_res.status_code == 204:
                        offset += len(chunk)
                        continue
                    elif patch_res.status_code in RETRYABLE_STATUSES:
                        raise requests.exceptions.HTTPError(f"HTTP {patch_res.status_code}")
                    else:
                        return {"key": filename, "success": False, "error": f"HTTP {patch_res.status_code}"}
                except Exception:
                    resynced = False
                    for attempt in range(MAX_RETRIES):
                        renderer.update_chapter_status(filename, "Network Err... Resyncing", offset/size)
                        time.sleep(RETRY_DELAY)
                        try:
                            head_res = session.head(upload_location, headers={"Tus-Resumable": "1.0.0"}, timeout=30)
                            if head_res.status_code == 200:
                                server_offset = int(head_res.headers.get("Upload-Offset", 0))
                                offset = server_offset
                                resynced = True
                                break
                        except Exception:
                            pass
                            
                    if not resynced:
                        return {"key": filename, "success": False, "error": "Chunk failed & unable to resync offset"}
                            
    except Exception as e:
        return {"key": filename, "success": False, "error": str(e)[:30]}
        
    renderer.update_chapter_status(filename, "✅ Uploaded", 1.0)
    return {"key": filename, "success": True}

def print_files_table(files, upload_type):
    total_size = sum(f["size"] for f in files)
    size_mb = total_size / (1024 * 1024)

    print_success(f"Found {len(files)} file(s)  ({size_mb:.1f} MB total)\n")

    col_file  = max((len(f["filename"]) for f in files), default=8)
    col_file  = max(col_file, 8)
    col_num   = 10
    col_title = 30

    header = (
        f"  {'Filename':<{col_file}}  "
        f"{'Number':<{col_num}}  "
        f"{'Title':<{col_title}}  "
        f"{'Size':>10}"
    )
    print(f"{Colors.OKCYAN}{header}{Colors.RESET}")
    print(f"  {'-' * col_file}  {'-' * col_num}  {'-' * col_title}  {'-' * 10}")

    for f in files:
        num_str   = str(f["number"])
        title_str = f["title"] if f["title"] else "-"
        sz_str    = f"{f['size'] / (1024 * 1024):.2f} MB"
        print(
            f"  {f['filename']:<{col_file}}  "
            f"{num_str:<{col_num}}  "
            f"{title_str:<{col_title}}  "
            f"{sz_str:>10}"
        )
    print("")


def run_dry_run():
    print(f"{Colors.HEADER}{Colors.BOLD}")
    print("========================================")
    print("   MangaDot.net Batch Uploader          ")
    print("   *** DRY RUN MODE (no upload) ***     ")
    print("========================================")
    print(f"{Colors.RESET}")

    while True:
        prompt_txt = "Enter the directory path containing your .cbz/.zip files"
        if os.path.isdir(DEFAULT_CHAPTERS_DIR):
            directory = prompt(prompt_txt, default=DEFAULT_CHAPTERS_DIR)
        else:
            directory = prompt(prompt_txt)
        if os.path.isdir(directory):
            break
        print_error("Directory does not exist. Please try again.")

    upload_type_choice = prompt("Upload type? (1) Chapter  (2) Volume", default="1")
    upload_type = "volume" if upload_type_choice == "2" else "chapter"

    chapter_naming = "extract"
    custom_regex = None
    if upload_type == "chapter":
        naming_choice = prompt("Chapter naming format? (1) Auto-detect title  (2) Force 'Chapter X'  (3) Custom regex", default="2")
        if naming_choice == "2":
            chapter_naming = "preset"
        elif naming_choice == "3":
            chapter_naming = "custom"
            print_info("Regex Tip: If your regex has parentheses (Group 1), that group becomes the title. Otherwise, the whole match is used.")
            custom_regex = prompt("Enter your regex pattern")
        else:
            chapter_naming = "extract"

    print("\n" + "-"*40 + "\n")
    print_info("Scanning directory for files...")
    files = get_files_in_dir(directory, upload_type, chapter_naming, custom_regex)
    if not files:
        print_error("No valid .cbz or .zip files found in the directory.")
        sys.exit(1)

    print_files_table(files, upload_type)

    numbers = [f["number"] for f in files]
    int_numbers = sorted(list(set(int(n) for n in numbers if n == int(n))))
    
    missing = []
    if len(int_numbers) > 1:
        for i in range(len(int_numbers) - 1):
            if int_numbers[i+1] - int_numbers[i] > 1:
                missing.extend(range(int_numbers[i] + 1, int_numbers[i+1]))
                
    if missing:
        term = "chapters" if upload_type == "chapter" else "volumes"
        if len(missing) <= 15:
            missing_str = ", ".join(map(str, missing))
            print_warning(f"Missing {term} detected in sequence: {missing_str}")
        else:
            print_warning(f"Missing {term} detected: {len(missing)} {term} are missing between {missing[0]} and {missing[-1]}.")
        print_warning("Please verify this is intentional before proceeding.\n")

    print(f"{Colors.OKGREEN}[Dry run complete — no files were uploaded.]{Colors.RESET}")
    input(f"\n{Colors.WARNING}Press Enter to exit...{Colors.RESET}")
    sys.exit(0)

def process_uploads(files_to_upload, req_session, manga_id, group_ids, upload_type, language, scanlator_name, thread_count):
    chunks = [files_to_upload[i:i + MAX_BATCH_SIZE] for i in range(0, len(files_to_upload), MAX_BATCH_SIZE)]
    
    file_keys = [f["filename"] for f in files_to_upload]
    renderer = UIRenderer(file_keys)
    renderer.start()
    
    failed_chapters = []

    for chunk_idx, chunk in enumerate(chunks, 1):
        chapters_payload = []
        for f in chunk:
            chapters_payload.append({
                "chapter_number": f["number"] if upload_type == "chapter" else 0,
                "volume_number": f["number"] if upload_type == "volume" else None,
                "chapter_title": f["title"]
            })
            
        init_payload = {
            "manga_id": manga_id,
            "language": language,
            "group_ids": group_ids,
            "type": upload_type,
            "scanlator_name": scanlator_name,
            "chapters": chapters_payload
        }
        
        try:
            res = req_session.post(BATCH_INIT_ENDPOINT, json=init_payload, timeout=600)
            res.raise_for_status()
            batch_data = res.json()
            if not batch_data.get("success"): raise Exception(str(batch_data))
            batch_id = batch_data["batch_id"]
        except Exception as e:
            for f in chunk: 
                renderer.update_chapter_status(f["filename"], f"❌ Batch Init Failed", 1.0)
                failed_chapters.append(f["filename"])
            continue

        with concurrent.futures.ThreadPoolExecutor(max_workers=thread_count) as executor:
            futures = [executor.submit(
                upload_file_tus_worker, req_session, renderer, f, manga_id, group_ids, upload_type, batch_id, language, scanlator_name
            ) for f in chunk]
            
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                if not result['success']:
                    renderer.update_chapter_status(result['key'], f"❌ {result['error']}", 1.0)
                    failed_chapters.append(result['key'])

        try:
            comp_res = req_session.post(f"{BASE_URL}/api/uploads/batch/{batch_id}/complete", timeout=600)
            comp_res.raise_for_status()
        except Exception as e:
            pass
            
    sys.stdout.write("\n" * 2)
    sys.stdout.flush()
    
    return failed_chapters    

def main():
    parser = argparse.ArgumentParser(description="MangaDot.net Batch Uploader")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scan a directory and preview parsed chapters without logging in or uploading anything."
    )
    args, _ = parser.parse_known_args()

    if args.dry_run:
        run_dry_run()

    print(f"{Colors.HEADER}{Colors.BOLD}")
    print("========================================")
    print("      MangaDot.net Batch Uploader       ")
    print("========================================")
    print(f"{Colors.RESET}")

    req_session = requests.Session()
    req_session.headers.update({
        "Origin": BASE_URL,
        "Referer": f"{BASE_URL}/"
    })

    no_retry_adapter = HTTPAdapter(max_retries=0)
    req_session.mount("https://", no_retry_adapter)
    req_session.mount("http://", no_retry_adapter)
    
    supported_browsers = {
        "1": ("chrome", rookiepy.chrome),
        "2": ("firefox", rookiepy.firefox),
        "3": ("brave", rookiepy.brave),
        "4": ("edge", rookiepy.edge),
        "5": ("opera", rookiepy.opera),
        "6": ("vivaldi", rookiepy.vivaldi)
    }
    
    current_browser = "firefox"
    
    # ── COOKIE RE-EXTRACTION SYSTEM ──
    def extract_and_validate_session(browser_name):
        print_info(f"Attempting to extract cookies from {browser_name.title()}...")
        selected_ua = get_dynamic_user_agent(browser_name)
        req_session.headers.update({"User-Agent": selected_ua})
        
        try:
            req_session.cookies.clear()
            get_cookies_fn = next((fn for name, fn in supported_browsers.values() if name == browser_name), None)
            
            if get_cookies_fn:
                browser_cookies = get_cookies_fn(domains=["mangadot.net", ".mangadot.net"])
                if browser_cookies:
                    for cookie in browser_cookies:
                        req_session.cookies.set(cookie['name'], cookie['value'], domain=cookie['domain'])
                    
                    print_info("Validating session with Mangadot...")
                    email = validate_session(req_session)
                    if email:
                        print_success(f"Successfully authenticated as: {email}")
                        return True
                    else:
                        print_warning("Cookies extracted, but session validation failed (expired/unauthorized).")
                else:
                    print_warning(f"No Mangadot.net cookies found in {browser_name.title()}.")
        except Exception as e:
            print_warning(f"Failed to extract cookies from {browser_name.title()}: {e}")
            print_warning(f"Note: Make sure the browser is fully CLOSED before continuing.")
        return False

    # First Authentication Execution
    while True:
        if extract_and_validate_session(current_browser):
            break
        
        print_info("\nAuthentication failed. Please select an option to retry:")
        for key, (name, _) in supported_browsers.items():
            active_marker = f" {Colors.OKCYAN}(active){Colors.RESET}" if name == current_browser else ""
            print(f"  [{key}] {name.title()}{active_marker}")
        print("  [q] Quit script")
        
        choice = prompt("Select an option", default="2").lower()
        if choice == 'q':
            print_info("Exiting script.")
            sys.exit(0)
        elif choice in supported_browsers:
            current_browser = supported_browsers[choice][0]
        else:
            print_error("Invalid selection. Defaulting back to Firefox.")
            current_browser = "firefox"

    print("\n" + "-"*40 + "\n")

    while True:
        prompt_txt = "Enter the directory path containing your .cbz/.zip files"
        if os.path.isdir(DEFAULT_CHAPTERS_DIR):
            directory = prompt(prompt_txt, default=DEFAULT_CHAPTERS_DIR)
        else:
            directory = prompt(prompt_txt)
            
        if os.path.isdir(directory): break
        print_error("Directory does not exist. Please try again.")

    # ── METADATA AUTO-SCAN & PRE-POPULATION SYSTEM ──
    # Extract just the parent folder name from the input path to use as a fallback guess
    guessed_title = Path(directory).name if directory else ""

    manga_id = None
    while not manga_id:
        m_input = prompt("Search Manga by Title, or enter ID directly", default=guessed_title)
        
        # If it's a numeric value, parse directly as the Target Manga ID
        if m_input.isdigit():
            manga_id = int(m_input)
            break
            
        # Treat as search query strings
        print_info(f"Searching MangaDot for title matches: '{m_input}'...")
        results = search_manga(m_input, req_session)
        if not results:
            print_warning("No matching manga titles found on MangaDot. Try another search query.")
            guessed_title = None # Force raw input requirements if guess was bad
            continue
            
        for i, m in enumerate(results): 
            print(f"  [{i+1}] {m['title']} (ID: {m['id']})")
            
        sel = prompt(f"Select a number 1-{len(results)} (or type 's' to search again)", default="1")
        if sel.lower() == 's': 
            guessed_title = None
            continue
        try:
            sel_idx = int(sel) - 1
            manga_id = results[sel_idx]['id']
            print_success(f"Selected Manga: {results[sel_idx]['title']} (ID: {manga_id})")
        except (ValueError, IndexError): 
            print_error("Invalid numerical selection.")

    req_session.headers.update({"Referer": f"{BASE_URL}/manga/{manga_id}/upload"})

    upload_type_choice = prompt("Upload type? (1) Chapter (2) Volume", default="1")
    upload_type = "volume" if upload_type_choice == "2" else "chapter"

    chapter_naming = "extract"
    custom_regex = None
    if upload_type == "chapter":
        naming_choice = prompt("Chapter naming format? (1) Auto-detect title  (2) Force 'Chapter X'  (3) Custom regex", default="2")
        if naming_choice == "2":
            chapter_naming = "preset"
        elif naming_choice == "3":
            chapter_naming = "custom"
            custom_regex = prompt("Enter your regex pattern")
        else:
            chapter_naming = "extract"

    language = prompt("Language code", default="en")

    is_group = prompt("Upload as a Group? (y/n)", default="y").lower().startswith('y')
    group_ids = []
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
            for i, g in enumerate(results): 
                print(f"  [{i+1}] {g['name']} (ID: {g['id']})")
                
            sel = prompt(f"Select a number 1-{len(results)} (or type 's' to search again)", default="1")
            if sel.lower() == 's': continue
            try:
                sel_idx = int(sel) - 1
                group_ids = [results[sel_idx]['id']]
                print_success(f"Selected Group: {results[sel_idx]['name']} (ID: {group_ids[0]})")
            except (ValueError, IndexError): 
                print_error("Invalid numerical selection.")
    else:
        scanlator_name = prompt("Enter your individual Scanlator Name")

    while True:
        try:
            threads_str = prompt("Enter number of parallel uploads (1-10)", default="3")
            thread_count = int(threads_str)
            if 1 <= thread_count <= 10: break
            else: print_error("Please enter a number between 1 and 10.")
        except ValueError: print_error("Invalid input.")

    print("\n" + "-"*40 + "\n")
    print_info("Scanning directory for files...")
    files = get_files_in_dir(directory, upload_type, chapter_naming, custom_regex)
    if not files:
        print_error("No valid .cbz or .zip files found in the directory.")
        sys.exit(1)

    print_files_table(files, upload_type)

    confirm = prompt("Proceed with upload? (y/n)", default="y").lower()
    if not confirm.startswith('y'):
        print_info("Upload aborted by user.")
        sys.exit(0)

    current_files_to_upload = files
    
    # ── RESILIENT RUNTIME RETRY STATE ──
    while True:
        failed_chapters = process_uploads(
            current_files_to_upload, req_session, manga_id, group_ids, upload_type, language, scanlator_name, thread_count
        )
        
        print(f"{Colors.OKCYAN}--- Operations step complete. ---{Colors.RESET}")

        if not failed_chapters:
            print(f"{Colors.OKGREEN}✅ All chapters were processed successfully!")
            if os.path.exists("failed.txt"):
                os.remove("failed.txt")
            break

        print(f"{Colors.FAIL}⚠️ {len(failed_chapters)} chapters failed or timed out.{Colors.RESET}")
        try:
            with open("failed.txt", "w", encoding="utf-8") as f:
                for chap in sorted(failed_chapters, key=natural_sort_key):
                    f.write(f"{chap}\n")
            print(f"Failed list updated in `failed.txt`.")
        except Exception as e:
            print(f"{Colors.FAIL}Could not write to `failed.txt`: {e}")

        # Hot-swap tracker storage array to scale exclusively on residual failures
        current_files_to_upload = [f for f in current_files_to_upload if f["filename"] in failed_chapters]

        print(f"\n{Colors.WARNING}🚨 UPLOAD PAUSED: Session token expired or closed out mid-upload.{Colors.RESET}")
        print("1. Open your browser and cleanly refresh/log into MangaDot.net to fetch a clean token.")
        print("2. CRITICAL: Close the browser window entirely so disk lock hooks are released.")
        
        # Let dying threads settle completely before parsing prompt
        time.sleep(1.5)
        flush_input_buffer()
        
        retry_choice = prompt("Ready to load fresh browser database cookies and resume remaining items? (y/n)", default="y").lower()
        if not retry_choice.startswith('y'):
            print_info("Exiting execution block. Remaining files are cataloged.")
            break
            
        print_info("Re-verifying updated runtime data cookies...")
        while True:
            if extract_and_validate_session(current_browser):
                print_success("Fresh storage session context established! Continuing batch upload operations...")
                break
            
            print_warning("No authorized active cookie dataset recognized yet from browser profile history.")
            
            time.sleep(1.5)
            flush_input_buffer()
            
            action = prompt("Type 'r' to try extracting cookies again, or 'q' to quit", default="r").lower()
            if action == 'q':
                sys.exit(0)

    # ── EMBEDDED METADATA DASHBOARD RENDER ──
    manga_url = f"{BASE_URL}/manga/{manga_id}"
    print(f"\n{Colors.OKCYAN}[*]{Colors.RESET} Fetching upload confirmation details...")
    
    try:
        api_res = req_session.get(f"{BASE_URL}/api/manga/{manga_id}", timeout=15)
        if api_res.status_code == 200:
            manga_data = api_res.json().get("manga", {})
            
            title = manga_data.get("title", "Unknown Title")
            alt_titles = manga_data.get("alt_titles", [])
            status = manga_data.get("status", "N/A")
            description = manga_data.get("description", "No description available.")
            photo = manga_data.get("photo", "")
            
            clean_desc = re.sub(r'<[^>]*>', '', description)[:150] + "..." if description else "N/A"
            
            print("\n" + "=" * 50)
            print(f"{Colors.HEADER}{Colors.BOLD}🎉 UPLOAD CONFIRMED ON MANGADOT{Colors.RESET}")
            print("=" * 50)
            print(f"  {Colors.BOLD}Title:{Colors.RESET}       {title}")
            if alt_titles:
                print(f"  {Colors.BOLD}Alt Title:{Colors.RESET}   {alt_titles[0] if isinstance(alt_titles, list) else alt_titles}")
            print(f"  {Colors.BOLD}Status:{Colors.RESET}      {status.upper()}")
            print(f"  {Colors.BOLD}Synopsis:{Colors.RESET}    {clean_desc}")
            if photo:
                cover_url = photo if photo.startswith("http") else f"{BASE_URL}{photo}"
                print(f"  {Colors.BOLD}Cover Art:{Colors.RESET}   {cover_url}")
            print("-" * 50)
            print(f"  {Colors.OKGREEN}{Colors.BOLD}Direct Link:{Colors.RESET} {manga_url}")
            print("=" * 50 + "\n")
        else:
            print(f"\n{Colors.OKCYAN}[*]{Colors.RESET} You can view your manga here: {manga_url}\n")
            
    except Exception as e:
        print_warning(f"Could not parse embedded metadata: {e}")
        print(f"\n{Colors.OKCYAN}[*]{Colors.RESET} You can view your manga here: {manga_url}\n")

    input(f"{Colors.WARNING}Press Enter to exit...{Colors.RESET}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n" + Colors.WARNING + "[!] Script interrupted by user." + Colors.RESET)
        sys.exit(0)