"""Upload progress screen."""
import time
import threading
import logging
import traceback

import shiboken6
from PySide6.QtCore import Qt, QThread, QTimer, Signal, QObject, QItemSelection, QItemSelectionModel
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QProgressBar, QMessageBox, QAbstractItemView, QDialog,
    QHeaderView, QSizePolicy, QMenu
)
from PySide6.QtGui import QFont, QColor

from .. import uploader
from .. import auth
from .. import config as config_mod
from .. import parser as parser_mod
from .. import util
from . import thread_is_running, workers
from .widgets import heading, StatCard, StatusPill, make_flat_link, GlassBox, IconButton, SegmentedToggle
from .theme import Color

COL_FILENAME = 0
COL_TITLE = 1
COL_STATUS = 2
COL_PROGRESS = 3
COL_SPEED = 4
COL_ETA = 5
COL_ACTIONS = 6

_TERMINAL_PREFIXES = ("\u2705", "\u274c", "\u23f8\ufe0f", "\u23f8", "\u26a0\ufe0f", "\u26a0")

# _on_file_progress (via _update_overall_progress/_update_stat_cards and,
# on a bucket change, _relayout_table) does real Qt style/layout work per
# call. Each call alone is cheap, but file_progress signals arrive as a
# burst whenever many files cross a milestone within the same instant -
# e.g. many verify polls landing in the same ~1s window once a batch's
# files start finishing verification together (get_verify_sem's slot
# count controls how many CAN finish at once). Processing an entire
# burst back-to-back in one Qt event-loop turn showed up as a native
# "stack overflow" crash on Windows with large batches (147 files) even
# though no single call is recursive - deep nested native Qt calls
# stacking up across dozens of back-to-back calls exhausted the thread's
# stack. Capping how many progress updates get applied per drain tick
# (below) spreads a big burst across several timer ticks instead of one
# unbroken run, without ever dropping an update - just delaying the
# least-recent ones by a tick or two.
_PROGRESS_DRAIN_INTERVAL_MS = 50
_PROGRESS_DRAIN_MAX_PER_TICK = 20

# See _relayout_table()'s docstring: debounces multiple relayout
# requests (automatic bucket-change relayouts during a burst, plus any
# user filter/sort click landing in the same window) into one rebuild.
# 120ms is comfortably above one animation frame so it's imperceptible
# as a delay, but long enough to catch a genuine multi-request burst.
_RELAYOUT_DEBOUNCE_MS = 120


def _status_kind(status: str) -> str:
    if status.startswith("\u2705"):
        return "success"
    if status.startswith("\u274c"):
        return "danger"
    if status.startswith("\u23f8"):
        return "warning"
    if status.startswith("\u26a0"):
        return "warning"
    return "info"


def _fmt_pill_detail(current, total):
    """Compact 'so-far/total' byte readout for the dim fragment inside
    a row's status pill, e.g. '20/40MB'. Deliberately denser than
    util.fmt_size() (which formats each side independently and would
    produce mismatched units like '0.02 GB/0.04 GB') - both sides
    always share one unit, chosen off the total, with no decimals so it
    stays short enough to fit next to the status word."""
    if not total or total <= 0:
        return ""
    if total >= 1024 ** 3:
        unit, div = "GB", 1024 ** 3
    elif total >= 1024 ** 2:
        unit, div = "MB", 1024 ** 2
    else:
        unit, div = "KB", 1024
    cur_val = max(0, min(current, total)) / div
    tot_val = total / div
    # Sub-1 KB/MB/GB values still need a decimal or "0/0" is all that
    # would show for genuinely small-but-nonzero progress.
    if tot_val < 10:
        return f"{cur_val:.1f}/{tot_val:.1f}{unit}"
    return f"{round(cur_val)}/{round(tot_val)}{unit}"


_VERIFYING_PREFIX = "Verifying... ("


def _parse_verifying_elapsed(status: str):
    """Extract N from 'Verifying... (Ns)', or None if status isn't a
    verifying line. uploader.py only re-emits this status roughly every
    RETRY_DELAY (5s) - once per poll - which reads as a frozen/broken
    timer on screen for anyone watching it tick by seconds. The GUI
    fills the gap with its own 1s QTimer (see _tick_verifying_timers),
    using this parse to seed/resync the local clock off the backend's
    own reported value whenever a real update arrives."""
    if not status.startswith(_VERIFYING_PREFIX) or not status.endswith("s)"):
        return None
    try:
        return int(status[len(_VERIFYING_PREFIX):-2])
    except ValueError:
        return None


class _UploadWorker(workers.AbortableWorker):
    file_progress = Signal(str, str, float, str, str, object, object)
    batch_event = Signal(str, dict)
    file_paused = Signal(dict, object, int, bool)
    file_cancelled = Signal(dict)
    finished = Signal(list, bool, dict)

    def __init__(self, files, session, manga_id, group_ids, upload_type,
                 language, scanlator_name, thread_count, per_file_group_map,
                 verify_timeout, current_user_id, is_group_upload, per_file_scanlator_map,
                 resume_paused_state=None, only_filenames=None, per_file_language_map=None,
                 skip_verification=True):
        super().__init__()
        self.files = files
        self.session = session
        self.manga_id = manga_id
        self.group_ids = group_ids
        self.upload_type = upload_type
        self.language = language
        self.scanlator_name = scanlator_name
        self.thread_count = thread_count
        self.per_file_group_map = per_file_group_map
        self.verify_timeout = verify_timeout
        self.current_user_id = current_user_id
        self.is_group_upload = is_group_upload
        self.per_file_scanlator_map = per_file_scanlator_map
        # When True, uploaded files skip the post-upload verification
        # poll entirely (see uploader.upload_file_tus) and are marked
        # done as soon as the TUS transfer itself succeeds. Threaded
        # through to both process_uploads (fresh upload, below) and
        # into batch_config for resume_paused_upload, same as
        # verify_timeout.
        self.skip_verification = skip_verification
        # Only used on the fresh-upload path below (process_uploads) - a
        # resumed upload (resume_paused_state is not None) goes through
        # resume_paused_upload() instead, which has no per-file-language
        # concept yet, same as it has none for a fresh upload's other
        # per-file maps' persisted state.
        self.per_file_language_map = per_file_language_map
        # resume_paused_state: the dict loaded from
        # config.load_paused_upload(), or None for a normal fresh
        # upload. When set, run() calls uploader.resume_paused_upload()
        # instead of process_uploads() - self.files is ignored in that
        # case, since resume_paused_upload() reconstructs the file list
        # from the persisted state itself (see resume_paused_state["files"]).
        self.resume_paused_state = resume_paused_state
        # only_filenames: passed straight through to
        # resume_paused_upload()'s own only_filenames - lets a resume
        # cover just one right-clicked file instead of the whole paused
        # batch. Ignored (has no effect) on a fresh, non-resume upload.
        self.only_filenames = only_filenames
        # Separate from self.abort_event (inherited from AbortableWorker):
        # abort means "stop and mark failed", pause means "stop cleanly
        # and remember exactly where we got to, so it can resume later".
        # Not added to AbortableWorker itself since _OptimizationWorker
        # (the other AbortableWorker subclass) has no resumable-pause
        # concept - optimizing images isn't a resumable network transfer.
        self.pause_event = threading.Event()
        # One uploader.FileControl per file about to be uploaded, keyed
        # by norm_filepath - built up front (in the constructor, before
        # the worker thread even starts) so the GUI thread can look a
        # file's control up and call .pause()/.resume()/.cancel() on it
        # from a right-click handler at any time during the upload,
        # without any race against run() creating it later. See
        # get_file_control().
        source_files = (resume_paused_state["files"] if resume_paused_state is not None else files)
        self.file_controls = {
            parser_mod.norm_filepath(f["filepath"]): uploader.FileControl()
            for f in source_files
        }

    def pause(self):
        """Signal this worker to stop cleanly at its next chunk
        boundary, preserving resumable state, rather than aborting.
        Safe to call from any thread."""
        self.pause_event.set()

    def get_file_control(self, filepath):
        return self.file_controls.get(parser_mod.norm_filepath(filepath))

    def run(self):
        logging.debug("_UploadWorker.run() ENTER, is_resume=%s, only_filenames=%s, thread=%s",
                      self.resume_paused_state is not None, self.only_filenames,
                      threading.current_thread().name)

        def progress_cb(filename, status, fraction, speed_str="", eta_str="", **kwargs):
            # current/total (bytes) aren't sent with every call - e.g.
            # "Creating upload...", "Verifying...", and the paused
            # callback all omit them - so they're forwarded as-is
            # (possibly None) and the receiving side falls back to
            # fraction * known file size when they're missing.
            current = kwargs.get("current")
            total = kwargs.get("total")
            self.file_progress.emit(filename, status, fraction, speed_str, eta_str, current, total)

        def batch_event_cb(event, **kwargs):
            self.batch_event.emit(event, kwargs)

        def file_paused_cb(file_info, upload_location, offset, fully_uploaded):
            self.file_paused.emit(file_info, upload_location, offset, fully_uploaded)

        def file_cancelled_cb(file_info):
            self.file_cancelled.emit(file_info)

        # Every path below MUST reach self.finished.emit(...) no matter
        # what - a row's status (e.g. "Resuming...") is only ever
        # updated in response to a signal from this worker, so if this
        # method raises and finished never fires, that row is stuck
        # forever with no way to know anything went wrong. This bit the
        # previous version: _tus_offset()'s HEAD request (used to verify
        # a resume's server-side offset) has its own SessionExpiredError
        # path that wasn't caught anywhere between here and there, so an
        # expired session mid-resume silently killed the whole worker
        # thread and left the row frozen on "Resuming..." with its
        # button disabled, with nothing in the UI ever explaining why.
        try:
            if self.resume_paused_state is not None:
                logging.debug("_UploadWorker.run(): calling uploader.resume_paused_upload()")
                failed, session_expired, reasons = uploader.resume_paused_upload(
                    self.resume_paused_state, self.session,
                    progress_callback=progress_cb,
                    on_batch_event=batch_event_cb,
                    abort_event=self.abort_event,
                    pause_event=self.pause_event,
                    on_file_paused=file_paused_cb,
                    file_controls=self.file_controls,
                    on_file_cancelled=file_cancelled_cb,
                    only_filenames=self.only_filenames,
                )
                logging.debug("_UploadWorker.run(): resume_paused_upload RETURNED failed=%s session_expired=%s", failed, session_expired)
            else:
                logging.debug("_UploadWorker.run(): calling uploader.process_uploads()")
                failed, session_expired, reasons = uploader.process_uploads(
                    self.files, self.session, self.manga_id, self.group_ids, self.upload_type,
                    self.language, self.scanlator_name, self.thread_count,
                    per_file_group_map=self.per_file_group_map,
                    verify_timeout=self.verify_timeout,
                    current_user_id=self.current_user_id,
                    is_group_upload=self.is_group_upload,
                    progress_callback=progress_cb,
                    on_batch_event=batch_event_cb,
                    per_file_scanlator_map=self.per_file_scanlator_map,
                    abort_event=self.abort_event,
                    pause_event=self.pause_event,
                    on_file_paused=file_paused_cb,
                    file_controls=self.file_controls,
                    on_file_cancelled=file_cancelled_cb,
                    per_file_language_map=self.per_file_language_map,
                    skip_verification=self.skip_verification,
                )
                logging.debug("_UploadWorker.run(): process_uploads RETURNED failed=%s session_expired=%s", failed, session_expired)
        except uploader.SessionExpiredError:
            logging.debug("_UploadWorker.run(): caught SessionExpiredError")
            session_expired = True
            failed = [f["filename"] for f in self._all_source_files()]
            reasons = {name: "Session expired" for name in failed}
            self.batch_event.emit("session_expired", {})
        except Exception as e:
            # Catch-all: whatever this was, every file this worker was
            # responsible for gets reported failed with the real error
            # rather than left stuck - see the try's docstring above.
            logging.exception("Upload worker crashed unexpectedly")
            failed = [f["filename"] for f in self._all_source_files()]
            reasons = {name: f"Unexpected error: {e}" for name in failed}
            session_expired = False
        logging.debug("_UploadWorker.run(): about to emit finished(failed=%s, session_expired=%s)", failed, session_expired)
        self.finished.emit(failed, session_expired, reasons)
        logging.debug("_UploadWorker.run(): finished.emit() returned, run() about to exit")

    def _all_source_files(self):
        if self.resume_paused_state is not None:
            files = self.resume_paused_state["files"]
            if self.only_filenames is not None:
                files = [f for f in files if f["filename"] in self.only_filenames]
            return files
        return self.files


