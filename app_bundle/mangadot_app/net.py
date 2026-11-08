"""Browser user-agent detection (local install + web fallback) and caching."""
import os
import re
import sys
import json
import platform
import subprocess
import threading
import logging
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import requests

from . import config as config_mod
from . import debugging

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

_UA_CACHE = {}
_UA_CACHE_LOCK = threading.Lock()

# How long a cached user-agent is trusted before we re-detect live, even if
# nothing has actually failed yet. This runs once a day so staleness
# self-corrects for every user on a plain schedule, not just for the one
# browser whose login happened to fail on a given day.
_UA_CACHE_MAX_AGE_SECONDS = 24 * 60 * 60

GENRE_TAXONOMY = {
    "Demographic": ["Josei", "Seinen", "Shoujo", "Shounen"],
    "Genre": [
        "Action", "Adventure", "Comedy", "Drama", "Fantasy", "Historical",
        "Horror", "Mecha", "Mystery", "Psychological", "Romance", "Sci-Fi",
        "Slice of Life", "Sports", "Supernatural", "Thriller", "Tragedy"
    ],
    "Theme & content": [
        "Cooking", "Demons", "Ecchi", "Harem", "Isekai", "Magic",
        "Martial Arts", "Medical", "Military", "Music", "School Life", "Webtoon"
    ],
    "More": [
        "Academy", "Acting", "Adult", "Aliens", "Animals", "Anthology",
        "Apocalypse", "Avant Garde", "Award Winning", "BDSM", "Boys Love",
        "Bully", "Business", "Child Abuse", "Child Neglect", "Comic",
        "Crime", "crossdressing", "Crossdressing", "Cultivation",
        "Delinquents", "Difficult Childhood", "dojinshi", "Doujinshi",
        "Erotica", "Female Protagonist", "Femdom", "Fight",
        "futanari on male", "futunari", "Gender Bender", "Genderswap",
        "Ghosts", "Girls Love", "Gore", "Gourmet", "Gyaru", "Hentai",
        "Hunters", "Idol", "Incest", "Loli", "Lolicon", "Mafia",
        "Magical Girls", "Mahou Shoujo", "Manga", "Manhua", "Manhwa",
        "Mature", "Medieval Area", "Monster Girls", "Monsters", "Myth",
        "Ninja", "Nobility", "Office Romance", "Office Worker",
        "Office Workers", "One Shot", "Otome", "Overpowered",
        "Philosophical", "playboy", "Police", "Politics",
        "Post-Apocalyptic", "Reincarnation", "Revenge", "Reverse Harem",
        "Royalty", "Samurai", "School", "Seinin", "Shota", "shotacon",
        "Shotacon", "Shoujo Ai", "Shounen Ai", "Smut", "Superhero",
        "Survival", "Suspense", "System", "Time Travel",
        "Traditional Games", "uncensored", "Vampires", "Video Games",
        "Villainess", "Virtual Reality", "War", "Workplace", "Wuxia",
        "Yaoi", "Yuri", "Zombies"
    ]
}

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
            "zen":     [(winreg.HKEY_CURRENT_USER,  r"SOFTWARE\Mozilla\Zen Browser", ""),
                        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Mozilla\Zen Browser", ""),
                        (winreg.HKEY_CURRENT_USER,  r"SOFTWARE\Zen Browser", ""),
                        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Zen Browser", ""),
                        (winreg.HKEY_CURRENT_USER,  r"SOFTWARE\Mozilla\Zen Browser", "CurrentVersion"),
                        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Mozilla\Zen Browser", "CurrentVersion")],
        }
        for hive, path, key in paths.get(browser, []):
            try:
                with winreg.OpenKey(hive, path) as k:
                    val, _ = winreg.QueryValueEx(k, key)
                    v = _clean_version(val)
                    if v: return v
            except OSError: continue
    except ImportError:
        return None  
    return None

