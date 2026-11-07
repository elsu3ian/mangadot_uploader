"""Session authentication"""
import os
import re
import sys
import json
import time
import signal
import shutil
import sqlite3
import tempfile
import subprocess
import atexit
import logging

import requests
import websocket
import rookiepy
import urllib.request

from . import net
from . import util

BASE_URL = "https://mangadot.net"

CDP_BASE_PORT = 9222
CDP_PORT_OFFSETS = {"chrome": 0, "edge": 1, "brave": 2, "vivaldi": 3, "opera": 4}
CDP_STARTUP_WAIT = 20

CDP_REGISTRY_APP_NAMES = {
    "chrome":  "chrome.exe",
    "edge":    "msedge.exe",
    "brave":   "brave.exe",
    "vivaldi": "vivaldi.exe",
    "opera":   "opera.exe",
}

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

GECKO_DEBUG_STARTUP_WAIT = 180  # generous: the person needs time to actually log in, possibly through a Cloudflare check


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


def _cdp_port_for(browser_key):
    return CDP_BASE_PORT + CDP_PORT_OFFSETS.get(browser_key, 99)


def _cdp_profile_dir_for(browser_key):
    return os.path.join(CDP_PROFILE_ROOT, browser_key)


def _gecko_debug_profile_dir_for(browser_key):
    return os.path.join(GECKO_DEBUG_PROFILE_ROOT, browser_key)


# --- Gecko-based (Zen/Firefox) cookie reading via rookiepy ---------------

def _read_cookie_db_safely(db_path, domains=None):
    # 1. Try direct read first (works if browser is fully closed)
    try:
        result = rookiepy.firefox_based(db_path, domains=domains)
        logging.debug(
            "rookiepy direct read of %s succeeded, %d cookie(s) for domains=%s",
            db_path, len(result), domains,
        )
        return result
    except Exception as e:
        logging.debug("rookiepy direct read failed for %s: %s: %s", db_path, type(e).__name__, e)
        
    # 2. Safe fallback for live databases using SQLite Backup API.
    #
    # IMPORTANT: do NOT open the source with immutable=1 here. That flag
    # tells SQLite the file will never change while open, so it skips
    # locking *and* ignores any pending -wal file entirely. Firefox/Zen
    # run in WAL mode, so recent writes (e.g. a just-created session
    # cookie) often live only in cookies.sqlite-wal until checkpointed -
    # an immutable read silently misses them, and on Windows the mismatch
    # between "immutable" and a file the browser still holds open can
    # also throw outright. Plain mode=ro respects the browser's lock
    # state and still sees WAL contents, which is what we want for a
    # database that's genuinely live.
    tmp_dir = tempfile.mkdtemp(prefix="mangadot_gecko_")
    try:
        tmp_db = os.path.join(tmp_dir, "cookies.sqlite")
        db_uri = f"file:{urllib.request.pathname2url(db_path)}?mode=ro"

        try:
            with sqlite3.connect(db_uri, uri=True, timeout=5) as src, sqlite3.connect(tmp_db) as dst:
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
    profile_roots = []
    
    if sys.platform == 'win32':
        if browser_name == "firefox":
            profile_roots = [os.path.expandvars(r'%APPDATA%\Mozilla\Firefox\Profiles')]
        else: # Zen
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
            profile_roots = [os.path.expanduser('~/Library/Application Support/zen/Profiles'),
                             os.path.expanduser('~/Library/Application Support/Zen/Profiles')]
    else:
        if browser_name == "firefox":
            profile_roots = [os.path.expanduser('~/.mozilla/firefox')]
        else:
            profile_roots = [os.path.expanduser('~/.zen')]

    all_dbs = []
    for root in profile_roots:
        if not os.path.isdir(root): continue
        for entry in os.listdir(root):
            db_path = os.path.join(root, entry, 'cookies.sqlite')
            if os.path.isfile(db_path):
                all_dbs.append(db_path)

    # CRITICAL: Sort by Newest first to hit the active profile.
    all_dbs.sort(key=lambda x: os.path.getmtime(x) if os.path.exists(x) else 0, reverse=True)

    for db_path in all_dbs:
        cookies = _read_cookie_db_safely(db_path, domains=domains)
        if cookies:
            return cookies
            
    return []


