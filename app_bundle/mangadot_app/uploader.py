"""TUS resumable-upload protocol client, plus MangaDot's batch init/complete
wrapper around it and the concurrent multi-file upload orchestrator.
"""
import io
import os
import re
import json
import time
import math
import random
import logging
import threading
import concurrent.futures

import requests
from requests.adapters import HTTPAdapter

from . import parser as parser_mod
from . import util
from . import config as config_mod
from . import net

BASE_URL             = "https://mangadot.net"
TUS_ENDPOINT         = f"{BASE_URL}/api/tus/"
BATCH_INIT_ENDPOINT  = f"{BASE_URL}/api/uploads/batch/init"

MAX_BATCH_SIZE       = 100
MAX_RETRIES          = 3
RETRY_DELAY          = 5
_VERIFY_CONCURRENCY  = 5
_VERIFY_SEM_WAIT     = 1
RETRYABLE_STATUSES   = [429, 500, 502, 503, 504, 524]
FATAL_SIZE_STATUSES  = [413, 415]
MAX_VERIFY_SECONDS   = 60

# Cross-worker / cross-thread batch completion pacing to eliminate MangaDot HTTP 429 rate limits
_BATCH_COMPLETE_LOCK = threading.Lock()
_LAST_BATCH_COMPLETE_TIME = 0.0
_BATCH_COMPLETE_MIN_INTERVAL = 2.5  # Enforce minimum 2.5 seconds between completion calls

def _pace_batch_complete(abort_event=None) -> bool:
    """Paces batch completion calls across all workers/threads.
    Ensures that consecutive POST /api/uploads/batch/{id}/complete requests
    have at least _BATCH_COMPLETE_MIN_INTERVAL (2.5s) between them, preventing
    MangaDot HTTP 429 rate limits during concurrent uploads.
    Returns False if abort_event is set during pacing, True otherwise."""
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

class _ChunkStream(io.BytesIO):
    """Wraps bytes payload with length and tracks bytes read to report real-time progress."""
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


class SessionExpiredError(Exception):
    pass


class BatchInitError(Exception):
    pass


class FileControl:
    """Per-file pause/cancel switches, layered on top of (never
    replacing) the existing batch-wide abort_event/pause_event.

    Every existing abort_event.is_set() / pause_event.is_set() check
    site in upload_file_tus continues to work unchanged - a batch
    pause/cancel still stops everything, exactly as before. This class
    adds an *additional*, independent per-file signal that a caller
    (typically the GUI, via a right-click "Pause"/"Cancel" on one row)
    can set without touching any other file's transfer.

    is_paused() / is_cancelled() are the OR of "this file's own event"
    and "the batch-wide event" - so call sites that already check e.g.
    `abort_event.is_set()` can be upgraded to
    `file_control.is_cancelled(abort_event)` and get both behaviors for
    free, with no risk of the per-file layer accidentally overriding a
    batch-wide stop.

    One FileControl is created per file that goes into a batch (see
    process_uploads' `controls` dict) and lives for that file's full
    upload, since it wraps two plain threading.Events - it does not
    need to be re-created or reset for a resume; resumed files simply
    get fresh FileControl instances the same as a first attempt would.
    """

    def __init__(self):
        self.pause_event = threading.Event()
        self.cancel_event = threading.Event()

    def pause(self):
        """Pause just this file - safe to call from any thread. The
        in-flight chunk (if any) still finishes or fails on its own
        terms first, same guarantee as the batch-wide pause_event; see
        upload_file_tus's docstring."""
        self.pause_event.set()

    def resume(self):
        """Clear a per-file pause so a still-running worker loop (one
        that hasn't yet returned a {"paused": True} result) can
        continue past its next check. Note: once a file's worker
        thread HAS already returned paused, "resuming" it for real
        means re-submitting it as a new upload via resume_hint (see
        resume_paused_upload) - this method only helps if the pause
        hasn't taken effect yet."""
        self.pause_event.clear()

    def cancel(self):
        """Cancel just this file - not resumable, same semantics as
        the batch-wide abort_event but scoped to one file. Safe to
        call from any thread."""
        self.cancel_event.set()

    def is_paused(self, batch_pause_event=None):
        if self.pause_event.is_set():
            return True
        return batch_pause_event is not None and batch_pause_event.is_set()

    def is_cancelled(self, batch_abort_event=None):
        if self.cancel_event.is_set():
            return True
        return batch_abort_event is not None and batch_abort_event.is_set()


_VERIFY_SEM       = None
_VERIFY_SEM_SIZE  = None
_VERIFY_SEM_LOCK  = threading.Lock()