def _read_zen_ini_version():
    """Fallback reader for Zen Browser milestone version from platform.ini or application.ini."""
    candidate_paths = [
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Zen Browser" / "platform.ini",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Zen Browser" / "platform.ini",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "zen" / "platform.ini",
    ]
    for p in candidate_paths:
        if p.exists() and p.is_file():
            try:
                content = p.read_text(encoding="utf-8", errors="ignore")
                m = re.search(r"Milestone\s*=\s*(\d+(?:\.\d+)*)", content)
                if m:
                    return _clean_version(m.group(1))
            except Exception:
                pass

    appdata_profiles = Path(os.environ.get("APPDATA", "")) / "zen" / "Profiles"
    if appdata_profiles.exists() and appdata_profiles.is_dir():
        for comp in appdata_profiles.glob("*/compatibility.ini"):
            try:
                content = comp.read_text(encoding="utf-8", errors="ignore")
                m = re.search(r"Milestone\s*=\s*(\d+(?:\.\d+)*)", content)
                if m:
                    return _clean_version(m.group(1))
            except Exception:
                pass
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
        if browser in ("firefox", "zen"): return f"Mozilla/5.0 ({arch_clause}; rv:{own_major}.0) Gecko/20100101 Firefox/{own_major}.0"
        if browser == "edge":    return f"Mozilla/5.0 ({arch_clause}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_major}.0.0.0 Safari/537.36 Edg/{own_major}.0.0.0"
        if browser == "opera":   return f"Mozilla/5.0 ({arch_clause}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_major}.0.0.0 Safari/537.36 OPR/{own_major}.0.0.0"
        if browser == "vivaldi": return f"Mozilla/5.0 ({arch_clause}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_major}.0.0.0 Safari/537.36 Vivaldi/{version}"
        return f"Mozilla/5.0 ({arch_clause}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_major}.0.0.0 Safari/537.36"
    elif sys.platform == 'darwin':
        mac_ver = _detect_macos_ver()
        if browser in ("firefox", "zen"): return f"Mozilla/5.0 (Macintosh; Intel Mac OS X {mac_ver}; rv:{own_major}.0) Gecko/20100101 Firefox/{own_major}.0"
        if browser == "edge":    return f"Mozilla/5.0 (Macintosh; Intel Mac OS X {mac_ver}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_major}.0.0.0 Safari/537.36 Edg/{own_major}.0.0.0"
        if browser == "opera":   return f"Mozilla/5.0 (Macintosh; Intel Mac OS X {mac_ver}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_major}.0.0.0 Safari/537.36 OPR/{own_major}.0.0.0"
        if browser == "vivaldi": return f"Mozilla/5.0 (Macintosh; Intel Mac OS X {mac_ver}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_major}.0.0.0 Safari/537.36 Vivaldi/{version}"
        return f"Mozilla/5.0 (Macintosh; Intel Mac OS X {mac_ver}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_major}.0.0.0 Safari/537.36"
    else:
        if browser in ("firefox", "zen"): return f"Mozilla/5.0 (X11; Linux x86_64; rv:{own_major}.0) Gecko/20100101 Firefox/{own_major}.0"
        if browser == "edge":    return f"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_major}.0.0.0 Safari/537.36 Edg/{own_major}.0.0.0"
        if browser == "opera":   return f"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_major}.0.0.0 Safari/537.36 OPR/{own_major}.0.0.0"
        if browser == "vivaldi": return f"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_major}.0.0.0 Safari/537.36 Vivaldi/{version}"
        return f"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_major}.0.0.0 Safari/537.36"