# --- CDP (Chrome DevTools Protocol) fallback for Chromium browsers -------

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
    """Shared lookup used by both the CDP (Chromium) and Gecko finders:
    Windows registry App Paths first, then the per-platform candidate
    list (PATH search on Linux, literal file check elsewhere)."""
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


GECKO_REGISTRY_APP_NAMES = {
    "firefox": "firefox.exe",
    "zen": "zen.exe",
}


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
        # RuntimeError: subprocess.run can fail with "can't create new
        # thread" when one of these lookups runs from an atexit handler
        # during interpreter shutdown - nothing to do but give up quietly.
        return False


def _wait_for_process_exit(pid, timeout=0.5, poll_interval=0.05):
    """Polls whether `pid` is still alive, returning as soon as it exits
    or once `timeout` seconds have passed. Used after sending SIGTERM so
    a process gets a real chance to exit cleanly before being escalated
    to SIGKILL, rather than always being force-killed after a flat sleep
    regardless of whether SIGTERM already worked.

    os.kill(pid, 0) sends no actual signal - it just checks whether the
    process still exists, raising ProcessLookupError once it's gone (or
    PermissionError if it exists but we can't signal it, which we treat
    the same as "still alive" here since that's the safer assumption).
    """
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


def _kill_stale_tracked_process(pid_file, expected_exe):
    """Shared body of _cdp_kill_stale_process/_gecko_kill_stale_process:
    reads the launch-time pid file, verifies the pid is really our
    browser (not a recycled pid), force-kills it, and removes the file."""
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
            try:
                os.kill(old_pid, signal.SIGTERM)
                _wait_for_process_exit(old_pid, timeout=0.5)
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


def _cdp_kill_stale_process(browser_key):
    _kill_stale_tracked_process(_cdp_pid_file(browser_key),
                                _find_browser_executable(browser_key))


def _kill_processes_by_profile_dir(profile_dir):
    """Kills every process whose command line references profile_dir,
    regardless of PID - the necessary fallback for browsers that
    re-exec/hand off to a new child process almost immediately after
    being launched (extremely common with a fresh --user-data-dir),
    which leaves the PID captured at launch time pointing at a
    long-dead process by the time cleanup actually runs.

    Matching on profile_dir instead of a PID is what makes this safe:
    profile_dir is this app's own dedicated, per-browser directory
    (see _cdp_profile_dir_for/_gecko_debug_profile_dir_for) that only
    ever appears in a command line because THIS app passed it as
    --user-data-dir/-profile - a person's normal, everyday browser
    windows (using their real profile) can never match it, so this
    can't accidentally kill anything the person didn't launch through
    the app's own debug-login flow."""
    try:
        if sys.platform == "win32":
            # wmic is deprecated but still present on every Windows
            # 10/11 install as of this writing; tasklist has no
            # command-line filter, so this is the simplest built-in
            # option without adding a new dependency. Falls back to
            # PowerShell's CIM cmdlet if wmic is gone, unusable for
            # this path, or simply finds nothing.
            #
            # profile_dir ultimately derives from this machine's own
            # profile root (see _cdp_profile_dir_for), but Windows user
            # names may legally contain an apostrophe (O'Brien) and a
            # WQL string literal has no way to escape one - so paths
            # containing ' skip straight to the PowerShell fallback.
            pids = []
            if "'" not in profile_dir:
                escaped = profile_dir.replace("\\", "\\\\")  # WQL LIKE treats \ as its escape char
                result = subprocess.run(
                    ["wmic", "process", "where",
                     f"CommandLine like '%{escaped}%'", "get", "ProcessId"],
                    capture_output=True, text=True, timeout=10, check=False,
                )
                if result.returncode == 0:
                    pids = [int(p) for p in re.findall(r'\d+', result.stdout)]
            if not pids:
                # The profile dir reaches the filter through an environment
                # variable rather than being interpolated into the command
                # text. No quoting scheme survives every possible path, but
                # an env var needs none at all: PowerShell reads the literal
                # value itself, so apostrophes/backslashes/spaces pass
                # through untouched and no crafted path can break out of the
                # -like comparison. (The previous version interpolated an
                # escaped copy of the path directly into this string with
                # doubled backslashes - which -like treats as literal
                # characters, so the fallback never actually matched any
                # real Windows path.)
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
                    os.kill(pid, signal.SIGTERM)
                except ProcessLookupError:
                    continue
            for pid in pids:
                if _wait_for_process_exit(pid, timeout=0.5):
                    continue
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
    except (subprocess.SubprocessError, OSError, ValueError, RuntimeError) as e:
        # RuntimeError covers interpreter-shutdown races: this runs from
        # atexit handlers, where subprocess.run's internal reader thread
        # can fail to start ("can't create new thread") - previously that
        # raised past every handler and printed a scary traceback on every
        # exit even though it's harmless at that point.
        logging.debug("_kill_processes_by_profile_dir(%r): %s", profile_dir, e)