class UploadProgressScreen(QWidget):
    upload_finished = Signal(set, float)
    back_requested = Signal()

    def __init__(self, files, session, manga_id, group_ids, upload_type,
                 language, scanlator_name, thread_count, per_file_group_map=None,
                 verify_timeout=uploader.MAX_VERIFY_SECONDS, current_user_id=None,
                 is_group_upload=None, per_file_scanlator_map=None,
                 resume_paused_state=None, already_done_files=None, manga_title=None, parent=None,
                 per_file_language_map=None, skip_verification=True):
        super().__init__(parent)
        self.all_files = files
        self.session = session
        self.manga_id = manga_id
        self.manga_title = manga_title
        self.group_ids = group_ids
        self.upload_type = upload_type
        self.language = language
        self.scanlator_name = scanlator_name
        self.thread_count = thread_count
        self.per_file_group_map = per_file_group_map or {}
        self.verify_timeout = verify_timeout
        self.current_user_id = current_user_id
        self.is_group_upload = is_group_upload
        self.per_file_scanlator_map = per_file_scanlator_map or {}
        self.per_file_language_map = per_file_language_map or {}
        # See _UploadWorker.skip_verification / uploader.upload_file_tus -
        # when True, uploaded files bypass the post-upload verification
        # poll entirely and are marked done as soon as the transfer
        # itself succeeds. Persisted into batch_config (see
        # _persist_paused_state) so a paused-then-resumed batch keeps
        # honoring the same choice.
        self.skip_verification = skip_verification
        # See _UploadWorker.resume_paused_state - when set, _start_upload
        # drives uploader.resume_paused_upload() instead of a fresh
        # process_uploads() call. Only meant to be used once: after a
        # resumed batch finishes, a subsequent _start_upload() call (e.g.
        # "Retry failed") should go through the normal fresh-upload path,
        # not try to resume again from now-stale state.
        self.resume_paused_state = resume_paused_state
        self._was_resuming = resume_paused_state is not None

        self._row_by_filename = {}
        self._file_info_by_filename = {}
        self._thread = None
        self._worker = None
        self._upload_start = None
        self._last_failed = []
        self._last_reasons = {}
        self._status_by_filename = {}
        self._cancel_requested = False
        self._cancel_then_go_back = False
        self._pause_requested = False
        self._paused_files = []  # collected via _on_file_paused, persisted once the batch actually stops
        self._is_paused_state = False  # True once _handle_paused fires; drives the pause/resume icon toggle
        self._last_clicked_row = None  # anchor row for right-click "Select range to here"
        self._inline_resume_threads = set()  # keeps per-row resume QThreads alive; see _on_resume_one_clicked

        # filename -> wall-clock time.time() the row's current verify
        # attempt began, used by _tick_verifying_timers to render a
        # smooth per-second "(Ns)" clock in between the backend's own
        # ~5s-apart "Verifying... (Ns)" ticks (see
        # _parse_verifying_elapsed's docstring for why that's needed).
        self._verify_started_at = {}

        # --- Table ordering / filtering state ---
        # "default": grouped by status - Uploading on top, Queued in
        # the middle, Done+Failed at the bottom (chapter order within
        # that bottom group) - regardless of chapter number or when
        # each file started. "chapter": flat natural chapter-number
        # order, status ignored entirely. "time": flat order by real
        # wall-clock start time (_upload_started_at_by_filename),
        # status ignored entirely. Whichever mode is active governs the
        # WHOLE table's row order - see _visible_ordered_filenames().
        self._sort_mode = "default"
        # filename -> real wall-clock time.time() of the first tick
        # that moved a file off "queued", assigned once by
        # _on_file_progress and never reassigned (so pausing/resuming a
        # file doesn't shuffle it in "Upload time" order the way
        # re-queuing would). Queued files with no entry here sort after
        # every started file in "time" mode.
        self._upload_started_at_by_filename = {}
        # None = All. Otherwise one of the _status_kind() values this
        # screen uses: "queued", "uploading", "success", "warning"
        # (paused), "danger" (failed). Set by clicking a stat card or a
        # filter chip; see _set_status_filter().
        self._status_filter = None
        # Cache of each file's latest known status/progress/speed/eta,
        # kept in sync by _on_file_progress on every tick. Needed
        # because _relayout_table() may reposition/repopulate a row at
        # any time (sort or filter change), and has to redraw it with
        # whatever that file's CURRENT state is - not reset it back to
        # "Queued" the way the original _reset_table row-builder did.
        self._live_state_by_filename = {}

        self._build_ui()
        self._start_upload(self.all_files, already_done_files=already_done_files)

        self._verify_timer = QTimer(self)
        self._verify_timer.setInterval(1000)
        self._verify_timer.timeout.connect(self._tick_verifying_timers)
        self._verify_timer.start()

        # Coalescing buffer for file_progress signals - see
        # _queue_file_progress()/_drain_file_progress_queue() below for
        # why this exists.
        self._pending_progress = {}
        self._progress_drain_timer = QTimer(self)
        self._progress_drain_timer.setInterval(_PROGRESS_DRAIN_INTERVAL_MS)
        self._progress_drain_timer.timeout.connect(self._drain_file_progress_queue)
        self._progress_drain_timer.start()

        # Debounce timer for _relayout_table() - see its docstring.
        # setSingleShot: each _relayout_table() call (re)starts this
        # rather than letting it repeat, so a burst of requests inside
        # one debounce window collapses into exactly one rebuild when
        # the window closes, not one per interval.
        self._relayout_timer = QTimer(self)
        self._relayout_timer.setSingleShot(True)
        self._relayout_timer.timeout.connect(self._do_relayout_table)

    @classmethod
    def for_resume(cls, paused_state, session, parent=None):
        """Builds a screen that resumes a previously-paused upload,
        reconstructing every constructor argument from the persisted
        state itself (see config.load_paused_upload()) rather than
        requiring the caller to unpack batch_config/files manually.

        The `files` shown in the table are the persisted per-file
        entries (which is what the user will see resuming) - the
        underlying worker ignores this list for its own upload logic
        when resume_paused_state is set (see _UploadWorker.run()) and
        instead reconstructs the authoritative file list from
        paused_state["files"] itself, so there's no risk of the two
        getting out of sync.

        paused_state["completed_files"] (files that already finished
        successfully before this paused state was saved - see
        config.save_paused_upload()) is passed through as
        already_done_files so those rows still show up as Done instead
        of vanishing just because they're outside paused_state["files"]
        - see _start_upload's already_done_files docstring."""
        bc = paused_state["batch_config"]
        return cls(
            files=paused_state["files"],
            session=session,
            manga_id=bc["manga_id"],
            group_ids=bc["group_ids"],
            upload_type=bc["upload_type"],
            language=bc["language"],
            scanlator_name=bc.get("scanlator_name"),
            thread_count=bc.get("thread_count", 4),
            per_file_group_map=bc.get("per_file_group_map"),
            verify_timeout=bc.get("verify_timeout", uploader.MAX_VERIFY_SECONDS),
            current_user_id=bc.get("current_user_id"),
            is_group_upload=bc.get("is_group_upload"),
            per_file_scanlator_map=bc.get("per_file_scanlator_map"),
            resume_paused_state=paused_state,
            already_done_files=paused_state.get("completed_files"),
            manga_title=bc.get("manga_title"),
            skip_verification=bc.get("skip_verification", True),
            parent=parent,
        )

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 20, 28, 24)
        outer.setSpacing(14)

        unit = "volume" if self.upload_type == "volume" else "chapter"
        if self.manga_title:
            from html import escape
            heading_title = f"Uploading \u201c{escape(self.manga_title)}\u201d"
        else:
            heading_title = "Uploading"
        outer.addWidget(heading(heading_title, f"Sending {len(self.all_files)} {unit}(s) to MangaDot \u2014 you can leave this running."))

        stats_row = QHBoxLayout()
        stats_row.setSpacing(10)
        self.stat_queued = StatCard("0", "Queued")
        self.stat_uploading = StatCard("0", "Uploading", kind="accent")
        self.stat_done = StatCard("0", "Done", kind="success")
        self.stat_paused = StatCard("0", "Paused", kind="warning")
        self.stat_failed = StatCard("0", "Failed", kind="danger")
        # Each card's filter value matches the SegmentedToggle option
        # values in filter_toggle above - clicking a card and clicking
        # the equivalent chip do the exact same thing (_set_status_filter),
        # and _sync_filter_controls() keeps both in visual sync no
        # matter which one the user actually clicked.
        self._stat_card_filter_values = {
            id(self.stat_queued): "queued",
            id(self.stat_uploading): "uploading",
            id(self.stat_done): "success",
            id(self.stat_paused): "warning",
            id(self.stat_failed): "danger",
        }
        for card in (self.stat_queued, self.stat_uploading, self.stat_done, self.stat_paused, self.stat_failed):
            card.clicked.connect(lambda c=card: self._on_stat_card_clicked(c))
            stats_row.addWidget(card)
        outer.addLayout(stats_row)

        status_row = QHBoxLayout()
        status_row.setSpacing(8)

        self.status_label = QLabel("Starting upload\u2026")
        self.status_label.setWordWrap(True)
        self.status_label.setProperty("role", "subheading")
        status_row.addWidget(self.status_label, 1)

        # Global pause/resume as a single icon button living right next
        # to the status text (previously a full-width "Pause upload"
        # text button down in bottom_row) - set_kind() flips it between
        # 'pause' and 'resume' in place rather than swapping widgets, so
        # this one button always reflects the batch's current state.
        self.pause_icon_button = IconButton("pause", "Pause upload")
        self.pause_icon_button.clicked.connect(self._on_pause_or_resume_clicked)
        status_row.addWidget(self.pause_icon_button)

        outer.addLayout(status_row)

        overall_row = QHBoxLayout()
        overall_row.setSpacing(10)

        self.overall_progress = QProgressBar()
        self.overall_progress.setFormat("%v / %m files")
        self.overall_progress.setFixedHeight(22)
        overall_row.addWidget(self.overall_progress, 1)

        # Live "so far / total" byte readout, sitting right beside the
        # files-count bar rather than replacing it - the bar already
        # answers "how many files", this answers "how much data",
        # updated on every _on_file_progress tick from
        # _bytes_so_far_by_filename (see _update_overall_progress).
        self.overall_bytes_label = QLabel("")
        self.overall_bytes_label.setProperty("role", "hint")
        self.overall_bytes_label.setStyleSheet(f"color: {Color.TEXT_MUTED}; font-size: 12px;")
        overall_row.addWidget(self.overall_bytes_label)

        outer.addLayout(overall_row)

        table_controls_row = QHBoxLayout()
        table_controls_row.setSpacing(16)

        filter_label = QLabel("Show:")
        filter_label.setStyleSheet(f"color: {Color.TEXT_MUTED}; font-size: 12px;")
        table_controls_row.addWidget(filter_label)

        # "All" plus one chip per status this screen tracks. Clicking a
        # chip (or the matching stat card - see _on_stat_card_clicked)
        # filters the table down to just that status; both controls
        # share the same _status_filter state and stay in sync via
        # _sync_filter_controls().
        self.filter_toggle = SegmentedToggle(
            [(None, "All"), ("queued", "Queued"), ("uploading", "Uploading"),
             ("success", "Done"), ("warning", "Paused"), ("danger", "Failed")],
            current=None,
        )
        self.filter_toggle.changed.connect(self._set_status_filter)
        table_controls_row.addWidget(self.filter_toggle)

        table_controls_row.addStretch(1)

        sort_label = QLabel("Sort by:")
        sort_label.setStyleSheet(f"color: {Color.TEXT_MUTED}; font-size: 12px;")
        table_controls_row.addWidget(sort_label)

        self.sort_toggle = SegmentedToggle(
            [("default", "Default"), ("chapter", "Chapter #"), ("time", "Upload time")],
            current=self._sort_mode,
        )
        self.sort_toggle.changed.connect(self._set_sort_mode)
        table_controls_row.addWidget(self.sort_toggle)

        outer.addLayout(table_controls_row)

        selection_row = QHBoxLayout()
        selection_row.setSpacing(10)
        self.selection_label = QLabel("")
        self.selection_label.setProperty("role", "hint")
        selection_row.addWidget(self.selection_label)
        selection_row.addStretch(1)

        self.selection_pause_button = make_flat_link(QPushButton("Pause selected"))
        self.selection_pause_button.clicked.connect(lambda: self._apply_action_to_selection("pause"))
        self.selection_pause_button.setVisible(False)
        selection_row.addWidget(self.selection_pause_button)

        self.selection_resume_button = make_flat_link(QPushButton("Resume selected"))
        self.selection_resume_button.clicked.connect(lambda: self._apply_action_to_selection("resume"))
        self.selection_resume_button.setVisible(False)
        selection_row.addWidget(self.selection_resume_button)

        self.selection_cancel_button = make_flat_link(QPushButton("Cancel selected"), color=Color.DANGER, hover_color=Color.CRIMSON_HOVER)
        self.selection_cancel_button.clicked.connect(lambda: self._apply_action_to_selection("cancel"))
        self.selection_cancel_button.setVisible(False)
        selection_row.addWidget(self.selection_cancel_button)

        outer.addLayout(selection_row)

        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(["Filename", "Title", "Status", "Progress", "Speed", "ETA", ""])
        # ExtendedSelection (not the old NoSelection) is what gives
        # range-select for free: click a row, shift-click another row to
        # select the whole range between them (or ctrl-click to build up
        # a non-contiguous selection) - all native QTableWidget behavior,
        # no custom range-tracking code needed. SelectRows means a click
        # anywhere in a row selects that whole row, not just one cell.
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.setShowGrid(False)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_row_context_menu)
        self.table.itemSelectionChanged.connect(self._on_table_selection_changed)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(COL_FILENAME, QHeaderView.Interactive)
        header.setSectionResizeMode(COL_TITLE, QHeaderView.Stretch)
        header.setSectionResizeMode(COL_STATUS, QHeaderView.Fixed)
        header.setSectionResizeMode(COL_PROGRESS, QHeaderView.Fixed)
        header.setSectionResizeMode(COL_SPEED, QHeaderView.Fixed)
        header.setSectionResizeMode(COL_ETA, QHeaderView.Fixed)
        header.setSectionResizeMode(COL_ACTIONS, QHeaderView.Fixed)
        self.table.setColumnWidth(COL_FILENAME, 260)
        self.table.setColumnWidth(COL_PROGRESS, 140)
        self.table.setColumnWidth(COL_STATUS, 228)
        self.table.setColumnWidth(COL_SPEED, 100)
        self.table.setColumnWidth(COL_ETA, 70)
        self.table.setColumnWidth(COL_ACTIONS, 76)
        header.setSectionsMovable(True)
        header.setHighlightSections(False)

        self._restore_column_order()

        outer.addWidget(self.table, 1)

        bottom_row = QHBoxLayout()

        self.cancel_button = QPushButton("Cancel upload")
        self.cancel_button.clicked.connect(self._on_cancel_clicked)
        bottom_row.addWidget(self.cancel_button)

        bottom_row.addStretch(1)

        self.back_button = make_flat_link(QPushButton("Back"))
        self.back_button.clicked.connect(self._on_back_clicked)
        bottom_row.addWidget(self.back_button)

        continue_box = GlassBox(
            tint_rgba="rgba(74, 222, 128, 18)", 
            border_color=Color.SUCCESS, 
        )
        continue_box_layout = QHBoxLayout(continue_box)
        continue_box_layout.setContentsMargins(14, 6, 14, 6)
        
        self.done_button = make_flat_link(QPushButton("Continue"), bold=True)
        self.done_button.setEnabled(False)
        self.done_button.clicked.connect(self._on_done_clicked)
        
        continue_box_layout.addWidget(self.done_button)
        bottom_row.addWidget(continue_box)
        outer.addLayout(bottom_row)

    def _restore_column_order(self):
        cfg = config_mod.load_config()
        order = cfg.get("upload_table_column_order")
        if not order or len(order) != self.table.columnCount():
            return
        header = self.table.horizontalHeader()
        for target_visual_index, logical_index in enumerate(order):
            current_visual_index = header.visualIndex(logical_index)
            if current_visual_index != -1 and current_visual_index != target_visual_index:
                header.moveSection(current_visual_index, target_visual_index)

    def _reset_table(self, files, already_done_files=None):
        already_done_files = list(already_done_files or [])
        all_rows = sorted(list(files) + already_done_files, key=lambda f: f.get("number", 0))
        total_files = len(all_rows)
        done_filenames = {f["filename"] for f in already_done_files}

        # Reset overall progress bar back to cyan (default state)
        self.overall_progress.setProperty("state", "")
        self.overall_progress.style().unpolish(self.overall_progress)
        self.overall_progress.style().polish(self.overall_progress)
        
        self.overall_progress.setRange(0, total_files)
        self.overall_progress.setValue(len(already_done_files))

        self._row_by_filename = {}
        self._finished_filenames = set(done_filenames)
        self._status_by_filename = {
            f["filename"]: ("success" if f["filename"] in done_filenames else "queued")
            for f in all_rows
        }
        self._file_info_by_filename = {f["filename"]: f for f in all_rows}

        # Bytes tally for the live total-progress readout beside
        # overall_progress: total is fixed for the whole run (sum of
        # every row's known file size); so-far starts with already-done
        # rows counted as fully uploaded, and grows/shrinks per-file as
        # _on_file_progress reports (see _update_overall_progress).
        self._total_bytes_all_files = sum(f.get("size") or 0 for f in all_rows)
        self._bytes_so_far_by_filename = {
            f["filename"]: (f.get("size") or 0) for f in already_done_files
        }

        # Fresh run - drop any leftover per-second verify clocks from a
        # previous batch (retry/resume) so _tick_verifying_timers never
        # redraws a "(Ns)" for a filename that isn't even in this run.
        self._verify_started_at = {}

        # Fresh run - old sort-mode timestamps and live-state snapshots
        # belong to a previous batch's filenames and would otherwise
        # leak into _visible_ordered_filenames()'s "time" sort or get
        # read back by _populate_row() for files that are only
        # superficially the same (e.g. a retry reusing a filename).
        self._upload_started_at_by_filename = {}
        self._live_state_by_filename = {
            f["filename"]: {
                "status": ("\u2705 Uploaded" if f["filename"] in done_filenames else "Queued"),
                "kind": "success" if f["filename"] in done_filenames else "neutral",
                "fraction": 1.0 if f["filename"] in done_filenames else 0.0,
                "speed_str": "",
                "eta_str": "",
                "detail": "",
            }
            for f in all_rows
        }

        self.table.setRowCount(total_files)
        for row, f in enumerate(all_rows):
            self._row_by_filename[f["filename"]] = row
            self._populate_row(row, f["filename"])

        self._update_stat_cards()
        self._update_overall_progress()
        self._sync_filter_controls()

    def _populate_row(self, row, filename):
        """(Re)builds every cell in `row` from scratch for `filename`,
        using whatever's in self._live_state_by_filename (falling back
        to a fresh Queued row if that file has no snapshot yet). This
        is the one place row content is ever built - both the initial
        _reset_table() and _relayout_table() (sort/filter changes) call
        it, so a row always looks the same regardless of *why* it's
        being (re)drawn. _on_file_progress updates cells in place for
        the common case (no reposition needed) and does NOT go through
        here - see its own docstring."""
        f = self._file_info_by_filename.get(filename, {"filename": filename})
        state = self._live_state_by_filename.get(filename) or {
            "status": "Queued", "kind": "neutral", "fraction": 0.0,
            "speed_str": "", "eta_str": "", "detail": "",
        }
        kind = state["kind"]
        is_done = kind == "success"

        mono = QFont()
        mono.setStyleHint(QFont.Monospace)

        filename_item = QTableWidgetItem(filename)
        filename_item.setForeground(QColor(Color.TEXT_SECONDARY))
        self.table.setItem(row, COL_FILENAME, filename_item)

        title_item = QTableWidgetItem(f.get("title") or "-")
        self.table.setItem(row, COL_TITLE, title_item)

        pill = StatusPill(state["status"], kind)
        pill.set_detail(state.get("detail") or "")
        self.table.setCellWidget(row, COL_STATUS, self._wrap_pill(pill))

        bar = QProgressBar()
        bar.setRange(0, 100)
        pct = int(max(0.0, min(1.0, state["fraction"])) * 100)
        bar.setValue(pct)
        bar.setFixedHeight(16)
        bar.setTextVisible(False)
        if pct >= 100 and kind == "success":
            bar.setProperty("state", "success")
        elif kind == "danger":
            bar.setProperty("state", "danger")
        self.table.setCellWidget(row, COL_PROGRESS, bar)

        speed_item = QTableWidgetItem(state.get("speed_str") or "\u2013")
        speed_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        speed_item.setFont(mono)
        self.table.setItem(row, COL_SPEED, speed_item)

        eta_item = QTableWidgetItem(state.get("eta_str") or "\u2013")
        eta_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        eta_item.setFont(mono)
        self.table.setItem(row, COL_ETA, eta_item)

        action_widget = self._make_row_action_button(filename)
        if kind in ("success", "danger"):
            action_widget._action_button.setEnabled(False)
        elif kind == "warning":
            action_widget._action_button.set_kind("resume", "Resume this file")
            action_widget._action_button.setEnabled(True)
        self.table.setCellWidget(row, COL_ACTIONS, action_widget)

    def _relayout_table(self):
        """Requests a table relayout. Debounced via a short single-shot
        QTimer instead of rebuilding immediately: this can be called
        from several places in quick succession - the automatic
        bucket-change path (_on_file_progress, potentially many times
        in a burst as files finish/verify/fail together) AND user
        clicks on the Show:/sort controls - and each call does a full
        setRowCount() + rebuild of every visible row's cell widgets.
        Two or more of those landing back-to-back on the GUI thread
        (e.g. a filter click during an active upload's own
        automatic-relayout burst) compounded into the same native
        stack-overflow crash the progress-update burst caused - see
        _PROGRESS_DRAIN_INTERVAL_MS above for that one. Debouncing
        collapses any pile of requests within _RELAYOUT_DEBOUNCE_MS into
        a single real rebuild (_do_relayout_table) instead of running
        one per request. The rebuild always reflects the LATEST state
        at the time it actually runs, so nothing about what gets shown
        changes - only how many times the expensive work runs."""
        if self._relayout_timer.isActive():
            return
        self._relayout_timer.start(_RELAYOUT_DEBOUNCE_MS)

    def _do_relayout_table(self):
        """The actual rebuild _relayout_table() debounces into - see
        its docstring above. Never call this directly from elsewhere;
        go through _relayout_table() so concurrent requests keep
        coalescing."""
        ordered = self._visible_ordered_filenames()
        self.table.setRowCount(len(ordered))
        self._row_by_filename = {}
        for row, filename in enumerate(ordered):
            self._row_by_filename[filename] = row
            self._populate_row(row, filename)

    def _make_row_action_button(self, filename):
        """One small pause/resume IconButton per row, centered in the
        Actions column. Starts as 'pause' (queued/uploading state);
        _on_file_progress flips it to 'resume' once that row's status
        goes terminal-paused, and back again if the row starts moving
        (e.g. after a per-file resume). Kept in its own wrapper widget
        (like _wrap_pill) purely to get consistent centering/margins
        inside the cell, matching the rest of the table's cell-widget
        pattern rather than introducing a new one."""
        wrap = QWidget()
        wrap.setStyleSheet("background: transparent;")
        layout = QHBoxLayout(wrap)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignCenter)
        button = IconButton("pause", "Pause this file", size=26, icon_size=14)
        button.clicked.connect(lambda: self._on_row_action_clicked(filename))
        layout.addWidget(button)
        wrap._action_button = button
        return wrap

    def _row_action_button(self, filename):
        row = self._row_by_filename.get(filename)
        if row is None:
            return None
        container = self.table.cellWidget(row, COL_ACTIONS)
        return getattr(container, "_action_button", None) if container else None

    def _on_row_action_clicked(self, filename):
        button = self._row_action_button(filename)
        if button is None:
            return
        if button._kind == "pause":
            self._pause_single_file(filename)
        else:
            self._on_resume_one_clicked(filename)

    def _pause_single_file(self, filename):
        """Pauses exactly one in-flight file via its FileControl,
        without touching the batch-wide pause_event or any other file -
        this is the per-row equivalent of _on_pause_clicked(), reachable
        from either the row's IconButton or the right-click menu."""
        if self._worker is None or not shiboken6.isValid(self._worker):
            return
        control = self._worker.get_file_control(self._filepath_for(filename))
        if control is not None:
            logging.debug(
                "DIAG _pause_single_file CALLED for %r, worker id=%s, control id=%s\nSTACK:\n%s",
                filename, id(self._worker), id(control),
                "".join(traceback.format_stack()[:-1]),
            )
            control.pause()

    def _cancel_single_file(self, filename):
        if self._worker is None or not shiboken6.isValid(self._worker):
            return
        control = self._worker.get_file_control(self._filepath_for(filename))
        if control is not None:
            control.cancel()

    def _filepath_for(self, filename):
        info = self._file_info_by_filename.get(filename)
        return info["filepath"] if info else filename

    def _on_row_context_menu(self, pos):
        """Right-click menu for one row: Pause/Resume/Cancel scoped to
        that single file, matching whatever the row's own action button
        currently offers (so the menu and the button never disagree).
        If more than one row is already selected when the right-click
        lands on a selected row, the actions apply to the WHOLE
        selection instead of just the clicked row - this is the same
        convention most file managers use for right-click-on-a-multi-
        selection, and it means the user doesn't have to hunt for a
        separate "selected" toolbar to act on a range they just picked."""
        item = self.table.itemAt(pos)
        clicked_row = item.row() if item is not None else self.table.rowAt(pos.y())
        if clicked_row < 0:
            return
        clicked_filename = self.table.item(clicked_row, COL_FILENAME).text()

        selected_rows = {idx.row() for idx in self.table.selectionModel().selectedRows()}
        if len(selected_rows) > 1 and clicked_row in selected_rows:
            filenames = [self.table.item(r, COL_FILENAME).text() for r in sorted(selected_rows)]
        else:
            filenames = [clicked_filename]

        menu = QMenu(self)
        label_suffix = f" ({len(filenames)} files)" if len(filenames) > 1 else ""
        pause_action = menu.addAction(f"Pause{label_suffix}")
        resume_action = menu.addAction(f"Resume{label_suffix}")
        menu.addSeparator()
        cancel_action = menu.addAction(f"Cancel{label_suffix}")
        menu.addSeparator()
        select_range_action = menu.addAction("Select range to here")
        select_range_action.setEnabled(self._last_clicked_row is not None and self._last_clicked_row != clicked_row)

        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen is None:
            pass
        elif chosen == pause_action:
            for fn in filenames:
                self._pause_single_file(fn)
        elif chosen == resume_action:
            for fn in filenames:
                self._on_resume_one_clicked(fn)
        elif chosen == cancel_action:
            self._confirm_and_cancel_files(filenames)
        elif chosen == select_range_action:
            self._select_row_range(self._last_clicked_row, clicked_row)

        self._last_clicked_row = clicked_row

    def _select_row_range(self, start_row, end_row):
        lo, hi = sorted((start_row, end_row))
        self.table.clearSelection()
        selection = QItemSelection(
            self.table.model().index(lo, 0),
            self.table.model().index(hi, self.table.columnCount() - 1),
        )
        self.table.selectionModel().select(selection, QItemSelectionModel.Select | QItemSelectionModel.Rows)

    def _on_table_selection_changed(self):
        rows = self.table.selectionModel().selectedRows()
        count = len(rows)
        if count <= 1:
            self.selection_label.setText("")
            self.selection_pause_button.setVisible(False)
            self.selection_resume_button.setVisible(False)
            self.selection_cancel_button.setVisible(False)
            return
        self.selection_label.setText(f"{count} files selected")
        self.selection_pause_button.setVisible(True)
        self.selection_resume_button.setVisible(True)
        self.selection_cancel_button.setVisible(True)
        if rows:
            self._last_clicked_row = rows[-1].row()

    def _selected_filenames(self):
        rows = sorted({idx.row() for idx in self.table.selectionModel().selectedRows()})
        return [self.table.item(r, COL_FILENAME).text() for r in rows]

    def _apply_action_to_selection(self, action):
        filenames = self._selected_filenames()
        if not filenames:
            return
        if action == "pause":
            for fn in filenames:
                self._pause_single_file(fn)
        elif action == "resume":
            for fn in filenames:
                self._on_resume_one_clicked(fn)
        elif action == "cancel":
            self._confirm_and_cancel_files(filenames)

    def _confirm_and_cancel_files(self, filenames):
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Question)
        msg.setWindowTitle("Cancel file(s)?")
        plural = "s" if len(filenames) != 1 else ""
        msg.setText(
            f"Cancel {len(filenames)} file{plural}? This can't be undone - "
            f"cancelled file{plural} will need to be re-uploaded from the start, "
            f"unlike a pause."
        )
        yes_btn = msg.addButton("Cancel file(s)", QMessageBox.YesRole)
        msg.addButton("Keep them", QMessageBox.NoRole)
        msg.setDefaultButton(yes_btn)
        msg.exec()
        if msg.clickedButton() != yes_btn:
            return
        for fn in filenames:
            self._cancel_single_file(fn)

    @staticmethod
    def _wrap_pill(pill):
        wrap = QWidget()
        wrap.setStyleSheet("background: transparent;")
        
        layout = QHBoxLayout(wrap)
        layout.setContentsMargins(8, 0, 8, 0)
        
        pill.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout.addWidget(pill, 1, Qt.AlignVCenter)
        
        wrap._pill = pill
        return wrap

    def _pill_in_row(self, row):
        container = self.table.cellWidget(row, COL_STATUS)
        return getattr(container, "_pill", None) if container else None

    def _start_upload(self, files_to_upload, only_filenames=None, already_done_files=None):
        # self.all_files defines the scope _not_yet_reported_files() (and
        # therefore _persist_paused_state()) considers "this run" - it
        # MUST track whatever's actually being uploaded right now, not
        # stay pinned to the very first batch from __init__. Without
        # this, resuming a smaller paused subset (say 37 of the
        # original 41, because 4 already finished in an earlier
        # session) left self.all_files at the full 41: if THIS resumed
        # run later paused or errored again, _not_yet_reported_files()
        # would iterate all 41 original files, find the 4 long-since-
        # finished ones missing from both self._paused_files and
        # self._status_by_filename (since _reset_table only seeded
        # status for the 37 in THIS run), and wrongly resurrect them as
        # "not yet reported" - re-queuing already-uploaded chapters,
        # which then hit 409/"Already Exists" on the server and showed
        # up as pointless re-uploads of finished work.
        #
        # already_done_files: files that finished in an EARLIER session
        # (e.g. via an individual per-row resume before this global
        # resume ran) and are therefore correctly excluded from
        # files_to_upload/paused_state["files"] - but should still show
        # up in the table as Done, not silently vanish. Without this,
        # _reset_table(files_to_upload) truncates the table to ONLY the
        # files in this run, so any file finished earlier disappears
        # from view entirely and the stat cards read "0 Done" even
        # though nothing was actually lost or re-uploaded - it just
        # looked that way because the table stopped showing it.
        self.all_files = sorted(files_to_upload + list(already_done_files or []), key=lambda f: f.get("number", 0))
        self._reset_table(files_to_upload, already_done_files=already_done_files)
        self.done_button.setEnabled(False)
        self._cancel_requested = False
        self._cancel_then_go_back = False
        self._pause_requested = False
        self._paused_files = []
        self._is_paused_state = False
        self.cancel_button.setEnabled(True)
        self.pause_icon_button.setEnabled(True)
        self.pause_icon_button.set_kind("pause", "Pause upload")
        self.back_button.setEnabled(True)
        self.status_label.setText(f"Uploading {len(files_to_upload)} file(s)\u2026")
        self._upload_start = time.time()

        self._thread = QThread()
        self._worker = _UploadWorker(
            files_to_upload, self.session, self.manga_id, self.group_ids, self.upload_type,
            self.language, self.scanlator_name, self.thread_count, self.per_file_group_map,
            self.verify_timeout, self.current_user_id, self.is_group_upload, self.per_file_scanlator_map,
            resume_paused_state=self.resume_paused_state,
            only_filenames=only_filenames,
            per_file_language_map=self.per_file_language_map,
            skip_verification=self.skip_verification,
        )
        self.resume_paused_state = None  # one-shot: only the first _start_upload() call resumes
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.file_progress.connect(self._queue_file_progress)
        self._worker.batch_event.connect(self._on_batch_event)
        self._worker.file_paused.connect(self._on_file_paused)
        self._worker.file_cancelled.connect(self._on_file_cancelled)
        self._worker.finished.connect(self._on_upload_finished)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)

        self._thread.start()

    def _queue_file_progress(self, filename, status, fraction, speed_str="", eta_str="",
                              current=None, total=None):
        """Entry point for the (batch-upload) worker's file_progress
        signal - buffers the latest update per filename instead of
        calling _on_file_progress() immediately. See the module-level
        comment above _PROGRESS_DRAIN_INTERVAL_MS for why: a burst of
        many files finishing/ticking within the same instant (e.g. a
        run of verify polls landing together) previously meant that
        many back-to-back _on_file_progress calls in a single Qt
        event-loop turn, which was deep enough to overflow the native
        stack on large batches. Buffering by filename means a file that
        ticks multiple times before the next drain only keeps its most
        recent state - nothing is double-applied, and no intermediate
        purely-cosmetic tick is lost in a way that matters (the final
        state for that drain interval is always what gets shown).
        _drain_file_progress_queue() (run by a QTimer, see __init__)
        applies at most _PROGRESS_DRAIN_MAX_PER_TICK of these per
        interval, spreading a big burst across multiple ticks instead
        of one unbroken run."""
        self._pending_progress[filename] = (status, fraction, speed_str, eta_str, current, total)

    def _drain_file_progress_queue(self):
        """Runs every _PROGRESS_DRAIN_INTERVAL_MS (see __init__).
        Applies up to _PROGRESS_DRAIN_MAX_PER_TICK buffered updates by
        calling the real _on_file_progress() for each - same end
        result as calling it directly from the signal, just capped in
        how many happen per Qt event-loop turn. Leftover entries beyond
        the cap simply wait for the next tick; since _queue_file_progress
        only ever keeps the latest state per filename, nothing is lost
        or double-applied by being deferred a tick or two.

        Always applies at most the cap, even when called as part of the
        final flush (_flush_file_progress_queue, used by
        _on_upload_finished) - see that method for why an uncapped
        drain (this method's previous full=True mode) was itself a
        crash risk on a mass-cancel, and don't reintroduce that here."""
        if not self._pending_progress:
            return
        # dict preserves insertion order - draining oldest-queued first
        # keeps the earliest-finished files' rows updating first, rather
        # than an arbitrary order changing tick to tick.
        for filename in list(self._pending_progress.keys())[:_PROGRESS_DRAIN_MAX_PER_TICK]:
            status, fraction, speed_str, eta_str, current, total = self._pending_progress.pop(filename)
            self._on_file_progress(filename, status, fraction, speed_str, eta_str, current, total)

    def _flush_file_progress_queue_then(self, callback):
        """Used only by _on_upload_finished (see there). Guarantees
        every buffered progress update is applied - so final state
        (row status, stat cards) is accurate - WITHOUT ever applying
        more than _PROGRESS_DRAIN_MAX_PER_TICK of them in one
        uninterrupted call. Each chunk runs via _drain_file_progress_queue
        on a real, separate QTimer tick (letting Qt's event loop
        actually run between chunks), and `callback` (the rest of
        _on_upload_finished's work) only runs once the buffer is
        genuinely empty.

        This replaces an earlier full=True mode on
        _drain_file_progress_queue that applied every buffered entry in
        one uncapped pass - a mass-cancel (Cancel upload while dozens
        of files are in flight) lands most of them in the buffer within
        the same instant, and applying all of them back-to-back with no
        yield back to the event loop reintroduced the exact GUI-thread
        pile-up the capping was meant to prevent - observed as a
        Windows stack-overflow crash specifically on cancel."""
        if not self._pending_progress:
            callback()
            return
        self._drain_file_progress_queue()
        QTimer.singleShot(_PROGRESS_DRAIN_INTERVAL_MS, lambda: self._flush_file_progress_queue_then(callback))

    def _on_file_progress(self, filename, status, fraction, speed_str="", eta_str="",
                           current=None, total=None):
        """Updates one row's cells IN PLACE for the common case (status
        bucket unchanged - just new %/speed/eta/verify-seconds), which
        is what happens on nearly every tick. Only calls
        _relayout_table() when this file's status bucket actually
        crosses queued/uploading/success/warning/danger, since a full
        table rebuild on every fractional-percent tick would be both
        wasteful and visually jittery for a couple hundred rows. Also
        keeps _live_state_by_filename current on every call regardless,
        since _relayout_table() (triggered by sort/filter changes, not
        just by this method) needs an up-to-date snapshot for every
        file at all times, not just the ones whose bucket just flipped."""
        row = self._row_by_filename.get(filename)

        kind = _status_kind(status)

        # current/total (bytes) aren't sent with every progress update
        # (see progress_cb's comment) - when missing, fall back to
        # fraction * this file's known size, so the dim "so far/total"
        # fragment and the overall byte tally stay populated (if a bit
        # less precise) even during steps like "Verifying..." that
        # don't report raw byte counts of their own.
        if total is None:
            file_info = self._file_info_by_filename.get(filename)
            total = file_info.get("size") if file_info else None
        if current is None and total:
            current = fraction * total
        if kind == "success":
            # Done - lock this file's contribution in at its full size
            # rather than deleting it. Popping here was the bug: with N
            # concurrent threads, every single file completion (not just
            # this one) would wipe that file's bytes from the running
            # sum, so the overall "so far" total only ever reflected
            # whatever was mid-upload in that instant - it looked like
            # it "reset" every time any thread finished, and the shown
            # total fell further and further behind actual progress the
            # more files completed.
            if total:
                self._bytes_so_far_by_filename[filename] = total
            else:
                self._bytes_so_far_by_filename.pop(filename, None)
        elif kind == "danger":
            # Failed - these bytes genuinely didn't make it, so (unlike
            # success) they should NOT be counted toward "uploaded so
            # far".
            self._bytes_so_far_by_filename.pop(filename, None)
        elif current is not None and total:
            self._bytes_so_far_by_filename[filename] = min(current, total)

        display_status = status
        for prefix in _TERMINAL_PREFIXES:
            if display_status.startswith(prefix):
                display_status = display_status[len(prefix):].strip()
                break

        reported_elapsed = _parse_verifying_elapsed(display_status)
        if reported_elapsed is not None:
            # A real backend tick just arrived with its own elapsed
            # count - resync the local per-second clock to it
            # (time.time() - reported_elapsed) rather than trusting
            # whatever the 1s QTimer last drew, so occasional
            # scheduling jitter never lets the two drift apart, and
            # so a paused-then-resumed verify restarts its clock
            # from the backend's fresh count instead of the old
            # pre-pause start time.
            self._verify_started_at[filename] = time.time() - reported_elapsed
        else:
            self._verify_started_at.pop(filename, None)

        detail = _fmt_pill_detail(current, total) if kind not in ("success", "danger") else ""

        is_terminal = status.startswith(_TERMINAL_PREFIXES)
        new_bucket = kind if is_terminal else "uploading"
        old_bucket = self._status_by_filename.get(filename)

        # First tick that actually moves a file off "queued" is that
        # file's real upload-start time - assigned once and never
        # reassigned, so pausing/resuming a file doesn't shuffle it to
        # the back of "Upload time" order the way re-queuing would.
        if old_bucket == "queued" and new_bucket != "queued" and filename not in self._upload_started_at_by_filename:
            self._upload_started_at_by_filename[filename] = time.time()

        self._live_state_by_filename[filename] = {
            "status": display_status,
            "kind": kind,
            "fraction": fraction,
            "speed_str": speed_str,
            "eta_str": eta_str,
            "detail": detail,
        }

        if is_terminal:
            self._finished_filenames.add(filename)
        else:
            self._finished_filenames.discard(filename)
        self._status_by_filename[filename] = new_bucket

        if new_bucket != old_bucket:
            # Bucket changed (e.g. uploading -> success) - the row may
            # need to move (sorted-by-chapter puts finished files at
            # the end automatically since chapter order is fixed, but
            # "time" order and any active filter both depend on bucket
            # too), so let a full relayout place it correctly rather
            # than trying to patch its position in place.
            self._relayout_table()
        elif row is not None:
            # Same bucket as before - cheap in-place cell update, no
            # repositioning needed.
            self._update_row_cells(row, display_status, kind, fraction, speed_str, eta_str, detail)

        self._update_overall_progress()
        self._update_stat_cards()

    def _update_row_cells(self, row, display_status, kind, fraction, speed_str, eta_str, detail):
        """Cheap in-place redraw of one already-correctly-positioned
        row's cells - the common-case path _on_file_progress takes when
        a tick doesn't cross a status-bucket boundary. Never touches
        row position/count; _relayout_table() owns that."""
        pill = self._pill_in_row(row)
        if pill is not None:
            pill.set_kind(kind, display_status, detail=detail)

        action_button = self.table.cellWidget(row, COL_ACTIONS)
        action_button = getattr(action_button, "_action_button", None)
        if action_button is not None:
            if kind == "warning":
                # Paused - offer Resume for this one file
                action_button.set_kind("resume", "Resume this file")
                action_button.setEnabled(True)
            elif kind in ("success", "danger"):
                # Done or genuinely failed - nothing left to pause/resume
                action_button.setEnabled(False)
            else:
                action_button.set_kind("pause", "Pause this file")
                action_button.setEnabled(True)

        speed_item = self.table.item(row, COL_SPEED)
        if speed_item is not None:
            speed_item.setText(speed_str if speed_str else "\u2013")

        eta_item = self.table.item(row, COL_ETA)
        if eta_item is not None:
            eta_item.setText(eta_str if eta_str else "\u2013")

        bar = self.table.cellWidget(row, COL_PROGRESS)
        if bar is not None:
            pct = int(max(0.0, min(1.0, fraction)) * 100)
            bar.setValue(pct)
            new_state = "success" if pct >= 100 and kind == "success" else (
                "danger" if kind == "danger" else "")
            # unpolish()+polish() forces Qt's style engine to fully
            # re-evaluate this widget - same cost/cause as StatusPill's
            # stylesheet reapply above. setValue() alone already repaints
            # the bar; the style only needs a real repolish when the
            # "state" property (which drives the success/danger color via
            # QSS) actually flips, not on every percent tick.
            if bar.property("state") != new_state:
                bar.setProperty("state", new_state)
                bar.style().unpolish(bar)
                bar.style().polish(bar)

    def _tick_verifying_timers(self):
        """Runs every 1s (see the QTimer started in __init__). For each
        row currently mid-verify, redraws its pill's '(Ns)' using a
        locally-computed elapsed time rather than waiting on the
        backend, which only re-emits a fresh status roughly every
        RETRY_DELAY (5s) - see _parse_verifying_elapsed's docstring.
        Skips rows the backend hasn't (or no longer) reports as
        verifying, so it never fights a real status update or resurrects
        a clock for a file that already finished/paused/failed.

        Safety net: uploader.py's own verify_timeout check is the real
        enforcement (fixed separately to also fire mid-pagination-sweep,
        not just between sweeps - see upload_file_tus), but if a status
        update is ever missed or delayed for any reason, this local
        clock has nothing telling it to stop - it would otherwise just
        keep climbing on-screen past the real timeout with no upper
        bound (observed once as "Verifying... (639s)" against a 60s
        configured timeout). Capping the displayed/tracked elapsed time
        at self.verify_timeout plus one retry cycle's worth of slack
        (RETRY_DELAY, for the in-flight request that was already
        running when the deadline passed) means the on-screen number
        can never visibly outlive the timeout that's supposed to bound
        it, even if a real status update is somehow delayed past that
        point."""
        if not self._verify_started_at or not shiboken6.isValid(self):
            return
        stale_cutoff = self.verify_timeout + uploader.RETRY_DELAY
        for filename, started_at in list(self._verify_started_at.items()):
            row = self._row_by_filename.get(filename)
            pill = self._pill_in_row(row) if row is not None else None
            if pill is None:
                self._verify_started_at.pop(filename, None)
                continue
            elapsed = max(0, int(time.time() - started_at))
            if elapsed > stale_cutoff:
                # No real status update arrived to end this file's verify
                # clock even after the timeout plus slack has passed -
                # stop trusting/displaying this local estimate rather
                # than let it climb indefinitely. The backend's own
                # timeout return is still the source of truth for what
                # actually happened to the file; this only stops the
                # DISPLAY from lying about it in the meantime.
                self._verify_started_at.pop(filename, None)
                continue
            # Preserve whatever detail (byte count) is already showing -
            # this tick only ever touches the elapsed-seconds text.
            text = f"Verifying... ({elapsed}s)"
            pill.set_kind("info", text, detail=pill.detail())
            state = self._live_state_by_filename.get(filename)
            if state is not None:
                state["status"] = text

    def _update_overall_progress(self):
        done = len(self._finished_filenames)
        self.overall_progress.setValue(done)

        total = self._total_bytes_all_files
        if total:
            so_far = min(sum(self._bytes_so_far_by_filename.values()), total)
            self.overall_bytes_label.setText(f"{util.fmt_size(so_far)} / {util.fmt_size(total)}")
        else:
            self.overall_bytes_label.setText("")

    def _update_stat_cards(self):
        queued = uploading = done = paused = failed = 0
        for status in self._status_by_filename.values():
            if status == "queued":
                queued += 1
            elif status == "uploading" or status == "info":
                uploading += 1
            elif status == "success":
                done += 1
            elif status == "warning":
                # "warning" is _status_kind()'s bucket for the ⏸️ prefix
                # (paused files) - keep it out of "failed" (❌ / danger)
                # so a paused batch doesn't display as 41 failures.
                paused += 1
            elif status == "danger":
                failed += 1
        self.stat_queued.set_value(queued)
        self.stat_uploading.set_value(uploading)
        self.stat_done.set_value(done)
        self.stat_paused.set_value(paused)
        self.stat_failed.set_value(failed)

    def _on_stat_card_clicked(self, card):
        value = self._stat_card_filter_values.get(id(card))
        if value is None:
            return
        # Clicking the already-active card's own filter clears it back
        # to All - same "click again to deselect" behavior a filter
        # chip gets from SegmentedToggle, just reachable from the card
        # too since both control the same _status_filter.
        self._set_status_filter(None if self._status_filter == value else value)

    def _set_status_filter(self, value):
        if value == self._status_filter:
            return
        self._status_filter = value
        self._sync_filter_controls()
        self._relayout_table()

    def _set_sort_mode(self, mode):
        if mode == self._sort_mode:
            return
        self._sort_mode = mode
        self._relayout_table()

    def _sync_filter_controls(self):
        """Keeps filter_toggle's highlighted chip and every stat card's
        active-border in agreement with self._status_filter, regardless
        of which of the two controls the user actually clicked."""
        self.filter_toggle.set_current(self._status_filter)
        for card in (self.stat_queued, self.stat_uploading, self.stat_done,
                     self.stat_paused, self.stat_failed):
            card.set_active(self._stat_card_filter_values.get(id(card)) == self._status_filter)

    def _visible_ordered_filenames(self):
        """Computes the filename order _relayout_table() should give
        the table's rows: filtered down to self._status_filter (None =
        everything), then fully ordered by self._sort_mode.

        'default': grouped by status regardless of chapter/start time -
        Uploading+Paused on top, Queued in the middle, Done+Failed at
        the bottom (chapter order within that bottom group, so a failed
        file sits next to its finished siblings rather than wherever it
        happened to fail).
        'chapter': flat chapter-number order, status ignored entirely -
        this is the original/only behavior before 'default' and 'time'
        existed.
        'time': flat order by real wall-clock start time
        (_upload_started_at_by_filename), status ignored entirely;
        files that haven't started yet have no timestamp, so they sort
        after every file that HAS started (in chapter order among
        themselves) - "upload time" for a not-yet-begun file is
        undefined, and burying them at the end (in a stable,
        predictable sub-order) is far more useful than scattering them
        throughout the started ones.
        """
        if self._status_filter is None:
            filenames = list(self._file_info_by_filename.keys())
        else:
            filenames = [
                fn for fn, status in self._status_by_filename.items()
                if status == self._status_filter
            ]

        def chapter_key(fn):
            info = self._file_info_by_filename.get(fn) or {}
            return info.get("number", 0)

        if self._sort_mode == "time":
            def time_key(fn):
                started_at = self._upload_started_at_by_filename.get(fn)
                started = started_at is not None
                # (not started_first, started_at_or_chapter) - started
                # files (started=True -> not started=False -> sorts
                # first) ordered by real start time; not-yet-started
                # files all share started=False -> sort after, tied
                # broken by chapter number.
                return (not started, started_at if started else chapter_key(fn))
            filenames.sort(key=time_key)
        elif self._sort_mode == "default":
            # 0 = Uploading/Paused, 1 = Queued, 2 = Done/Failed - ties
            # within each band broken by chapter number, so the bottom
            # band in particular reads as a normal chapter-ordered list
            # with finished and failed rows interleaved naturally.
            def band(fn):
                bucket = self._status_by_filename.get(fn, "queued")
                if bucket in ("uploading", "warning"):
                    return 0
                if bucket == "queued":
                    return 1
                return 2  # success, danger
            filenames.sort(key=lambda fn: (band(fn), chapter_key(fn)))
        else:
            filenames.sort(key=chapter_key)

        return filenames

    def _on_batch_event(self, event, kwargs):
        if event == "batch_init_failed":
            self.status_label.setText(f"A batch failed to start: {kwargs.get('error', 'unknown error')}")
        elif event == "session_expired":
            self.status_label.setText("Session expired mid-upload \u2014 will pause once the current batch finishes.")
        elif event == "batch_complete_failed":
            self.status_label.setText(
                f"Warning: batch {kwargs.get('batch_id')} uploaded but the server-side "
                f"'complete' step failed: {kwargs.get('error')}"
            )
        elif event == "file_warning":
            self.status_label.setText(f"{kwargs.get('filename')}: {kwargs.get('warning')}")

    def _on_upload_finished(self, failed, session_expired, reasons):
        # Flush any progress updates still buffered by
        # _queue_file_progress() - the worker's `finished` signal is
        # itself queued the same way as file_progress, so by the time
        # this runs every real file_progress tick from this batch has
        # already been queued (Qt delivers queued signals in the order
        # they were posted). Without this, a handful of files that
        # ticked right before the batch finished could still be sitting
        # in the buffer, un-applied, when _finish_upload_after_flush
        # (below) reads final state (e.g. row status, stat cards).
        #
        # Goes through _flush_file_progress_queue_then rather than
        # draining synchronously in one uncapped pass: a mass-cancel
        # (Cancel upload while dozens of files are in flight) lands
        # most of them in the buffer within the same instant, and an
        # uncapped single-pass drain applied all of them back-to-back
        # with no yield back to the event loop - a real observed cause
        # of a Windows stack-overflow crash specifically on cancel. The
        # rest of what this method used to do now lives in
        # _finish_upload_after_flush, which only runs once the buffer
        # is confirmed empty.
        self._flush_file_progress_queue_then(
            lambda: self._finish_upload_after_flush(failed, session_expired, reasons)
        )

    def _finish_upload_after_flush(self, failed, session_expired, reasons):
        self._last_failed = failed
        self._last_reasons = reasons

        if self._pause_requested:
            self._handle_paused(failed)
            return

        if self._cancel_requested:
            if self._was_resuming:
                config_mod.clear_paused_upload()
            self._handle_cancelled(failed)
            return

        if session_expired:
            if self._was_resuming:
                config_mod.clear_paused_upload()
            self.overall_progress.setProperty("state", "danger")
            self.overall_progress.style().unpolish(self.overall_progress)
            self.overall_progress.style().polish(self.overall_progress)
            self._handle_session_expired(failed)
            return

        elapsed = time.time() - self._upload_start
        if not failed:
            if self._was_resuming:
                config_mod.clear_paused_upload()
            self.status_label.setText("\u2705 All files were processed successfully!")
            self.status_label.setProperty("role", "success")
            self.status_label.style().unpolish(self.status_label)
            self.status_label.style().polish(self.status_label)
            
            # Turn main bar green on 100% success
            self.overall_progress.setProperty("state", "success")
            self.overall_progress.style().unpolish(self.overall_progress)
            self.overall_progress.style().polish(self.overall_progress)
            
            self.done_button.setEnabled(True)
            self._final_failed_set = set()
            self._final_elapsed = elapsed
            return

        # Turn main bar red on any failures
        self.overall_progress.setProperty("state", "danger")
        self.overall_progress.style().unpolish(self.overall_progress)
        self.overall_progress.style().polish(self.overall_progress)

        self._offer_retry(failed, reasons, elapsed)

    def _handle_paused(self, failed):
        elapsed = time.time() - self._upload_start if self._upload_start else 0.0
        succeeded_filenames = {
            fn for fn, status in self._status_by_filename.items() if status == "success"
        }

        # Final save now that the batch has actually stopped cleanly -
        # on top of whatever incremental saves already happened via
        # _on_file_paused as each file reported in.
        self._persist_paused_state()
        resumable_count = len(self._paused_files) + len(self._not_yet_reported_files())

        self.overall_progress.setProperty("state", "")
        self.overall_progress.style().unpolish(self.overall_progress)
        self.overall_progress.style().polish(self.overall_progress)

        self.status_label.setText(
            f"\u23f8\ufe0f Paused \u2014 {len(succeeded_filenames)} of {len(self.all_files)} file(s) finished, "
            f"{resumable_count} remaining and saved for later. "
            f"You can resume now, or resume next time you open MangaDot Uploader."
        )
        # Flip the global icon button to Resume, and make it live again
        # (it was disabled while "Pausing..." was in flight) - clicking
        # it now calls _on_pause_or_resume_clicked, which sees
        # self._is_paused_state == True and resumes in place instead of
        # requiring the app to be closed and reopened.
        self._is_paused_state = True
        self.pause_icon_button.set_kind("resume", "Resume upload")
        self.pause_icon_button.setEnabled(resumable_count > 0)
        self.done_button.setEnabled(True)
        self._final_failed_set = set(failed)
        self._final_elapsed = elapsed

    def _handle_cancelled(self, failed):
        elapsed = time.time() - self._upload_start if self._upload_start else 0.0
        succeeded_count = len(self.all_files) - len(failed)

        self.overall_progress.setProperty("state", "danger" if failed else "")
        self.overall_progress.style().unpolish(self.overall_progress)
        self.overall_progress.style().polish(self.overall_progress)

        if self._cancel_then_go_back:
            self.status_label.setText(
                f"Upload cancelled \u2014 {succeeded_count} file(s) had already finished. "
                f"Returning to chapter selection\u2026"
            )
            self.back_requested.emit()
            return

        self.status_label.setText(
            f"Upload cancelled \u2014 {succeeded_count} of {len(self.all_files)} file(s) "
            f"finished before cancelling."
        )
        self.done_button.setEnabled(True)
        self._final_failed_set = set(failed)
        self._final_elapsed = elapsed

    def _handle_session_expired(self, failed):
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Warning)
        msg.setWindowTitle("Session expired")
        msg.setText("Your MangaDot session expired mid-upload. You'll need to log back in to resume the remaining files.")
        ok_btn = msg.addButton(QMessageBox.Ok)
        msg.addButton(QMessageBox.Cancel)
        msg.setDefaultButton(QMessageBox.Ok)
        msg.exec()
        if msg.clickedButton() != ok_btn:
            self.status_label.setText("Upload paused \u2014 session expired. Click Continue to stop here.")
            self.done_button.setEnabled(True)
            self._final_failed_set = set(failed)
            self._final_elapsed = time.time() - self._upload_start
            return

        self.status_label.setText("Re-authenticating\u2026")
        self._reauth_thread = QThread()
        self._reauth_worker = _ReauthWorker(self.session)
        self._reauth_worker.moveToThread(self._reauth_thread)
        self._reauth_thread.started.connect(self._reauth_worker.run)
        self._reauth_worker.finished.connect(self._on_reauth_finished)
        self._reauth_worker.finished.connect(self._reauth_thread.quit)
        self._reauth_worker.finished.connect(self._reauth_worker.deleteLater)
        self._reauth_thread.finished.connect(self._reauth_thread.deleteLater)
        self._reauth_thread.start()

    def _on_reauth_finished(self, winner):
        if not winner:
            QMessageBox.critical(
                self, "Re-authentication failed",
                "Could not find a valid MangaDot session in any browser. "
                "Log in to MangaDot in your browser, then click Continue to try again."
            )
            self.status_label.setText("Re-authentication failed \u2014 upload paused.")
            self.done_button.setEnabled(True)
            self._final_failed_set = set(self._last_failed)
            self._final_elapsed = time.time() - self._upload_start
            return

        self.current_user_id = winner["user_id"]
        failed_set = set(self._last_failed)
        remaining = [f for f in self.all_files if f["filename"] in failed_set]
        self.status_label.setText(f"Resuming upload for {len(remaining)} paused chapter(s)\u2026")
        self._start_upload(remaining)

    def _offer_retry(self, failed, reasons, elapsed):
        log_path = uploader.write_failed_log(self.manga_id, failed, reasons)
        log_note = f"\n\nFailed list saved to: {log_path}" if log_path else ""

        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Question)
        msg.setWindowTitle("Some uploads failed")
        msg.setText(f"{len(failed)} file(s) failed after all retries.{log_note}\n\nRetry ONLY the failed file(s)?")
        yes_btn = msg.addButton(QMessageBox.Yes)
        msg.addButton(QMessageBox.No)
        msg.setDefaultButton(QMessageBox.Yes)
        msg.exec()
        if msg.clickedButton() == yes_btn:
            failed_set = set(failed)
            remaining = [f for f in self.all_files if f["filename"] in failed_set]
            self.status_label.setText(f"Retrying {len(remaining)} failed chapter(s)\u2026")
            self._start_upload(remaining)
        else:
            if self._was_resuming:
                config_mod.clear_paused_upload()
            self.status_label.setText(f"{len(failed)} file(s) left unresolved.")
            self.done_button.setEnabled(True)
            self._final_failed_set = set(failed)
            self._final_elapsed = elapsed

    def _on_cancel_clicked(self):
        self._confirm_and_cancel(then_go_back=False)

    def _on_back_clicked(self):
        self._confirm_and_cancel(then_go_back=True)

    def _on_pause_or_resume_clicked(self):
        if getattr(self, "_is_paused_state", False):
            self._on_resume_all_clicked()
        else:
            self._on_pause_clicked()

    def _on_pause_clicked(self):
        done_count = sum(1 for s in self._status_by_filename.values() if s == "success")
        remaining_count = len(self.all_files) - done_count

        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Question)
        msg.setWindowTitle("Pause upload?")
        text = (f"Pause uploading? {remaining_count} file(s) remain.\n\n"
                f"Any file currently mid-transfer will finish its current chunk "
                f"before pausing, so nothing is left in a half-sent state. "
                f"You can resume from where you left off next time you open MangaDot Uploader.")
        msg.setText(text)
        yes_btn = msg.addButton("Pause", QMessageBox.YesRole)
        msg.addButton("Keep uploading", QMessageBox.NoRole)
        msg.setDefaultButton(yes_btn)
        msg.exec()
        if msg.clickedButton() != yes_btn:
            return

        self._pause_requested = True
        self.pause_icon_button.setEnabled(False)
        self.cancel_button.setEnabled(False)
        self.back_button.setEnabled(False)
        self.status_label.setText("Pausing\u2026 waiting for in-flight file(s) to reach a safe stopping point.")
        if self._worker is not None and shiboken6.isValid(self._worker):
            logging.debug(
                "DIAG _on_pause_clicked CALLED (global pause), worker id=%s, "
                "self id=%s (screen instance)", id(self._worker), id(self),
            )
            self._worker.pause()

    def _on_resume_all_clicked(self):
        """Resumes the whole paused batch from right here on this
        screen - the in-screen counterpart to main.py's
        _offer_resume_if_paused() startup dialog. Re-reads the
        just-written paused state from disk (via config.load_paused_upload())
        rather than reusing self._paused_files directly, since that's
        exactly what _persist_paused_state() / _handle_paused() already
        wrote out and it keeps this one code path (UploadProgressScreen.for_resume's
        shape) as the single source of truth for "what does a resume
        need" instead of duplicating that assembly here."""
        paused_state = config_mod.load_paused_upload()
        if paused_state is None:
            QMessageBox.information(
                self, "Nothing to resume",
                "No paused upload was found to resume."
            )
            return
        self._is_paused_state = False
        self.resume_paused_state = paused_state
        self._was_resuming = True

        # Already-completed files, from two sources merged together:
        #  1. paused_state.get("completed_files") - files persisted as
        #     done by WHATEVER run/screen last wrote paused_upload.json
        #     (see config.save_paused_upload()'s completed_files param).
        #     This is the only source available if the app was closed
        #     and reopened, since a fresh screen has no in-memory history.
        #  2. self.all_files filtered against paused_filenames - this
        #     screen's OWN live view, covering files it just watched
        #     finish (e.g. an individual per-row resume) that may not
        #     have been persisted to completed_files yet at the exact
        #     moment this click happened.
        # Deduplicated by filename so a file known to both sources only
        # renders once.
        paused_filenames = {f["filename"] for f in paused_state["files"]}
        from_disk = paused_state.get("completed_files") or []
        from_memory = [f for f in self.all_files if f["filename"] not in paused_filenames]
        already_done_files = list({f["filename"]: f for f in from_disk + from_memory}.values())

        self.status_label.setText(f"Resuming {len(paused_state['files'])} paused file(s)\u2026")
        self._start_upload(paused_state["files"], already_done_files=already_done_files)

    def _on_resume_one_clicked(self, filename):
        """Resumes a single paused file IN PLACE - i.e. only that one
        row updates; the rest of the table (other Done/Paused/Failed
        rows) is left exactly as-is. Deliberately does NOT go through
        _start_upload()/_reset_table(), since those rebuild the whole
        table from scratch and would wipe out everyone else's status
        just to resume one file. Used by both the per-row Resume icon
        button and the right-click "Resume" menu action.

        Runs its own small, self-contained _UploadWorker/QThread pair,
        independent of self._worker/self._thread (which, by the time
        this is reachable, already finished - _handle_paused or
        _on_upload_finished already fired for the main batch). Tracked
        in self._inline_resume_threads purely to keep them alive (a
        QThread whose only reference is a local variable can be
        garbage-collected out from under itself) - NOT reused as
        self._worker, so this can't be confused with or interfere with
        a subsequent full "Resume all"/"Retry failed" that replaces
        self._worker normally."""
        paused_state = config_mod.load_paused_upload()
        logging.debug("_on_resume_one_clicked(%r): loaded paused_state=%s", filename, "present" if paused_state else "None")
        if paused_state is None:
            QMessageBox.information(
                self, "Nothing to resume",
                "No paused state was found on disk for this file - it may "
                "already have been resumed or the paused upload was cleared."
            )
            return
        matching = [f for f in paused_state["files"] if f["filename"] == filename]
        logging.debug("_on_resume_one_clicked(%r): matching=%d entries", filename, len(matching))
        if not matching:
            QMessageBox.information(
                self, "Nothing to resume",
                f"'{filename}' isn't in the currently saved paused state."
            )
            return

        button = self._row_action_button(filename)
        if button is not None:
            button.setEnabled(False)
        self._on_file_progress(filename, "\u23f3 Resuming\u2026", 0.0)
        logging.debug("_on_resume_one_clicked(%r): status set to Resuming, about to build worker/thread", filename)

        thread = QThread()
        # Build the worker's controls from just the matching file(s),
        # not the full on-disk paused_state - matches only_filenames'
        # intent exactly and keeps a stray FileControl from lingering
        # for files this run has nothing to do with.
        scoped_state = dict(paused_state)
        scoped_state["files"] = matching
        worker = _UploadWorker(
            [], self.session, self.manga_id, self.group_ids, self.upload_type,
            self.language, self.scanlator_name, self.thread_count, self.per_file_group_map,
            self.verify_timeout, self.current_user_id, self.is_group_upload, self.per_file_scanlator_map,
            resume_paused_state=scoped_state, only_filenames={filename},
            skip_verification=self.skip_verification,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.file_progress.connect(self._on_file_progress)
        worker.file_paused.connect(self._on_inline_resume_paused)
        worker.file_cancelled.connect(self._on_file_cancelled)

        def _on_worker_finished(failed, expired, reasons, _filename=filename, _thread=thread, _worker=worker):
            logging.debug("_on_resume_one_clicked(%r): worker.finished received, failed=%s expired=%s reasons=%s",
                          _filename, failed, expired, reasons)
            self._on_inline_resume_finished(_filename, failed, expired, reasons)
            logging.debug("_on_resume_one_clicked(%r): _on_inline_resume_finished returned, calling thread.quit()", _filename)
            _thread.quit()

        worker.finished.connect(_on_worker_finished)
        worker.finished.connect(worker.deleteLater)

        def _on_thread_finished(_filename=filename, _thread=thread):
            logging.debug("_on_resume_one_clicked(%r): thread.finished received, discarding from _inline_resume_threads", _filename)
            self._inline_resume_threads.discard(_thread)

        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(_on_thread_finished)

        self._inline_resume_threads.add(thread)
        logging.debug("_on_resume_one_clicked(%r): calling thread.start(), pool size now %d", filename, len(self._inline_resume_threads))
        thread.start()
        logging.debug("_on_resume_one_clicked(%r): thread.start() returned (this should be near-instant)", filename)

    def _on_inline_resume_paused(self, file_info, upload_location, offset, fully_uploaded):
        """A single-file inline resume got paused again (e.g. session
        expired mid-transfer) rather than completing - update the
        persisted paused state for just this file, same bookkeeping
        _on_file_paused does for the main batch, without touching
        self._paused_files for files that aren't part of the currently
        running main batch.

        Goes through config.update_paused_upload() (one locked
        read-modify-write) rather than a separate load_paused_upload()
        + save_paused_upload() pair, since the latter is exactly the
        race that let this file's entry get silently clobbered by the
        main batch (or another inline resume) writing in between the
        read and the write."""
        filename = file_info["filename"]
        updated_entry = {
            "filename": filename,
            "filepath": file_info["filepath"],
            "number": file_info["number"],
            "title": file_info.get("title"),
            "size": file_info["size"],
            "upload_location": upload_location,
            "offset": offset,
            "fully_uploaded": fully_uploaded,
        }

        def merge(files):
            return [f for f in files if f["filename"] != filename] + [updated_entry]

        config_mod.update_paused_upload(merge)
        pct = (offset / file_info["size"]) if file_info.get("size") else 0.0
        self._on_file_progress(filename, "\u23f8\ufe0f Paused", pct)

    def _on_inline_resume_finished(self, filename, failed, session_expired, reasons):
        logging.debug("_on_inline_resume_finished(%r) ENTER, failed=%s", filename, failed)
        # Whether it succeeded or failed again, this file is no longer
        # "paused" from THIS screen's own point of view - drop any stale
        # entry _on_file_paused may have added to self._paused_files
        # earlier (e.g. from an earlier batch-wide pause that included
        # this file, before it was individually resumed). Without this,
        # self._paused_files keeps the old entry forever (it's only ever
        # reset to [] inside _start_upload, which the inline-resume path
        # deliberately never calls - see _on_resume_one_clicked's
        # docstring), so a LATER _persist_paused_state() call (from a
        # subsequent pause) would fold this stale entry back into
        # resumable_files via list(self._paused_files) + ... and write
        # it to disk's "files" list even though the file had already
        # succeeded and was correctly recorded in completed_files too -
        # resulting in the same file appearing in BOTH lists at once.
        self._paused_files = [f for f in self._paused_files if f["filename"] != filename]
        if filename not in failed:
            # Succeeded - drop it from the persisted paused-upload file
            # list so a later "Resume all" doesn't try to re-send it,
            # AND record it in completed_files so a screen rebuilt
            # from scratch (e.g. the app closed/reopened, or another
            # global resume) still knows this file is done instead of
            # having no record of it anywhere once it's off the
            # resumable list. This second half was the actual gap
            # behind "already-uploaded files disappear after resume" -
            # removing the entry alone was correct (it's genuinely not
            # resumable-pending anymore) but left nothing on disk
            # recording that it succeeded, so for_resume() had no way to
            # show it as Done.
            logging.debug("_on_inline_resume_finished(%r): calling update_paused_upload to remove entry + mark completed", filename)
            file_info = self._file_info_by_filename.get(filename)
            config_mod.update_paused_upload(
                lambda files: [f for f in files if f["filename"] != filename],
                mutate_completed_fn=lambda done: (
                    [f for f in done if f["filename"] != filename] + ([file_info] if file_info else [])
                ),
            )
            # Also update THIS screen's own self._status_by_filename to
            # "success" - without this, _not_yet_reported_files() (used
            # by a LATER _persist_paused_state() call, e.g. triggered by
            # a different file pausing afterward) has no way of knowing
            # this file already succeeded via the inline-resume path
            # above, since that path writes straight to disk and never
            # goes through _on_file_progress. It would fall through into
            # _not_yet_reported_files()'s catch-all as "still
            # queued/untouched", get written back with offset=0, and
            # silently clobber the correct completed-state this method
            # just wrote to disk two lines above - which is exactly the
            # "global pause overwrites an already-finished individual
            # resume" bug this fixes.
            logging.debug("DIAG _on_inline_resume_finished(%r): marking success in self._status_by_filename to prevent later clobber", filename)
            self._on_file_progress(filename, "\u2705 Uploaded", 1.0)
        button = self._row_action_button(filename)
        if button is not None:
            button.setEnabled(True)
        logging.debug("_on_inline_resume_finished(%r) RETURNING (button re-enabled=%s)", filename, button is not None)

    def _build_batch_config(self):
        return {
            "manga_id": self.manga_id,
            "group_ids": self.group_ids,
            "upload_type": self.upload_type,
            "language": self.language,
            "scanlator_name": self.scanlator_name,
            "thread_count": self.thread_count,
            "per_file_group_map": self.per_file_group_map,
            "per_file_scanlator_map": self.per_file_scanlator_map,
            "verify_timeout": self.verify_timeout,
            "current_user_id": self.current_user_id,
            "is_group_upload": self.is_group_upload,
            "skip_verification": self.skip_verification,
        }

    def _not_yet_reported_files(self):
        """Files from this batch that are neither confirmed successful
        nor already in self._paused_files - i.e. still queued/untouched
        when the pause took effect, or (if we're being called mid-batch,
        before the worker has fully stopped) simply haven't reported in
        yet. Included with offset=0/upload_location=None so a resume
        simply re-queues them from scratch."""
        succeeded_filenames = {
            fn for fn, status in self._status_by_filename.items() if status == "success"
        }
        paused_filenames = {f["filename"] for f in self._paused_files}
        result = []
        for f in self.all_files:
            if f["filename"] in succeeded_filenames or f["filename"] in paused_filenames:
                continue
            result.append({
                "filename": f["filename"], "filepath": f["filepath"],
                "number": f["number"], "title": f.get("title"), "size": f["size"],
                "upload_location": None, "offset": 0, "fully_uploaded": False,
            })
        return result

    def _persist_paused_state(self):
        """Merges the current batch's best-known paused files into
        whatever's on disk right now - safe to call repeatedly (e.g.
        once per file as they report in) and safe to call concurrently
        with an inline per-file resume's own writes (see
        _on_inline_resume_paused/_on_inline_resume_finished), since both
        now go through config.update_paused_upload(), which holds one
        lock across its whole read-modify-write cycle instead of each
        side doing its own separate load-then-save.

        Previously this called config.save_paused_upload() directly
        with ONLY this batch's self._paused_files, which is a blind
        full-file overwrite - if an inline resume for a different file
        had just removed itself from disk, this would silently
        resurrect it (or vice versa: an inline resume's save landing
        right after this one would erase files this batch had just
        paused). That race is exactly what caused 'Nothing to resume:
        No paused state was found on disk for this file' - the file
        genuinely was there a moment earlier, and then a second writer
        clobbered it before the first read could act on it.

        Deliberately does NOT early-return when self._paused_files /
        _not_yet_reported_files() are both empty - a cancel that removes
        the LAST tracked file for this batch still needs to run the
        merge (to actually erase that file's stale on-disk entry), even
        though there's nothing left to write for this batch itself.

        Called incrementally from _on_file_paused rather than only once
        at the very end, because if the app is closed while paused,
        stop_background_work()'s thread.wait(3000) can time out before
        the batch has fully stopped (a chunk PATCH already in flight can
        legitimately take longer than 3s to finish) - if nothing were
        persisted until _on_upload_finished fired, a slow-to-stop pause
        could close the app having saved nothing at all, silently losing
        everything the pause was supposed to protect."""
        resumable_files = list(self._paused_files) + self._not_yet_reported_files()
        # Every filename this run is responsible for - used so the merge
        # below can correctly REPLACE this run's own stale on-disk
        # entries (both paused and still-queued) instead of only ever
        # adding new copies alongside old ones.
        #
        # This was previously self._all_batch_filenames_ever_paused,
        # which only grew when a file actually paused - so a
        # still-queued file's entry (from _not_yet_reported_files(),
        # written fresh on every call since it has no fixed identity of
        # its own) was never recognized as "already on disk, replace
        # it" on the NEXT call. Each _persist_paused_state() call (fired
        # once per file as it pauses - see docstring) re-wrote a full
        # copy of every remaining not-yet-reported file without ever
        # dropping the previous call's copies, so the on-disk file grew
        # by roughly one full "not yet reported" batch on every single
        # call (41, then ~80, ~117, ~152... climbing indefinitely
        # instead of staying near 41) until it held hundreds of
        # duplicate/stale entries for the same handful of files.
        this_run_filenames = {f["filename"] for f in self.all_files}
        if not resumable_files and not this_run_filenames:
            return

        # This run's own view of which of ITS files have succeeded -
        # e.g. the 3 files a person watched finish before pausing the
        # rest. Persisted alongside the paused files list (as full
        # file-info dicts, not just names, so a resumed screen has real
        # filepath/size/etc. to render a proper Done row) so a screen
        # rebuilt from scratch later (main.py's startup resume dialog,
        # or another _persist_paused_state() call from a different run)
        # can still show them as Done instead of having no record of
        # them at all once they're no longer in the resumable list.
        this_run_succeeded_filenames = {
            fn for fn, status in self._status_by_filename.items() if status == "success"
        } & this_run_filenames
        this_run_succeeded_files = [
            self._file_info_by_filename[fn] for fn in this_run_succeeded_filenames
            if fn in self._file_info_by_filename
        ]

        def merge(current_files):
            # Keep whatever's already on disk for files THIS RUN doesn't
            # own (e.g. another still-running inline resume's own paused
            # entry, or a different batch's leftover state), then
            # overlay this run's current view of its own files on top -
            # this replaces ALL of this run's previous on-disk entries
            # (paused or still-queued) with exactly one fresh copy each,
            # rather than accumulating duplicates across calls.
            untouched = [f for f in current_files if f["filename"] not in this_run_filenames]
            logging.debug(
                "DIAG _persist_paused_state.merge screen id=%s: "
                "on-disk BEFORE had %d file(s) %r | this_run_filenames=%d | "
                "self._paused_files=%r | resumable_files being WRITTEN=%r",
                id(self), len(current_files),
                [f["filename"] for f in current_files],
                len(this_run_filenames),
                [f["filename"] for f in self._paused_files],
                [f["filename"] for f in resumable_files],
            )
            return untouched + resumable_files

        def merge_completed(current_completed):
            # Same replace-this-run's-own-entries pattern as merge()
            # above, applied to completed_files instead of files - keeps
            # completed entries from OTHER runs/batches intact while
            # making this run's own completed set authoritative for the
            # filenames it actually owns.
            untouched = [f for f in current_completed if f["filename"] not in this_run_filenames]
            return untouched + this_run_succeeded_files

        config_mod.update_paused_upload(merge, batch_config_if_new=self._build_batch_config(), mutate_completed_fn=merge_completed)

    def _on_file_paused(self, file_info, upload_location, offset, fully_uploaded):
        """Collects one file's resumable state as it arrives from the
        worker (see _UploadWorker.file_paused) and persists immediately
        - see _persist_paused_state() for why this can't wait until the
        whole batch finishes."""
        filename = file_info["filename"]
        logging.debug(
            "DIAG _on_file_paused ENTER filename=%r upload_location=%s offset=%s "
            "fully_uploaded=%s pause_requested=%s cancel_requested=%s",
            filename, upload_location, offset, fully_uploaded,
            getattr(self, "_pause_requested", None), getattr(self, "_cancel_requested", None),
        )
        # Drop any earlier entry for this filename first (a file can
        # legitimately report paused more than once - e.g. paused,
        # inline-resumed, then paused again) so _paused_files never ends
        # up with two stale entries for the same file.
        self._paused_files = [f for f in self._paused_files if f["filename"] != filename]
        self._paused_files.append({
            "filename": filename,
            "filepath": file_info["filepath"],
            "number": file_info["number"],
            "title": file_info.get("title"),
            "size": file_info["size"],
            "upload_location": upload_location,
            "offset": offset,
            "fully_uploaded": fully_uploaded,
        })
        self._persist_paused_state()
        pct = (offset / file_info["size"]) if file_info.get("size") else 0.0
        self._on_file_progress(filename, "\u23f8\ufe0f Paused", pct)

    def _on_file_cancelled(self, file_info):
        """A per-file cancel (FileControl.cancel(), from a row's
        right-click menu) is NOT resumable, unlike a pause - so unlike
        _on_file_paused, this file must never end up in
        self._paused_files / the persisted paused-upload state. If an
        earlier pause already recorded this filename (e.g. the user
        paused the whole batch, then individually cancelled one of the
        now-paused rows), that stale entry is removed here too, so a
        later "resume all" doesn't try to resume a file the user
        explicitly cancelled."""
        filename = file_info["filename"]
        self._paused_files = [f for f in self._paused_files if f["filename"] != filename]
        self._persist_paused_state()
        self._on_file_progress(filename, "\u274c Cancelled", 1.0)

    def _confirm_and_cancel(self, then_go_back):
        done_count = sum(1 for s in self._status_by_filename.values() if s == "success")
        remaining_count = len(self.all_files) - done_count

        action_desc = "go back to chapter selection" if then_go_back else "cancel the upload"
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Warning)
        msg.setWindowTitle("Cancel upload?")
        text = f"Are you sure you want to {action_desc}?"
        if done_count:
            text += (f"\n\n{done_count} file(s) have already finished uploading and will "
                     f"remain on MangaDot - cancelling only stops the {remaining_count} "
                     f"remaining file(s), it does not undo what's already been uploaded.")
        msg.setText(text)
        yes_btn = msg.addButton("Yes, " + action_desc.capitalize(), QMessageBox.YesRole)
        msg.addButton("Keep uploading", QMessageBox.NoRole)
        msg.setDefaultButton(yes_btn)
        msg.exec()
        if msg.clickedButton() != yes_btn:
            return

        self._cancel_requested = True
        self._cancel_then_go_back = then_go_back
        self.cancel_button.setEnabled(False)
        self.back_button.setEnabled(False)
        self.status_label.setText("Cancelling\u2026 waiting for in-flight file(s) to stop.")
        self.stop_background_work()

    def _on_done_clicked(self):
        header = self.table.horizontalHeader()
        order = [header.logicalIndex(visual) for visual in range(self.table.columnCount())]

        cfg = config_mod.load_config()
        cfg["upload_table_column_order"] = order
        cfg.pop("upload_table_state", None)  
        config_mod.save_config(cfg)

        self.upload_finished.emit(
            getattr(self, "_final_failed_set", set()),
            getattr(self, "_final_elapsed", 0.0),
        )

    def stop_background_work(self):
        # self._worker isn't reset to None after it finishes and is
        # deleteLater()'d (only ever reassigned by _start_upload), so if
        # stop_background_work() runs after an upload already completed,
        # self._worker may point at an object whose C++ side is gone.
        # shiboken6.isValid() is the same guard thread_is_running() uses
        # for QThread, for exactly this reason.
        if self._worker is not None and shiboken6.isValid(self._worker):
            if self._cancel_requested:
                # Explicit Cancel: actually interrupt the worker's
                # blocking call. This used to be a no-op - the branch
                # below only ever called self._worker.pause(), so
                # clicking "Cancel upload" set self._cancel_requested
                # and then did NOTHING to the running worker. abort_event
                # (checked by uploader._cancelled() at every chunk/
                # verify-loop boundary) stayed clear, so in-flight files
                # kept uploading/verifying normally; the only visible
                # effect was thread.quit()/wait(3000) below timing out
                # after 3s because quit() only stops a QThread's event
                # loop, not a thread stuck inside one long Python call
                # (see AbortableWorker's own docstring). Net result:
                # "Cancelling... waiting for in-flight file(s) to stop."
                # never resolved and the upload just continued in the
                # background. Calling abort() here sets abort_event, so
                # _cancelled() starts returning True at the next
                # checkpoint and the worker's run() actually unwinds and
                # emits finished() for real.
                self._worker.abort()
            elif self._pause_requested:
                # Already told to stop via the explicit Pause button -
                # that request already called .pause() itself. Don't
                # override an explicit pause here.
                pass
            else:
                # The app is being closed (window X, main.py's
                # closeEvent, or a screen teardown) without the user
                # explicitly choosing Pause or Cancel first. Treat this
                # as a pause rather than an abort: the whole point of
                # this feature is that closing the app mid-upload
                # shouldn't throw away in-flight progress - it should be
                # resumable next time, the same as clicking Pause
                # deliberately would have done. _on_upload_finished
                # (still connected - we're not tearing the thread down
                # until after giving it a chance to report its paused
                # state) will route through _handle_paused and persist
                # it via config.save_paused_upload(), same as the
                # explicit Pause button path.
                self._pause_requested = True
                logging.debug(
                    "DIAG stop_background_work AUTO-PAUSE (no explicit pause/cancel "
                    "requested), worker id=%s, self id=%s\nSTACK:\n%s",
                    id(self._worker), id(self), "".join(traceback.format_stack()[:-1]),
                )
                self._worker.pause()
        for thread in (self._thread, getattr(self, "_reauth_thread", None)):
            if thread is not None and thread_is_running(thread):
                thread.quit()
                thread.wait(3000)


class _ReauthWorker(QObject):
    finished = Signal(object)

    def __init__(self, session):
        super().__init__()
        self.session = session

    def run(self):
        winner, _ = auth.try_all_browsers(self.session)
        self.finished.emit(winner)