def get_dynamic_user_agent(browser, force_refresh=False):
    """Returns a plausible, cached user-agent string for `browser`...

    force_refresh=True skips both the in-memory and on-disk cache and runs
    live detection instead. Used when a cached UA has just been used to
    replay real cookies and the login still failed - a stale UA (e.g. Zen
    updating past whatever version was cached) can look identical to a
    genuinely invalid session, so a failed validate_session() is enough
    reason to stop trusting the cache once and re-detect.

    Independently of that, every cache entry also carries a `cached_at`
    timestamp and expires on its own after _UA_CACHE_MAX_AGE_SECONDS (one
    day). This covers users who never hit a failed login at all (a lenient
    site may not reject a mismatched UA outright) - without this, a stale
    entry could sit untouched indefinitely and only surface as a problem
    much later, in a context that no longer looks related to the cache.

    Entries written by older versions of this app are a bare string with no
    timestamp. Those are treated as already-expired the first time they're
    read here, so the cache self-heals on first run after an update with no
    migration step needed.
    """
    import time

    with _UA_CACHE_LOCK:
        if not force_refresh:
            if browser in _UA_CACHE:
                return _UA_CACHE[browser]

            cfg = config_mod.load_config()
            cached_uas = cfg.get("cached_user_agents", {})
            entry = cached_uas.get(browser)

            if isinstance(entry, dict) and entry.get("ua"):
                age = time.time() - entry.get("cached_at", 0)
                if age < _UA_CACHE_MAX_AGE_SECONDS:
                    _UA_CACHE[browser] = entry["ua"]
                    return entry["ua"]
                logging.debug(
                    "get_dynamic_user_agent: cached UA for %s is %.1f days old, re-detecting",
                    browser, age / 86400
                )
            elif isinstance(entry, str) and entry:
                # Old bare-string cache format, written before expiry existed.
                # No timestamp to check, so treat as expired and re-detect once.
                logging.debug(
                    "get_dynamic_user_agent: %s has an old-format cache entry with no "
                    "timestamp, treating as expired", browser
                )
        else:
            _UA_CACHE.pop(browser, None)
            logging.debug("get_dynamic_user_agent: force_refresh=True for %s, bypassing cache", browser)

    # Zen has no separate registry/plist entry of its own on most installs,
    # so fall back to reading Firefox's installed version as a stand-in -
    # but only when Zen's own version can't be determined directly. This
    # previously always substituted Firefox's version for Zen unconditionally,
    # which silently diverges from Zen's real version (Zen tracks its own
    # release cadence, independent of whatever Firefox happens to be
    # installed) and can produce a UA that doesn't match the browser that
    # actually created the session cookies being replayed.
    lookup_browser = browser
    version = None

    try:
        if sys.platform == 'win32':    version = _read_windows_registry(lookup_browser)
        elif sys.platform == 'darwin': version = _read_mac_plist(lookup_browser)
        else:                          version = _read_linux_version(lookup_browser)
    except (OSError, ValueError) as e:
        logging.debug("get_dynamic_user_agent: local version detection failed for %s: %s", lookup_browser, e)
        version = None

    if not version and browser == "zen":
        version = _read_zen_ini_version()
        if not version:
            # Fall back to Firefox's registry as a secondary stand-in
            lookup_browser = "firefox"
            try:
                if sys.platform == 'win32':    version = _read_windows_registry(lookup_browser)
                elif sys.platform == 'darwin': version = _read_mac_plist(lookup_browser)
                else:                          version = _read_linux_version(lookup_browser)
            except (OSError, ValueError) as e:
                logging.debug("get_dynamic_user_agent: Firefox fallback detection failed: %s", e)
                version = None

    if not version and lookup_browser in ("chrome", "edge", "firefox"):
        try:
            version = _fetch_web_version(lookup_browser, timeout=5)
        except (requests.exceptions.RequestException, json.JSONDecodeError, ValueError) as e:
            logging.debug("get_dynamic_user_agent: web version fetch failed for %s: %s", lookup_browser, e)
            version = None

    chromium_version = _get_chromium_version_for_browser(lookup_browser)
    ua = _build_user_agent(lookup_browser, version, chromium_version)

    with _UA_CACHE_LOCK:
        _UA_CACHE[browser] = ua
        try:
            fresh_config = config_mod.load_config()
            cached_uas = fresh_config.get("cached_user_agents", {})
            cached_uas[browser] = {"ua": ua, "cached_at": time.time()}
            fresh_config["cached_user_agents"] = cached_uas
            config_mod.save_config(fresh_config)
        except OSError as e:
            logging.debug("get_dynamic_user_agent: failed to persist UA cache: %s", e)

    return ua

BASE_URL = "https://mangadot.net"

def create_base_session(proxy_url=None, proxy_no_verify=False, debug_enabled=False):
    import urllib3

    session = requests.Session()
    session.headers.update({
        "Origin": "https://mangadot.net",
        "Referer": "https://mangadot.net/"
    })

    if proxy_url:
        session.proxies.update({"http": proxy_url, "https": proxy_url})
    
    if proxy_no_verify:
        session.verify = False
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        
    if debug_enabled:
        session.hooks['response'].append(debugging.log_request_response)

    return session

def fetch_image_bytes(session, url, timeout=10):
    if not url:
        return None
    try:
        if session:
            resp = session.get(url, timeout=timeout)
        else:
            resp = requests.get(url, timeout=timeout)
        if resp.status_code == 200:
            return resp.content
    except requests.exceptions.RequestException:
        pass
    return None

def build_uploaded_chapter_map(session, manga_id, upload_type, user_id):
    import time
    chapter_map = {}
    base_check_url = (
        f"{BASE_URL}/api/manga/{manga_id}/volumes"
        if upload_type == "volume"
        else f"{BASE_URL}/api/manga/{manga_id}/chapters/list"
    )

    page = 1
    seen_ids = set()

    while page <= 100:
        try:
            res = session.get(
                f"{base_check_url}?page={page}&limit=100&_t={int(time.time())}",
                headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
                timeout=10
            )
            if res.status_code != 200:
                break
            data = res.json()
        except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
            logging.debug("build_uploaded_chapter_map: error on page %d: %s", page, e)
            break

        if isinstance(data, dict):
            items = data.get("volumes", data.get("chapters", []))
        elif isinstance(data, list):
            items = data
        else:
            items = []

        if not items:
            break

        new_items_found = False
        for item in items:
            if not isinstance(item, dict):
                continue

            try:
                raw_num = item.get("volume_number" if upload_type == "volume" else "chapter_number")
                if raw_num is None:
                    continue

                num_str = f"{round(float(raw_num), 4):g}"
                item_id = item.get("id")

                if item_id:
                    if item_id not in seen_ids:
                        seen_ids.add(item_id)
                        new_items_found = True

                    uploader_obj = item.get("uploader") if isinstance(item.get("uploader"), dict) else {}
                    uploader_id = item.get("uploaded_by") or item.get("uploader_id") or item.get("user_id") or uploader_obj.get("id")

                    if num_str not in chapter_map:
                        chapter_map[num_str] = item_id
                    elif str(uploader_id) == str(user_id):
                        chapter_map[num_str] = item_id
            except (ValueError, TypeError):
                pass

        if not new_items_found:
            break
        page += 1

    return chapter_map

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
        logging.error(f"Network error while looking up manga ID {manga_id}: {e}")
    except json.JSONDecodeError as e:
        logging.error(f"Unexpected response while looking up manga ID {manga_id}: {e}")
    return None, None

