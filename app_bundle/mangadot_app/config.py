"""Persisted user config: remembered library folder, cached user-agents, and upload history."""
import os
import sys
import json
import time
import shutil
import logging
import tempfile
import threading
from pathlib import Path


def _default_cache_dir():
    """Per-user application-data location for all runtime state (config,
    upload history, paused-upload state, image cache, crash/fault logs) -
    deliberately NOT inside the app's own install/source directory. A
    directory that ships with the code can be read-only when properly
    installed (Program Files, a PyInstaller exe under a managed path),
    and mixing mutable user state into it makes upgrades/uninstalls
    lossy. Uses the same per-platform base directories auth.py already
    uses for its browser debug profiles."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser(r"~\AppData\Local")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return Path(base) / "MangaDotUploader" / "cache"


# Older builds stored everything next to the source (mangadot_app/cache).
# Kept only so _migrate_legacy_cache_files() can carry those files over.
_LEGACY_CACHE_DIR = Path(__file__).resolve().parent / "cache"

CACHE_DIR = _default_cache_dir()
CONFIG_PATH = CACHE_DIR / ".mangadot_uploader.json"
DB_PATH = CACHE_DIR / "upload_history_db.json"
PAUSED_UPLOAD_PATH = CACHE_DIR / "paused_upload.json"


def _migrate_legacy_cache_files():
    """One-time carry-over of a pre-relocation cache into the new
    per-user location, so upload history and any paused upload survive
    the upgrade. Copies rather than moves: leaving the originals means
    rolling back to an older build keeps working, and silently deleting
    user data is never an uploader's call. Skipped when there's nothing
    legacy on disk (fresh install) or the new config already exists
    (migration already ran)."""
    if not _LEGACY_CACHE_DIR.is_dir() or CONFIG_PATH.exists():
        return
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copytree(_LEGACY_CACHE_DIR, CACHE_DIR, dirs_exist_ok=True,
                        ignore_dangling_symlinks=True)
        logging.debug("config: migrated legacy cache %s -> %s", _LEGACY_CACHE_DIR, CACHE_DIR)
    except OSError as e:
        # Non-fatal by design: worst case is losing old upload-history /
        # paused state and starting fresh - never worth blocking startup.
        logging.debug("config: legacy cache migration from %s failed: %s", _LEGACY_CACHE_DIR, e)


_migrate_legacy_cache_files()

# Guards every read-modify-write cycle against paused_upload.json.
# process_uploads() (the main batch) and any number of per-file inline
# resumes (see upload_progress_screen._on_resume_one_clicked) can all be
# running on different threads at the same time, and every one of them
# needs to load-mutate-save this single JSON file. Without a lock,
# two threads racing through "read the whole file, change one file's
# entry, write the whole file back" can lose each other's writes -
# whichever save() lands last wins and silently erases the other
# thread's change. This is a plain threading.Lock (not a filesystem
# lock) because every writer lives inside this one process - the app
# doesn't need cross-process safety here, only cross-thread.
_paused_upload_lock = threading.Lock()


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
    """No file locking - this does a plain read-modify-write via the
    caller (typically load_config() then save_config(cfg)), so two
    concurrent writers could race and one write could silently clobber
    the other.

    Most callers are GUI slots (button clicks, "on proceed" handlers,
    etc.) and therefore run on the main thread, where this isn't an
    issue in practice - the app never has two GUI slots executing
    concurrently. The one confirmed exception: net.py's UA-cache
    persistence (inside get_dynamic_user_agent()) is reached via
    auth.try_all_browsers() -> auth.try_browser(), which _AuthWorker
    (login_screen.py) runs on its own QThread - so this function
    genuinely can be called off the main thread. In the current
    codebase that's still safe in practice, since nothing else writes
    config while a login/auth attempt is in flight, but if a future
    change ever has two background workers persisting config
    concurrently, this function's lack of locking would need
    revisiting.
    """
    # Atomic tempfile + os.replace write, same pattern as save_db() -
    # this file previously used a plain open("w"), so a crash mid-write
    # could tear it; load_config() degrades gracefully but the user's
    # library path / UA cache would silently reset.
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(CACHE_DIR), prefix=".mangadot_cfg_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
            os.replace(tmp, CONFIG_PATH)
        finally:
            if os.path.exists(tmp):
                try: os.remove(tmp)
                except OSError: pass
    except (OSError, TypeError, ValueError) as e:
        logging.debug("save_config: failed to write %s: %s", CONFIG_PATH, e)


def remember_library(lib):
    if not lib:
        return
    lib = os.path.normpath(lib)
    cfg = load_config()
    if cfg.get("library") != lib:
        cfg["library"] = lib
        save_config(cfg)


# ==============================================================================
# 📚 SMART UPLOAD HISTORY DATABASE
# ==============================================================================

def load_db():
    try:
        with open(DB_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"version": 2, "uploaded": {}, "series": {}}
        data.setdefault("version", 2)
        if not isinstance(data.get("uploaded"), dict):
            data["uploaded"] = {}
        if not isinstance(data.get("series"), dict):
            data["series"] = {}
        uploaded = data["uploaded"]
        for k in list(uploaded.keys()):
            uploaded[k] = _normalize_uploaded_bucket(uploaded[k])
        return data
    except FileNotFoundError:
        return {"version": 2, "uploaded": {}, "series": {}}
    except (OSError, json.JSONDecodeError):
        return {"version": 2, "uploaded": {}, "series": {}}


def save_db(db):
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(DB_PATH.parent), prefix=".mangadot_db_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(db, f, indent=2)
            os.replace(tmp, DB_PATH)
        finally:
            if os.path.exists(tmp):
                try: os.remove(tmp)
                except OSError: pass
    except (OSError, TypeError, ValueError) as e:
        # This used to be a bare `pass`, which meant upload history could
        # silently stop persisting forever (e.g. after a disk-full or
        # permissions change) with nothing in any log - same failure shape
        # that made save_paused_upload's silent swallowing so hard to
        # diagnose. A warning here is the cheapest possible insurance.
        logging.warning("save_db: failed to write %s: %s", DB_PATH, e)


def _chapter_number_key(number):
    try:
        f = float(number)
    except (TypeError, ValueError):
        return str(number).strip()
    if f.is_integer():
        return str(int(f))
    return format(f, "g")


def _chapter_number_value(number):
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


def make_target_key(manga_id, upload_type, language, group_ids, scanlator_name):
    if group_ids:
        group_key = ",".join(str(g) for g in sorted(group_ids))
    elif scanlator_name:
        group_key = f"s:{scanlator_name.strip().lower()}"
    else:
        group_key = "none"
    return f"{manga_id}|{upload_type}|{language}|{group_key}"


def db_uploaded_numbers(target_key):
    db = load_db()
    bucket = db.get("uploaded", {}).get(target_key, [])
    return {_chapter_number_key(x) for x in bucket}


def db_record_uploaded(target_key, files):
    """No file locking, same as save_config() - relies on being called
    from a single thread at a time. Currently has exactly one call site
    (main.py's _on_upload_finished), reached via
    UploadProgressScreen.upload_finished, a Qt signal that's always
    delivered on the main thread since UploadProgressScreen itself lives
    there. Safe today; would need locking (or routing every writer
    through one dedicated thread/queue) if a second concurrent call site
    is ever added.
    """
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


def load_series_history():
    """Returns the {manga_id_str: series_info_dict} registry."""
    db = load_db()
    return db.get("series", {})


def db_record_series(manga_id, title, alt_titles=None, origin=None,
                     groups=None, chapters_pushed=None, username=None,
                     cover_url=None, mangadot_url=None, user_uploads_url=None):
    """Upserts rich series metadata and chapter records into db['series']."""
    if not manga_id:
        return
    db = load_db()
    series_map = db.setdefault("series", {})
    m_str = str(manga_id).strip()
    
    clean_alts = []
    if isinstance(alt_titles, list):
        clean_alts = [str(a).strip() for a in alt_titles if a and str(a).strip()]
    elif alt_titles:
        clean_alts = [str(alt_titles).strip()]

    entry = series_map.setdefault(m_str, {
        "manga_id": int(m_str) if m_str.isdigit() else m_str,
        "title": title or f"Manga #{m_str}",
        "alt_titles": clean_alts,
        "origin": origin or "N/A",
        "mangadot_url": mangadot_url or f"https://mangadot.net/manga/{m_str}",
        "user_uploads_url": user_uploads_url or (f"https://mangadot.net/user/{username}/uploads?series={m_str}" if username else f"https://mangadot.net/manga/{m_str}"),
        "groups": groups or [],
        "total_chapters": 0,
        "uploaded_chapters": [],
        "cover_url": cover_url or "",
        "username": username or "",
        "last_uploaded_at": time.strftime("%Y-%m-%d %H:%M:%S")
    })

    if title and title != f"Manga #{m_str}":
        entry["title"] = title
    if clean_alts:
        existing_alts = list(entry.get("alt_titles") or [])
        for a in clean_alts:
            if a not in existing_alts:
                existing_alts.append(a)
        entry["alt_titles"] = existing_alts
    if origin and origin != "N/A":
        entry["origin"] = origin
    if cover_url:
        entry["cover_url"] = cover_url
    if username:
        entry["username"] = username
        entry["user_uploads_url"] = f"https://mangadot.net/user/{username}/uploads?series={m_str}"
    if mangadot_url:
        entry["mangadot_url"] = mangadot_url

    # Merge groups
    existing_groups = list(entry.get("groups") or [])
    for g in (groups or []):
        g_clean = str(g).strip()
        if g_clean and g_clean not in existing_groups:
            existing_groups.append(g_clean)
    entry["groups"] = existing_groups

    # Merge chapters
    existing_chs = set(str(x) for x in entry.get("uploaded_chapters", []))
    for c in (chapters_pushed or []):
        c_str = _chapter_number_key(c)
        if c_str and c_str not in existing_chs:
            entry.setdefault("uploaded_chapters", []).append(c_str)
            existing_chs.add(c_str)

    try:
        entry["uploaded_chapters"] = sorted(entry["uploaded_chapters"], key=lambda x: float(x))
    except (ValueError, TypeError):
        entry["uploaded_chapters"] = sorted(entry["uploaded_chapters"])

    entry["total_chapters"] = len(entry["uploaded_chapters"])
    entry["last_uploaded_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    save_db(db)
    return entry


def db_update_series_metadata(manga_id, metadata):
    """Updates metadata (title, alt_titles, origin, cover_url) for a recorded series."""
    if not manga_id or not metadata:
        return
    db = load_db()
    series_map = db.setdefault("series", {})
    m_str = str(manga_id).strip()
    entry = series_map.get(m_str)
    if not entry:
        return
    for k in ("title", "alt_titles", "origin", "cover_url", "mangadot_url", "user_uploads_url"):
        if k in metadata and metadata[k]:
            entry[k] = metadata[k]
    save_db(db)


def get_all_tracked_series():
    """Returns a unified list of series records, reconciling db['series']
    with any historical records in db['uploaded']."""
    db = load_db()
    series_map = dict(db.get("series", {}))
    uploaded = db.get("uploaded", {})

    # Check for legacy keys: target_key = "manga_id|type|lang|group"
    for target_key, ch_list in uploaded.items():
        parts = target_key.split("|")
        if not parts:
            continue
        mid = parts[0].strip()
        if not mid:
            continue
        if mid not in series_map:
            # Create a stub entry for historical tracking
            series_map[mid] = {
                "manga_id": int(mid) if mid.isdigit() else mid,
                "title": f"Manga #{mid}",
                "alt_titles": [],
                "origin": "N/A",
                "mangadot_url": f"https://mangadot.net/manga/{mid}",
                "user_uploads_url": f"https://mangadot.net/manga/{mid}",
                "groups": [parts[3]] if len(parts) > 3 and parts[3] != "none" else [],
                "total_chapters": len(ch_list),
                "uploaded_chapters": [str(x) for x in ch_list],
                "cover_url": "",
                "username": "",
                "last_uploaded_at": "Historical"
            }
        else:
            # Backfill any chapters if series record was smaller
            ent = series_map[mid]
            existing_chs = set(str(x) for x in ent.get("uploaded_chapters", []))
            for c in ch_list:
                c_str = _chapter_number_key(c)
                if c_str and c_str not in existing_chs:
                    ent.setdefault("uploaded_chapters", []).append(c_str)
                    existing_chs.add(c_str)
            try:
                ent["uploaded_chapters"] = sorted(ent["uploaded_chapters"], key=lambda x: float(x))
            except (ValueError, TypeError):
                ent["uploaded_chapters"] = sorted(ent["uploaded_chapters"])
            ent["total_chapters"] = len(ent["uploaded_chapters"])

    return list(series_map.values())


# ==============================================================================
# ⏸️ PAUSED UPLOAD STATE
# ==============================================================================
# Persists enough of an in-flight upload batch to resume it later, even
# across closing and reopening the app. Only one paused upload is ever
# tracked at a time (the app only runs one upload flow at once), so this
# is a single JSON object rather than a keyed collection.
#
# IMPORTANT: nothing here is ever trusted blindly on resume. A file's
# saved "offset" is what the app last observed the server confirming -
# not a guarantee the server still has that upload session at all (TUS
# upload URLs can expire server-side, especially across a long pause).
# uploader.py's resume path always re-verifies with a HEAD request
# before continuing a file from its saved offset, and falls back to
# starting that one file over from scratch if the server no longer
# recognizes the upload_location. See uploader.py's resume_paused_upload().

PAUSED_UPLOAD_SCHEMA_VERSION = 2
# v2 adds "completed_files": full file-info dicts (same shape as
# "files") for files that finished successfully as part of this overall
# batch, whether before or after the pause that produced this state. v1
# had no way to represent "this file is done, don't touch it" - only
# "this file still needs uploading" (the "files" list). Without this,
# resuming an app that had been closed and reopened (main.py's
# _offer_resume_if_paused -> UploadProgressScreen.for_resume) had NO
# record of already-finished files at all: for_resume() builds its
# table purely from paused_state["files"], which by definition only
# ever contains not-yet-done files, so completed ones simply never
# existed anywhere the resumed screen could see. Full file-info dicts
# (not just filenames) are stored so a resumed screen can render a
# proper Done row (size, filepath, etc.) without reconstructing
# incomplete placeholder data. Bumping the schema version means any v1
# file on disk is treated as "nothing usable" (see load_paused_upload())
# rather than silently misread with a missing key.


def load_paused_upload():
    """Returns the paused-upload state dict, or None if there isn't one
    (nothing paused, the file's missing, or it's corrupt/unreadable/from
    an incompatible schema version - all treated the same way: no usable
    paused state, so the caller falls back to a normal fresh upload).

    Safe to call while another thread is mid-save: the lock ensures this
    never reads a half-written file, but a load() immediately followed
    by a separate save() elsewhere is still racy on its own - see
    update_paused_upload() for the read-modify-write-safe version any
    caller that's going to save afterwards should use instead."""
    with _paused_upload_lock:
        return _load_paused_upload_unlocked()


def _load_paused_upload_unlocked():
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
        logging.debug(
            "load_paused_upload: schema_version mismatch (found %r, expected %r); discarding stale paused state.",
            data.get("schema_version"), PAUSED_UPLOAD_SCHEMA_VERSION,
        )
        return None
    if not isinstance(data.get("files"), list):
        return None
    if not isinstance(data.get("completed_files"), list):
        # Defensive default rather than rejecting the whole file - keeps
        # a hand-edited or slightly-malformed-but-otherwise-valid file
        # usable, just without completed-file tracking for this load.
        data["completed_files"] = []
    return data


def save_paused_upload(batch_config, files, completed_files=None):
    """batch_config: dict of everything needed to re-invoke
    process_uploads() on resume (manga_id, group_ids, upload_type,
    language, scanlator_name, per_file_group_map, per_file_scanlator_map,
    is_group_upload, current_user_id, thread_count).

    files: list of per-file dicts, each at minimum {"filepath", "size",
    "number", "title"} (i.e. a normal file_info dict) plus optionally
    "upload_location" and "offset" for any file that had actually begun
    transferring when the pause happened. Files with no upload_location
    yet are resumed by simply re-queuing them from scratch - there's
    nothing server-side to verify for those.

    completed_files: file-info dicts (same {"filename", "filepath",
    "number", "title", "size"} shape as `files`, minus the
    upload_location/offset fields since they're no longer relevant) for
    files from THIS overall batch that have already finished
    successfully, whether before or after the pause this call is
    persisting. This is what lets a screen rebuilt from scratch (e.g.
    via for_resume() after the app was closed and reopened) know "these
    files are done, show them as Done" - with enough real data
    (filepath, size) to render a proper row - instead of having no
    record of them at all. A v1 paused-state file had no such field, so
    any file the user had already gotten through before pausing simply
    vanished from view once the app restarted, even though nothing was
    actually lost server-side.

    This is a full-file overwrite - if you're updating just one file's
    entry (adding/removing/replacing it) rather than replacing the
    ENTIRE files list, use update_paused_upload() instead, which holds
    the lock across the read AND the write so nothing else can save in
    between and get silently clobbered. Calling this directly from more
    than one thread for the same paused batch is exactly the race that
    caused files to vanish from disk after being right-click-resumed
    while the main batch was still pausing.

    Uses the same atomic tempfile + os.replace pattern as save_db(): a
    torn/partial write to this file would either lose the ability to
    resume (recoverable - falls back to "nothing paused") or, worse,
    leave a file that looks valid but has a corrupted offset, which is
    why this can't be a plain open-and-write.
    """
    with _paused_upload_lock:
        _save_paused_upload_unlocked(batch_config, files, completed_files)


def _dedupe_by_filename(file_dicts):
    seen = {}
    for f in file_dicts:
        seen[f["filename"]] = f  # last one wins, matches list-concat "replace" semantics used elsewhere
    return list(seen.values())


def _save_paused_upload_unlocked(batch_config, files, completed_files=None):
    data = {
        "schema_version": PAUSED_UPLOAD_SCHEMA_VERSION,
        "paused_at": time.time(),
        "batch_config": batch_config,
        "files": files,
        "completed_files": _dedupe_by_filename(completed_files or []),
    }
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(CACHE_DIR), prefix=".mangadot_paused_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                # default=str is a safety net, not a substitute for
                # keeping non-serializable objects (os.DirEntry, etc.)
                # out of these dicts in the first place - see
                # parser.finalize_file_entries(). Without SOME fallback
                # here, one stray non-serializable field anywhere in
                # `files`/`completed_files` throws, is swallowed below,
                # and silently discards this ENTIRE save - which is
                # worse than saving with one field stringified.
                json.dump(data, f, indent=2, default=str)
            os.replace(tmp, PAUSED_UPLOAD_PATH)
        finally:
            if os.path.exists(tmp):
                try: os.remove(tmp)
                except OSError: pass
    except (OSError, TypeError, ValueError) as e:
        # This used to be logging.debug(), which is easy to miss - a
        # save that silently fails here means paused/completed upload
        # state stops persisting from this point on with NOTHING
        # visible in the UI to indicate it, which is exactly what went
        # undiagnosed for several rounds before finding it in the log.
        logging.warning("save_paused_upload: failed to write %s: %s", PAUSED_UPLOAD_PATH, e)


def update_paused_upload(mutate_files_fn, batch_config_if_new=None, mutate_completed_fn=None):
    """Atomically load-modify-save paused_upload.json under a single
    lock acquisition, so no other thread's save can land in between the
    read and the write and get silently overwritten. This is the fix
    for files vanishing from the paused-upload state when the main
    upload batch and a per-file inline resume both try to update the
    same JSON file at close to the same time.

    mutate_files_fn: called as mutate_files_fn(current_files) where
    current_files is the "files" list from whatever's currently on disk
    (or [] if there's nothing paused yet / nothing usable). Must return
    the NEW complete files list to save. Examples:
        # remove one file that just finished resuming:
        update_paused_upload(lambda files: [f for f in files if f["filename"] != name])
        # add/replace one file's paused entry:
        update_paused_upload(lambda files: [f for f in files if f["filename"] != name] + [new_entry])

    mutate_completed_fn: called as mutate_completed_fn(current_completed)
    where current_completed is the "completed_files" list from disk (or
    [] if none) - same file-info-dict shape as `files`. Must return the
    NEW complete list. Optional - defaults to a no-op (keeps whatever's
    already on disk unchanged), since most mutations (a file pausing
    again, a per-file cancel) don't touch completion status. Pass this
    when a file finishes for good, e.g.:
        update_paused_upload(
            lambda files: [f for f in files if f["filename"] != name],
            mutate_completed_fn=lambda done: done + [file_info],
        )

    batch_config_if_new: the batch_config to use if there is NOT already
    a paused state on disk (i.e. this is the very first file being
    paused in a fresh batch). Ignored if a paused state already exists -
    the existing batch_config is preserved as-is, since batch_config
    describes the ORIGINAL batch (manga_id, group_ids, etc.), which
    never changes over the life of one paused upload.

    If the resulting files list is empty AND the resulting completed
    list is also empty, this clears the paused state entirely (same as
    clear_paused_upload()) rather than writing an empty-but-present
    file. If files is empty but completed_files is not (e.g. the very
    last remaining file just finished), the paused state is kept with an
    empty files list so completed_files isn't lost - the caller is
    expected to treat an empty files list as "nothing left to resume"
    while still being able to show which files finished.

    Returns the new files list that was saved (or None if the paused
    state was cleared entirely)."""
    with _paused_upload_lock:
        existing = _load_paused_upload_unlocked()
        current_files = existing["files"] if existing else []
        current_completed = existing["completed_files"] if existing else []
        batch_config = existing["batch_config"] if existing else batch_config_if_new
        logging.debug("update_paused_upload: acquired lock, %d existing file(s), %d completed on disk",
                      len(current_files), len(current_completed))

        new_files = mutate_files_fn(current_files)
        new_completed = mutate_completed_fn(current_completed) if mutate_completed_fn else current_completed
        logging.debug("update_paused_upload: mutate produced %d file(s), %d completed",
                      len(new_files) if new_files else 0, len(new_completed) if new_completed else 0)

        if not new_files and not new_completed:
            _clear_paused_upload_unlocked()
            return None
        if batch_config is None:
            # Nothing to attach these files to (no existing state and no
            # batch_config_if_new was given) - this shouldn't normally
            # happen since the first-ever pause always provides
            # batch_config_if_new, but fail safe rather than write a
            # paused state that can never actually be resumed.
            logging.debug("update_paused_upload: no batch_config available; not saving.")
            return None

        _save_paused_upload_unlocked(batch_config, new_files, new_completed)
        return new_files


def clear_paused_upload():
    """Removes any paused-upload state - called once a resumed (or
    freshly restarted) upload actually completes, or when the user
    explicitly discards a pause rather than resuming it. Safe to call
    when there's nothing to clear."""
    with _paused_upload_lock:
        _clear_paused_upload_unlocked()


def _clear_paused_upload_unlocked():
    try:
        os.remove(PAUSED_UPLOAD_PATH)
    except FileNotFoundError:
        pass
    except OSError as e:
        logging.debug("clear_paused_upload: failed to remove %s: %s", PAUSED_UPLOAD_PATH, e)