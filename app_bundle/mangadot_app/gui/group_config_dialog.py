"""Group/scanlator attribution"""
import os

from PySide6.QtCore import Qt, Signal, QObject
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QRadioButton, QButtonGroup, QListWidget, QListWidgetItem, QStackedWidget,
    QMessageBox, QSizePolicy, QCheckBox, QFrame, QScrollArea
)

from .. import parser as parser_mod
from .. import net
from . import thread_is_running, workers
from .widgets import Card, heading, section_label, hint_label, make_primary, make_flat_link, GlassBox, GroupPillWidget
from .theme import Color

_UNTAGGED_TARGET = "[Untagged files]"


def _search_group_queries(session, text):
    """Try each candidate query for `text` against the group search API,
    stopping at the first query that returns results. Shared by both the
    auto-detection and manual-search workers below."""
    results = []
    matched_query = None
    for q in parser_mod.group_search_queries(text):
        results = net.search_groups(q, session)
        if results:
            matched_query = q
            break
    return results, matched_query


class _GroupSearchWorker(QObject):
    finished = Signal(str, list, object)

    def __init__(self, session, name):
        super().__init__()
        self.session = session
        self.name = name

    def run(self):
        results, matched_query = _search_group_queries(self.session, self.name)
        self.finished.emit(self.name, results, matched_query)


class _ManualSearchWorker(QObject):
    finished = Signal(str, list)

    def __init__(self, session, query):
        super().__init__()
        self.session = session
        self.query = query

    def run(self):
        results, _matched_query = _search_group_queries(self.session, self.query)
        self.finished.emit(self.query, results)