def _unpack_str(val, default=""):
    if isinstance(val, dict):
        return str(val.get("en") or (next(iter(val.values())) if val else default))
    return str(val) if val is not None else default

def _unpack_name_list(val):
    if not val:
        return ""
    if isinstance(val, str):
        try:
            val = json.loads(val)
        except (json.JSONDecodeError, TypeError):
            return val
    if isinstance(val, list):
        return ", ".join(str(v) for v in val if v)
    return str(val)

def fetch_manga_full_details(manga_id, session):
    try:
        api_res = session.get(f"{BASE_URL}/api/manga/{manga_id}", timeout=15)
        if api_res.status_code != 200:
            return None
        manga_data = api_res.json().get("manga", {})
    except requests.exceptions.RequestException as e:
        logging.debug("fetch_manga_full_details(%s): network error: %s", manga_id, e)
        return None
    except json.JSONDecodeError as e:
        logging.debug("fetch_manga_full_details(%s): bad JSON response: %s", manga_id, e)
        return None

    title = _unpack_str(manga_data.get("title"), "Unknown Title")
    status = _unpack_str(manga_data.get("status"), "N/A")
    raw_desc = _unpack_str(manga_data.get("description"), "No description available.")
    photo = manga_data.get("photo", "")

    stripped = re.sub(r'<[^>]*>', '', raw_desc) if raw_desc else ""
    clean_desc = (stripped[:200] + "...") if len(stripped) > 200 else (stripped if stripped else "N/A")

    raw_alts = manga_data.get("alt_titles", [])
    alt_titles = []
    if isinstance(raw_alts, list):
        alt_titles = [_unpack_str(a) for a in raw_alts if a]
    elif raw_alts:
        alt_titles = [_unpack_str(raw_alts)]

    raw_genres = manga_data.get("genres", [])
    genre_names = []
    if isinstance(raw_genres, list):
        for g in raw_genres:
            val = _unpack_str(g.get("name") or g.get("title") or g if isinstance(g, dict) else g)
            if val and val not in genre_names:
                genre_names.append(val)

    mangabaka_id = (
        manga_data.get("mangabaka_id")
        or manga_data.get("baka_id")
        or manga_data.get("mangaupdates_id")
        or (manga_data.get("external_links") or {}).get("mangabaka")
        or (manga_data.get("external_links") or {}).get("baka")
    )
    mangabaka_url = f"https://mangabaka.org/{mangabaka_id}" if mangabaka_id else None

    origin = _unpack_str(manga_data.get("country_of_origin")) or None
    authors = _unpack_name_list(manga_data.get("authors")) or None
    artists = _unpack_name_list(manga_data.get("artists")) or None

    avg_rating = manga_data.get("avg_rating")
    rating_count = manga_data.get("rating_count")
    rating_display = None
    if avg_rating is not None:
        try:
            rating_display = f"{float(avg_rating):g}/10"
        except (TypeError, ValueError):
            rating_display = None
        if rating_display and rating_count is not None:
            rating_display += f" ({rating_count})"

    return {
        "title": title,
        "alt_title": alt_titles[0] if alt_titles and alt_titles[0] else None,
        "alt_titles": alt_titles,
        "status": status,
        "genres": genre_names,
        "description": clean_desc,
        "cover_url": to_full_cover_url(photo),
        "manga_url": f"{BASE_URL}/manga/{manga_id}",
        "mangabaka_url": mangabaka_url,
        "origin": origin,
        "authors": authors,
        "artists": artists,
        "rating": rating_display,
    }