def _verify_concurrency_for(thread_count):
    """_VERIFY_CONCURRENCY (5) was sized for small/default thread
    counts. At thread_count=30, up to 30 uploads can finish and enter
    verification within moments of each other, but only 5 could ever
    get a slot at once - every file past the first 5 sits in the
    semaphore queue burning real wall-clock time against its own
    verify_timeout (elapsed_verify is deliberately real time, not
    queue-adjusted - see the comment in upload_file_tus - because
    queue-adjusting it was the ORIGINAL "Verification timeout reached"
    bug). With enough threads and a big enough batch, most files never
    get a turn before timing out - exactly the "most chapters show
    Verification timeout" symptom this fixes.
    Scale with thread_count instead of a fixed constant: about a third
    of the upload threads may realistically be verifying at once,
    floored at the original 5 (matches previous behavior for small
    thread counts) and capped at 15 (each verify poll is still a real
    server round-trip - too many concurrent ones just moves the
    bottleneck server-side instead of fixing it)."""
    return max(_VERIFY_CONCURRENCY, min(15, thread_count // 3))


def get_verify_sem(thread_count=None):
    """thread_count: the batch's actual ThreadPoolExecutor size: sizes
    the semaphore to match on first creation. None (or omission)
    keeps the original fixed _VERIFY_CONCURRENCY, for any caller that
    genuinely doesn't know its batch's thread_count.
    This semaphore is a module-level singleton (shared across whatever
    batch(es) are running), so only the FIRST call's thread_count takes
    effect - later calls with a different thread_count do not resize
    an already-created semaphore. That matches how this app actually
    runs (one upload batch at a time per process), and avoids the
    complexity of resizing a semaphore threads may already be waiting
    on."""
    global _VERIFY_SEM, _VERIFY_SEM_SIZE
    if _VERIFY_SEM is None:
        with _VERIFY_SEM_LOCK:
            if _VERIFY_SEM is None:
                _VERIFY_SEM_SIZE = (
                    _verify_concurrency_for(thread_count) if thread_count else _VERIFY_CONCURRENCY
                )
                _VERIFY_SEM = threading.Semaphore(_VERIFY_SEM_SIZE)
    return _VERIFY_SEM


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


def build_shared_upload_session(session):
    """Clones the login session once into a dedicated session shared by
    every worker thread of one batch. requests.Session isn't formally
    thread-safe, but this is safe in practice under one strict invariant:
    headers/cookies/proxies/verify are snapshotted HERE, before the pool
    starts, and nothing mutates the shared session while workers are
    running (session-expiry re-auth builds a fresh session instead -
    see process_uploads' 401 path). Keep it that way.
    """
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


class _NoOpProgress:
    def __call__(self, filename, status, fraction, **kwargs):
        pass


def upload_file_tus(session, file_info, manga_id, group_ids,
                     upload_type, batch_id, language, scanlator_name, abort_event,
                     verify_timeout=MAX_VERIFY_SECONDS, current_user_id=None,
                     is_group_upload=False, has_file_specific_group=True,
                     upload_session=None, progress_callback=None,
                     pause_event=None, resume_hint=None, file_control=None,
                     skip_verification=True, thread_count=None):
    """pause_event: an optional threading.Event, checked at the same
    chunk-boundary points as abort_event (never mid-PATCH-request - a
    chunk that's already in flight always finishes or fails on its own
    terms before a pause takes effect, so the server never sees a
    request severed mid-transfer). When set, this returns a distinct
    {"paused": True, ...} result (not a failure) carrying the exact
    upload_location/offset the caller needs to persist and later verify
    before resuming - see config.save_paused_upload() and
    resume_paused_upload() below.

    file_control: an optional FileControl for this one file. Checked at
    every one of the same boundary points as abort_event/pause_event,
    via file_control.is_cancelled(abort_event) / .is_paused(pause_event)
    - both of which already fold in the batch-wide event, so this is a
    pure addition: a batch-wide pause/cancel still works exactly as
    before even when file_control is None or unused. A per-file cancel
    is reported the same way as a batch-wide abort (success=False,
    error="Cancelled") since it is NOT resumable - the caller is
    expected to just drop that file from any future resume, exactly
    like any other genuine failure. A per-file pause reports through
    the same {"paused": True, ...} path a batch-wide pause would.

    resume_hint: an optional {"upload_location": str, "offset": int,
    "fully_uploaded": bool} dict. When given, this SKIPS creating a new
    TUS upload session (the POST to TUS_ENDPOINT) entirely and resumes
    directly against the given upload_location/offset instead - this is
    what makes a resume actually continue the SAME server-side upload
    rather than starting a second, separate one for the same file.

    resume_hint's offset must already have been verified against the
    server (via a HEAD request - see resume_paused_upload()) by the
    caller before this is ever called; upload_file_tus itself does not
    re-verify it, since resume_paused_upload's whole job is to do that
    verification once per file up front and only pass resume_hint
    through for files that actually checked out."""
    progress_callback = progress_callback or _NoOpProgress()
    filename = file_info["filename"]
    filepath = file_info["filepath"]
    size     = file_info["size"]

    def _cancelled():
        return (abort_event.is_set() if abort_event is not None else False) or \
               (file_control.is_cancelled() if file_control is not None else False)

    def _paused():
        if pause_event is not None and pause_event.is_set():
            return True
        return file_control.is_paused() if file_control is not None else False

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

        if resume_hint is not None and resume_hint.get("fully_uploaded"):
            # This file's bytes were already 100% uploaded before the
            # pause - only verification polling remained. Skip straight
            # to that; there is no TUS session or chunk loop to resume.
            already_exists = False
            upload_location = None
            offset = size
            start_time = time.time()
        elif resume_hint is not None and resume_hint.get("upload_location"):
            already_exists = False
            upload_location = resume_hint["upload_location"]
            offset = resume_hint["offset"]
            start_time = time.time()
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
            if upload_type == "volume":
                tus_metadata["volume_number"] = file_info["number"]
                if file_info.get("title"):
                    tus_metadata["volume_title"] = file_info["title"]
            else:
                raw_title = file_info.get("title")
                if not raw_title or not str(raw_title).strip():
                    try:
                        raw_title = f"Chapter {float(file_info.get('number', 0)):g}"
                    except Exception:
                        raw_title = f"Chapter {file_info.get('number', 0)}"
                tus_metadata["chapter_title"] = str(raw_title).strip()
            if scanlator_name:
                tus_metadata["scanlator_name"] = scanlator_name

            encoded_metadata = parser_mod.encode_tus_metadata(tus_metadata)
            headers = {
                "Tus-Resumable":   "1.0.0",
                "Upload-Length":   str(size),
                "Upload-Metadata": encoded_metadata,
            }

            already_exists = False
            upload_location = None
            for attempt in range(MAX_RETRIES):
                if _cancelled(): return {"key": filename, "success": False, "error": "Aborted"}
                if _paused():
                    return {"key": filename, "paused": True, "upload_location": None, "offset": 0}
                try:
                    progress_callback(filename, "Creating upload...", 0.0)
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
                        progress_callback(filename, "Create Err... Retrying", 0.0)
                        if not _interruptible_sleep(RETRY_DELAY, abort_event):
                            return {"key": filename, "success": False, "error": "Aborted"}
                    else: return {"key": filename, "success": False, "error": f"Init failed: {str(e)[:30]}"}

            offset = size if already_exists else 0
            start_time = time.time()

        # Speed/ETA must be computed from bytes moved DURING THIS RUN,
        # not from `offset` itself - offset already includes bytes
        # uploaded in an earlier, separate session for a resumed file
        # (resume_hint["offset"] can be many MB on the very first loop
        # iteration here, while `elapsed` is still a fraction of a
        # second since start_time was just set above). Dividing the
        # full offset by that tiny elapsed time produces wildly
        # inflated speeds like "1.58 GB/s" on a resumed file that's
        # barely started this session. bytes_at_session_start pins the
        # baseline so speed reflects only what actually moved just now.
        bytes_at_session_start = offset

        chunk_size = 20 * 1024 * 1024  # 20 MB native chunks matching site uploader

        try:
            with open(filepath, 'rb') as f:
                while offset < size:
                    if _cancelled(): return {"key": filename, "success": False, "error": "Aborted"}
                    if _paused():
                        return {"key": filename, "paused": True, "upload_location": upload_location, "offset": offset}

                    if f.tell() != offset:
                        f.seek(offset)

                    chunk = f.read(chunk_size)
                    if not chunk: break

                    chunk_done = False
                    resynced   = False
                    for patch_attempt in range(MAX_RETRIES):
                        try:
                            elapsed = time.time() - start_time
                            bytes_this_session = offset - bytes_at_session_start
                            if elapsed > 0 and bytes_this_session > 0:
                                speed_bps = bytes_this_session / elapsed
                                remaining_bytes = size - offset
                                eta_seconds = remaining_bytes / speed_bps if speed_bps > 0 else 0
                                speed_str = f"{util.fmt_size(speed_bps)}/s"
                                eta_str = util.fmt_duration(eta_seconds)
                            else:
                                speed_str = "Calculating..."
                                eta_str = "..."

                            progress_callback(
                                filename, "Uploading...", offset / size,
                                current=offset, total=size,
                                speed_str=speed_str, eta_str=eta_str
                            )
                            
                            patch_headers = {
                                "Tus-Resumable": "1.0.0",
                                "Upload-Offset": str(offset),
                                "Content-Type":  "application/offset+octet-stream",
                            }
                            def _on_chunk_bytes(n):
                                cur = offset + n
                                progress_callback(
                                    filename, "Uploading...", cur / size,
                                    current=cur, total=size,
                                    speed_str=speed_str, eta_str=eta_str
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
                                    progress_callback(filename, f"Resyncing chunk... ({patch_attempt + 1})", offset / size, current=offset, total=size)
                                    if not _interruptible_sleep(_compute_retry_delay(patch_res, patch_attempt), abort_event):
                                        return {"key": filename, "success": False, "error": "Aborted"}
                                else: return {"key": filename, "success": False, "error": "HTTP 409 (Offset Conflict)"}
                            elif patch_res.status_code in RETRYABLE_STATUSES:
                                if patch_attempt < MAX_RETRIES - 1:
                                    progress_callback(filename, f"Retrying chunk (HTTP {patch_res.status_code}, attempt {patch_attempt + 1})...", offset / size, current=offset, total=size)
                                    if not _interruptible_sleep(_compute_retry_delay(patch_res, patch_attempt), abort_event):
                                        return {"key": filename, "success": False, "error": "Aborted"}
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
                                progress_callback(filename, f"Net Err, Retrying... (attempt {patch_attempt + 1})", offset / size, current=offset, total=size)
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

        found        = False
        found_item   = None
        verify_start = time.time()

        if skip_verification:
            # User opted out of the post-upload verification poll entirely
            # (see MAX_VERIFY_SECONDS / verify_timeout above) - the file
            # already finished its TUS upload successfully at this point,
            # we just never confirm it landed with the right chapter
            # number/group/scanlator server-side. Distinct from the
            # no-group case below: that one still tries to verify when it
            # can and only skips when there's nothing to match against;
            # this is an explicit, unconditional user choice.
            label = "✅ Already Exists" if already_exists else "✅ Uploaded (Unverified — skipped)"
            progress_callback(filename, label, 1.0, current=size, total=size, speed=0.0, eta=0.0)
            return {
                "key": filename,
                "success": True,
                "warning": None if already_exists else "Uploaded without verification: verification was skipped by user setting.",
            }

        if not group_ids and not scanlator_name:
            if is_group_upload and not has_file_specific_group:
                label = "⚠️ Uploaded (Unverified — no group)"
                progress_callback(filename, label, 1.0, current=size, total=size, speed=0.0, eta=0.0)
                return {
                    "key": filename,
                    "success": True,
                    "warning": "Uploaded without attribution verification: no resolved group/scanlator for this file."
                }
            label = "✅ Already Exists" if already_exists else "✅ Uploaded"
            progress_callback(filename, label, 1.0, current=size, total=size, speed=0.0, eta=0.0)
            return {"key": filename, "success": True}

        last_reported_elapsed = -RETRY_DELAY  # force an immediate first report
        while not found:
            if _cancelled(): return {"key": filename, "success": False, "error": "Aborted"}
            if _paused():
                return {"key": filename, "paused": True, "upload_location": None, "offset": size,
                        "fully_uploaded": True}

            # elapsed_verify is real wall-clock time since this file
            # entered verification - full stop. An earlier version tried
            # to subtract out time spent waiting for a free verify slot
            # (only _VERIFY_CONCURRENCY=3 at once) on the theory that
            # queued time "isn't the file's fault". In practice that
            # made the configured verify_timeout meaningless: every
            # failed semaphore acquire below also cost a full
            # RETRY_DELAY sleep just above, and only the acquire portion
            # was ever subtracted back out, so elapsed_verify drifted
            # further and further behind real time the longer a big
            # batch congested the 3 verify slots. Symptom: setting the
            # timeout to 10/30/60s had little effect - the real timeout
            # kept firing much later than the configured value, if it
            # ever caught up at all. Wall-clock time is what the user
            # actually set and actually sees ticking in the "Verifying...
            # (Ns)" label, so the check and the label now agree exactly.
            elapsed_verify = int(time.time() - verify_start)
            if elapsed_verify >= verify_timeout:
                if already_exists:
                    label = "✅ Already Exists"
                else:
                    label = "✅ Uploaded (Pending Index)"
                progress_callback(filename, label, 1.0, current=size, total=size, speed=0.0, eta=0.0)
                return {
                    "key": filename,
                    "success": True,
                    "warning": None if already_exists else "Upload completed via TUS; awaiting server indexing in /api/uploads/mine."
                }

            # Report to the GUI at most once per RETRY_DELAY (5s), NOT
            # once per semaphore-retry iteration. upload_progress_screen
            # (_UploadWorker.progress_cb) forwards every call here
            # straight to a Qt Signal delivered on the main thread, and
            # the GUI's own _tick_verifying_timers already runs a local
            # 1s QTimer per verifying row that advances the "Verifying...
            # (Ns)" label between backend updates on its own (see that
            # method's docstring) - it was built expecting this callback
            # only every ~5s. A first attempt at this fix made the
            # semaphore wait short (~1s) for responsive timeout-checking
            # but called progress_callback on every one of those fast
            # iterations too; with _VERIFY_CONCURRENCY=8 and a large
            # batch, dozens of files could be queued on the semaphore at
            # once, each emitting a signal roughly once a second - a
            # sustained flood of cross-thread queued Qt calls big enough
            # to saturate the event loop and freeze the window ("Not
            # Responding"), even though no single call blocked. The
            # semaphore retry loop below still spins fast (bounded by
            # _VERIFY_SEM_WAIT) so elapsed_verify/verify_timeout keep
            # getting rechecked promptly - only the GUI-facing report
            # rate changed, back to what the GUI already expects.
            if elapsed_verify - last_reported_elapsed >= RETRY_DELAY:
                progress_callback(filename, f"Verifying... ({elapsed_verify}s)", 1.0, current=size, total=size, speed=0.0, eta=0.0)
                last_reported_elapsed = elapsed_verify

            sem = get_verify_sem(thread_count)
            # Bounded acquire instead of a blocking `with sem:` - lets
            # this loop iteration give up on waiting for a slot and go
            # back around to re-check elapsed_verify/verify_timeout
            # (and refresh the displayed label) rather than blocking
            # indefinitely on a busy semaphore for however long it takes.
            #
            # This wait is intentionally short (_VERIFY_SEM_WAIT, ~1s) and
            # is the ONLY wait in this loop iteration when a slot isn't
            # free - there is no separate RETRY_DELAY sleep stacked in
            # front of it. An earlier version slept the full RETRY_DELAY
            # (5s) *and then* did a RETRY_DELAY-bounded acquire, so every
            # failed acquire cost ~10s of real wall-clock time, and with
            # only _VERIFY_CONCURRENCY slots available that time all
            # counted against verify_timeout - a file queued behind a
            # busy semaphore on a large batch could burn its entire
            # timeout budget without ever reaching the server check.
            # Retrying quickly here (and only sleeping the full
            # RETRY_DELAY after an actual completed check finds no match,
            # further down) keeps queued files responsive without
            # falsely eating into their timeout.
            acquired = sem.acquire(timeout=_VERIFY_SEM_WAIT)
            if not acquired:
                continue
            try:
                # Primary check: /api/uploads/mine (reliable even while awaiting moderation)
                try:
                    mine_items = net.fetch_my_uploads(
                        worker_session, manga_id=manga_id, upload_type=upload_type, language=language, limit=50, max_pages=2
                    )
                except SessionExpiredError:
                    raise
                except Exception as e:
                    logging.debug("verify: error checking /api/uploads/mine: %s", e)
                    mine_items = None

                if isinstance(mine_items, list) and mine_items:
                    for item in mine_items:
                        try:
                            if upload_type == "volume":
                                match = math.isclose(float(item.get("volume_number", -1)), float(file_info["number"]), abs_tol=0.001)
                            else:
                                match = math.isclose(float(item.get("chapter_number", -1)), float(file_info["number"]), abs_tol=0.001)
                        except (ValueError, TypeError):
                            match = False

                        if not match:
                            continue
                        if item.get("language") and language and str(item["language"]).lower() != str(language).lower():
                            continue

                        item_group_ids = []
                        if item.get("group_id"):
                            item_group_ids.append(item["group_id"])
                        for g in item.get("groups") or []:
                            if isinstance(g, dict) and g.get("id"):
                                item_group_ids.append(g["id"])
                            elif isinstance(g, int):
                                item_group_ids.append(g)

                        item_scanlator = (item.get("scanlator_name") or item.get("scanlator") or "").strip().lower()

                        if group_ids and any(gid in item_group_ids for gid in group_ids):
                            found_item = item
                            found = True
                            break

                        if not group_ids and scanlator_name:
                            if isinstance(item_scanlator, str) and item_scanlator == scanlator_name.strip().lower():
                                found_item = item
                                found = True
                                break

                        if not group_ids and not scanlator_name:
                            found_item = item
                            found = True
                            break

                if found:
                    break

                if not _interruptible_sleep(min(2.0, RETRY_DELAY), abort_event):
                    return {"key": filename, "success": False, "error": "Aborted"}
            except SessionExpiredError:
                raise
            except (requests.exceptions.RequestException, json.JSONDecodeError):
                continue
            finally:
                # Manual acquire() above (replacing the previous `with
                # get_verify_sem():`) needs an explicit matching release,
                # in a finally so it still runs on every exit path from
                # this try block (normal completion, SessionExpiredError
                # re-raised, or the request-exception `continue`) -
                # without this the permit would leak on any of those
                # paths and the verify slots (_VERIFY_CONCURRENCY) would
                # eventually starve entirely as more files upload over a
                # long session.
                sem.release()

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
        progress_callback(filename, label, 1.0, current=size, total=size, speed=0.0, eta=0.0)
        return {"key": filename, "success": True}
    finally:
        if owns_session:
            worker_session.close()


def process_uploads(files_to_upload, req_session, manga_id, group_ids,
                     upload_type, language, scanlator_name, thread_count,
                     per_file_group_map=None, verify_timeout=MAX_VERIFY_SECONDS,
                     current_user_id=None, is_group_upload=None,
                     progress_callback=None, on_batch_event=None,
                     per_file_scanlator_map=None, abort_event=None,
                     pause_event=None, on_file_paused=None, resume_hints=None,
                     file_controls=None, on_file_cancelled=None,
                     per_file_language_map=None, skip_verification=True):
    """abort_event: an optional threading.Event the caller keeps a
    reference to. If provided, setting it from another thread (e.g. a
    GUI's "cancel"/"stop background work" handler) will interrupt this
    batch at the next retry/chunk/verify-poll boundary - the same
    mechanism already used internally for session-expiry pauses. If not
    provided, a fresh event is created and used only internally, exactly
    as before (this batch simply can't be cancelled from outside).

    pause_event: like abort_event, but for a resumable pause rather than
    a cancellation. Files that were mid-transfer when paused report
    their exact upload_location/offset via on_file_paused(file_info,
    upload_location, offset, fully_uploaded) instead of being counted as
    failed - the caller is responsible for persisting that (see
    config.save_paused_upload()) and later resuming via
    resume_paused_upload(). Deliberately NOT threaded through the return
    tuple: the only real caller does a strict 3-value unpack of this
    function's return, so changing that shape would break it. A
    callback matches the existing on_batch_event pattern instead.

    Files not yet started when the pause takes effect (still queued,
    never got as far as executor.submit) are reported via
    on_file_paused too, with upload_location=None and offset=0 - on
    resume they're simply re-queued from scratch, since there's nothing
    server-side to verify for a file that was never sent.

    resume_hints: an optional dict, keyed the same way as
    per_file_group_map/per_file_scanlator_map (norm_filepath ->
    {"upload_location": str, "offset": int, "fully_uploaded": bool}).
    Threaded through to upload_file_tus's resume_hint parameter for any
    file that has an entry - see resume_paused_upload(), which is
    responsible for populating this only with entries it has already
    verified against the server.

    file_controls: an optional dict the CALLER creates and keeps a
    reference to, mapping norm_filepath -> uploader.FileControl(). If a
    file's norm_filepath has an entry, that FileControl is passed
    through to upload_file_tus for that file, letting the caller
    pause/resume/cancel that single file independently of the rest of
    the batch (e.g. a GUI's per-row right-click menu) without affecting
    any other file's transfer or the batch-wide abort_event/pause_event.
    Files with no entry behave exactly as before (batch-wide control
    only) - this parameter is purely additive. The caller is
    responsible for creating one FileControl per file up front (before
    calling process_uploads) if it wants this; process_uploads never
    creates or removes entries from this dict itself.

    on_file_cancelled: like on_file_paused, but for a per-file cancel
    (file_control.cancel()) specifically - called as
    on_file_cancelled(file_info) once that file's worker actually stops
    and returns "Aborted"/"Cancelled" for reasons attributable to its
    OWN FileControl rather than the batch. This is a courtesy signal
    only (mark_failed already handles putting the file in the normal
    failed/reasons return either way) - it exists so a GUI can, for
    example, distinguish "I cancelled this one file on purpose" from "it
    failed for a real network/server reason" without inspecting the
    error string.

    per_file_language_map: an optional dict, keyed the same way as
    per_file_group_map/per_file_scanlator_map (norm_filepath -> language
    code). A file with an entry here uploads under THAT language instead
    of the batch-wide `language` argument - resolved per-file at the
    same point group/scanlator overrides already are, then passed
    through to upload_file_tus's own `language` parameter (which was
    already a plain per-call argument even before this - only the batch
    layer above it ever assumed one language for the whole run). Files
    with no entry use `language` unchanged, exactly like the other two
    per-file maps. NOTE: does NOT split BATCH_INIT_ENDPOINT chunks by
    language - confirmed via live test that the server assigns each
    chapter's language from its own TUS upload metadata, not from
    batch-init's `language` field, so mixed-language files safely share
    one chunk/batch_id."""
    progress_callback = progress_callback or _NoOpProgress()
    on_batch_event = on_batch_event or (lambda event, **kwargs: None)
    on_file_paused = on_file_paused or (lambda *a, **kw: None)
    on_file_cancelled = on_file_cancelled or (lambda *a, **kw: None)
    resume_hints = resume_hints or {}
    file_controls = file_controls or {}

    per_file_group_map = per_file_group_map or {}
    per_file_scanlator_map = per_file_scanlator_map or {}
    per_file_language_map = per_file_language_map or {}

    if is_group_upload is None:
        is_group_upload = bool(group_ids) or any(per_file_group_map.values())

    chunks = [files_to_upload[i:i + MAX_BATCH_SIZE] for i in range(0, len(files_to_upload), MAX_BATCH_SIZE)]

    failed_chapters = []
    failure_reasons = {}
    session_expired = False
    abort_event      = abort_event if abort_event is not None else threading.Event()

    shared_upload_session = build_shared_upload_session(req_session)

    def mark_failed(name, reason, status):
        progress_callback(name, status, 1.0)
        if name not in failed_chapters:
            failed_chapters.append(name)
        failure_reasons[name] = reason

    def control_for(f):
        norm_path = f.get("norm_filepath") or parser_mod.norm_filepath(f["filepath"])
        return file_controls.get(norm_path)

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=thread_count) as executor:
            for chunk in chunks:
                if pause_event is not None and pause_event.is_set():
                    for f in chunk:
                        on_file_paused(f, None, 0, False)
                    continue

                # A file individually paused/cancelled before its chunk
                # ever started (still queued, never reached
                # executor.submit) needs to be pulled out of this chunk
                # here - upload_file_tus can only honor a per-file
                # FileControl once it's actually running, so a file
                # that's paused/cancelled while still waiting in the
                # queue would otherwise upload anyway.
                still_queued = []
                for f in chunk:
                    fc = control_for(f)
                    if fc is not None and fc.is_cancelled():
                        mark_failed(f["filename"], "Cancelled", "❌ Cancelled")
                        on_file_cancelled(f)
                    elif fc is not None and fc.is_paused(pause_event):
                        on_file_paused(f, None, 0, False)
                    else:
                        still_queued.append(f)
                chunk = still_queued
                if not chunk:
                    continue

                if session_expired:
                    for f in chunk:
                        mark_failed(f["filename"], "Paused — session expired before upload", "⏸️ Paused (Session)")
                    continue

                chapters_payload = []
                for f in chunk:
                    raw_title = f.get("title")
                    if not raw_title or not str(raw_title).strip():
                        try:
                            raw_title = f"Chapter {float(f.get('number', 0)):g}"
                        except Exception:
                            raw_title = f"Chapter {f.get('number', 0)}"
                    chapters_payload.append({
                        "chapter_number": f["number"] if upload_type == "chapter" else 0,
                        "volume_number": f["number"] if upload_type == "volume" else None,
                        "chapter_title": str(raw_title).strip()
                    })

                chunk_group_ids = set(group_ids) if group_ids else set()
                for f in chunk:
                    f_groups = per_file_group_map.get(f.get("norm_filepath") or parser_mod.norm_filepath(f["filepath"]))
                    if f_groups:
                        chunk_group_ids.update(f_groups)
                init_payload = {"manga_id": manga_id, "language": language, "group_ids": list(chunk_group_ids),
                                 "type": upload_type, "scanlator_name": scanlator_name, "chapters": chapters_payload}
                batch_id = None
                try:
                    res = req_session.post(BATCH_INIT_ENDPOINT, json=init_payload, timeout=(10, 30))
                    if res.status_code in (401, 403):
                        session_expired = True
                        abort_event.set()
                        on_batch_event("session_expired")
                        for f in chunk:
                            mark_failed(f["filename"], "Paused — authentication expired", "⏸️ Paused (Auth)")
                        continue
                    res.raise_for_status()
                    batch_data = res.json()
                    batch_id = batch_data.get("batch_id")
                    if not batch_id and not batch_data.get("success"):
                        raise BatchInitError(str(batch_data)[:200])
                except (requests.exceptions.RequestException, json.JSONDecodeError, BatchInitError, KeyError) as e:
                    on_batch_event("batch_init_failed", error=str(e)[:80])
                    for f in chunk:
                        mark_failed(f["filename"], f"Batch init failed: {str(e)[:80]}", "❌ Batch Init Failed")
                    continue

                # Sliding-window submission instead of "submit the whole
                # chunk, let the executor's internal queue throttle it":
                # with 41 files and thread_count=4, submitting all 41 up
                # front means 37 futures sit unscheduled inside the
                # executor with nothing checking their FileControl until
                # the executor happens to reach them - a right-click
                # Pause/Cancel on one of those rows would silently do
                # nothing until its turn came up, sometimes much later,
                # sometimes never in practice. Instead: submit only as
                # many as thread_count, and submit each NEXT file only
                # once a slot frees up - re-checking that next file's
                # FileControl/pause_event/abort_event right before that
                # submission, so a pause/cancel clicked while a file is
                # still waiting for a slot is honored immediately rather
                # than only once it's already running.
                pending = list(chunk)
                futures = {}
                chunk_had_success = False

                def _submit_next():
                    """Pops and submits files from `pending` until either
                    the window is full (len(futures) == thread_count) or
                    `pending` is empty. Files that are paused/cancelled
                    via their FileControl right at this moment are
                    reported and skipped instead of submitted - this is
                    the check that a batch-submit-everything approach
                    was missing for anything past the first thread_count
                    files."""
                    while pending and len(futures) < thread_count:
                        f = pending.pop(0)
                        if pause_event is not None and pause_event.is_set():
                            on_file_paused(f, None, 0, False)
                            continue
                        fc = control_for(f)
                        if fc is not None and fc.is_cancelled(abort_event):
                            mark_failed(f["filename"], "Cancelled", "❌ Cancelled")
                            on_file_cancelled(f)
                            continue
                        if fc is not None and fc.is_paused(pause_event):
                            on_file_paused(f, None, 0, False)
                            continue

                        norm_path = f.get("norm_filepath") or parser_mod.norm_filepath(f["filepath"])
                        file_specific_groups = per_file_group_map.get(norm_path)
                        file_specific_scanlator = per_file_scanlator_map.get(norm_path)
                        file_specific_language = per_file_language_map.get(norm_path)
                        resume_hint = resume_hints.get(norm_path)

                        if file_specific_scanlator:
                            resolved_group_ids = []
                            has_file_specific_group = False
                            resolved_scanlator = file_specific_scanlator
                        else:
                            has_file_specific_group = bool(file_specific_groups)
                            resolved_group_ids = file_specific_groups if file_specific_groups is not None else group_ids
                            resolved_scanlator = scanlator_name

                        resolved_language = file_specific_language if file_specific_language else language

                        future = executor.submit(
                            upload_file_tus, req_session, f, manga_id,
                            resolved_group_ids,
                            upload_type, batch_id, resolved_language, resolved_scanlator, abort_event,
                            verify_timeout, current_user_id,
                            is_group_upload, has_file_specific_group,
                            shared_upload_session, progress_callback,
                            pause_event, resume_hint, fc,
                            skip_verification, thread_count
                        )
                        futures[future] = f

                def _handle_one_result(future):
                    nonlocal chunk_had_success, session_expired
                    f_info = futures.pop(future)
                    fc = control_for(f_info)
                    try:
                        result = future.result()
                        if result.get('paused'):
                            on_file_paused(
                                f_info, result.get('upload_location'), result.get('offset', 0),
                                result.get('fully_uploaded', False),
                            )
                            progress_callback(result['key'], "⏸️ Paused", result.get('offset', 0) / max(f_info.get('size', 1), 1))
                        elif result['success']:
                            chunk_had_success = True
                            if result.get('warning'):
                                on_batch_event("file_warning", filename=f_info['filename'], warning=result['warning'])
                        else:
                            # A per-file cancel (as opposed to a genuine
                            # upload failure) surfaces here as an
                            # ordinary "Aborted" result, same as a
                            # batch-wide abort would - the
                            # is_cancelled() check tells us which one
                            # actually caused it, purely so
                            # on_file_cancelled can fire for the GUI.
                            if fc is not None and fc.cancel_event.is_set():
                                on_file_cancelled(f_info)
                                mark_failed(result['key'], "Cancelled", "❌ Cancelled")
                            else:
                                mark_failed(result['key'], result.get('error', 'Unknown error'), f"❌ {result['error']}")
                    except SessionExpiredError:
                        session_expired = True
                        abort_event.set()
                        on_batch_event("session_expired")
                        mark_failed(f_info["filename"], "Paused — authentication expired", "⏸️ Paused (Auth)")

                try:
                    _submit_next()
                    while futures:
                        done, _ = concurrent.futures.wait(
                            list(futures.keys()), return_when=concurrent.futures.FIRST_COMPLETED
                        )
                        for done_future in done:
                            _handle_one_result(done_future)
                        # A slot just freed up - if the batch/this file's
                        # pause/cancel wasn't set, pull the next waiting
                        # file in immediately, checking IT fresh too.
                        _submit_next()
                    # Anything left in `pending` here means pause/cancel
                    # emptied the window before every file got a turn -
                    # already reported via on_file_paused/on_file_cancelled
                    # inside _submit_next(), nothing further to do.
                except KeyboardInterrupt:
                    abort_event.set()
                    for f in futures:
                        f.cancel()
                    raise

                if batch_id and not session_expired and chunk_had_success:
                    def _send_complete_worker(b_id, cookies_snap, headers_snap, proxies_snap, verify_opt, a_event, ev_cb):
                        MAX_COMPLETE_RETRIES = 5
                        with requests.Session() as s:
                            s.cookies.update(cookies_snap)
                            s.headers.update(headers_snap)
                            if proxies_snap:
                                s.proxies.update(proxies_snap)
                            s.verify = verify_opt
                            for comp_attempt in range(MAX_COMPLETE_RETRIES):
                                comp_res = None
                                try:
                                    if not _pace_batch_complete(a_event):
                                        break
                                    comp_res = s.post(f"{BASE_URL}/api/uploads/batch/{b_id}/complete", timeout=(10, 30))
                                    if comp_res.status_code in (401, 403):
                                        break
                                    comp_res.raise_for_status()
                                    logging.debug(f"Batch {b_id} completion housekeeping succeeded.")
                                    break
                                except requests.exceptions.RequestException as e:
                                    resp = e.response if hasattr(e, 'response') and e.response is not None else comp_res
                                    delay = _compute_retry_delay(resp, comp_attempt)
                                    if resp is not None and resp.status_code == 429:
                                        delay = max(delay, 30.0)

                                    if comp_attempt < MAX_COMPLETE_RETRIES - 1:
                                        logging.warning(f"Batch complete hit rate limit/error. Retrying in {delay:.1f}s (Attempt {comp_attempt + 1}/{MAX_COMPLETE_RETRIES})...")
                                        if not _interruptible_sleep(delay, a_event):
                                            break
                                    else:
                                        if ev_cb:
                                            ev_cb("batch_complete_failed", batch_id=b_id, error=str(e))
                                        logging.warning(f"Batch {b_id} complete call failed after {MAX_COMPLETE_RETRIES} attempts: {e}")

                    # Decoupled / asynchronous housekeeping call: does not block the UI or subsequent upload batches
                    threading.Thread(
                        target=_send_complete_worker,
                        args=(
                            batch_id,
                            dict(req_session.cookies),
                            dict(req_session.headers),
                            dict(req_session.proxies) if req_session.proxies else {},
                            req_session.verify,
                            abort_event,
                            on_batch_event,
                        ),
                        daemon=True,
                    ).start()
    except KeyboardInterrupt:
        abort_event.set()
        raise
    finally:
        shared_upload_session.close()

    return failed_chapters, session_expired, failure_reasons


def resume_paused_upload(paused_state, req_session, progress_callback=None,
                          on_batch_event=None, abort_event=None,
                          pause_event=None, on_file_paused=None,
                          file_controls=None, on_file_cancelled=None,
                          only_filenames=None):
    """Resumes a previously-paused upload batch from persisted state
    (see config.load_paused_upload()/save_paused_upload()).

    only_filenames: an optional set/list of filenames. If given, ONLY
    those files from paused_state["files"] are resumed - everything
    else in the paused state is left untouched (i.e. NOT touched,
    re-queued, or removed from disk here). This is what a GUI's
    per-file "Resume" (as opposed to "Resume all") should pass: resume
    exactly the one file the user right-clicked, without pulling every
    other still-paused file back into this run too. The caller remains
    responsible for updating/re-persisting config's paused-upload state
    afterwards to reflect which files are no longer paused (see
    upload_progress_screen._persist_paused_state - the same
    incremental-save pattern applies to a partial resume).

    file_controls / on_file_cancelled: threaded straight through to
    process_uploads() - see its docstring. Lets per-file pause/cancel
    keep working across a resume the same as it does on a fresh upload.

    Nothing in paused_state is trusted blindly. For every file that had
    an upload_location recorded (i.e. was actually mid-transfer when
    paused), this sends a real HEAD request to that URL first and asks
    the server what offset it actually has right now - a TUS upload
    session can expire server-side, especially across a pause spanning
    an app restart, and the only way to know is to ask. Three outcomes
    per file:

    - Server confirms the same offset (or a higher one, e.g. if a
      resync happened before the pause was noticed) -> resume from
      the server-confirmed offset via upload_file_tus's resume_hint.
    - Server responds but with a LOWER offset than we saved (unusual,
      but possible if the server-side record was somehow rolled back) ->
      trust the server's lower number, not our stale local one.
    - HEAD fails entirely (404/410/timeout/anything) -> this upload
      session is gone. Fall back to a completely fresh upload for that
      one file, starting a new TUS session from byte 0. This is safe -
      it just means that file re-uploads instead of resuming - but
      silently treating a dead session as resumable would either fail
      outright or, worse, upload corrupted/misaligned data.

    Files with fully_uploaded=True (paused during verification polling,
    after their bytes were already 100% sent) skip the HEAD check
    entirely - there's no TUS session to verify, they just need
    verification polling picked back up.

    Files with no upload_location at all (paused before they'd even
    started) are simply re-queued from scratch, same as any normal
    upload of that file.

    Returns the same (failed_chapters, session_expired, failure_reasons)
    tuple as process_uploads(), plus a dict of per-file resume outcomes
    ({"resumed": [...], "restarted": [...], "not_started": [...]}) via
    on_batch_event("resume_summary", ...) so the caller can tell the
    user what actually happened (e.g. "2 files resumed, 1 had to
    restart because its upload session expired").
    """
    on_batch_event = on_batch_event or (lambda event, **kwargs: None)

    batch_config = paused_state["batch_config"]
    saved_files = paused_state["files"]
    if only_filenames is not None:
        only_filenames = set(only_filenames)
        saved_files = [f for f in saved_files if f["filename"] in only_filenames]

    shared_session = build_shared_upload_session(req_session)
    resume_hints = {}
    files_to_upload = []
    resumed, restarted, not_started = [], [], []

    try:
        for f in saved_files:
            norm_path = parser_mod.norm_filepath(f["filepath"])
            files_to_upload.append(f)

            upload_location = f.get("upload_location")
            if not upload_location:
                logging.debug("resume_paused_upload: %r has no upload_location, will restart from scratch", f["filename"])
                not_started.append(f["filename"])
                continue

            if f.get("fully_uploaded"):
                logging.debug("resume_paused_upload: %r already fully_uploaded, skipping HEAD check", f["filename"])
                resume_hints[norm_path] = {
                    "upload_location": None, "offset": f["size"], "fully_uploaded": True,
                }
                resumed.append(f["filename"])
                continue

            logging.debug("resume_paused_upload: %r sending HEAD to %s to verify offset (timeout up to 40s)...",
                          f["filename"], upload_location)
            server_offset = _tus_offset(shared_session, upload_location)
            logging.debug("resume_paused_upload: %r HEAD returned server_offset=%s", f["filename"], server_offset)
            if server_offset is None:
                # Dead/expired session - this file starts over completely.
                restarted.append(f["filename"])
                continue

            resume_hints[norm_path] = {
                "upload_location": upload_location,
                "offset": min(server_offset, f["size"]),
                "fully_uploaded": False,
            }
            resumed.append(f["filename"])
    finally:
        shared_session.close()

    logging.debug("resume_paused_upload: HEAD-verification pass done - resumed=%s restarted=%s not_started=%s",
                  resumed, restarted, not_started)
    on_batch_event("resume_summary", resumed=resumed, restarted=restarted, not_started=not_started)

    logging.debug("resume_paused_upload: handing off %d file(s) to process_uploads()", len(files_to_upload))
    return process_uploads(
        files_to_upload, req_session,
        batch_config["manga_id"], batch_config["group_ids"],
        batch_config["upload_type"], batch_config["language"],
        batch_config["scanlator_name"], batch_config["thread_count"],
        per_file_group_map=batch_config.get("per_file_group_map"),
        verify_timeout=batch_config.get("verify_timeout", MAX_VERIFY_SECONDS),
        current_user_id=batch_config.get("current_user_id"),
        is_group_upload=batch_config.get("is_group_upload"),
        progress_callback=progress_callback,
        on_batch_event=on_batch_event,
        per_file_scanlator_map=batch_config.get("per_file_scanlator_map"),
        abort_event=abort_event,
        pause_event=pause_event,
        on_file_paused=on_file_paused,
        resume_hints=resume_hints,
        file_controls=file_controls,
        on_file_cancelled=on_file_cancelled,
        skip_verification=batch_config.get("skip_verification", True),
    )


def write_failed_log(manga_id, failed_chapters, failure_reasons, log_dir=None):
    import datetime
    if log_dir is None:
        # The old default was a CWD-relative "logs/", which silently landed
        # somewhere else whenever the app wasn't launched from its own folder
        # (and sat in a read-only install directory under Program Files).
        # The per-user cache dir is where the rest of the app's durable
        # state lives, so failed-upload reports go there too.
        log_dir = str(config_mod.CACHE_DIR / "logs")
    safe_id = str(manga_id) if manga_id else "unknown"
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    failed_log_name = os.path.join(log_dir, f"failed_manga_{safe_id}_{timestamp}.txt")
    try:
        os.makedirs(log_dir, exist_ok=True)
        with open(failed_log_name, "w", encoding="utf-8") as f:
            f.write(f"# Failed uploads for manga {safe_id} — {timestamp}\n")
            f.write(f"# {BASE_URL}/manga/{safe_id}\n")
            f.write("# <filename>\t<reason>\n\n")
            for chap in sorted(failed_chapters, key=parser_mod.natural_sort_key):
                reason = failure_reasons.get(chap, "Unknown error")
                f.write(f"{chap}\t{reason}\n")
        return failed_log_name
    except OSError as e:
        logging.warning(f"Could not write failed-uploads log to {failed_log_name}: {e}")
        return None