def cleanup_all_cdp_processes():
    for browser in ["chrome", "edge", "brave", "vivaldi", "opera"]:
        _cdp_kill_stale_process(browser)
        _kill_processes_by_profile_dir(_cdp_profile_dir_for(browser))


atexit.register(cleanup_all_cdp_processes)


# --- Dedicated debug-profile launch for Gecko browsers (Zen/Firefox) -----
#
# MangaDot serves a Cloudflare *managed* challenge (confirmed via the
# Cf-Mitigated: challenge response header and the "Just a moment..." /
# cf_chl interstitial body). That challenge requires actually executing
# JavaScript in a real browser engine to earn a fresh cf_clearance cookie -
# no HTTP client, however well it spoofs its TLS fingerprint, can clear it.
# Chromium browsers already get past this via the CDP path above, because
# CDP drives a genuine Chromium engine. This section gives Zen/Firefox the
# same capability using a completely separate, isolated debug profile
# (-profile + -no-remote), rather than the person's everyday browsing
# profile - deliberately not Marionette/remote-debugging-port, since
# leaving those enabled on a real browsing profile changes fingerprint
# signals (sets navigator.webdriver, etc.) in a way that can make
# Cloudflare *more* suspicious, which is the opposite of what we want here.
# The dedicated profile just needs to log in once; after that we read its
# cookies.sqlite the same way get_gecko_cookies already does for any
# other profile.

def _gecko_pid_file(browser_key):
    return os.path.join(_gecko_debug_profile_dir_for(browser_key), ".gecko_launch.pid")


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
            # RuntimeError: possible interpreter-shutdown race (see
            # _kill_processes_by_profile_dir).
            return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, PermissionError):
            return False
        except OSError:
            return False


def _gecko_kill_stale_process(browser_key):
    _kill_stale_tracked_process(_gecko_pid_file(browser_key),
                                _find_gecko_executable(browser_key))


def cleanup_all_gecko_debug_processes():
    for browser in ["zen", "firefox"]:
        _gecko_kill_stale_process(browser)
        _kill_processes_by_profile_dir(_gecko_debug_profile_dir_for(browser))


atexit.register(cleanup_all_gecko_debug_processes)


class GeckoLaunchError(Exception):
    pass


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