def _scrape_profile_stats_html(session, username):
    try:
        res = session.get(f"{BASE_URL}/user/{username}", timeout=(5, 15))
        if res.status_code != 200:
            logging.debug("_scrape_profile_stats_html: HTTP %s for /user/%s", res.status_code, username)
            return {}
        html = res.text
    except requests.exceptions.RequestException as e:
        logging.debug("_scrape_profile_stats_html: network error: %s", e)
        return {}

    def extract(pattern, cast_int=False):
        match = re.search(pattern, html, re.DOTALL)
        if not match:
            return None
        val = match.group(1).strip()
        return int(val.replace(",", "")) if cast_int else val

    def extract_num_then_label(label_text):
        """Matches stats like:
        <span class="pf-num ...">1,319</span> series
        or <span ...>60,348</span> tracked
        or <b>41,799</b> read here
        or bare 1,319 series
        """
        pattern_tag = (
            r'<[a-zA-Z0-9]+[^>]*>([\d,]+)</[a-zA-Z0-9]+>\s*'
            r'(?:<!--\s*-->)?\s*' + re.escape(label_text)
        )
        val = extract(pattern_tag, cast_int=True)
        if val is not None:
            return val

        pattern_bare = r'(?:^|[>\s])([\d,]+)\s*(?:<!--\s*-->)?\s*' + re.escape(label_text)
        return extract(pattern_bare, cast_int=True)

    stats = {}

    series = extract_num_then_label("series")
    if series is not None:
        stats["series"] = series

    tracked = extract_num_then_label("tracked")
    if tracked is not None:
        stats["tracked"] = tracked

    read_here = extract_num_then_label("read here")
    if read_here is not None:
        stats["read_here"] = read_here

    chapters = extract_num_then_label("chapters")
    if chapters is not None:
        stats["chapters"] = chapters

    level = extract(r'Lv\s*(?:<[^>]+>)?\s*(\d+)\s*(?:</[^>]+>)?', cast_int=True)
    if level is not None:
        stats["level"] = level

    rank_match = re.search(
        r'Lv\s*(?:<[^>]+>)?\s*\d+\s*(?:</[^>]+>)?\s*(?:<!--\s*-->)?\s*([A-Za-z]+)',
        html
    )
    if rank_match:
        stats["rank"] = rank_match.group(1).strip()

    followers = extract_num_then_label("followers")
    if followers is not None:
        stats["followers"] = followers

    following = extract_num_then_label("following")
    if following is not None:
        stats["following"] = following

    return stats

def _fetch_user_stats_api(session, username):
    """Fetches user stats from /api/users/{username} which returns
    live profile stats, XP, level, rank, tracked, read_here, followers, following, etc.
    Falls back gracefully if the endpoint returns non-200.
    """
    if not username:
        return {}
    try:
        res = session.get(f"{BASE_URL}/api/users/{username}", timeout=(5, 15))
        if res.status_code == 200:
            payload = res.json()
            data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
            user_obj = data.get("user") or {}
            xp_obj = data.get("xp") or {}
            stats_obj = data.get("stats") or {}
            follow_obj = (data.get("follow") or {}).get("counts") or {}
            streak_obj = data.get("streak") or {}

            stats = {
                "level": xp_obj.get("level"),
                "rank": xp_obj.get("level_name"),
                "series": stats_obj.get("total_manga", 0),
                "tracked": stats_obj.get("chapters_read", 0),
                "read_here": stats_obj.get("chapters_credited", 0),
                "followers": follow_obj.get("followers", 0),
                "following": follow_obj.get("following", 0),
                "streak": streak_obj.get("current_streak", 0),
                "completed": stats_obj.get("manga_completed", 0),
            }
            if user_obj.get("display_name"):
                stats["display_name"] = user_obj["display_name"]
            if user_obj.get("bio"):
                stats["bio"] = user_obj["bio"]
            if user_obj.get("profile_pic"):
                stats["avatar"] = user_obj["profile_pic"]
            if user_obj.get("background_pic"):
                stats["cover"] = user_obj["background_pic"]
            return stats
        logging.debug("_fetch_user_stats_api: HTTP %s for /api/users/%s", res.status_code, username)
    except requests.exceptions.RequestException as e:
        logging.debug("_fetch_user_stats_api: network error: %s", e)
    except (json.JSONDecodeError, ValueError) as e:
        logging.debug("_fetch_user_stats_api: invalid json: %s", e)

    return _scrape_profile_stats_html(session, username)

def _fetch_profile_identity(session):
    try:
        res = session.get(f"{BASE_URL}/api/profile", timeout=(5, 15))
        if res.status_code != 200:
            return None
        data = res.json()
        return data.get("profile") if isinstance(data.get("profile"), dict) else data
    except requests.exceptions.RequestException as e:
        logging.debug("_fetch_profile_identity: network error: %s", e)
        return None
    except json.JSONDecodeError as e:
        logging.debug("_fetch_profile_identity: unexpected (non-JSON) response: %s", e)
        return None

