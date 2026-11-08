"""MangaDot Uploader - GUI entry point."""
import os
import sys
import time
import logging
import traceback
import datetime
import faulthandler
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QThread, QObject, Signal
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QStackedWidget, QMessageBox, QWidget,
    QVBoxLayout, QFileDialog, QSpacerItem, QSizePolicy
)

from mangadot_app.gui import theme
from mangadot_app.gui import thread_is_running
from mangadot_app.gui.widgets import StepStrip, ProfileLoginPage
from mangadot_app.gui.picker_screen import PickerScreen
from mangadot_app.gui.subset_picker_screen import SubsetPickerScreen
from mangadot_app.gui.login_screen import LoginScreen
from mangadot_app.gui.group_config_dialog import GroupConfigScreen
from mangadot_app.gui.title_review_screen import TitleReviewScreen
from mangadot_app.gui.upload_progress_screen import UploadProgressScreen
from mangadot_app.gui.settings_dialog import StartupSettingsDialog
from mangadot_app.gui.optimizer_progress_screen import OptimizerProgressScreen
from mangadot_app.gui.summary_screen import SummaryScreen
from mangadot_app import parser as parser_mod
from mangadot_app import debugging
from mangadot_app import config as config_mod
from mangadot_app import net

_ASSETS_DIR = Path(__file__).resolve().parent / "mangadot_app" / "assets"
_LOGO_PATH = _ASSETS_DIR / "mangadotnet-purple.svg"

_STEP_LOGIN = 0
_STEP_MANGA = 1
_STEP_ATTRIBUTION = 2
_STEP_REVIEW = 3
_STEP_UPLOAD = 4
_STEP_DONE = 5

# Crash log path: CACHE_DIR is guaranteed writable (config.py already
# writes its own JSON files there), unlike the exe's own install
# directory, which can be read-only (e.g. under Program Files). A
# --windowed/--noconsole build has nowhere else for an uncaught
# exception's traceback to go - without this it just vanishes with the
# window, which is exactly what made the "second simultaneous upload"
# crash impossible to diagnose from a bug report alone.
CRASH_LOG_PATH = config_mod.CACHE_DIR / "crash.log"

# faulthandler dumps every thread's Python-level call stack straight to
# a file the instant SIGSEGV/SIGABRT/SIGFPE/SIGBUS/SIGILL fires - this
# is DIFFERENT from (and complementary to) _install_crash_handler()
# below. sys.excepthook/threading.excepthook only ever see a genuine
# Python exception object; a native-level crash (e.g. a Qt/C++
# use-after-free, or a crash inside a C extension) never raises one -
# the process just dies - so those hooks stay silent and crash.log
# never gets written for this class of bug. This is exactly the gap
# that made the "crashes with an empty crash.log" report undiagnosable
# from sys.excepthook alone: no Python exception ever existed to catch.
# faulthandler's file handle needs to stay open for the process's
# entire lifetime (it writes directly at signal-handler time, which
# cannot safely reopen a file), so it's kept as a module-level global
# rather than a local closed after setup.
_FAULT_LOG_PATH = config_mod.CACHE_DIR / "fault.log"
_fault_log_file = None


def _install_fault_handler():
    global _fault_log_file
    _FAULT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _fault_log_file = open(_FAULT_LOG_PATH, "a", encoding="utf-8")
    _fault_log_file.write(
        f"\n{'=' * 70}\n{datetime.datetime.now().isoformat()} - fault handler armed\n{'=' * 70}\n"
    )
    _fault_log_file.flush()
    faulthandler.enable(file=_fault_log_file, all_threads=True)




def _install_crash_handler():
    """Routes every uncaught exception on the main thread AND on any
    QThread worker to CRASH_LOG_PATH, then lets the default handler run
    afterward (still prints to stderr when a console is attached, and
    still lets Qt/Python do whatever it would normally do on an unhandled
    exception - this only adds a durable record, it doesn't change
    behavior otherwise).

    sys.excepthook alone only covers the main thread. A worker QThread's
    run() raising an uncaught exception goes through
    threading.excepthook instead (Python 3.8+) - PySide6's QThread.run()
    is invoked via Python's threading machinery under the hood, so both
    hooks are needed to actually catch "the crash happened in a
    background upload/optimizer/profile-fetch thread" cases, which is
    exactly the shape most of this app's crashes are likely to take.
    """
    import threading

    CRASH_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

    def _write_crash(exc_type, exc_value, exc_tb, thread_name="MainThread"):
        try:
            with open(CRASH_LOG_PATH, "a", encoding="utf-8") as f:
                f.write("=" * 70 + "\n")
                f.write(f"{datetime.datetime.now().isoformat()} - unhandled exception on {thread_name}\n")
                f.write("=" * 70 + "\n")
                traceback.print_exception(exc_type, exc_value, exc_tb, file=f)
                f.write("\n")
        except Exception:
            # If we can't even write the crash log, don't let that
            # itself become a second unhandled exception during
            # exception handling - just fall through to the default
            # hooks below, which still print to stderr if a console is
            # attached.
            pass

    _default_excepthook = sys.excepthook

    def _main_thread_hook(exc_type, exc_value, exc_tb):
        _write_crash(exc_type, exc_value, exc_tb, thread_name="MainThread")
        _default_excepthook(exc_type, exc_value, exc_tb)

    sys.excepthook = _main_thread_hook

    _default_thread_excepthook = threading.excepthook

    def _thread_hook(args):
        _write_crash(args.exc_type, args.exc_value, args.exc_traceback,
                     thread_name=(args.thread.name if args.thread else "UnknownThread"))
        _default_thread_excepthook(args)

    threading.excepthook = _thread_hook