class GroupConfigScreen(QWidget):
    config_finished = Signal(dict)
    back_requested = Signal()

    def __init__(self, session, directory, upload_type="chapter", parent=None):
        super().__init__(parent)
        self.session = session
        self.directory = directory
        self.upload_type = upload_type

        self._threads = []
        self._workers = [] 
        self._name_to_group = {}
        self._name_to_groups = {}
        self._per_file_names = {}
        self._per_file_group_map_result = {}
        self._pending_resolutions = 0
        self._resolved_group_ids = []
        self._fallback_groups = []
        self._resolved_group_name = None
        self._strip_bracket_groups = False
        self._detected_names = []
        self._untagged_files = []
        self._active_target_name = None
        self._auto_candidates = {}
        # True once the user explicitly chooses "apply one group to
        # everything" instead of resolving detected per-file tags. This is
        # a deliberate override, not a fallback for empty detection - it
        # exists specifically for the case detection DID find name(s) but
        # the user doesn't want per-file routing for them (e.g. the
        # detected tags aren't real group credits, or they just don't
        # want the hassle of resolving each one).
        self._force_single_group = False
        # Group subfolders (e.g. 'Solo Leveling/Asura Scans/'): their names are
        # detected like bracket tags. A folder that doesn't match a real group
        # can instead be credited to a scanlator name, or left out entirely.
        self._folder_names = set()
        self._folder_scanlator = {}   # folder name -> scanlator name
        self._skipped_folders = set()

        self._build_ui()
        self._detect_groups()

    def _build_ui(self):
        # Wrapped in a scroll area so this screen's content (which can
        # genuinely be tall - detected list + override box + search
        # results, all at once) never gets clipped by the taskbar or the
        # window's fixed height, regardless of how many groups/results
        # are showing. NOT setAlignment(Qt.AlignHCenter) - see
        # picker_screen.py's own scroll area for why that flag causes a
        # vertical content-jump glitch when combined with
        # setWidgetResizable(True).
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("background: transparent;")
        root_layout.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)

        outer = QVBoxLayout(content)
        outer.setContentsMargins(28, 20, 28, 24)
        # Base spacing kept tight (was 16px uniformly, which left a
        # visibly oversized gap under the heading - see screenshot) -
        # the heading->mode_card gap now relies on just this base value,
        # while the two gaps that benefit from more separation
        # (mode_card->page_stack, page_stack->bottom_row) get their own
        # explicit addSpacing() below instead of inheriting a value
        # that was really only right for one of the three gaps.
        outer.setSpacing(8)

        outer.addWidget(heading("Credit this upload", "Attribute the chapters to a scan group, or upload under your own name."))

        mode_card = Card()
        # This card holds exactly one row of radio buttons - Card's
        # default 24/20/24/20 margins are sized for cards with real
        # content (like the two group-detection panels below), and on a
        # single-row card that padding reads as a visible empty band
        # above and below the row rather than intentional breathing room.
        # Overriding just this instance's margins (not touching Card
        # itself, which would affect every other card in the app).
        mode_card.layout().setContentsMargins(24, 10, 24, 10)
        mode_row = QHBoxLayout()
        mode_row.setSpacing(16)
        self.group_radio = QRadioButton("Upload as a group")
        self.individual_radio = QRadioButton("Upload as an individual scanlator")
        self.group_radio.setChecked(True)
        mode_group = QButtonGroup(self)
        mode_group.addButton(self.group_radio)
        mode_group.addButton(self.individual_radio)
        self.group_radio.toggled.connect(self._on_mode_changed)
        mode_row.addWidget(self.group_radio)
        mode_row.addWidget(self.individual_radio)
        mode_row.addStretch(1)
        mode_card.addLayout(mode_row)
        outer.addWidget(mode_card)
        outer.addSpacing(8)

        self.page_stack = QStackedWidget()
        outer.addWidget(self.page_stack, 1)

        group_page = Card()
        # Trimmed top/bottom margins (Card's default is 20px each) -
        # this card already has to fit two full columns of detection/
        # search UI within the page_stack's share of a fixed-height
        # window, and the full default padding was part of what pushed
        # the Back/Continue row below the window's bottom edge.
        group_page.layout().setContentsMargins(24, 10, 24, 10)

        # --- Two-column layout: detected-groups/override (left) next to
        # search-and-resolve (right), 50/50 split. Previously everything
        # stacked in one column, which is what forced the taskbar-
        # crowding/clipping this screen was seeing - splitting the two
        # concerns side by side roughly halves the vertical space either
        # column needs.
        columns_row = QHBoxLayout()
        columns_row.setSpacing(20)

        # Both columns wrapped in GlassBox - the same reusable glowing
        # cyan-bordered/tinted panel already used elsewhere on this exact
        # screen (search_button_box, continue_box below) - previously
        # this whole two-column area was built from a hand-rolled inline
        # stylesheet on force_single_group_box only, with the rest of
        # each column sitting on bare, unstyled QWidget containers. Using
        # GlassBox for BOTH columns, with identical margins/spacing, is
        # what actually makes them read as a matched, symmetrical pair
        # instead of two differently-styled halves.
        left_container = GlassBox(
            tint_rgba="rgba(92, 225, 230, 10)",
            border_color=Color.ACCENT_SOFT_BORDER,
        )
        right_container = GlassBox(
            tint_rgba="rgba(92, 225, 230, 10)",
            border_color=Color.ACCENT_SOFT_BORDER,
        )

        left_col = QVBoxLayout(left_container)
        left_col.setContentsMargins(16, 16, 16, 16)
        left_col.setSpacing(12)
        right_col = QVBoxLayout(right_container)
        right_col.setContentsMargins(16, 16, 16, 16)
        right_col.setSpacing(12)

        self.detection_label = hint_label("Scanning filenames for group tags\u2026")
        self.detection_label.setWordWrap(True)
        left_col.addWidget(self.detection_label)

        # Own visually distinct box (not just addWidget'd into the same
        # flat stack as detection_label/detected_list) so it reads as a
        # deliberate control the user should notice and decide on, rather
        # than blending into the detection output above it. Hidden until
        # _detect_groups() actually finds name(s) - offers an explicit
        # way OUT of per-file detection/resolution, for cases where the
        # detected tag(s) aren't real group credits, or the user just
        # wants one group applied to every file regardless. Checking it
        # disables the detected-names list below and makes the manual
        # search box the sole source of truth at Continue time.
        self.force_single_group_box = QFrame()
        self.force_single_group_box.setStyleSheet(
            f"QFrame {{ background-color: {Color.ACCENT_SOFT}; "
            f"border: 1px solid {Color.ACCENT_SOFT_BORDER}; border-radius: 8px; }}"
        )
        force_single_group_layout = QVBoxLayout(self.force_single_group_box)
        force_single_group_layout.setContentsMargins(14, 10, 14, 10)
        self.force_single_group_checkbox = QCheckBox(
            "Apply one group to all files (ignore detected tags)"
        )
        self.force_single_group_checkbox.setProperty("wordWrap", True)
        force_single_group_layout.addWidget(self.force_single_group_checkbox)
        self.force_single_group_box.setVisible(False)
        self.force_single_group_checkbox.toggled.connect(self._on_force_single_group_toggled)
        left_col.addWidget(self.force_single_group_box)

        self.detected_list = QListWidget()
        # Kept modest rather than tall - this list sits inside a
        # fixed-height window alongside the mode row, search column, and
        # Back/Continue row, and a tall minimum here was what pushed
        # those buttons below the window's bottom edge. It still shows
        # several rows at once and scrolls internally beyond that.
        self.detected_list.setMinimumHeight(120)
        self.detected_list.setStyleSheet(
            f"QListWidget {{ background-color: {Color.BG_APP}; "
            f"border: 1px solid {Color.BORDER}; border-radius: 9px; }}"
            f"QListWidget::item {{ padding: 3px 6px; }}"
            f"QListWidget::item:hover {{ background-color: {Color.ACCENT_SOFT}; }}"
        )
        self.detected_list.itemClicked.connect(self._on_detected_name_clicked)
        left_col.addWidget(self.detected_list, 1)

        # Shown only while a group *folder* is the active target.
        self.folder_actions = QWidget()
        folder_actions_layout = QHBoxLayout(self.folder_actions)
        folder_actions_layout.setContentsMargins(0, 2, 0, 0)
        folder_actions_layout.setSpacing(6)
        self.folder_scanlator_btn = QPushButton("Credit as scanlator")
        self.folder_scanlator_btn.setToolTip("Upload this folder's files credited to a scanlator name instead of a group")
        self.folder_scanlator_btn.clicked.connect(self._on_folder_as_scanlator)
        self.folder_skip_btn = QPushButton("Skip folder")
        self.folder_skip_btn.setToolTip("Leave this folder's files out of the upload")
        self.folder_skip_btn.clicked.connect(self._on_folder_skip)
        self.folder_reset_btn = QPushButton("Reset")
        self.folder_reset_btn.setToolTip("Undo the scanlator/skip choice for this folder")
        self.folder_reset_btn.clicked.connect(self._on_folder_reset)
        for b in (self.folder_scanlator_btn, self.folder_skip_btn, self.folder_reset_btn):
            b.setCursor(Qt.PointingHandCursor)
            folder_actions_layout.addWidget(b)
        folder_actions_layout.addStretch(1)
        self.folder_actions.setVisible(False)
        left_col.addWidget(self.folder_actions)
        left_col.addStretch(0)

        self.search_target_label = QLabel("")
        self.search_target_label.setWordWrap(True)
        self.search_target_label.setProperty("role", "muted")
        right_col.addWidget(self.search_target_label)

        self.assigned_pills_label = section_label("Assigned group(s):")
        right_col.addWidget(self.assigned_pills_label)

        self.pills_container = QWidget()
        self.pills_layout = QHBoxLayout(self.pills_container)
        self.pills_layout.setContentsMargins(6, 4, 6, 4)
        self.pills_layout.setSpacing(6)
        self.pills_layout.setAlignment(Qt.AlignLeft)

        self.pills_scroll = QScrollArea()
        self.pills_scroll.setWidgetResizable(True)
        self.pills_scroll.setFrameShape(QFrame.NoFrame)
        self.pills_scroll.setStyleSheet(
            f"background-color: {Color.BG_APP}; border: 1px solid {Color.BORDER}; border-radius: 8px;"
        )
        self.pills_scroll.setFixedHeight(46)
        self.pills_scroll.setWidget(self.pills_container)
        right_col.addWidget(self.pills_scroll)

        right_col.addWidget(section_label("Search MangaDot's group directory"))
        search_row = QHBoxLayout()
        search_row.setSpacing(8)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search group by name, or enter numeric ID directly")
        self.search_input.returnPressed.connect(self._on_manual_search)
        self.search_input.setStyleSheet(
            f"QLineEdit {{ background-color: {Color.BG_APP}; "
            f"border: 1px solid {Color.ACCENT_SOFT_BORDER}; border-radius: 6px; padding: 6px 8px; }}"
            f"QLineEdit:focus {{ border: 1px solid {Color.ACCENT}; }}"
        )
        self.search_button = make_flat_link(QPushButton("Search"), color=Color.ACCENT, hover_color=Color.ACCENT_HOVER, bold=True)
        self.search_button.clicked.connect(self._on_manual_search)
        search_button_box = GlassBox(
            tint_rgba="rgba(92, 225, 230, 18)",
            border_color=Color.ACCENT_SOFT_BORDER,
        )
        search_button_box.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        search_button_box_layout = QHBoxLayout(search_button_box)
        search_button_box_layout.setContentsMargins(16, 4, 16, 4)
        search_button_box_layout.addWidget(self.search_button)
        search_row.addWidget(self.search_input, 1)
        search_row.addWidget(search_button_box)
        right_col.addLayout(search_row)

        self.search_results_list = QListWidget()
        self.search_results_list.itemDoubleClicked.connect(self._on_search_result_picked)
        self.search_results_list.setStyleSheet(
            f"QListWidget {{ background-color: {Color.BG_APP}; "
            f"border: 1px solid {Color.BORDER}; border-radius: 9px; }}"
        )
        right_col.addWidget(self.search_results_list, 1)

        selected_row = QHBoxLayout()
        self.selected_group_label = QLabel("No group selected yet.")
        self.selected_group_label.setWordWrap(True)
        self.selected_group_label.setProperty("role", "muted")
        selected_row.addWidget(self.selected_group_label, 1)

        self.clear_selected_btn = QPushButton("Clear")
        self.clear_selected_btn.setCursor(Qt.PointingHandCursor)
        self.clear_selected_btn.setStyleSheet(
            f"color: {Color.TEXT_MUTED}; background: transparent; border: none; font-size: 11px; padding: 2px 6px;"
        )
        self.clear_selected_btn.setVisible(False)
        self.clear_selected_btn.clicked.connect(self._on_clear_fallback_groups)
        selected_row.addWidget(self.clear_selected_btn)
        right_col.addLayout(selected_row)

        # Equal stretch factor (1, 1) on identically-styled GlassBox
        # containers is what makes the two columns align perfectly side
        # by side and stay the same width as each other regardless of
        # window size.
        columns_row.addWidget(left_container, 1)
        columns_row.addWidget(right_container, 1)

        group_page.addLayout(columns_row)

        self.page_stack.addWidget(group_page)

        individual_page = Card()
        individual_page.addWidget(section_label("Scanlator credit"))
        individual_page.addWidget(hint_label("Shown publicly as the uploader credit on every chapter."))
        self.scanlator_input = QLineEdit()
        self.scanlator_input.setPlaceholderText("Your scanlator / uploader name")
        individual_page.addWidget(self.scanlator_input)
        individual_page.layout().addStretch(1)
        self.page_stack.addWidget(individual_page)

        outer.addSpacing(8)
        bottom_row = QHBoxLayout()
        self.back_button = QPushButton("Back")
        self.back_button.clicked.connect(self.back_requested.emit)
        bottom_row.addWidget(self.back_button)
        bottom_row.addStretch(1)
        continue_box = GlassBox(
            tint_rgba="rgba(92, 225, 230, 18)",
            border_color=Color.ACCENT_SOFT_BORDER,
        )
        continue_box_layout = QHBoxLayout(continue_box)
        continue_box_layout.setContentsMargins(14, 6, 14, 6)
        self.continue_button = make_flat_link(QPushButton("Continue"), bold=True)
        self.continue_button.clicked.connect(self._on_continue)
        continue_box_layout.addWidget(self.continue_button)
        bottom_row.addWidget(continue_box)
        outer.addLayout(bottom_row)

    def _mark_group_selected(self, name):
        self.selected_group_label.setText(f"\u2705 Selected group: {name}")
        self.selected_group_label.setProperty("role", "success")
        self.selected_group_label.style().unpolish(self.selected_group_label)
        self.selected_group_label.style().polish(self.selected_group_label)

    def _on_mode_changed(self, checked):
        self.page_stack.setCurrentIndex(0 if self.group_radio.isChecked() else 1)

    def _detect_groups(self):
        names, per_file = parser_mod.detect_groups_from_filenames(self.directory, self.upload_type)
        self._per_file_names = per_file
        folder_names = parser_mod.group_folder_names(self.directory) if self.upload_type != "folder" else []
        self._folder_names = set(folder_names)
        # Folders first (in folder order), then bracket tags.
        self._detected_names = folder_names + sorted(n for n in names if n not in self._folder_names)
        names = list(self._detected_names)

        if self.upload_type == "folder":
            try:
                all_files = [
                    parser_mod.norm_filepath(os.path.join(self.directory, f))
                    for f in os.listdir(self.directory)
                    if os.path.isdir(os.path.join(self.directory, f))
                ]
            except OSError:
                all_files = []
        else:
            # Includes archives inside group/language subfolders.
            all_files = parser_mod.list_upload_archives(self.directory)

        norm_tagged = {parser_mod.norm_filepath(p) for p in per_file.keys()}
        self._untagged_files = [f for f in all_files if parser_mod.norm_filepath(f) not in norm_tagged]

        if not names:
            self.detection_label.setText(
                "No group tags detected in filenames. Search for your group below, "
                "or switch to individual scanlator mode."
            )
            return

        if self._folder_names:
            untagged_count = len(self._untagged_files)
            loose = f" (+ {untagged_count} file(s) outside them)" if untagged_count else ""
            self.detection_label.setText(
                f"Detected {len(self._folder_names)} group folder(s): {', '.join(folder_names)}{loose}. "
                f"Click a folder to fix its match, credit it to a scanlator, or skip it."
            )
            self.force_single_group_box.setVisible(True)
            for name in names:
                item = QListWidgetItem()
                item.setData(Qt.UserRole, name)
                self.detected_list.addItem(item)
                self._refresh_detected_list_item(name)
            if self._untagged_files:
                item = QListWidgetItem()
                item.setData(Qt.UserRole, _UNTAGGED_TARGET)
                self.detected_list.addItem(item)
                self._refresh_detected_list_item(_UNTAGGED_TARGET)
            self._update_search_target_label()
            self._pending_resolutions = len(names)
            workers.prune_finished(self._threads, self._workers)
            for name in names:
                worker = _GroupSearchWorker(self.session, name)
                thread, worker = workers.run_worker(worker, on_finished=self._on_group_resolved)
                self._threads.append(thread)
                self._workers.append(worker)
            return

        is_mixed = parser_mod.is_groups_mixed(per_file) or bool(self._untagged_files)
        untagged_count = len(self._untagged_files)
        untagged_hint = f" (+ {untagged_count} untagged chapters)" if untagged_count else ""
        if is_mixed:
            unique_sets = parser_mod.distinct_group_sets(per_file)
            # One line instead of a bullet per distinct grouping - each
            # grouping (e.g. a file tagged with more than one group at
            # once) still keeps its names joined by "+", but the groupings
            # themselves now sit inline next to the intro text separated
            # by commas, rather than stacked vertically below it.
            groupings_text = ", ".join("+".join(sorted(gnames)) for gnames in unique_sets)
            if groupings_text:
                self.detection_label.setText(f"Detected mixed groups across chapters: {groupings_text}{untagged_hint}")
            else:
                self.detection_label.setText(f"Detected group(s) from filenames: {', '.join(names)}{untagged_hint}  (resolving…)")
        else:
            self.detection_label.setText(f"Detected group(s) from filenames: {', '.join(names)}{untagged_hint}  (resolving…)")

        # Offer the escape hatch as soon as ANY tag(s) were detected - not
        # just for the mixed case. A single clean detection can still be
        # wrong (e.g. a two-letter tag that isn't actually a group), so
        # the user should be able to override before search-resolution
        # even starts, not only after getting stuck partway through it.
        self.force_single_group_box.setVisible(True)

        for name in names:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, name)
            self.detected_list.addItem(item)
            self._refresh_detected_list_item(name)

        if self._untagged_files:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, _UNTAGGED_TARGET)
            self.detected_list.addItem(item)
            self._refresh_detected_list_item(_UNTAGGED_TARGET)

        self._update_search_target_label()

        self._pending_resolutions = len(names)
        workers.prune_finished(self._threads, self._workers)
        for name in names:
            worker = _GroupSearchWorker(self.session, name)
            thread, worker = workers.run_worker(worker, on_finished=self._on_group_resolved)
            self._threads.append(thread)
            self._workers.append(worker)

    def _detected_list_item_for(self, name):
        for i in range(self.detected_list.count()):
            item = self.detected_list.item(i)
            if item.data(Qt.UserRole) == name:
                return item
        return None

    def _refresh_detected_list_item(self, name):
        """Updates one row in the detected-names list to show its current
        resolution status and whether it's the active search target -
        called whenever a name resolves, or whenever the active target
        changes, so the list always reflects reality rather than the
        static plain-text-only list this used to be."""
        item = self._detected_list_item_for(name)
        if item is None:
            return
        if name == _UNTAGGED_TARGET:
            count = len(self._untagged_files)
            if self._force_single_group:
                status = f"\u2014 Untagged files ({count} chapters)  (ignored \u2014 one group applies to all files)"
                item.setText(status)
                item.setForeground(QColor(Color.TEXT_MUTED))
                return
            if _UNTAGGED_TARGET in self._name_to_groups and self._name_to_groups[_UNTAGGED_TARGET]:
                groups = self._name_to_groups[_UNTAGGED_TARGET]
                names_str = " + ".join(g.get("name") or f"ID {g.get('id')}" for g in groups)
                status = f"✓ Untagged files ({count})  →  {names_str}"
            else:
                status = f"⚠ Untagged files ({count} chapters)  (no group assigned — click to select)"
            if name == self._active_target_name:
                status += "   ← editing this"
            item.setText(status)
            item.setForeground(QColor(Color.TEXT_PRIMARY))
            return

        folder_prefix = "\U0001F4C1 " if name in self._folder_names else ""
        if name in self._skipped_folders and not self._force_single_group:
            item.setText(f"\u2014 {folder_prefix}{name}  (skipped \u2014 not uploaded)"
                         + ("   \u2190 editing this" if name == self._active_target_name else ""))
            item.setForeground(QColor(Color.TEXT_MUTED))
            return
        if name in self._folder_scanlator and not self._force_single_group:
            item.setText(f"\u2713 {folder_prefix}{name}  \u2192  scanlator '{self._folder_scanlator[name]}'"
                         + ("   \u2190 editing this" if name == self._active_target_name else ""))
            item.setForeground(QColor(Color.TEXT_PRIMARY))
            return

        if self._force_single_group:
            # Background resolution keeps running even while the override
            # is active (there's no cheap way to cancel an in-flight
            # search worker), but showing "searching..."/"unresolved" for
            # a tag the user has explicitly said to ignore is actively
            # misleading - it looks like something is still pending or
            # broken, when actually nothing about it matters anymore.
            status = f"\u2014 {name}  (ignored \u2014 one group applies to all files)"
            item.setText(status)
            item.setForeground(QColor(Color.TEXT_MUTED))
            return
        if name in self._name_to_groups and self._name_to_groups[name]:
            groups = self._name_to_groups[name]
            names_str = " + ".join(g.get("name") or f"ID {g.get('id')}" for g in groups)
            status = f"✓ {folder_prefix}{name}  →  {names_str}"
        elif self._pending_resolutions > 0 and (name not in self._name_to_groups or not self._name_to_groups[name]):
            status = f"⏳ {folder_prefix}{name}  (searching…)"
        elif folder_prefix:
            status = f"⚠ {folder_prefix}{name}  (no matching group — click to search, credit as scanlator, or skip)"
        else:
            status = f"⚠ {name}  (unresolved — click to search a match)"
        if name == self._active_target_name:
            status += "   ← editing this"
        item.setText(status)
        item.setForeground(QColor(Color.TEXT_PRIMARY))

    def _refresh_assigned_pills(self):
        if not hasattr(self, "pills_layout"):
            return
        while self.pills_layout.count():
            item = self.pills_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        target_name = self._active_target_name
        groups = self._name_to_groups.get(target_name, []) if target_name else self._fallback_groups

        if not groups:
            empty_lbl = QLabel("No groups assigned yet — search or enter ID below to add")
            empty_lbl.setStyleSheet(f"color: {Color.TEXT_MUTED}; font-size: 11px; font-style: italic; background: transparent;")
            self.pills_layout.addWidget(empty_lbl)
        else:
            for g in groups:
                pill = GroupPillWidget(g, removable=True, parent=self)
                pill.removed.connect(self._on_remove_group_pill)
                self.pills_layout.addWidget(pill)

        self.pills_layout.addStretch(1)

    def _on_remove_group_pill(self, group):
        target_name = self._active_target_name
        gid = group.get("id")
        gname = (group.get("name") or "").strip().lower()

        if target_name:
            current_list = self._name_to_groups.get(target_name, [])
            self._name_to_groups[target_name] = [
                g for g in current_list
                if not (gid is not None and g.get("id") == gid) and not (gname and (g.get("name") or "").strip().lower() == gname)
            ]
            if not self._name_to_groups[target_name]:
                self._name_to_groups.pop(target_name, None)
                self._name_to_group.pop(target_name, None)
            else:
                self._name_to_group[target_name] = self._name_to_groups[target_name][0]
            self._refresh_detected_list_item(target_name)
            self._finalize_auto_detection()
        else:
            self._fallback_groups = [
                g for g in self._fallback_groups
                if not (gid is not None and g.get("id") == gid) and not (gname and (g.get("name") or "").strip().lower() == gname)
            ]
            self._resolved_group_ids = [g["id"] for g in self._fallback_groups if g.get("id") is not None]
            self._resolved_group_name = ", ".join(g["name"] for g in self._fallback_groups if g.get("name"))
            if self._resolved_group_name:
                self._mark_group_selected(self._resolved_group_name)
            else:
                self.selected_group_label.setText("No group selected yet.")
                self.selected_group_label.setProperty("role", "muted")
                self.selected_group_label.style().unpolish(self.selected_group_label)
                self.selected_group_label.style().polish(self.selected_group_label)

        self._refresh_assigned_pills()

    def _update_folder_actions(self):
        name = self._active_target_name
        is_folder = bool(name) and name in self._folder_names and not self._force_single_group
        self.folder_actions.setVisible(is_folder)
        if is_folder:
            customized = name in self._folder_scanlator or name in self._skipped_folders
            self.folder_reset_btn.setVisible(customized)

    def _on_folder_as_scanlator(self):
        from PySide6.QtWidgets import QInputDialog
        name = self._active_target_name
        if not name or name not in self._folder_names:
            return
        text, ok = QInputDialog.getText(
            self, "Credit folder to a scanlator",
            f"Scanlator name for the files in '{name}':",
            text=self._folder_scanlator.get(name) or parser_mod.split_group_folder_name(name)[0] or name,
        )
        text = (text or "").strip()
        if not ok or not text:
            return
        self._folder_scanlator[name] = text
        self._skipped_folders.discard(name)
        self._name_to_groups.pop(name, None)
        self._name_to_group.pop(name, None)
        self._refresh_detected_list_item(name)
        self._finalize_auto_detection()
        self._update_folder_actions()
        self._refresh_assigned_pills()

    def _on_folder_skip(self):
        name = self._active_target_name
        if not name or name not in self._folder_names:
            return
        self._skipped_folders.add(name)
        self._folder_scanlator.pop(name, None)
        self._name_to_groups.pop(name, None)
        self._name_to_group.pop(name, None)
        self._refresh_detected_list_item(name)
        self._finalize_auto_detection()
        self._update_folder_actions()
        self._refresh_assigned_pills()

    def _on_folder_reset(self):
        name = self._active_target_name
        if not name:
            return
        self._skipped_folders.discard(name)
        self._folder_scanlator.pop(name, None)
        self._refresh_detected_list_item(name)
        self._update_folder_actions()

    def _folder_paths(self, folder_name):
        # Only files physically inside the folder - a loose top-level file
        # tagged '[Official]' is not part of the 'Official/' folder.
        folder_dir = parser_mod.norm_filepath(os.path.join(self.directory, folder_name))
        return [p for p, names in self._per_file_names.items()
                if names == [folder_name] and os.path.dirname(p) == folder_dir]

    def _update_search_target_label(self):
        self._update_folder_actions()
        if self._active_target_name == _UNTAGGED_TARGET:
            count = len(self._untagged_files)
            self.search_target_label.setText(
                f"Target: Untagged files ({count} chapters). Search or enter ID below to assign group."
            )
            self.search_target_label.setStyleSheet(f"color: {Color.ACCENT}; font-weight: 500;")
            if hasattr(self, "assigned_pills_label"):
                self.assigned_pills_label.setText(f"Assigned group(s) for untagged files ({count} chapters):")
        elif self._active_target_name:
            self.search_target_label.setText(
                f"Tag: '{self._active_target_name}'. Double-click a candidate or search/enter ID below to add groups."
            )
            self.search_target_label.setStyleSheet(f"color: {Color.ACCENT}; font-weight: 500;")
            if hasattr(self, "assigned_pills_label"):
                self.assigned_pills_label.setText(f"Assigned group(s) for '{self._active_target_name}':")
        else:
            self.search_target_label.setText(
                "No specific tag selected — search below to pick a fallback group "
                "for the whole upload, or click an unresolved tag on the left."
            )
            self.search_target_label.setStyleSheet(f"color: {Color.TEXT_SECONDARY};")
            if hasattr(self, "assigned_pills_label"):
                self.assigned_pills_label.setText("Assigned fallback group(s) for all files:")
        self._refresh_assigned_pills()

    def _on_detected_name_clicked(self, item):
        name = item.data(Qt.UserRole)
        if not name:
            return
        self._active_target_name = name
        self._update_search_target_label()
        self._render_search_results_for_active_target()
        self.search_input.setFocus()

    def _on_force_single_group_toggled(self, checked):
        self._force_single_group = checked
        # Detected-name targeting only makes sense while per-file
        # resolution is still in play - disable clicking a specific name
        # while the override is on, so every search box result falls
        # through _apply_group_choice_to_target's "no active target"
        # branch and sets ONE fallback group for the whole batch, exactly
        # like it already does today when detection found nothing at all.
        self.detected_list.setEnabled(not checked)
        if checked:
            self._active_target_name = None
            self.search_target_label.setText(
                "Detected tag(s) will be ignored. Search below to pick ONE group "
                "for every file in this upload."
            )
            self.search_target_label.setStyleSheet(f"color: {Color.ACCENT};")
        else:
            # Re-arm targeting at whatever's still unresolved, same
            # starting point _finalize_auto_detection would have left it
            # at, so turning the checkbox back off doesn't strand the
            # user with a stale/blank target.
            next_unresolved = next(
                (n for n in self._detected_names if n not in self._name_to_group), None
            )
            if next_unresolved is None and self._untagged_files and _UNTAGGED_TARGET not in self._name_to_groups:
                next_unresolved = _UNTAGGED_TARGET
            self._active_target_name = next_unresolved
            self._update_search_target_label()
        # Repaint every detected-name row immediately so stale "searching
        # ..."/"unresolved" text from before the toggle doesn't linger
        # until the next background event happens to touch that row -
        # without this, checking the box left rows showing "searching..."
        # indefinitely even though nothing about them still matters.
        all_targets = list(self._detected_names)
        if self._untagged_files:
            all_targets.append(_UNTAGGED_TARGET)
        for name in all_targets:
            self._refresh_detected_list_item(name)
        self._render_search_results_for_active_target()

    def _on_group_resolved(self, name, results, matched_query):
        self._pending_resolutions -= 1

        match = parser_mod.auto_match_group(name, results, matched_query=matched_query)
        if match:
            self._name_to_group[name] = match
            if name not in self._name_to_groups:
                self._name_to_groups[name] = [match]
        else:
            # Stash the candidates (possibly empty) against this specific
            # name instead of writing them straight into the shared
            # search_results_list.
            self._auto_candidates[name] = results

        self._refresh_detected_list_item(name)

        if self._pending_resolutions == 0:
            self._finalize_auto_detection()
            if self._active_target_name is None and not self._force_single_group:
                first_unresolved = next(
                    (n for n in self._detected_names if n not in self._name_to_groups or not self._name_to_groups[n]), None
                )
                if first_unresolved is None and self._untagged_files and _UNTAGGED_TARGET not in self._name_to_groups:
                    first_unresolved = _UNTAGGED_TARGET
                if first_unresolved:
                    self._active_target_name = first_unresolved
                    self._update_search_target_label()
                    self._render_search_results_for_active_target()

    def _render_search_results_for_active_target(self):
        """Shows the auto-search candidates (if any) for whichever name
        is currently the active search target."""
        self.search_results_list.clear()
        self._refresh_assigned_pills()
        name = self._active_target_name
        if not name:
            return

        if name == _UNTAGGED_TARGET:
            count = len(self._untagged_files)
            if _UNTAGGED_TARGET in self._name_to_groups and self._name_to_groups[_UNTAGGED_TARGET]:
                current_names = ", ".join(g.get("name") or str(g.get("id")) for g in self._name_to_groups[_UNTAGGED_TARGET])
                self.search_results_list.addItem(
                    QListWidgetItem(f"Assigned for untagged files ({count} chapters): {current_names}")
                )
                self.search_results_list.addItem(
                    QListWidgetItem("Search below or enter numeric ID above to add joint group(s).")
                )
            else:
                self.search_results_list.addItem(
                    QListWidgetItem(f"Untagged files ({count} chapters): search below or enter numeric ID above to assign a group.")
                )
            return

        candidates = self._auto_candidates.get(name) or []
        if candidates:
            self.search_results_list.addItem(QListWidgetItem(f"— Candidates for '{name}' (double-click to add): —"))
            for g in candidates:
                item = QListWidgetItem(f"{g['name']} (ID: {g['id']})")
                item.setData(Qt.UserRole, (name, g))
                self.search_results_list.addItem(item)
        elif name in self._auto_candidates:
            self.search_results_list.addItem(
                QListWidgetItem(f"No auto-match found for '{name}' — search below or enter numeric ID above.")
            )
        elif name in self._name_to_groups and self._name_to_groups[name]:
            current_names = ", ".join(g.get("name") or str(g.get("id")) for g in self._name_to_groups[name])
            self.search_results_list.addItem(
                QListWidgetItem(f"Assigned: {current_names}")
            )
            self.search_results_list.addItem(
                QListWidgetItem("Search below or enter numeric ID above to add joint group(s).")
            )

    def _finalize_auto_detection(self):
        if not self._name_to_groups and not self._name_to_group:
            return  
        if self._force_single_group:
            return

        is_mixed = parser_mod.is_groups_mixed(self._per_file_names) or bool(self._untagged_files)

        if is_mixed:
            self._per_file_group_map_result = parser_mod.resolve_per_file_group_ids(
                self._per_file_names, self._name_to_groups
            )
            self._strip_bracket_groups = True
            
            # Explicitly set mixed name for UI
            self._resolved_group_name = "Multiple / Auto-Detected"
            summary_parts = []
            for n, g_list in self._name_to_groups.items():
                if n == _UNTAGGED_TARGET:
                    continue
                g_str = " + ".join(g.get("name") or str(g.get("id")) for g in g_list)
                summary_parts.append(f"{n} → {g_str}")
            if self._untagged_files and _UNTAGGED_TARGET in self._name_to_groups and self._name_to_groups[_UNTAGGED_TARGET]:
                u_str = " + ".join(g.get("name") or str(g.get("id")) for g in self._name_to_groups[_UNTAGGED_TARGET])
                summary_parts.append(f"Untagged ({len(self._untagged_files)}) → {u_str}")
            self.selected_group_label.setText("Auto-resolved: " + ", ".join(summary_parts))
        else:
            all_ids = []
            all_names = []
            for g_list in self._name_to_groups.values():
                for g in g_list:
                    if g.get("id") is not None and g["id"] not in all_ids:
                        all_ids.append(g["id"])
                    if g.get("name") and g["name"] not in all_names:
                        all_names.append(g["name"])
            self._resolved_group_ids = all_ids
            self._resolved_group_name = ", ".join(all_names)
            self._strip_bracket_groups = True
            self._mark_group_selected(self._resolved_group_name)

    def _on_manual_search(self):
        query = self.search_input.text().strip()
        if not query:
            return
        if query.isdigit():
            self._apply_group_choice_to_target({"id": int(query), "name": f"ID: {query}"})
            return

        # Capture which name this search is actually for, right now -
        # not whatever happens to be active later when the (async)
        # result arrives. See _on_manual_search_finished for why this
        # matters.
        search_target = self._active_target_name

        self.search_results_list.clear()
        self.search_results_list.addItem(QListWidgetItem(f"Searching for '{query}'…"))
        self.search_button.setEnabled(False)

        worker = _ManualSearchWorker(self.session, query)
        workers.prune_finished(self._threads, self._workers)
        thread, worker = workers.run_worker(
            worker,
            on_finished=lambda q, results: self._on_manual_search_finished(q, results, search_target),
        )
        self._threads.append(thread)
        self._workers.append(worker)

    def _on_manual_search_finished(self, query, results, search_target):
        """search_target is whichever name was active when this search
        was launched (see _on_manual_search) - deliberately NOT
        self._active_target_name, which may have changed while the
        search was in flight (the user clicked a different detected
        name, or picked a match for another one) while waiting on this
        one. Without pinning it, results for e.g. 'LostNerevarine-Empire'
        could silently render as if they were for whatever name the user
        had since clicked on instead - or worse, get attributed to that
        other name if picked, resolving the wrong tag.
        """
        self.search_button.setEnabled(True)

        if search_target != self._active_target_name:
            # The user moved on to a different name while this search
            # was running. Don't touch the results list they're
            # currently looking at (it belongs to the new active
            # target) - but don't just silently drop this search either,
            # since as far as the user's concerned they asked for it and
            # deserve to see it happened. Recording it here means
            # switching back to search_target re-shows these results
            # instead of "no exact match" / an empty list.
            if results:
                self._auto_candidates[search_target] = results
                self._refresh_detected_list_item(search_target)
            return

        self.search_results_list.clear()
        if not results:
            msg = f"No groups found for '{query}'. Try a different spelling, or enter the group's numeric ID above instead."
            self.search_results_list.addItem(QListWidgetItem(msg))
            return
        if search_target:
            self.search_results_list.addItem(
                QListWidgetItem(f"— Pick a match for '{search_target}': —")
            )
        for g in results:
            item = QListWidgetItem(f"{g['name']} (ID: {g['id']})")
            item.setData(Qt.UserRole, (search_target, g))
            self.search_results_list.addItem(item)

    def _on_search_result_picked(self, item):
        data = item.data(Qt.UserRole)
        if not data:
            return
        target_name, group = data
        self._apply_group_choice_to_target(group, target_name=target_name)

    def _apply_group_choice_to_target(self, group, target_name=None):
        """Records `group` as the resolution for `target_name` if given
        (or self._active_target_name if not), or as the whole-batch
        fallback group if there's genuinely no active target.

        This is the single place that decides "does this pick resolve
        one specific detected bracket-tag name, or does it set the
        uniform group for every file with no per-tag match" - previously
        that decision lived duplicated (and inconsistently) across the
        numeric-ID shortcut and the search-result-click handler, and
        neither of them ever considered which name the user had actually
        selected to search for, which is why picking a manual search
        result never resolved the specific unresolved tag it was meant
        to.
        """
        name = target_name if target_name is not None else self._active_target_name
        if name:
            self._skipped_folders.discard(name)
            self._folder_scanlator.pop(name, None)
            if name not in self._name_to_groups:
                self._name_to_groups[name] = []
            gid = group.get("id")
            gname = (group.get("name") or "").strip().lower()
            if not any((gid is not None and g.get("id") == gid) or (gname and (g.get("name") or "").strip().lower() == gname) for g in self._name_to_groups[name]):
                self._name_to_groups[name].append(group)
            self._name_to_group[name] = self._name_to_groups[name][0]
            self._refresh_detected_list_item(name)
            self._finalize_auto_detection()
            self._refresh_assigned_pills()
            self.search_input.clear()
        else:
            gid = group.get("id")
            gname = (group.get("name") or "").strip().lower()
            if not any((gid is not None and g.get("id") == gid) or (gname and (g.get("name") or "").strip().lower() == gname) for g in self._fallback_groups):
                self._fallback_groups.append(group)
            self._resolved_group_ids = [g["id"] for g in self._fallback_groups if g.get("id") is not None]
            self._resolved_group_name = ", ".join(g["name"] for g in self._fallback_groups if g.get("name"))
            self._mark_group_selected(self._resolved_group_name)
            self._refresh_assigned_pills()
            if hasattr(self, "clear_selected_btn"):
                self.clear_selected_btn.setVisible(True)
            self.search_input.clear()

    def _on_clear_fallback_groups(self):
        target_name = self._active_target_name
        if target_name and target_name in self._name_to_groups:
            self._name_to_groups.pop(target_name, None)
            self._name_to_group.pop(target_name, None)
            self._refresh_detected_list_item(target_name)
            self._finalize_auto_detection()
            self._refresh_assigned_pills()
        else:
            self._fallback_groups = []
            self._resolved_group_ids = []
            self._resolved_group_name = None
            self.selected_group_label.setText("No group selected yet.")
            self.selected_group_label.setProperty("role", "muted")
            self.selected_group_label.style().unpolish(self.selected_group_label)
            self.selected_group_label.style().polish(self.selected_group_label)
            self._refresh_assigned_pills()
        if hasattr(self, "clear_selected_btn"):
            self.clear_selected_btn.setVisible(False)

    def _unresolved_group_detections(self):
        """Returns (unresolved_names, affected_filepaths) for bracket-tag
        names that were detected in filenames but never matched to an
        actual group.
        """
        if not self._per_file_names:
            return [], []

        handled = self._skipped_folders | set(self._folder_scanlator)
        unresolved_names = sorted({
            name
            for names in self._per_file_names.values()
            for name in names
            if (name not in self._name_to_groups or not self._name_to_groups[name]) and name not in handled
        }, key=str.lower)

        if not unresolved_names:
            return [], []

        unresolved_set = {n.lower() for n in unresolved_names}
        affected_files = sorted(
            filepath for filepath, names in self._per_file_names.items()
            if any(n.lower() in unresolved_set for n in names)
        )
        return unresolved_names, affected_files

    def _on_continue(self):
        if self.individual_radio.isChecked():
            scanlator_name = self.scanlator_input.text().strip()
            if not scanlator_name:
                QMessageBox.warning(self, "Missing name", "Please enter your scanlator name.")
                return
            self.config_finished.emit({
                "is_group_upload": False,
                "group_ids": [],
                "scanlator_name": scanlator_name,
                "per_file_group_map": {},
                "strip_bracket_groups": False,
                "group_name": scanlator_name, 
            })
            return

        has_untagged_assigned = bool(
            self._untagged_files
            and _UNTAGGED_TARGET in self._name_to_groups
            and self._name_to_groups[_UNTAGGED_TARGET]
        )
        folder_scanlator_map = {}
        skipped_paths = []
        if not self._force_single_group:
            for folder, scan_name in self._folder_scanlator.items():
                for p in self._folder_paths(folder):
                    folder_scanlator_map[p] = scan_name
            for folder in self._skipped_folders:
                skipped_paths.extend(self._folder_paths(folder))

        if (not self._resolved_group_ids and not any(self._per_file_group_map_result.values())
                and not has_untagged_assigned and not folder_scanlator_map and not skipped_paths):
            QMessageBox.warning(
                self, "No group selected",
                "Please search for and select a group (or enter its ID) before continuing."
            )
            return

        if self._force_single_group:
            # User explicitly chose to ignore per-file detected tags -
            # the "unresolved tag(s)" warning below is about tags that
            # were never matched, which is irrelevant once the user has
            # said not to use per-file matching at all. Also strip any
            # partial per_file_group_map_result that resolution may have
            # built before the checkbox was ticked, so a stray earlier
            # resolve doesn't leak through as a silent per-file override
            # despite the override being on.
            self.config_finished.emit({
                "is_group_upload": True,
                "group_ids": self._resolved_group_ids,
                "scanlator_name": None,
                "per_file_group_map": {},
                "per_file_group_names": {},
                "strip_bracket_groups": self._strip_bracket_groups,
                "group_name": self._resolved_group_name,
            })
            return

        unresolved_names, affected_files = self._unresolved_group_detections()
        if unresolved_names:
            file_list = "\n".join(f"  • {os.path.basename(p)}" for p in affected_files[:10])
            if len(affected_files) > 10:
                file_list += f"\n  … and {len(affected_files) - 10} more"
            names_str = ", ".join(f"'{n}'" for n in unresolved_names)

            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Warning)
            msg.setWindowTitle("Unresolved group tag(s)")
            msg.setText(
                f"{names_str} {'was' if len(unresolved_names) == 1 else 'were'} found in filenames but "
                f"could not be matched to a group on the site.\n\n"
                f"{len(affected_files)} file(s) will upload with NO group attribution if you continue:\n"
                f"{file_list}"
            )
            msg.setInformativeText("Go back and search/select a match for the unresolved tag(s), or continue anyway?")
            go_back_btn = msg.addButton("Go back and resolve", QMessageBox.RejectRole)
            msg.addButton("Continue without group", QMessageBox.AcceptRole)
            msg.setDefaultButton(go_back_btn)
            msg.exec()
            if msg.clickedButton() == go_back_btn:
                return

        # Warning for untagged files that have no group assigned
        if self._untagged_files and not has_untagged_assigned and not self._resolved_group_ids:
            file_list = "\n".join(f"  • {os.path.basename(p)}" for p in self._untagged_files[:10])
            if len(self._untagged_files) > 10:
                file_list += f"\n  … and {len(self._untagged_files) - 10} more"

            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Warning)
            msg.setWindowTitle("Untagged chapters without group")
            msg.setText(
                f"{len(self._untagged_files)} chapter(s) have no group tags in their filenames and no group assigned:\n"
                f"{file_list}\n\n"
                f"They will upload with NO group attribution if you continue."
            )
            msg.setInformativeText("Go back and select a group for untagged chapters, or continue without group?")
            go_back_btn = msg.addButton("Go back and assign group", QMessageBox.RejectRole)
            cont_btn = msg.addButton("Continue without group", QMessageBox.AcceptRole)
            msg.setDefaultButton(go_back_btn)
            msg.exec()
            if msg.clickedButton() == go_back_btn:
                self._active_target_name = _UNTAGGED_TARGET
                self._update_search_target_label()
                self._render_search_results_for_active_target()
                self.search_input.setFocus()
                return
            elif msg.clickedButton() == cont_btn:
                self._resolved_group_ids = []
                self._resolved_group_name = None

        per_file_map = dict(self._per_file_group_map_result)
        per_file_names = parser_mod.resolve_per_file_group_names(
            self._per_file_names, self._name_to_groups
        )
        for p in list(folder_scanlator_map) + skipped_paths:
            per_file_map.pop(p, None)
            per_file_names.pop(p, None)

        if has_untagged_assigned:
            untagged_groups = self._name_to_groups[_UNTAGGED_TARGET]
            untagged_ids = [g["id"] for g in untagged_groups if g.get("id") is not None]
            untagged_gnames = [g["name"] for g in untagged_groups if g.get("name")]
            if untagged_ids:
                for uf in self._untagged_files:
                    per_file_map[uf] = list(untagged_ids)
                    if untagged_gnames:
                        per_file_names[uf] = list(untagged_gnames)
        elif self._resolved_group_ids and not self._per_file_names:
            for uf in self._untagged_files:
                per_file_map[uf] = list(self._resolved_group_ids)
                if self._resolved_group_name:
                    per_file_names[uf] = [g.strip() for g in self._resolved_group_name.split(",") if g.strip()]

        self.config_finished.emit({
            "is_group_upload": True,
            "group_ids": self._resolved_group_ids,
            "scanlator_name": None,
            "per_file_group_map": per_file_map,
            "per_file_group_names": per_file_names,
            "per_file_scanlator_map": folder_scanlator_map,
            "skipped_paths": skipped_paths,
            "strip_bracket_groups": self._strip_bracket_groups,
            "group_name": self._resolved_group_name, 
        })

    def stop_background_work(self):
        for thread in self._threads:
            if thread_is_running(thread):
                thread.quit()
                thread.wait(2000)