def fetch_profile_stats(session, username=None):
    if username:
        with ThreadPoolExecutor(max_workers=2) as pool:
            identity_future = pool.submit(_fetch_profile_identity, session)
            stats_future = pool.submit(_fetch_user_stats_api, session, username)
            profile = identity_future.result()
            stats = stats_future.result()
    else:
        profile = _fetch_profile_identity(session)
        if not profile:
            return None
        scraped_username = profile.get("username", "")
        stats = _fetch_user_stats_api(session, scraped_username) if scraped_username else {}

    if not profile:
        return None

    resolved_username = profile.get("username", "") or username or ""
    avatar = stats.get("avatar") or profile.get("profile_pic") or profile.get("avatar") or profile.get("photo") or profile.get("avatar_url")
    cover = stats.get("cover") or profile.get("background_pic") or profile.get("cover_pic") or profile.get("banner") or profile.get("cover_url") or profile.get("cover")
    display_name = stats.get("display_name") or profile.get("display_name") or profile.get("nickname") or resolved_username
    bio = stats.get("bio") or profile.get("bio", "")
    return {
        "username": resolved_username,
        "display_name": display_name,
        "avatar_url": to_full_cover_url(avatar) if avatar else None,
        "cover_url": to_full_cover_url(cover) if cover else None,
        "bio": bio,
        "level": stats.get("level", profile.get("level")),
        "rank": stats.get("rank") or profile.get("rank", ""),
        "role": profile.get("role") or stats.get("role", "READER"),
        "series": stats.get("series", profile.get("series", 0)),
        "tracked": stats.get("tracked", profile.get("tracked") or profile.get("manga_tracked", 0)),
        "read_here": stats.get("read_here", profile.get("read_here") or profile.get("chapters_read", 0)),
        "chapters": stats.get("chapters", profile.get("chapters", 0)),
        "followers": stats.get("followers", profile.get("followers", 0)),
        "following": stats.get("following", profile.get("following", 0)),
        # Kept for backward compatibility with anything still reading the
        # old shape - the current site header no longer exposes these, so
        # they'll stay 0 unless a future page brings them back.
        "manga_tracked": stats.get("tracked") or profile.get("manga_tracked") or 0,
        "chapters_read": stats.get("read_here") or profile.get("chapters_read", 0),
        "manga_completed": stats.get("completed") or profile.get("manga_completed", 0),
        "tracked_count": stats.get("tracked") or profile.get("tracked_count") or 0,
        "streak": stats.get("streak") or profile.get("streak", 0),
    }

def search_manga(query, session):
    try:
        res = session.get(f"{BASE_URL}/search.data", params={"search": query}, timeout=(10, 30))
        if res.status_code != 200: return []
        arr = res.json()
    except requests.exceptions.RequestException as e:
        logging.error(f"Network error while searching for manga: {e}")
        return []
    except json.JSONDecodeError as e:
        logging.error(f"Search returned an unreadable response: {e}")
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

    seen = set()
    return [m for m in mangas if not (m["id"] in seen or seen.add(m["id"]))]

def _normalize_mangabaka_url(url_or_id):
    if not url_or_id:
        return ""
    s = str(url_or_id).strip()
    if s.isdigit():
        return f"https://mangabaka.org/manga/{s}/manga"
    m = re.search(r"mangabaka\.org/(?:series/|manga/)?(\d+)(?:/([^/?#]+))?", s, re.IGNORECASE)
    if m:
        mb_id = m.group(1)
        slug = m.group(2) or "manga"
        return f"https://mangabaka.org/manga/{mb_id}/{slug}"
    return s

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

COVER_UPLOAD_MAX_BYTES = 10 * 1024 * 1024