# ==============================================================================
# 🧠 WORKERS & GUI LOGIC
# ==============================================================================

class _ProfileFetchWorker(QObject):
    finished = Signal(object)  
    def __init__(self, session, username=None):
        super().__init__()
        self.session = session
        self.username = username

    def run(self):
        profile = net.fetch_profile_stats(self.session, username=self.username)
        self.finished.emit(profile)


class _SummaryDetailsWorker(QObject):
    finished = Signal(object, object, dict)

    def __init__(self, session, manga_id, upload_type, user_id):
        super().__init__()
        self.session = session
        self.manga_id = manga_id
        self.upload_type = upload_type
        self.user_id = user_id

    def run(self):
        details = net.fetch_manga_full_details(self.manga_id, self.session)
        
        cover_bytes = None
        if details and details.get("cover_url"):
            cover_bytes = net.fetch_image_bytes(self.session, details["cover_url"])

        chapter_map = net.build_uploaded_chapter_map(
            self.session, self.manga_id, self.upload_type, self.user_id
        )

        self.finished.emit(details, cover_bytes, chapter_map)


class MainWindow(QMainWindow):
    def __init__(self, settings):
        super().__init__()
        self.setWindowTitle("MangaDot Uploader")
        self.resize(1172, 602)
        self.settings = settings
        self.session = None
        self.username = None
        self.user_id = None
        self.upload_progress_screen = None
        self.group_config_screen = None
        self.picker_screen = None
        self.optimizer_screen = None
        self.subset_picker_screen = None
        self.summary_screen = None
        self.title_review_screen = None
        self.login_screen = None
        self.profile_card = None
        self._chapter_map = {}
        self._profile_thread = None
        self._profile_worker = None
        self._summary_thread = None
        self._summary_worker = None
        self._target_key = None
        self._last_per_file_group_map = {}
        self._last_per_file_scanlator_map = {}
        self._last_per_file_language_map = {}
        self._manga_title = None
        self._manga_id = None
        # Populated by the mixed-language popup in _scan_and_pick_subset
        # when the user chooses "Use detected languages" - maps
        # norm_filepath -> detected language code for files that got a
        # confirmed per-file language. A file with no entry here falls
        # back to self._lang (the dropdown default), same convention as
        # per_file_group_map/per_file_scanlator_map already use.
        self._per_file_language_map = {}
        self._lang = "en"
        self._upload_type = "chapter"
        self._group_label = None
        self._group_config = {}

        # Determine mode
        self._is_dry_run = getattr(self.settings, "launch_mode", "normal") == "dry_run"

        central = QWidget()
        outer_layout = QVBoxLayout(central)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        self.step_strip = StepStrip()
        outer_layout.addWidget(self.step_strip)

        self.stack = QStackedWidget()
        outer_layout.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        if self._is_dry_run:
            self._show_step_strip = True
            self.step_strip.setVisible(True)
            self.session = net.create_base_session(
                self.settings.proxy_url, 
                self.settings.proxy_no_verify, 
                self.settings.debug_enabled
            )
            self.username = "Dry Run User"
            self.user_id = "0"
            self._advance_to_manga_picker()
            
        elif self.settings.opt_mode == "standalone":
            self._show_step_strip = False
            self.step_strip.setVisible(False)
            self._start_standalone_optimizer()
        else:
            self._show_step_strip = True
            self.step_strip.setVisible(True)
            self._start_login()

    _TRACKED_SCREEN_ATTRS = (
        "login_screen", "upload_progress_screen", "group_config_screen",
        "picker_screen", "optimizer_screen", "subset_picker_screen",
        "summary_screen", "title_review_screen", "profile_card",
    )

    def _teardown_screens(self, remove_from_stack=False):
        """Stops every tracked screen's background work (and the two
        module-level fetch threads), optionally also removing each
        screen from self.stack and scheduling it for deletion.

        Used by both closeEvent (remove_from_stack=False - the process is
        exiting anyway, no need to touch the stack) and
        _restart_from_settings (remove_from_stack=True - previously that
        method deleted every screen via deleteLater() without ever
        calling stop_background_work() first, so a live upload/optimizer
        thread with signal connections back into its (now being deleted)
        screen could later try to deliver a signal to a partially/fully
        deleted QObject).

        profile_card is included here even though it isn't one of the
        *_screen attributes and lives outside the QStackedWidget as an
        alias for the ProfileLoginPage's banner (self.profile_page.banner)
        - it has its own background thread (avatar/cover fetch) via
        ProfileBannerWidget.stop_background_work() and was previously
        never told to stop at all.
        """
        for screen_attr in self._TRACKED_SCREEN_ATTRS:
            screen = getattr(self, screen_attr, None)
            if screen is not None and hasattr(screen, "stop_background_work"):
                screen.stop_background_work()

        if self._profile_thread is not None and thread_is_running(self._profile_thread):
            self._profile_thread.quit()
            self._profile_thread.wait(3000)
        if self._summary_thread is not None and thread_is_running(self._summary_thread):
            self._summary_thread.quit()
            self._summary_thread.wait(3000)

        if remove_from_stack:
            while self.stack.count() > 0:
                widget = self.stack.widget(0)
                self.stack.removeWidget(widget)
                widget.deleteLater()

    def closeEvent(self, event):
        self._teardown_screens(remove_from_stack=False)
        super().closeEvent(event)

    def _set_step(self, index):
        if self._show_step_strip:
            self.step_strip.set_current(index)

    def _show(self, widget):
        if self.stack.indexOf(widget) == -1:
            self.stack.addWidget(widget)
        self.stack.setCurrentWidget(widget)

    def _restart_from_settings(self):
        settings = StartupSettingsDialog()
        self.hide()
        
        if settings.exec():
            self.settings = settings
            self._is_dry_run = getattr(self.settings, "launch_mode", "normal") == "dry_run"
            
            if settings.debug_enabled:
                debugging.enable_debug_logging()
                
            self._teardown_screens(remove_from_stack=True)
                
            self.upload_progress_screen = None
            self.group_config_screen = None
            self.picker_screen = None
            self.optimizer_screen = None
            self.subset_picker_screen = None
            self.summary_screen = None
            self.title_review_screen = None
            self.login_screen = None
            self.profile_card = None

            if self._is_dry_run:
                self._show_step_strip = True
                self.step_strip.setVisible(True)
                self.session = net.create_base_session(
                    self.settings.proxy_url, 
                    self.settings.proxy_no_verify, 
                    self.settings.debug_enabled
                )
                self.username = "Dry Run User"
                self.user_id = "0"
                self._advance_to_manga_picker()
            elif self.settings.opt_mode == "standalone":
                self._show_step_strip = False
                self.step_strip.setVisible(False)
                self._start_standalone_optimizer()
            else:
                self._show_step_strip = True
                self.step_strip.setVisible(True)
                self._start_login()
                
            self.show()
        else:
            self.close()

    # ------------------------------------------------------ standalone optimizer
    def _start_standalone_optimizer(self):
        cfg = config_mod.load_config()
        start_dir = cfg.get("library", "")
        directory = QFileDialog.getExistingDirectory(self, "Select Folder to Optimize", start_dir)

        if not directory:
            self.close()
            return

        config_mod.remember_library(directory)
        self.optimizer_screen = OptimizerProgressScreen(directory, self.settings)
        if getattr(self.optimizer_screen, "_declined", False):
            self._start_standalone_optimizer()
            return
        self.optimizer_screen.optimization_finished.connect(lambda _: self.close())
        self._show(self.optimizer_screen)

    # -------------------------------------------------------------------- login
    def _start_login(self):
        self._set_step(_STEP_LOGIN)
        self.login_placeholder = QWidget()
        self._show(self.login_placeholder)

        self.login_screen = LoginScreen(
            parent=self,
            proxy_url=self.settings.proxy_url,
            proxy_no_verify=self.settings.proxy_no_verify,
            debug_enabled=self.settings.debug_enabled
        )
        self.login_screen.login_succeeded.connect(self._on_login_succeeded)
        self.login_screen.content_resized.connect(
            lambda: self._position_popup_centered(self.login_screen)
        )
        QTimer.singleShot(50, self._show_login_popup)

    def _show_login_popup(self):
        self._position_popup_centered(self.login_screen)
        self.login_screen.show()
        QTimer.singleShot(150, lambda: self._position_popup_centered(self.login_screen))

    def _position_popup_centered(self, dialog):
        if hasattr(dialog, "_resize_to_content"):
            dialog._resize_to_content()
        else:
            dialog.adjustSize()
        main_geo = self.geometry()
        x = main_geo.x() + (main_geo.width() - dialog.width()) // 2
        y = main_geo.y() + (main_geo.height() - dialog.height()) // 2
        dialog.move(max(x, 0), max(y, 0))

    def _on_login_succeeded(self, username, user_id, session):
        self.username = username
        self.user_id = user_id
        self.session = session
        if hasattr(self, "settings") and self.settings is not None:
            self.settings.session = session
            self.settings.username = username

        if hasattr(self.login_screen, "stop_background_work"):
            self.login_screen.stop_background_work()
        self.login_screen.close()

        if self._offer_resume_if_paused():
            return

        winner = getattr(self.login_screen, "_winner", None)
        browser_name = winner["browser"].title() if winner else ""

        self.profile_page = ProfileLoginPage(
            logo_path=_LOGO_PATH,
            username=username,
            browser_name=browser_name,
            session=session,
        )
        self.profile_card = self.profile_page.banner  # kept for _on_profile_fetched below
        self.profile_page.continue_clicked.connect(self._advance_to_manga_picker)
        self._show(self.profile_page)

        self._profile_thread = QThread()
        self._profile_worker = _ProfileFetchWorker(session, username=username)
        self._profile_worker.moveToThread(self._profile_thread)
        self._profile_thread.started.connect(self._profile_worker.run)
        self._profile_worker.finished.connect(self._on_profile_fetched)
        self._profile_worker.finished.connect(self._profile_thread.quit)
        self._profile_worker.finished.connect(self._profile_worker.deleteLater)
        self._profile_thread.finished.connect(self._profile_thread.deleteLater)
        self._profile_thread.start()

    def _on_profile_fetched(self, profile):
        if profile:
            self.profile_card.set_profile(profile)
        else:
            self.profile_card.set_fetch_failed()

    def _offer_resume_if_paused(self):
        """Returns True if a paused upload was found AND the user chose
        to resume it (in which case the caller should skip building the
        normal post-login flow - this method already showed the resumed
        UploadProgressScreen itself). Returns False if there was nothing
        paused, or the user chose to discard it - either way, the normal
        flow should proceed as if nothing happened."""
        paused_state = config_mod.load_paused_upload()
        if paused_state is None:
            return False

        bc = paused_state.get("batch_config", {})
        files = paused_state.get("files", [])
        paused_at = paused_state.get("paused_at")
        age_str = self._format_paused_age(paused_at) if paused_at else "an unknown time ago"

        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Question)
        msg.setWindowTitle("Resume paused upload?")
        msg.setText(
            f"You have a paused upload from {age_str} "
            f"({len(files)} file(s) remaining, manga ID {bc.get('manga_id', '?')}).\n\n"
            f"Resume it now, or discard it and start fresh?"
        )
        resume_btn = msg.addButton("Resume upload", QMessageBox.YesRole)
        msg.addButton("Discard and start fresh", QMessageBox.NoRole)
        msg.setDefaultButton(resume_btn)
        msg.exec()

        if msg.clickedButton() != resume_btn:
            config_mod.clear_paused_upload()
            return False

        bc = paused_state["batch_config"]
        self._manga_id = bc["manga_id"]
        # Paused-upload state never persisted the manga title (only its
        # id), so there's nothing to show here without an extra network
        # fetch - UploadProgressScreen/SummaryScreen just fall back to
        # the manga_id-only label in this one path.
        self._manga_title = None
        self._upload_type = bc["upload_type"]
        self._lang = bc.get("language")
        self._group_label = "Resumed upload"
        self._group_config = {
            "is_group_upload": bc.get("is_group_upload"),
            "group_ids": bc.get("group_ids") or [],
            "scanlator_name": bc.get("scanlator_name"),
            "per_file_group_map": bc.get("per_file_group_map"),
        }
        self._last_per_file_group_map = bc.get("per_file_group_map") or {}
        self._last_per_file_scanlator_map = bc.get("per_file_scanlator_map") or {}
        self._target_key = config_mod.make_target_key(
            self._manga_id, self._upload_type, self._lang,
            self._group_config["group_ids"], self._group_config["scanlator_name"],
        )
        # _on_upload_finished normally reads all_files from
        # self.title_review_screen.files - which is None on this path,
        # since resuming skips that screen entirely. Standing in a
        # lightweight object with just the attribute it actually reads
        # avoids needing a parallel copy of _on_upload_finished's logic
        # just for the resume case.
        class _ResumedFilesStandIn:
            """Not a QObject - deliberately. This only exists to satisfy
            _on_upload_finished's getattr(self.title_review_screen,
            "files", []) read, since the resume path skips the real
            TitleReviewScreen entirely. deleteLater() is a no-op stub
            (not the real QObject deferred-deletion mechanism) because
            _cleanup_previous_upload_cycle() and _teardown_screens()
            unconditionally call it on every tracked screen attribute,
            including this one - without this stub, starting a second
            upload cycle (e.g. "Upload Again") after a resumed session
            would raise AttributeError."""
            def __init__(self, files):
                self.files = files
            def deleteLater(self):
                pass
        self.title_review_screen = _ResumedFilesStandIn(paused_state["files"])

        self._show_step_strip = True
        self.step_strip.setVisible(True)
        self._set_step(_STEP_UPLOAD)
        self.upload_progress_screen = UploadProgressScreen.for_resume(paused_state, self.session)
        self.upload_progress_screen.upload_finished.connect(self._on_upload_finished)
        self._show(self.upload_progress_screen)
        return True

    @staticmethod
    def _format_paused_age(paused_at):
        seconds = max(0, time.time() - paused_at)
        if seconds < 60:
            return "less than a minute ago"
        minutes = int(seconds // 60)
        if minutes < 60:
            return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
        hours = int(minutes // 60)
        if hours < 24:
            return f"{hours} hour{'s' if hours != 1 else ''} ago"
        days = int(hours // 24)
        return f"{days} day{'s' if days != 1 else ''} ago"

    def _advance_to_manga_picker(self):
        self._cleanup_previous_upload_cycle()
        self._set_step(_STEP_MANGA)
        self.picker_screen = PickerScreen(session=self.session, username=self.username)
        self.picker_screen.picker_finished.connect(self._on_picker_finished)
        self._show(self.picker_screen)

    def _cleanup_previous_upload_cycle(self):
        """Removes and deletes screens left over from a completed upload
        cycle when starting a new one (via "Upload Again" or the initial
        post-login advance). Safe to do here specifically: once a fresh
        picker_screen is about to start the flow over, nothing can still
        need to navigate "back" into the previous cycle's
        group_config_screen / subset_picker_screen / title_review_screen
        / upload_progress_screen / optimizer_screen, or into the outgoing
        picker_screen itself. Those same screens are deliberately left
        alone by mid-flow back_requested handlers, where a user going
        "back" genuinely does need the previous screen instance to still
        be alive (e.g. group_config_screen.back_requested reshows
        self.picker_screen)."""
        cycle_attrs = (
            "picker_screen", "group_config_screen", "subset_picker_screen",
            "title_review_screen", "upload_progress_screen", "optimizer_screen",
            "summary_screen",
        )
        for attr in cycle_attrs:
            screen = getattr(self, attr, None)
            if screen is None:
                continue
            if hasattr(screen, "stop_background_work"):
                screen.stop_background_work()
            if isinstance(screen, QWidget) and self.stack.indexOf(screen) != -1:
                self.stack.removeWidget(screen)
            screen.deleteLater()
            setattr(self, attr, None)

    # ------------------------------------------------------------------ picker
    def _on_picker_finished(self, folder, manga_id, manga_title, lang, threads, upload_type,
                             chapter_naming, custom_regex, strip_groups, verify_timeout,
                             skip_verification):
        self._folder = folder
        self._manga_id = manga_id
        self._manga_title = manga_title or None
        self._lang = lang
        self._threads = threads
        self._upload_type = upload_type
        self._chapter_naming = chapter_naming or "extract"
        self._custom_regex = custom_regex or None
        self._advanced_strip = strip_groups
        self._verify_timeout = verify_timeout
        self._skip_verification = skip_verification
        self._manga_details = getattr(self.picker_screen, "selected_manga_details", None)

        self.session.headers.update({"Referer": f"https://mangadot.net/manga/{manga_id}/upload"})

        self._set_step(_STEP_ATTRIBUTION)
        self.group_config_screen = GroupConfigScreen(self.session, folder, upload_type=self._upload_type)
        self.group_config_screen.config_finished.connect(self._on_group_config_finished)
        self.group_config_screen.back_requested.connect(
            lambda: (self._set_step(_STEP_MANGA), self._show(self.picker_screen))
        )
        self._show(self.group_config_screen)

    def _on_group_config_finished(self, group_config):
        self._group_config = group_config
        self._group_label = group_config.get("group_name", "-")

        if self.settings.opt_mode == "chained" and not self._is_dry_run:
            self.optimizer_screen = OptimizerProgressScreen(self._folder, self.settings)
            if getattr(self.optimizer_screen, "_declined", False):
                self._show(self.group_config_screen)
                return
            self.optimizer_screen.optimization_finished.connect(self._on_optimization_finished)
            self._show(self.optimizer_screen)
        else:
            self._scan_and_pick_subset()

    def _on_optimization_finished(self, new_folder):
        self._folder = new_folder
        self._scan_and_pick_subset()

    # ------------------------------------------------------------------ scan
    def _scan_and_pick_subset(self):
        custom_renames, custom_extractor = parser_mod.parse_custom_regex_input(self._custom_regex)

        files, errors = parser_mod.scan_directory_files(
            self._folder,
            upload_type=self._upload_type,
            chapter_naming=self._chapter_naming,
            custom_regex=custom_extractor,
            custom_renames=custom_renames,
            strip_groups=self._group_config.get("strip_bracket_groups", False) or self._advanced_strip,
        )

        if errors:
            QMessageBox.warning(self, "Some files were skipped", "\n".join(errors[:10]))
        if not files:
            QMessageBox.critical(self, "No files found", f"No {self._upload_type} archives (.cbz/.zip) found in:\n{self._folder}")
            return

        if self._upload_type == "chapter":
            drift = parser_mod.detect_episode_drift(files)
            if drift:
                msg = QMessageBox(self)
                msg.setWindowTitle("Numbering Conflict Detected")
                msg.setText(
                    "Filename sequence and Episode labels disagree "
                    "(this can happen after a season reset or inserted specials).\n\n"
                    f"{len(drift['conflicts'])} file(s) affected.\n"
                    f"Example: '{drift['example_filename']}'\n"
                    f" -> File Index: {drift['example_file_index']:g}\n"
                    f" -> Episode Label: {drift['example_episode_label']:g}\n\n"
                    "How should these be sorted on MangaDot?"
                )
                cont_btn = msg.addButton(f"Continuous (Use Ch {drift['example_file_index']:g})", QMessageBox.AcceptRole)
                reset_btn = msg.addButton(f"Trust Labels (Use Ch {drift['example_episode_label']:g})", QMessageBox.AcceptRole)
                msg.exec()

                mode = "continuous" if msg.clickedButton() == cont_btn else "reset"
                parser_mod.apply_episode_drift_correction(files, mode)
                files.sort(key=lambda x: x["number"])

        approved_tags = self._group_config.get("approved_tags")
        if approved_tags is not None:
            parser_mod.apply_tag_filter_to_files(files, approved_tags)

        parser_mod.finalize_file_entries(files)

        # --- LANGUAGE DETECTION ---
        # Reset per-run: a previous folder's choice must not leak into this
        # scan if the user went Back and picked a different folder.
        self._per_file_language_map = {}

        detected_lang_map = parser_mod.detect_languages_from_files(files)
        if parser_mod.is_languages_mixed(detected_lang_map, dropdown_default=self._lang):
            tagged = {k: v for k, v in detected_lang_map.items() if v}
            untagged_paths = {k for k, v in detected_lang_map.items() if v is None}
            distinct_detected = set(tagged.values())

            breakdown = parser_mod.summarize_language_counts(tagged)
            if len(distinct_detected) > 1:
                lines = [f"These files appear to be in different languages:\n\n{breakdown}"]
                title = "Multiple Languages Detected"
            else:
                # Exactly one language was detected, but it doesn't match
                # the dropdown default - e.g. a single '[fr]' file sitting
                # among untagged ones while the dropdown is set to 'en'.
                # Wording matches this specific case rather than implying
                # several different languages were found, which would be
                # misleading here.
                lines = [
                    f"Detected a language tag that differs from your dropdown selection ({self._lang}):\n\n{breakdown}"
                ]
                title = "Detected Language Differs From Default"
            if untagged_paths:
                lines.append(
                    f"\n{len(untagged_paths)} file(s) had no language tag detected."
                )

            msg = QMessageBox(self)
            msg.setWindowTitle(title)
            msg.setText("\n".join(lines))
            # Short, fixed-width-safe labels - the earlier wording ("Use
            # detected languages", "Use dropdown default (en) for all")
            # depended on the dialog being wide enough to fit three
            # buttons' full sizeHint widths side by side. On Windows,
            # QMessageBox also reorders buttons by role rather than
            # addButton() call order (DestructiveRole lands in a fixed
            # native slot regardless of insertion order), so width alone
            # has to cover whatever order Windows picks - a wide spacer
            # was not reliably enough. Keeping every label under ~16
            # characters means three buttons fit comfortably regardless
            # of platform reordering, without needing a very wide dialog.
            use_detected_btn = msg.addButton("Use Detected", QMessageBox.YesRole)
            use_default_btn = msg.addButton(f"Use {self._lang} (default)", QMessageBox.NoRole)
            skip_btn = None
            if untagged_paths:
                skip_btn = msg.addButton("Skip Untagged", QMessageBox.DestructiveRole)
            layout = msg.layout()
            spacer = QSpacerItem(480, 0, QSizePolicy.Minimum, QSizePolicy.Expanding)
            layout.addItem(spacer, layout.rowCount(), 0, 1, layout.columnCount())
            msg.exec()

            clicked = msg.clickedButton()
            if clicked == skip_btn:
                files = [
                    f for f in files
                    if (f.get("norm_filepath") or parser_mod.norm_filepath(f["filepath"])) not in untagged_paths
                ]
                self._per_file_language_map = tagged
                if not files:
                    QMessageBox.information(
                        self, "Nothing left",
                        "All files were skipped (no language tag detected)."
                    )
                    self._show(self.group_config_screen)
                    return
            elif clicked == use_detected_btn:
                # Untagged files simply have no entry in this map, so they
                # fall back to self._lang downstream - same convention as
                # per_file_group_map/per_file_scanlator_map.
                self._per_file_language_map = tagged
            # else use_default_btn: leave _per_file_language_map empty,
            # every file uses self._lang exactly like before this feature.
        # --- END LANGUAGE DETECTION ---

        # --- SMART DB SKIPPING LOGIC ---
        # NOTE: still keyed on the single batch-wide self._lang for now.
        # With _per_file_language_map populated above, a mixed-language
        # batch's "already uploaded" check against this one target_key is
        # only correct for files actually using self._lang - files routed
        # to a different detected language via _per_file_language_map won't
        # be correctly matched against THEIR language's upload history yet.
        # This is the known follow-up (per-language-group dedup) - flagging
        # here rather than silently shipping a check that's subtly wrong
        # for mixed batches.
        self._target_key = config_mod.make_target_key(
            self._manga_id, self._upload_type, self._lang,
            self._group_config.get("group_ids") or [],
            self._group_config.get("scanlator_name")
        )

        already_uploaded = config_mod.db_uploaded_numbers(self._target_key)
        if already_uploaded:
            skip_candidates = [f for f in files if config_mod._chapter_number_key(f["number"]) in already_uploaded]
            if skip_candidates:
                msg = QMessageBox(self)
                msg.setWindowTitle("Already Uploaded")
                msg.setText(
                    f"{len(skip_candidates)} file(s) match numbers already recorded as uploaded to "
                    "this exact target (manga/type/language/group) from a previous run.\n\n"
                    "Do you want to skip them?"
                )
                yes_btn = msg.addButton("Skip already uploaded", QMessageBox.YesRole)
                msg.addButton("Keep all", QMessageBox.NoRole)
                msg.exec()

                if msg.clickedButton() == yes_btn:
                    skip_names = {f["filename"] for f in skip_candidates}
                    files = [f for f in files if f["filename"] not in skip_names]
                    if not files:
                        QMessageBox.information(self, "Nothing left", "All files in this batch were already recorded as uploaded.")
                        self._show(self.group_config_screen)
                        return
        # --- END DB LOGIC ---

        self._scanned_files = files

        if len(files) <= 3:
            self._load_title_review(files)
            return

        self.subset_picker_screen = SubsetPickerScreen(files, upload_type=self._upload_type)
        self.subset_picker_screen.selection_finished.connect(self._load_title_review)
        self.subset_picker_screen.back_requested.connect(
            lambda: self._show(self.group_config_screen)
        )
        self._show(self.subset_picker_screen)

    def _load_title_review(self, files):
        self._set_step(_STEP_REVIEW)
        # Seed each file's "language" field before it ever reaches the
        # table, the same way "groups"/"group_id" already arrive
        # pre-populated from the scan - lets TitleReviewScreen just read
        # f["language"] like it reads f["groups"], with no knowledge of
        # _per_file_language_map or the dropdown default needed on its
        # side. A file with a confirmed detection gets that; everything
        # else gets self._lang, exactly the "no entry = batch default"
        # convention _per_file_language_map already follows.
        for f in files:
            norm_path = f.get("norm_filepath") or parser_mod.norm_filepath(f["filepath"])
            f["language"] = self._per_file_language_map.get(norm_path) or self._lang

        # Reconcile f["groups"] with what Attribution actually resolved,
        # rather than leaving it as whatever was detected at SCAN time.
        # Those two can now disagree: "Apply one group to all files
        # (ignore detected tags)" on the group-config screen explicitly
        # discards per-file detection and emits an EMPTY
        # per_file_group_map, but until this fix f["groups"] here still
        # held the raw scan-time detection (e.g. "bl"/"pg"), so Review
        # kept displaying the ignored tag instead of the single group
        # that will actually be used - correct in the upload payload,
        # wrong on screen.
        #
        # An empty per_file_group_map means "everyone uploads under the
        # single group_name" - true whether that's because nothing was
        # ever mixed, or because the override explicitly discarded a real
        # mix - so f["groups"] gets cleared in both cases, deferring to
        # self._group_label exactly like a file with no detected groups
        # always has.
        #
        # A NON-empty per_file_group_map is the real-mixed case: it maps
        # filepath -> resolved numeric group IDs (see
        # resolve_per_file_group_ids), not names, so it must NOT be
        # copied into f["groups"] for display - that field's existing
        # scan-time values are already the correct human-readable names
        # (e.g. "GroupA"/"GroupB") and are left untouched here.
        gc = self._group_config or {}
        pf_group_map = gc.get("per_file_group_map") or {}
        pf_group_names = gc.get("per_file_group_names") or {}
        default_ids = gc.get("group_ids") or []
        default_name = gc.get("group_name")
        default_names = [default_name] if (default_name and default_name != "Multiple / Auto-Detected") else []

        for f in files:
            path = f.get("filepath", "")
            norm_p = f.get("norm_filepath") or (parser_mod.norm_filepath(path) if path else "")
            norm_path = os.path.normpath(path) if path else ""
            f_ids = (
                pf_group_map.get(path)
                or (pf_group_map.get(norm_p) if norm_p else None)
                or (pf_group_map.get(norm_path) if norm_path else None)
            )
            f_names = (
                pf_group_names.get(path)
                or (pf_group_names.get(norm_p) if norm_p else None)
                or (pf_group_names.get(norm_path) if norm_path else None)
            )

            if f_ids is not None:
                f["group_ids"] = list(f_ids) if isinstance(f_ids, (list, tuple)) else [f_ids]
                f["group_id"] = f["group_ids"][0] if f["group_ids"] else None
            elif not f.get("scanlator") and default_ids:
                f["group_ids"] = list(default_ids)
                f["group_id"] = default_ids[0]
            else:
                f["group_ids"] = []
                f["group_id"] = None

            if f_names is not None:
                f["groups"] = list(f_names) if isinstance(f_names, (list, tuple)) else [f_names]
            elif not f.get("scanlator") and default_names:
                f["groups"] = list(default_names)
            else:
                f["groups"] = []

        self.title_review_screen = TitleReviewScreen(
            files, upload_type=self._upload_type, group_label=self._group_label, session=self.session,
            preview_only=self._is_dry_run, manga_id=self._manga_id, language=self._lang
        )
        self.title_review_screen.review_finished.connect(self._on_review_finished)
        self.title_review_screen.back_requested.connect(self._back_to_subset_or_group)
        self._show(self.title_review_screen)

    def _back_to_subset_or_group(self):
        if self.subset_picker_screen is not None:
            self._show(self.subset_picker_screen)
        else:
            self._show(self.group_config_screen)

    def _on_review_finished(self, files):
        if self._is_dry_run:
            QMessageBox.information(self, "Dry Run Complete", "Dry run finished successfully. No files were uploaded.")
            self._restart_from_settings()
            return

        gc = self._group_config
        self._set_step(_STEP_UPLOAD)

        per_file_group_map, per_file_scanlator_map, per_file_language_map = parser_mod.build_upload_routing_maps(
            files, gc.get("per_file_group_map"), self._per_file_language_map
        )
        self._last_per_file_group_map = per_file_group_map
        self._last_per_file_scanlator_map = per_file_scanlator_map
        self._last_per_file_language_map = per_file_language_map

        stitch_spreads = getattr(self.title_review_screen, "stitch_spreads", False)
        auto_volume_cover = getattr(self.title_review_screen, "auto_volume_cover", False)

        self.upload_progress_screen = UploadProgressScreen(
            files, self.session, self._manga_id, gc.get("group_ids") or [], self._upload_type,
            self._lang, gc.get("scanlator_name"), self._threads,
            per_file_group_map=per_file_group_map,
            verify_timeout=self._verify_timeout,
            current_user_id=self.user_id,
            is_group_upload=gc.get("is_group_upload"),
            per_file_scanlator_map=per_file_scanlator_map,
            per_file_language_map=per_file_language_map,
            manga_title=self._manga_title,
            skip_verification=self._skip_verification,
            stitch_spreads=stitch_spreads,
            auto_volume_cover=auto_volume_cover,
        )
        self.upload_progress_screen.upload_finished.connect(self._on_upload_finished)
        self.upload_progress_screen.back_requested.connect(self._on_upload_back_requested)
        self._show(self.upload_progress_screen)

    def _on_upload_back_requested(self):
        self._set_step(_STEP_REVIEW)
        # title_review_screen is always set by this point - it's the only
        # path that leads into the upload screen - so this is the normal
        # case. The elif/else are defensive fallbacks only.
        if self.title_review_screen is not None:
            self._show(self.title_review_screen)
        elif self.subset_picker_screen is not None:
            self._show(self.subset_picker_screen)
        else:
            self._show(self.group_config_screen)

    def _on_upload_finished(self, failed_set, elapsed):
        self._set_step(_STEP_DONE)
        all_files = getattr(self.title_review_screen, "files", [])
        
        # --- DB LOGIC: Record successful uploads, grouped by each file's
        # own resolved language rather than one shared self._target_key.
        # f["language"] is seeded on every file back in _load_title_review
        # (per-file detected language, or self._lang as fallback) and can
        # be overwritten per-row in Review, so it's the actual language
        # that file uploaded under - a single batch-wide target_key would
        # silently mis-file any file whose language differs from self._lang.
        uploaded_files = [f for f in all_files if f["filename"] not in failed_set]
        if uploaded_files:
            by_lang = {}
            for f in uploaded_files:
                lang = f.get("language") or self._lang
                by_lang.setdefault(lang, []).append(f)
            for lang, group_files in by_lang.items():
                target_key = config_mod.make_target_key(
                    self._manga_id, self._upload_type, lang,
                    self._group_config.get("group_ids") or [],
                    self._group_config.get("scanlator_name"),
                )
                config_mod.db_record_uploaded(target_key, group_files)

            # Record rich series tracking metadata for Upload History
            meta = getattr(self, "_manga_details", None) or {}
            groups = []
            if self._group_label and self._group_label != "-":
                groups.append(self._group_label)
            if self._last_per_file_scanlator_map:
                for sc in self._last_per_file_scanlator_map.values():
                    if sc and sc not in groups:
                        groups.append(sc)

            config_mod.db_record_series(
                manga_id=self._manga_id,
                title=self._manga_title or meta.get("title"),
                alt_titles=meta.get("alt_titles") or ([meta.get("alt_title")] if meta.get("alt_title") else []),
                origin=meta.get("origin"),
                groups=groups,
                chapters_pushed=[f.get("number") for f in uploaded_files],
                username=self.username,
                cover_url=meta.get("cover_url"),
                mangadot_url=f"https://mangadot.net/manga/{self._manga_id}",
                user_uploads_url=f"https://mangadot.net/user/{self.username}/uploads?series={self._manga_id}" if self.username else None
            )
        # --- END DB LOGIC ---
        
        # 1. Initialize the UI strictly with data (no network session passed)
        self.summary_screen = SummaryScreen(
            self._manga_id, self._upload_type, self.username,
            self._group_label, all_files, failed_set, elapsed,
            per_file_group_map=self._last_per_file_group_map,
            per_file_scanlator_map=self._last_per_file_scanlator_map,
            is_group_upload=self._group_config.get("is_group_upload"),
            batch_group_ids=self._group_config.get("group_ids") or [],
        )
        self.summary_screen.done_requested.connect(self.close)
        self.summary_screen.upload_again_requested.connect(self._advance_to_manga_picker)
        self._show(self.summary_screen)

        # 2. Spin up the backend worker natively in the orchestrator
        self._summary_thread = QThread()
        self._summary_worker = _SummaryDetailsWorker(
            self.session, self._manga_id, self._upload_type, self.user_id
        )
        self._summary_worker.moveToThread(self._summary_thread)
        self._summary_thread.started.connect(self._summary_worker.run)
        
        # 3. Pipe the background data directly to the UI when it's done
        self._summary_worker.finished.connect(self.summary_screen.set_details)
        self._summary_worker.finished.connect(self._summary_thread.quit)
        self._summary_worker.finished.connect(self._summary_worker.deleteLater)
        self._summary_thread.finished.connect(self._summary_thread.deleteLater)
        self._summary_thread.start()


def _hide_child_consoles():
    """Frozen (PyInstaller --windowed) Windows builds only.

    A windowed exe has no console of its own, so every console program it
    spawns (pingo.exe, tasklist, taskkill, wmic, powershell, ...) gets a
    brand-new console window that flashes on screen. Rather than touching
    every subprocess call site, default CREATE_NO_WINDOW onto any Popen
    that doesn't already pass its own creationflags. The browser launches
    in auth.py pass CREATE_NEW_PROCESS_GROUP, so they are left alone.
    Does nothing when running from source, so dev runs are unchanged.
    """
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return
    import subprocess
    _orig_init = subprocess.Popen.__init__

    def _init(self, *args, **kwargs):
        if not kwargs.get("creationflags"):
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        _orig_init(self, *args, **kwargs)

    subprocess.Popen.__init__ = _init


def main():
    _hide_child_consoles()
    _install_fault_handler()
    _install_crash_handler()

    app = QApplication(sys.argv)
    app.setApplicationName("MangaDot Uploader")
    
    from PySide6.QtGui import QIcon
    icon_path = Path(__file__).resolve().parent / "mangadot_app" / "assets" / "favicon.ico"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    app.setStyle("Fusion")
    app.setPalette(theme.dark_palette())
    app.setFont(theme.base_font())
    app.setStyleSheet(theme.stylesheet())

    # Settings dialog stays on screen after Continue instead of closing -
    # it only auto-minimizes once the main uploader window actually has
    # focus, so it's still there (with proxy/optimizer choices intact) if
    # the user wants to reuse it, e.g. to launch a second instance for a
    # second manga.
    settings = StartupSettingsDialog(stay_open_on_accept=True)

    # Every confirmed use of the (reusable) settings dialog opens another
    # MainWindow - the whole point of stay_open_on_accept is letting the
    # user launch a second, independent upload window without re-entering
    # proxy/optimizer settings. Each one needs its own durable reference:
    # app._mangadot_main_window/_mangadot_focus_timer (singular) used to
    # be overwritten on every confirm, which dropped the ONLY strong
    # Python reference keeping the *previous* window (and its focus
    # QTimer) alive. Once that reference was gone, PySide6 was free to
    # garbage-collect the underlying C++ QMainWindow out from under a
    # still-running upload - any later signal delivery into it (a worker
    # thread's finished.emit(), a QTimer tick, anything) is a
    # use-after-free at the Qt/C++ level, which crashes hard with no
    # Python exception and therefore nothing for sys.excepthook or
    # crash.log to ever catch. Keeping a growing list instead means every
    # opened window - not just the most recent one - stays alive for as
    # long as the process runs, exactly matching how long each one's own
    # QThreads/timers might still legitimately be doing work.
    app._mangadot_windows = []
    app._mangadot_focus_timers = []

    def _on_settings_confirmed():
        if settings.debug_enabled:
            debugging.enable_debug_logging()

        window = MainWindow(settings)
        window.show()
        window.activateWindow()
        window.raise_()
        app._mangadot_windows.append(window)  # keep every window alive, not just the latest

        def _minimize_settings_once_main_focused():
            if window.isActiveWindow():
                settings.showMinimized()
                focus_timer.stop()

        focus_timer = QTimer(window)
        focus_timer.timeout.connect(_minimize_settings_once_main_focused)
        focus_timer.start(200)
        app._mangadot_focus_timers.append(focus_timer)  # keep every timer alive, not just the latest

    settings.settings_confirmed.connect(_on_settings_confirmed)

    def _on_settings_closed_without_confirm():
        # Cancel, or the window's close button, before any main window
        # exists yet - nothing left to do, so quit.
        if not app._mangadot_windows:
            app.quit()

    settings.finished.connect(_on_settings_closed_without_confirm)
    settings.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()