def get_gecko_debug_cookies(browser_key, domains=None, on_launch=None):
    """Like get_gecko_cookies, but reads from a dedicated debug profile
    the app itself launches and controls - not any of the person's real
    browser profiles - so a real Gecko engine can clear MangaDot's
    Cloudflare challenge once, and we reuse the resulting session after.
    """
    profile_dir = _gecko_debug_profile_dir_for(browser_key)
    already_running = _gecko_tracked_process_alive(browser_key)

    if not already_running:
        launched_proc = _launch_gecko_debug_browser(browser_key, BASE_URL)
        if launched_proc is None:
            raise GeckoLaunchError(
                f"Could not find or launch {browser_key.title()} for the debug-profile "
                f"login flow. If it's installed in a custom location, its path can be "
                f"added to GECKO_BROWSER_EXECUTABLES in auth.py."
            )
        if on_launch:
            on_launch(
                f"Opened a dedicated {browser_key.title()} window for MangaDot sign-in. "
                f"Log into MangaDot in that window (solve the Cloudflare check if it "
                f"appears), then come back here and click Continue below."
            )

    db_path = os.path.join(profile_dir, "cookies.sqlite")
    deadline = time.time() + GECKO_DEBUG_STARTUP_WAIT
    cookies = []
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        if os.path.isfile(db_path):
            cookies = _read_cookie_db_safely(db_path, domains=domains)
            logging.debug(
                "get_gecko_debug_cookies[%s]: attempt %d, db exists, "
                "read returned %d cookie(s) for domains=%s",
                browser_key, attempt, len(cookies), domains,
            )
            if cookies:
                break
        else:
            logging.debug(
                "get_gecko_debug_cookies[%s]: attempt %d, %s does not exist yet",
                browser_key, attempt, db_path,
            )
        time.sleep(1.0)
    else:
        logging.debug(
            "get_gecko_debug_cookies[%s]: gave up after %d attempts (%ds), "
            "final cookie count=%d", browser_key, attempt, GECKO_DEBUG_STARTUP_WAIT, len(cookies),
        )

    return cookies


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
    return _tracked_process_alive(_cdp_pid_file(browser_key))


def _gecko_tracked_process_alive(browser_key):
    return _tracked_process_alive(_gecko_pid_file(browser_key))


class CdpLaunchError(Exception):
    pass


def get_cdp_cookies(browser_key, domains=None, on_launch=None):
    port = _cdp_port_for(browser_key)
    port_up = _cdp_port_is_up(port)
    trusted = port_up and _cdp_tracked_process_alive(browser_key)

    if not trusted:
        launched_proc = _cdp_launch_browser(browser_key, BASE_URL)
        if launched_proc is None:
            raise CdpLaunchError(
                f"Could not find or launch {browser_key.title()} for CDP mode. "
                f"If it's installed in a custom location, its path can be added "
                f"to CDP_BROWSER_EXECUTABLES in auth.py."
            )

        if on_launch:
            on_launch(f"Launched a dedicated {browser_key.title()} debug profile. "
                      f"If this is the first run, log into MangaDot in that window, then continue.")

        if not _cdp_wait_for_port(port):
            raise CdpLaunchError("Timed out waiting for the browser's debug port to come up.")

        if not _cdp_open_new_tab(port, BASE_URL) and on_launch:
            on_launch(f"Couldn't confirm {browser_key.title()} navigated to MangaDot - "
                      f"if the window looks blank, open {BASE_URL} in it manually.")

    raw_cookies = _cdp_get_all_cookies(port) or []

    domains = domains or []
    filtered = [
        {"name": c["name"], "value": c["value"], "domain": c["domain"]}
        for c in raw_cookies
        if not domains or any(c.get("domain", "").endswith(d.lstrip(".")) for d in domains)
    ]
    return filtered


# --- Session validation ----------------------------------------------------

def _parse_profile_response(res):
    """Returns (name, user_id, reason) - name is None if not a genuine login.

    Cloudflare's Cf-Mitigated: challenge header is the documented, reliable
    marker for a managed/JS challenge response (see
    developers.cloudflare.com/cloudflare-challenges/challenge-types/challenge-pages/detect-response).
    That challenge requires actually executing JavaScript in a browser
    engine to earn a fresh cf_clearance cookie - no amount of header or
    TLS-fingerprint spoofing from an HTTP client library clears it, so we
    detect and name it plainly instead of retrying with something that
    can't succeed.
    """
    if res.headers.get("Cf-Mitigated", "").lower() == "challenge":
        return None, None, (
            "Cloudflare served a managed/JS challenge (Cf-Mitigated: challenge) "
            "instead of the real API response. This has to be solved by an actual "
            "browser - copying cookies into a plain HTTP request can't clear it."
        )
    if res.status_code != 200:
        return None, None, f"HTTP {res.status_code}"
    try:
        data = res.json()
    except (json.JSONDecodeError, ValueError):
        return None, None, "HTTP 200 but non-JSON body (likely a Cloudflare/JS interstitial page)"
    profile = data.get("profile", {})
    name = profile.get("username") or profile.get("email")
    user_id = profile.get("id") or profile.get("user_id") or profile.get("uid")
    if name:
        return name, user_id, "ok"
    return None, None, "HTTP 200 valid JSON but no profile/username in it (session likely not authenticated)"


