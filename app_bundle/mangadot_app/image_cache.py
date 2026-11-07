"""Disk cache for profile avatar/cover images, keyed by username + URL.

Why URL-keyed rather than just username-keyed: the site's avatar_url and
cover_url (from net.fetch_profile_stats) always come from a fresh API
call - caching is never applied to that JSON, only to the two image
downloads it points at, which are the actually-slow part on a login
(see ProfileBannerWidget). If the user changes their picture on the
site, the URL the API returns changes too (new filename/hash) - so
"does the URL we have on file match the URL the API just gave us" is a
reliable, free staleness check that never needs to download and diff
image bytes. If the URL matches, the cached bytes are guaranteed to
still be the current picture; if it doesn't match, that's the site
telling us the picture changed, and we treat the cache as a miss and
re-download.

Storage: a small JSON manifest (username -> per-image {url, file}) plus
the actual image bytes as loose files in cache/profile_images/. Follows
the same atomic-write (tempfile + os.replace) and load-tolerant-of-
corruption pattern as config.py's save_db()/load_db(), for the same
reason - a half-written or corrupt cache should degrade to "just
re-download", never crash the app.
"""
import os
import json
import time
import hashlib
import tempfile
import threading
from pathlib import Path

from . import config

IMAGE_CACHE_DIR = config.CACHE_DIR / "profile_images"
MANIFEST_PATH = IMAGE_CACHE_DIR / "manifest.json"

# Same rationale as config.py's _paused_upload_lock: multiple profile
# banners could theoretically load concurrently (e.g. a second
# MainWindow - see main.py's _mangadot_windows list), all reading and
# writing this one manifest file from different threads.
_manifest_lock = threading.Lock()


def _load_manifest():
    try:
        with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_manifest(manifest):
    try:
        IMAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(IMAGE_CACHE_DIR), prefix=".manifest_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2)
            os.replace(tmp, MANIFEST_PATH)
        finally:
            if os.path.exists(tmp):
                try: os.remove(tmp)
                except OSError: pass
    except (OSError, TypeError, ValueError):
        pass


def _file_for(username, kind, url):
    # Hash the URL (not just kind) into the filename so a changed
    # picture's bytes never collide with - or get served in place of -
    # the previous one still referenced anywhere transiently in memory.
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    safe_username = "".join(c if c.isalnum() or c in "-_" else "_" for c in username) or "unknown"
    return f"{safe_username}_{kind}_{digest}.img"


def get_cached(username, avatar_url, cover_url):
    """Returns (avatar_bytes_or_None, cover_bytes_or_None) for whichever
    of the two URLs still match what's on file for this username. A
    None for either half means "no valid cache entry for this exact
    URL" (never downloaded yet, or the URL changed) - the caller should
    fetch it fresh, same as if no cache existed."""
    if not username:
        return None, None
    with _manifest_lock:
        manifest = _load_manifest()
        entry = manifest.get(username, {})
        avatar_bytes = _read_if_url_matches(entry.get("avatar"), avatar_url)
        cover_bytes = _read_if_url_matches(entry.get("cover"), cover_url)
        return avatar_bytes, cover_bytes


def _read_if_url_matches(sub_entry, current_url):
    if not sub_entry or not current_url:
        return None
    if sub_entry.get("url") != current_url:
        return None  # stale - URL on the site changed since this was cached
    filename = sub_entry.get("file")
    if not filename:
        return None
    try:
        with open(IMAGE_CACHE_DIR / filename, "rb") as f:
            return f.read()
    except OSError:
        return None  # file's gone missing on disk - treat as a miss, don't crash


def store(username, kind, url, image_bytes):
    """kind: 'avatar' or 'cover'. Call this once a fresh download
    succeeds, so next login for the same username+URL can skip the
    network entirely. Silently does nothing on any failure - a cache
    write failing should never surface to the user or block the UI
    update that already happened with the bytes in memory."""
    if not username or not url or not image_bytes:
        return
    filename = _file_for(username, kind, url)
    try:
        IMAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(IMAGE_CACHE_DIR), prefix=".img_", suffix=".tmp")
        with os.fdopen(fd, "wb") as f:
            f.write(image_bytes)
        os.replace(tmp, IMAGE_CACHE_DIR / filename)
    except OSError:
        return
    with _manifest_lock:
        manifest = _load_manifest()
        entry = manifest.setdefault(username, {})
        old = entry.get(kind)
        entry[kind] = {"url": url, "file": filename, "cached_at": time.time()}
        manifest[username] = entry
        _save_manifest(manifest)
    # Best-effort cleanup of the previous cached file for this
    # username+kind now that the manifest points at the new one - not
    # inside the lock (disk I/O doesn't need to hold it, and a failed
    # delete here is harmless: just an orphaned file, not a correctness
    # issue, since nothing in the manifest references it anymore).
    if old and old.get("file") and old["file"] != filename:
        try:
            os.remove(IMAGE_CACHE_DIR / old["file"])
        except OSError:
            pass