def _as_upload_file(value):
    """Normalizes a (filename, bytes, mime) upload input; None when unusable.
    If image content exceeds COVER_UPLOAD_MAX_BYTES (10 MB), it automatically
    resizes and compresses the image using PIL so it is never dropped."""
    if not isinstance(value, (tuple, list)) or len(value) != 3:
        return None
    filename, content, mime = value
    if not isinstance(content, (bytes, bytearray)) or not content:
        return None
    if not isinstance(mime, str) or not mime.lower().startswith("image/"):
        return None
    if len(content) > COVER_UPLOAD_MAX_BYTES:
        try:
            import io
            from PIL import Image
            img = Image.open(io.BytesIO(content))
            max_dim = 2400
            if max(img.size) > max_dim:
                ratio = max_dim / max(img.size)
                new_size = (max(1, int(img.size[0] * ratio)), max(1, int(img.size[1] * ratio)))
                img = img.resize(new_size, Image.Resampling.LANCZOS)
            out = io.BytesIO()
            if img.mode in ("RGBA", "P"):
                img.save(out, format="WEBP", quality=85)
                mime = "image/webp"
                filename = f"{str(filename or 'cover').rsplit('.', 1)[0]}.webp"
            else:
                img.convert("RGB").save(out, format="JPEG", quality=85, optimize=True)
                mime = "image/jpeg"
                filename = f"{str(filename or 'cover').rsplit('.', 1)[0]}.jpg"
            compressed = out.getvalue()
            logging.info("Auto-compressed oversized cover/banner from %d bytes to %d bytes", len(content), len(compressed))
            content = compressed
        except Exception as e:
            logging.warning("Failed to auto-compress oversized cover/banner (%d bytes): %s", len(content), e)
    if len(content) > COVER_UPLOAD_MAX_BYTES:
        logging.warning("cover/banner upload skipped: %d bytes exceeds %d MB cap",
                        len(content), COVER_UPLOAD_MAX_BYTES // (1024 * 1024))
        return None
    return (str(filename or "cover"), bytes(content), mime)

def build_create_payload(metadata):
    """Splits a create payload into a multipart or JSON request body.
    Returns (True, form_data, files) when usable cover_bytes/banner_bytes
    entries are present, else (False, json_payload, {})."""
    src = dict(metadata or {})
    cover_file = _as_upload_file(src.pop("cover_bytes", None))
    banner_file = _as_upload_file(src.pop("banner_bytes", None))

    _PROTECTED_IMAGE_DOMAINS = ("kagane.si", "kagane.cx", "kagane.moe", "kagane.net", "kagane.org", "kagane.to", "valirscans")
    if cover_file is not None:
        src.pop("cover_url", None)
    elif src.get("cover_url") and any(d in str(src.get("cover_url")).lower() for d in _PROTECTED_IMAGE_DOMAINS):
        src.pop("cover_url", None)

    if banner_file is not None:
        src.pop("banner_url", None)
    elif src.get("banner_url") and any(d in str(src.get("banner_url")).lower() for d in _PROTECTED_IMAGE_DOMAINS):
        src.pop("banner_url", None)

    if cover_file is None and banner_file is None:
        return False, src, {}
    data = {}
    for key, val in src.items():
        if val is None:
            continue
        if isinstance(val, (list, dict)):
            data[key] = json.dumps(val, ensure_ascii=False)
        elif isinstance(val, str):
            data[key] = val
        else:
            data[key] = str(val)
    files = {}
    if cover_file is not None:
        files["cover_file"] = cover_file
    if banner_file is not None:
        files["banner_file"] = banner_file
    return True, data, files

def create_manga_from_mangabaka(metadata, session):
    try:
        is_multi, body, files = build_create_payload(metadata)
        if is_multi:
            res = session.post(
                f"{BASE_URL}/api/manga/create-from-mangabaka",
                data=body,
                files=files,
                timeout=(10, 60),
            )
        else:
            res = session.post(
                f"{BASE_URL}/api/manga/create-from-mangabaka",
                json=body,
                timeout=(10, 30),
            )
        try:
            payload = res.json()
        except json.JSONDecodeError as e:
            logging.error(f"create_manga_from_mangabaka: unreadable response (HTTP {res.status_code}): {e}")
            return {"ok": False, "error": "MangaDot sent back something unreadable."}

        # Successful creation returns 200 or 201 with {"manga": {"id": ..., "title": ...}}
        if res.status_code in (200, 201):
            manga = payload.get("manga")
            if isinstance(manga, dict):
                return {"ok": True, "id": manga.get("id"), "title": manga.get("title")}
            if payload.get("success") and isinstance(payload.get("manga"), dict):
                manga = payload["manga"]
                return {"ok": True, "id": manga.get("id"), "title": manga.get("title")}

        err_msg = payload.get("detail") or payload.get("error") or f"HTTP {res.status_code}"
        return {"ok": False, "error": str(err_msg)}

    except requests.exceptions.RequestException as e:
        logging.error(f"create_manga_from_mangabaka: network error: {e}")
        return {"ok": False, "error": "Couldn't reach MangaDot."}

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
        slug = item.get("slug") or re.sub(r'[^a-zA-Z0-9]+', '-', (_mangabaka_primary_title(item.get("titles")) or "manga")).strip('-').lower() or "manga"
        results.append({
            "id": series_id,
            "title": _mangabaka_primary_title(item.get("titles")) or "Untitled",
            "status": item.get("status", ""),
            "cover_url": _mangabaka_thumbnail_url(item.get("cover")),
            "mangabaka_url": f"https://mangabaka.org/manga/{series_id}/{slug}",
        })
    return results, None

def search_groups(query, session):
    try:
        res = session.get(f"{BASE_URL}/api/groups/lookup", params={"q": query, "limit": 25}, timeout=(10, 30))
        if res.status_code != 200: return []
        return res.json().get("groups", [])
    except requests.exceptions.RequestException as e:
        logging.error(f"Network error while searching for groups: {e}")
        return []
    except json.JSONDecodeError as e:
        logging.error(f"Group search returned an unreadable response: {e}")
        return []

def parse_mangabaka_for_ui(data):
    origin_map = {"KR": "South Korea (KR)", "JP": "Japan (JP)", "CN": "China (CN)", "TW": "Taiwan (TW)"}
    official_map = {str(tag).lower(): tag for group in GENRE_TAXONOMY.values() for tag in group}
    
    selected_genres = set()
    for rg in data.get("genres", []):
        normalized = str(rg).lower().replace("_", " ").strip()
        selected_genres.add(official_map.get(normalized, str(rg).title()))

    authors = data.get("authors", [])
    artists = data.get("artists", [])
    alt_titles = data.get("alt_titles", [])

    return {
        "title": str(data.get("title", "")),
        "description": str(data.get("description", "")),
        "status": str(data.get("status", "")).capitalize(),
        "origin_val": origin_map.get(data.get("country_of_origin", ""), "Unknown"),
        "genres": list(selected_genres),
        "alt_titles": alt_titles if isinstance(alt_titles, list) else ([alt_titles] if alt_titles else []),
        "authors": ", ".join(authors) if isinstance(authors, list) else str(authors or ""),
        "artists": ", ".join(artists) if isinstance(artists, list) else str(artists or ""),
        "anilist_id": str(data.get("anilist_id") or ""),
        "mangaupdates_id": str(data.get("mangaupdates_id") or ""),
        "source_url": str(data.get("source_url") or ""),
        "cover_url": str(data.get("cover_url") or ""),
        "banner_url": str(data.get("banner_url") or ""),
    }

def format_ui_for_mangabaka(ui_data):
    rev_origin = {"Japan (JP)": "JP", "South Korea (KR)": "KR", "China (CN)": "CN", "Taiwan (TW)": "TW"}
    return {
        "title": ui_data["title"].strip(),
        "description": ui_data["description"].strip(),
        "status": ui_data["status"],
        "country_of_origin": rev_origin.get(ui_data["origin"], "Unknown"),
        "genres": ui_data["genres"],
        "alt_titles": ui_data["alt_titles"],
        "authors": [x.strip() for x in ui_data["authors"].split(",") if x.strip()],
        "artists": [x.strip() for x in ui_data["artists"].split(",") if x.strip()],
        "anilist_id": ui_data["anilist_id"].strip(),
        "mangaupdates_id": ui_data["mangaupdates_id"].strip(),
        "source_url": ui_data["source_url"].strip(),
        "cover_url": ui_data["cover_url"].strip(),
        "banner_url": ui_data["banner_url"].strip()
    }


def fetch_uploads_page(session, page=1, limit=50, manga_id=None, upload_type=None, language=None, sort="number_desc"):
    params = {"page": page, "limit": limit, "sort": sort}
    if manga_id is not None:
        params["manga_id"] = manga_id
    if upload_type:
        params["type"] = upload_type
    if language:
        params["language"] = language
    try:
        res = session.get(f"{BASE_URL}/api/uploads/mine", params=params, timeout=(10, 30))
        if res.status_code in (401, 403):
            raise SessionExpiredError()
        res.raise_for_status()
        return res.json()
    except requests.exceptions.RequestException as e:
        logging.debug("fetch_uploads_page error: %s", e)
        return {}


def fetch_my_uploads(session, manga_id=None, upload_type=None, language=None, limit=100, max_pages=5):
    """Fetches logged-in user's uploads from /api/uploads/mine.
    Authoritative for recent uploads including those awaiting moderation."""
    entries = []
    page = 1
    while page <= max_pages:
        data = fetch_uploads_page(session, page=page, limit=limit,
                                  manga_id=manga_id, upload_type=upload_type, language=language)
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
    """Query MangaDot for existing chapters or volumes under this title and language.
    Combines public published chapters and the member's moderation queue."""
    existing_numbers = set()

    # 1. Public published chapters
    try:
        base_url = (
            f"{BASE_URL}/api/manga/{manga_id}/volumes"
            if upload_type == "volume"
            else f"{BASE_URL}/api/manga/{manga_id}/chapters/list"
        )
        res = session.get(
            f"{base_url}?lang={language}",
            headers={"Referer": f"{BASE_URL}/manga/{manga_id}"},
            timeout=(10, 20)
        )
        if res.status_code == 200:
            data = res.json()
            items = data if isinstance(data, list) else (data.get("volumes") or data.get("chapters") or data.get("rows") or [])
            for item in items:
                if isinstance(item, dict):
                    raw_num = item.get("volume_number" if upload_type == "volume" else "chapter_number")
                    if raw_num is not None:
                        try:
                            f = float(raw_num)
                            key = str(int(f)) if f.is_integer() else format(f, "g")
                            existing_numbers.add(key)
                        except (ValueError, TypeError):
                            pass
    except Exception as e:
        logging.debug("fetch_remote_existing_numbers public check failed: %s", e)

    # 2. Member's uploads (pending, processing, approved)
    try:
        mine_uploads = fetch_my_uploads(session, manga_id=manga_id, upload_type=upload_type, language=language, limit=100, max_pages=2)
        for item in mine_uploads:
            if isinstance(item, dict) and item.get("status") != "rejected":
                raw_num = item.get("volume_number" if upload_type == "volume" else "chapter_number")
                if raw_num is not None:
                    try:
                        f = float(raw_num)
                        key = str(int(f)) if f.is_integer() else format(f, "g")
                        existing_numbers.add(key)
                    except (ValueError, TypeError):
                        pass
    except Exception as e:
        logging.debug("fetch_remote_existing_numbers mine check failed: %s", e)

    return existing_numbers