def validate_session(session):
    reason = "unknown"
    try:
        res = session.get(f"{BASE_URL}/api/profile", timeout=(10, 30))
        name, user_id, reason = _parse_profile_response(res)

        if name is not None:
            return name, user_id, "ok"
    except requests.exceptions.RequestException as e:
        reason = f"network error: {type(e).__name__}: {e}"
        logging.debug("validate_session: network error: %s", e)
    except Exception as e:
        reason = f"unexpected error: {type(e).__name__}: {e}"
        logging.debug("validate_session: unexpected error: %s", e)
    return None, None, reason


# --- Orchestration: try every browser, UI-agnostic -------------------------

SUPPORTED_BROWSERS = ["zen", "chrome", "firefox", "brave", "edge", "opera", "vivaldi"]
CDP_BROWSERS = ["chrome (cdp)", "edge (cdp)", "brave (cdp)", "vivaldi (cdp)", "opera (cdp)"]
GECKO_DEBUG_BROWSERS = ["zen (debug)", "firefox (debug)"]
ALL_BROWSER_CHOICES = SUPPORTED_BROWSERS + CDP_BROWSERS + GECKO_DEBUG_BROWSERS

_COOKIE_GETTERS = {
    "zen": lambda domains=None: get_gecko_cookies("zen", domains=domains),
    "firefox": lambda domains=None: get_gecko_cookies("firefox", domains=domains),
    "chrome": rookiepy.chrome,
    "brave": rookiepy.brave,
    "edge": rookiepy.edge,
    "opera": rookiepy.opera,
    "vivaldi": rookiepy.vivaldi,
    "chrome (cdp)":  lambda domains=None, on_launch=None: get_cdp_cookies("chrome", domains=domains, on_launch=on_launch),
    "edge (cdp)":    lambda domains=None, on_launch=None: get_cdp_cookies("edge", domains=domains, on_launch=on_launch),
    "brave (cdp)":   lambda domains=None, on_launch=None: get_cdp_cookies("brave", domains=domains, on_launch=on_launch),
    "vivaldi (cdp)": lambda domains=None, on_launch=None: get_cdp_cookies("vivaldi", domains=domains, on_launch=on_launch),
    "opera (cdp)":   lambda domains=None, on_launch=None: get_cdp_cookies("opera", domains=domains, on_launch=on_launch),
    "zen (debug)":     lambda domains=None, on_launch=None: get_gecko_debug_cookies("zen", domains=domains, on_launch=on_launch),
    "firefox (debug)": lambda domains=None, on_launch=None: get_gecko_debug_cookies("firefox", domains=domains, on_launch=on_launch),
}


def try_browser(req_session, browser_name, on_cdp_launch=None):
    get_cookies_fn = _COOKIE_GETTERS.get(browser_name)
    if get_cookies_fn is None:
        return {"browser": browser_name, "status": "error", "username": None, "user_id": None,
                "cookie_count": 0, "cookie_names": [], "error_type": "ValueError",
                "error_message": f"Unknown browser '{browser_name}'", "chromium_hint": False}

    base_browser = browser_name.replace(" (cdp)", "").replace(" (debug)", "")
    is_chromium = base_browser in CHROMIUM_BROWSERS
    needs_launch_callback = browser_name.endswith("(cdp)") or browser_name.endswith("(debug)")

    try:
        req_session.cookies.clear()
        req_session.headers.update({"User-Agent": net.get_dynamic_user_agent(base_browser)})

        if needs_launch_callback:
            browser_cookies = get_cookies_fn(domains=["mangadot.net", ".mangadot.net"], on_launch=on_cdp_launch)
        else:
            browser_cookies = get_cookies_fn(domains=["mangadot.net", ".mangadot.net"])

        if not browser_cookies:
            return {"browser": browser_name, "status": "no_cookies", "username": None, "user_id": None,
                    "cookie_count": 0, "cookie_names": [], "error_type": None, "error_message": None,
                    "chromium_hint": False}

        for cookie in browser_cookies:
            req_session.cookies.set(cookie['name'], cookie['value'], domain=cookie['domain'])

        username, user_id, reason = validate_session(req_session)
        if username:
            return {"browser": browser_name, "status": "success", "username": username, "user_id": user_id,
                    "cookie_count": len(browser_cookies), "cookie_names": [c['name'] for c in browser_cookies],
                    "error_type": None, "error_message": None, "chromium_hint": False}

        cloudflare_hint = (
            not needs_launch_callback and
            base_browser in ("zen", "firefox") and
            "Cloudflare served a managed/JS challenge" in (reason or "")
        )

        # A real cookie set that still fails validation is consistent with
        # a stale cached UA - e.g. the cache was written before the browser
        # last updated. That's true even when the first attempt came back
        # as a Cloudflare managed/JS challenge: a UA fingerprint Cloudflare
        # no longer recognizes can itself trigger that response, so a first
        # -attempt CF hint alone doesn't prove the challenge is genuinely
        # unsolvable. We only give up without retrying once we've confirmed
        # a fresh UA still gets CF-mitigated (handled after the retry below).
        # CDP/gecko-debug browsers skip this: their cookies come from a
        # browser we just launched/drove ourselves, so a UA mismatch is
        # much less likely to be the cause.
        if not needs_launch_callback:
            req_session.cookies.clear()
            req_session.headers.update(
                {"User-Agent": net.get_dynamic_user_agent(base_browser, force_refresh=True)}
            )
            for cookie in browser_cookies:
                req_session.cookies.set(cookie['name'], cookie['value'], domain=cookie['domain'])

            username, user_id, retry_reason = validate_session(req_session)
            if username:
                return {"browser": browser_name, "status": "success", "username": username, "user_id": user_id,
                        "cookie_count": len(browser_cookies), "cookie_names": [c['name'] for c in browser_cookies],
                        "error_type": None, "error_message": None, "chromium_hint": False}
            reason = retry_reason
            cloudflare_hint = (
                base_browser in ("zen", "firefox") and
                "Cloudflare served a managed/JS challenge" in (reason or "")
            )

        return {"browser": browser_name, "status": "not_recognized", "username": None, "user_id": None,
                "cookie_count": len(browser_cookies), "cookie_names": [c['name'] for c in browser_cookies],
                "error_type": None, "error_message": reason,
                "chromium_hint": False, "gecko_debug_hint": cloudflare_hint}

    except (CdpLaunchError, GeckoLaunchError) as e:
        return {"browser": browser_name, "status": "error", "username": None, "user_id": None,
                "cookie_count": 0, "cookie_names": [], "error_type": type(e).__name__,
                "error_message": str(e), "chromium_hint": False}
    except Exception as e:
        return {"browser": browser_name, "status": "error", "username": None, "user_id": None,
                "cookie_count": 0, "cookie_names": [], "error_type": type(e).__name__,
                "error_message": util.redact_home_path(str(e)),
                "chromium_hint": is_chromium and not needs_launch_callback}


def try_all_browsers(req_session, browsers=None, on_cdp_launch=None, progress_callback=None):
    browsers = browsers if browsers is not None else SUPPORTED_BROWSERS
    results = []
    for browser_name in browsers:
        result = try_browser(req_session, browser_name, on_cdp_launch=on_cdp_launch)
        results.append(result)
        
        if progress_callback:
            progress_callback(result)
            
        if result["status"] == "success":
            return result, results
            
    return None, results