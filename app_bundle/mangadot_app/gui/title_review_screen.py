"""Title review/editing screen."""
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QMenu, QDialog, QDialogButtonBox, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QAbstractItemView,
    QInputDialog, QStyledItemDelegate, QHeaderView, QSizePolicy, QComboBox,
    QFrame, QScrollArea
)
from PySide6.QtGui import QColor, QAction, QFont
from .widgets import Card, heading, section_label, hint_label, make_flat, GlassBox, make_flat_link, DialogSafeLineEdit, attach_combo_dots_overlay, GroupPillWidget
from .. import parser as parser_mod
from .. import util
from .. import config as config_mod
from . import theme
from .theme import Color
from . import thread_is_running, workers
from .group_config_dialog import _ManualSearchWorker

COL_FILENAME = 0
COL_NUMBER = 1
COL_TITLE = 2
COL_LANGUAGE = 3
COL_GROUP = 4
COL_SIZE = 5

DUPLICATE_BG = QColor(Color.ROW_DUPLICATE)
ROW_HEIGHT = 34


class ReadOnlyDelegate(QStyledItemDelegate):
    def createEditor(self, parent, option, index):
        return None


class CompactCellEditDelegate(QStyledItemDelegate):
    """QLineEdit editor for in-table cell editing (Title/Number columns).

    The global QLineEdit stylesheet is tuned for normal-height form fields
    (7px vertical padding on top of a border), which is taller than this
    table's 34px rows. Without an override here, the *default* global-
    styled QLineEdit gets dropped into a cell only slightly taller than
    the text itself, so the padding eats into the glyphs and the box
    renders squashed/clipped mid-edit (worst on the Title column, since
    it holds the longest text). This delegate gives the editor its own
    minimal-padding style and pins it to the actual row height,
    independent of the global form-input QSS."""

    def createEditor(self, parent, option, index):
        editor = QLineEdit(parent)
        editor.setStyleSheet(
            f"QLineEdit {{ background-color: {Color.BG_INPUT}; color: {Color.TEXT_PRIMARY}; "
            f"border: 1px solid {Color.ACCENT}; border-radius: 4px; padding: 1px 6px; }}"
        )
        return editor

    def updateEditorGeometry(self, editor, option, index):
        rect = option.rect
        editor.setGeometry(rect.x(), rect.y(), rect.width(), rect.height())


class _FindReplaceDialog(QDialog):
    def __init__(self, targets, scope_description, parent=None):
        super().__init__(parent)
        self.targets = targets
        self.setWindowTitle("Remove word/phrase")
        self.resize(480, 420)
        self.confirmed_pattern = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(10)
        layout.addWidget(hint_label(f"Applies to: {scope_description}"))

        self.pattern_input = QLineEdit()
        self.pattern_input.setPlaceholderText("Plain text, or a regex pattern")
        self.pattern_input.textChanged.connect(self._update_preview)
        layout.addWidget(self.pattern_input)

        self.preview_list = QListWidget()
        layout.addWidget(self.preview_list, 1)

        self.summary_label = QLabel("")
        self.summary_label.setWordWrap(True)
        self.summary_label.setProperty("role", "muted")
        layout.addWidget(self.summary_label)

        buttons = QDialogButtonBox()
        buttons.addButton(QDialogButtonBox.Ok)
        buttons.addButton(QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _update_preview(self):
        self.preview_list.clear()
        text = self.pattern_input.text().strip()
        if not text:
            self.summary_label.setText("")
            return

        pattern = parser_mod.compile_removal_pattern(text)
        affected = 0
        for f in self.targets:
            new_title = parser_mod.apply_removal_pattern(pattern, f["title"])
            if new_title is not None and new_title != f["title"]:
                affected += 1
                if self.preview_list.count() < 8:
                    self.preview_list.addItem(QListWidgetItem(f"{f['filename']}"))
                    self.preview_list.addItem(QListWidgetItem(f"   \u2212 {f['title']}"))
                    self.preview_list.addItem(QListWidgetItem(f"   + {new_title}"))

        if affected == 0:
            self.summary_label.setText(f'No titles contain "{text}" \u2014 nothing to change.')
        else:
            extra = affected - min(affected, 8)
            suffix = f" (...and {extra} more)" if extra > 0 else ""
            self.summary_label.setText(f"This will change {affected} of {len(self.targets)} title(s).{suffix}")

    def _on_accept(self):
        text = self.pattern_input.text().strip()
        if not text:
            self.reject()
            return
        self.confirmed_pattern = parser_mod.compile_removal_pattern(text)
        self.accept()


class _CandidatePickerDialog(QDialog):
    def __init__(self, filename, candidates, parent=None, number=None):
        super().__init__(parent)
        self.candidates = candidates or [("Full title (as detected)", filename)]
        self.setWindowTitle(f"Select title for {filename}")
        self.resize(460, 360)
        self.number = number
        self.result_title = None
        self.result_kind = None
        self.result_pattern = None
        self.result_candidate_index = None
        self.result_pattern_text = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(10)
        self.list_widget = QListWidget()
        for i, (label, text) in enumerate(self.candidates):
            item = QListWidgetItem(f"{label}: {text}")
            item.setData(Qt.UserRole, ("candidate", text, i))
            self.list_widget.addItem(item)

        remove_item = QListWidgetItem("Remove word/phrase (regex)\u2026")
        remove_item.setData(Qt.UserRole, ("regex_remove", None, None))
        self.list_widget.addItem(remove_item)

        zeros_item = QListWidgetItem("Remove unnecessary leading zeros\u2026")
        zeros_item.setData(Qt.UserRole, ("strip_zeros", None, None))
        self.list_widget.addItem(zeros_item)

        custom_item = QListWidgetItem("Type my own\u2026")
        custom_item.setData(Qt.UserRole, ("custom", None, None))
        self.list_widget.addItem(custom_item)

        pattern_item = QListWidgetItem("Custom pattern (e.g. \u201cScene N\u201d)\u2026")
        pattern_item.setData(Qt.UserRole, ("custom_pattern", None, None))
        self.list_widget.addItem(pattern_item)

        self.list_widget.itemDoubleClicked.connect(self._on_item_chosen)
        layout.addWidget(self.list_widget)

        buttons = QDialogButtonBox()
        buttons.addButton(QDialogButtonBox.Ok)
        buttons.addButton(QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_ok)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_item_chosen(self, item):
        self._resolve(item)
        if self.result_title is not None:
            self.accept()

    def _on_ok(self):
        item = self.list_widget.currentItem()
        if item is None:
            return
        self._resolve(item)
        if self.result_title is not None:
            self.accept()

    def _resolve(self, item):
        kind, value, index = item.data(Qt.UserRole)
        base_label, base_text = self.candidates[0]

        if kind == "candidate":
            self.result_title = value
            self.result_kind = "candidate"
            self.result_candidate_index = index
        elif kind == "strip_zeros":
            new_title = parser_mod.strip_leading_zeros_in_title(base_text)
            self.result_title = new_title
            self.result_kind = "strip_zeros"
        elif kind == "regex_remove":
            text, ok = QInputDialog.getText(
                self, "Remove word/phrase", "Enter word/phrase to remove (plain text, or a regex pattern):"
            )
            if not ok or not text.strip():
                return
            pattern = parser_mod.compile_removal_pattern(text.strip())
            new_title = parser_mod.apply_removal_pattern(pattern, base_text)
            if new_title is None:
                QMessageBox.warning(self, "Empty result", "Removing that would leave an empty title \u2014 try a narrower pattern.")
                return
            self.result_title = new_title
            self.result_kind = "regex_remove"
            self.result_pattern = pattern
        elif kind == "custom":
            text, ok = QInputDialog.getText(self, "Custom title", "Enter custom title:", text=base_text)
            if not ok or not text.strip():
                return
            self.result_title = text.strip()
            self.result_kind = "custom"
        elif kind == "custom_pattern":
            text, ok = QInputDialog.getText(
                self, "Custom pattern",
                "Enter a title pattern.\n\n"
                "Use N to mark where the chapter or volume number should appear,\n"
                "e.g. \u201cScene N\u201d, \u201cPage N\u201d, \u201cPart N: Awakening\u201d.\n\n"
                "If the pattern does not include N, the number will be appended\n"
                "automatically \u2014 for example, \u201cChapter\u201d becomes \u201cChapter 1\u201d, \u201cChapter 2\u201d, and so on:",
            )
            if not ok:
                return
            text = text.strip()
            if not text:
                return
            self.result_pattern_text = text
            self.result_title = parser_mod.apply_custom_number_pattern(text, self.number) if self.number is not None else text
            self.result_kind = "custom_pattern"


_GroupPillWidget = GroupPillWidget


class _GroupPickerDialog(QDialog):
    """Multi-group credit picker dialog. Allows searching MangaDot's group
    directory or entering numeric IDs to attach one or multiple groups (pills)
    to the target file(s) for joint scanlations / collaborations.
    """

    def __init__(self, session, targets_description, current_groups=None, current_group_ids=None, current_group=None, parent=None):
        super().__init__(parent)
        self.session = session
        self.selected_groups = []
        self._threads = []
        self._workers = []

        if current_groups:
            c_names = [current_groups] if isinstance(current_groups, str) else list(current_groups)
            c_ids = list(current_group_ids or [])
            for i, name in enumerate(c_names):
                gid = c_ids[i] if i < len(c_ids) else None
                if name:
                    self.selected_groups.append({"id": gid, "name": str(name).strip()})
        elif current_group_ids:
            for gid in current_group_ids:
                if gid:
                    self.selected_groups.append({"id": gid, "name": f"ID {gid}"})
        elif current_group:
            parts = [p.strip() for p in str(current_group).split(",") if p.strip()]
            for p in parts:
                self.selected_groups.append({"id": None, "name": p})

        self.setWindowTitle("Change group(s)")
        self.resize(480, 500)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(10)

        layout.addWidget(hint_label(f"Applies to: {targets_description}"))

        layout.addWidget(section_label("Assigned group(s)"))

        self.pills_container = QWidget()
        self.pills_layout = QHBoxLayout(self.pills_container)
        self.pills_layout.setContentsMargins(6, 4, 6, 4)
        self.pills_layout.setSpacing(8)
        self.pills_layout.setAlignment(Qt.AlignLeft)

        self.pills_scroll = QScrollArea()
        self.pills_scroll.setWidgetResizable(True)
        self.pills_scroll.setFrameShape(QFrame.NoFrame)
        self.pills_scroll.setStyleSheet(
            f"background-color: {Color.BG_APP}; border: 1px solid {Color.BORDER}; border-radius: 8px;"
        )
        self.pills_scroll.setFixedHeight(48)
        self.pills_scroll.setWidget(self.pills_container)
        layout.addWidget(self.pills_scroll)

        layout.addWidget(section_label("Search MangaDot directory to add group"))
        search_row = QHBoxLayout()
        search_row.setSpacing(8)
        self.search_input = DialogSafeLineEdit()
        self.search_input.setPlaceholderText("Search group by name, or enter numeric ID directly")
        self.search_input.returnPressed.connect(self._on_search)
        search_row.addWidget(self.search_input, 1)

        self.search_glass = GlassBox(tint_rgba="rgba(92, 225, 230, 18)", border_color=Color.ACCENT_SOFT_BORDER)
        self.search_glass.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        search_glass_layout = QHBoxLayout(self.search_glass)
        search_glass_layout.setContentsMargins(16, 4, 16, 4)
        self.search_button = make_flat_link(QPushButton("Search"), color=Color.ACCENT, hover_color=Color.ACCENT_HOVER, bold=True)
        self.search_button.setAutoDefault(False)
        self.search_button.setDefault(False)
        self.search_button.clicked.connect(self._on_search)
        search_glass_layout.addWidget(self.search_button)
        search_row.addWidget(self.search_glass)
        layout.addLayout(search_row)

        self.results_list = QListWidget()
        self.results_list.itemDoubleClicked.connect(self._on_result_picked)
        layout.addWidget(self.results_list, 1)

        self.feedback_label = QLabel("Double-click a search result to add it to the assigned groups.")
        self.feedback_label.setWordWrap(True)
        self.feedback_label.setProperty("role", "muted")
        layout.addWidget(self.feedback_label)

        buttons = QDialogButtonBox()
        accept_button = buttons.addButton("Apply group(s)", QDialogButtonBox.AcceptRole)
        accept_button.setAutoDefault(False)
        accept_button.setDefault(False)

        clear_btn = QPushButton("Clear all")
        clear_btn.setStyleSheet(f"color: {Color.TEXT_MUTED}; background: transparent; border: none; font-size: 12px; margin-right: 12px;")
        clear_btn.setCursor(Qt.PointingHandCursor)
        clear_btn.clicked.connect(self._on_clear_all)
        buttons.addButton(clear_btn, QDialogButtonBox.ActionRole)

        cancel_button = buttons.addButton(QDialogButtonBox.Cancel)
        cancel_button.setAutoDefault(False)
        cancel_button.setDefault(False)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._refresh_pills()

    def _refresh_pills(self):
        while self.pills_layout.count():
            item = self.pills_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self.selected_groups:
            empty_lbl = QLabel("No groups assigned (upload with no group credit)")
            empty_lbl.setStyleSheet(f"color: {Color.TEXT_MUTED}; font-size: 12px; font-style: italic; background: transparent;")
            self.pills_layout.addWidget(empty_lbl)
        else:
            for g in self.selected_groups:
                pill = _GroupPillWidget(g)
                pill.removed.connect(self._on_remove_group)
                self.pills_layout.addWidget(pill)

        self.pills_layout.addStretch(1)

    def _on_remove_group(self, group):
        self.selected_groups = [
            g for g in self.selected_groups
            if not (g.get("id") == group.get("id") and g.get("name") == group.get("name"))
        ]
        self._refresh_pills()

    def _on_clear_all(self):
        self.selected_groups = []
        self._refresh_pills()
        self.feedback_label.setText("Cleared all groups.")
        self.feedback_label.setProperty("role", "muted")
        self.feedback_label.style().unpolish(self.feedback_label)
        self.feedback_label.style().polish(self.feedback_label)

    def _add_group_dict(self, group):
        gid = group.get("id")
        gname = group.get("name") or (f"ID {gid}" if gid else "")
        for existing in self.selected_groups:
            if gid and existing.get("id") == gid:
                return
            if gname and existing.get("name", "").lower() == gname.lower():
                return
        self.selected_groups.append({"id": gid, "name": gname})
        self._refresh_pills()
        self.feedback_label.setText(f"Added group: {gname}")
        self.feedback_label.setProperty("role", "success")
        self.feedback_label.style().unpolish(self.feedback_label)
        self.feedback_label.style().polish(self.feedback_label)

    def _on_search(self):
        query = self.search_input.text().strip()
        if not query:
            return

        if query.isdigit():
            self._add_group_dict({"id": int(query), "name": f"ID {query}"})
            self.search_input.clear()
            return

        if self.session is None:
            QMessageBox.warning(
                self, "Can't search right now",
                "No active session to search MangaDot's directory — enter the group's numeric ID instead."
            )
            return

        self.results_list.clear()
        self.results_list.addItem(QListWidgetItem(f"Searching for '{query}'…"))
        self.search_button.setEnabled(False)

        worker = _ManualSearchWorker(self.session, query)
        workers.prune_finished(self._threads, self._workers)
        thread, worker = workers.run_worker(worker, on_finished=self._on_search_finished)
        self._threads.append(thread)
        self._workers.append(worker)

    def _on_search_finished(self, query, results):
        self.search_button.setEnabled(True)
        self.results_list.clear()
        if not results:
            self.results_list.addItem(
                QListWidgetItem(f"No groups found for '{query}'. Try a different spelling, or enter numeric ID above.")
            )
            return
        for g in results:
            item = QListWidgetItem(f"{g['name']} (ID: {g['id']})")
            item.setData(Qt.UserRole, g)
            self.results_list.addItem(item)

    def _on_result_picked(self, item):
        group = item.data(Qt.UserRole)
        if not group:
            return
        self._add_group_dict(group)

    def _on_accept(self):
        self.accept()

    @property
    def resolved_group_name(self):
        return ", ".join(g["name"] for g in self.selected_groups if g.get("name")) if self.selected_groups else None

    @property
    def resolved_group_id(self):
        return self.selected_groups[0]["id"] if (self.selected_groups and self.selected_groups[0].get("id")) else None

    @property
    def resolved_group_names(self):
        return [g["name"] for g in self.selected_groups if g.get("name")]

    @property
    def resolved_group_ids(self):
        return [g["id"] for g in self.selected_groups if g.get("id") is not None]

    def closeEvent(self, event):
        for thread in self._threads:
            if thread_is_running(thread):
                thread.quit()
                thread.wait(2000)
        super().closeEvent(event)


class _ScanlatorPickerDialog(QDialog):
    def __init__(self, targets_description, parent=None):
        super().__init__(parent)
        self.scanlator_name = None
        self.setWindowTitle("Set individual scanlator")
        self.resize(380, 180)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(10)

        layout.addWidget(hint_label(f"Applies to: {targets_description}"))
        layout.addWidget(section_label("SCANLATOR NAME"))

        self.name_input = DialogSafeLineEdit()
        self.name_input.setPlaceholderText("Enter scanlator / uploader name")
        self.name_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {Color.BG_APP};
                border: 1px solid {Color.ACCENT_SOFT_BORDER};
                border-radius: 6px;
                padding: 6px 8px;
                color: {Color.TEXT_PRIMARY};
            }}
            QLineEdit:focus {{
                border: 1px solid {Color.ACCENT};
            }}
        """)
        self.name_input.returnPressed.connect(self._on_accept)
        layout.addWidget(self.name_input)
        layout.addStretch(1)

        buttons = QDialogButtonBox()
        accept_button = buttons.addButton("Set Scanlator", QDialogButtonBox.AcceptRole)
        accept_button.setAutoDefault(False)
        accept_button.setDefault(False)
        cancel_button = buttons.addButton(QDialogButtonBox.Cancel)
        cancel_button.setAutoDefault(False)
        cancel_button.setDefault(False)

        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_accept(self):
        name = self.name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "No name", "Please enter a scanlator name.")
            return
        self.scanlator_name = name
        self.accept()


class _LanguagePickerDialog(QDialog):
    """Compact language picker for re-pointing already-selected rows at a
    different language, same idea as _ScanlatorPickerDialog but backed by
    the fixed util.LANGUAGES list instead of free text - there's no
    directory to search (unlike group), just a closed set of ~39 known
    languages, so a plain editable combo (same widget/pattern as
    picker_screen.py's lang_combo on the Manga step) is enough."""

    def __init__(self, targets_description, current_language=None, parent=None):
        super().__init__(parent)
        self.resolved_language = None
        self.setWindowTitle("Change language")
        self.resize(380, 180)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(10)

        layout.addWidget(hint_label(f"Applies to: {targets_description}"))
        if current_language:
            layout.addWidget(hint_label(f"Current: {current_language}"))
        layout.addWidget(section_label("LANGUAGE"))

        self.lang_combo = QComboBox()
        self.lang_combo.setEditable(True)
        self.lang_combo.setStyleSheet(f"""
            QComboBox {{
                background-color: {Color.BG_APP};
                border: 1px solid {Color.ACCENT_SOFT_BORDER};
                border-radius: 6px;
                padding: 6px 8px;
                color: {Color.TEXT_PRIMARY};
            }}
            QComboBox:focus {{
                border: 1px solid {Color.ACCENT};
            }}
        """)
        for code, name in util.LANGUAGES:
            self.lang_combo.addItem(f"{name} ({code})", code)

        if current_language:
            match_idx = -1
            for i in range(self.lang_combo.count()):
                if self.lang_combo.itemData(i) == current_language:
                    match_idx = i
                    break
            if match_idx >= 0:
                self.lang_combo.setCurrentIndex(match_idx)
            else:
                self.lang_combo.setEditText(current_language)

        layout.addWidget(self.lang_combo)
        # Same overlay used for the Manga step's lang_combo/upload_type_combo
        # (attach_combo_dots_overlay) - without it this combo was missing
        # both the visual "..." indicator AND whatever underlying arrow-
        # rendering issue that helper actually exists to fix ("invisible
        # arrow bug" per its docstring), not just the dots themselves.
        attach_combo_dots_overlay(self.lang_combo)
        layout.addStretch(1)

        buttons = QDialogButtonBox()
        accept_button = buttons.addButton("Set Language", QDialogButtonBox.AcceptRole)
        accept_button.setAutoDefault(False)
        accept_button.setDefault(False)
        cancel_button = buttons.addButton(QDialogButtonBox.Cancel)
        cancel_button.setAutoDefault(False)
        cancel_button.setDefault(False)

        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_accept(self):
        current_idx = self.lang_combo.currentIndex()
        if current_idx >= 0 and self.lang_combo.itemText(current_idx) == self.lang_combo.currentText():
            code = self.lang_combo.itemData(current_idx)
        else:
            code = parser_mod.extract_lang_code_from_text(self.lang_combo.currentText())
        code = (code or "").strip()
        if not code:
            QMessageBox.warning(self, "No language selected", "Choose or enter a language first.")
            return
        self.resolved_language = code
        self.accept()


class TitleReviewScreen(QWidget):
    review_finished = Signal(list)
    back_requested = Signal()

    def __init__(self, files, upload_type="chapter", group_label=None, session=None, parent=None, preview_only=False):
        """preview_only=True renders the same table/warnings but hides all
        editing tools and swaps the footer for a single 'Done' action that
        doesn't carry the files anywhere further — used by dry-run mode.

        session is optional: it's only needed to search MangaDot's group
        directory from the "Change group for selected" dialog. Without it
        (e.g. dry-run preview has none to give), that dialog still works
        via manual numeric group ID entry."""
        super().__init__(parent)
        self.files = files
        self.upload_type = upload_type
        self.group_label = group_label
        self.session = session
        self.preview_only = preview_only
        self._build_ui()
        self._populate_table()
        self._apply_initial_column_widths()

        if not self.preview_only:
            self._restore_column_order()

        self._refresh_warnings()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 20, 28, 24)
        outer.setSpacing(14)

        title = "Preview parsed files" if self.preview_only else "Review before uploading"
        subtitle = (
            "Dry run \u2014 nothing will be uploaded. This is exactly how MangaDot will see your files."
            if self.preview_only else
            "Double-click a title to edit it, right-click for more options, or use the tools below."
        )
        outer.addWidget(heading(title, subtitle))

        stats_row = QHBoxLayout()
        stats_row.setSpacing(10)
        self.summary_label = QLabel("")
        self.summary_label.setProperty("role", "subheading")
        stats_row.addWidget(self.summary_label)
        stats_row.addStretch(1)
        outer.addLayout(stats_row)

        self.warning_label = QLabel("")
        self.warning_label.setWordWrap(True)
        self.warning_label.setProperty("role", "warning")
        self.warning_label.setVisible(False)
        outer.addWidget(self.warning_label)

        if not self.preview_only:
            toolbar_card = Card()
            toolbar = QHBoxLayout()
            toolbar.setSpacing(8)
            self.global_remove_btn = make_flat(QPushButton("Remove word/phrase \u2014 all titles\u2026"))
            self.global_remove_btn.clicked.connect(self._on_global_remove)
            self.ranged_remove_btn = make_flat(QPushButton("Remove word/phrase \u2014 selected\u2026"))
            self.ranged_remove_btn.clicked.connect(self._on_ranged_remove)
            self.redo_group_btn = make_flat(QPushButton("Redo title \u2014 selected\u2026"))
            self.redo_group_btn.clicked.connect(self._on_redo_selected)
            toolbar.addWidget(self.global_remove_btn)
            toolbar.addWidget(self.ranged_remove_btn)
            toolbar.addWidget(self.redo_group_btn)
            toolbar.addStretch(1)
            
            hint = hint_label("Select rows + Delete to exclude \u00b7 right-click for more")
            hint.setWordWrap(False)
            toolbar.addWidget(hint)
            
            toolbar_card.addLayout(toolbar)
            outer.addWidget(toolbar_card)

        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["Filename", "Number", "Title", "Language", "Group", "Size"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
        self.table.setShowGrid(False)
        self.table.setFocusPolicy(Qt.StrongFocus)

        if self.preview_only:
            self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        else:
            self.table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)

        self.readonly_delegate = ReadOnlyDelegate(self.table)
        self.table.setItemDelegateForColumn(COL_FILENAME, self.readonly_delegate)
        self.table.setItemDelegateForColumn(COL_LANGUAGE, self.readonly_delegate)
        self.table.setItemDelegateForColumn(COL_GROUP, self.readonly_delegate)
        self.table.setItemDelegateForColumn(COL_SIZE, self.readonly_delegate)

        self.compact_edit_delegate = CompactCellEditDelegate(self.table)
        self.table.setItemDelegateForColumn(COL_NUMBER, self.compact_edit_delegate)
        self.table.setItemDelegateForColumn(COL_TITLE, self.compact_edit_delegate)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(COL_FILENAME, QHeaderView.Interactive)
        header.setSectionResizeMode(COL_NUMBER, QHeaderView.Fixed)
        header.setSectionResizeMode(COL_TITLE, QHeaderView.Stretch)
        header.setSectionResizeMode(COL_LANGUAGE, QHeaderView.Interactive)
        header.setSectionResizeMode(COL_GROUP, QHeaderView.Interactive)
        header.setSectionResizeMode(COL_SIZE, QHeaderView.Fixed)
        header.setSectionsMovable(not self.preview_only)
        header.setHighlightSections(False)

        self.table.itemChanged.connect(self._on_item_changed)
        if not self.preview_only:
            self.table.cellDoubleClicked.connect(self._on_cell_double_clicked)
            self.table.setContextMenuPolicy(Qt.CustomContextMenu)
            self.table.customContextMenuRequested.connect(self._on_context_menu)

        outer.addWidget(self.table, 1)

        bottom_row = QHBoxLayout()
        if not self.preview_only:
            self.back_button = QPushButton("Back")
            self.back_button.setCursor(Qt.PointingHandCursor)
            self.back_button.setAutoDefault(False)
            self.back_button.setStyleSheet(f"""
                QPushButton {{
                    background-color: transparent; 
                    color: {Color.TEXT_PRIMARY}; 
                    border: 1px solid {Color.BORDER}; 
                    border-radius: {theme.RADIUS_SM}px; 
                    padding: 6px 18px;
                }}
                QPushButton:hover {{
                    background-color: {Color.BG_HOVER};
                }}
            """)
            self.back_button.clicked.connect(self.back_requested.emit)
            bottom_row.addWidget(self.back_button)
        bottom_row.addStretch(1)

        proceed_box = GlassBox(
            tint_rgba="rgba(74, 222, 128, 18)", 
            border_color=Color.SUCCESS, 
        )
        proceed_box_layout = QHBoxLayout(proceed_box)
        proceed_box_layout.setContentsMargins(14, 6, 14, 6)

        if self.preview_only:
            self.proceed_button = make_flat_link(QPushButton("Done"), bold=True)
            self.proceed_button.clicked.connect(lambda: self.review_finished.emit(self.files))
        else:
            self.proceed_button = make_flat_link(QPushButton("Proceed with upload"), bold=True)
            self.proceed_button.clicked.connect(self._on_proceed)
            
        proceed_box_layout.addWidget(self.proceed_button)
        bottom_row.addWidget(proceed_box)
        
        outer.addLayout(bottom_row)

        self._populating = False

    def _restore_column_order(self):
        """Restores column ORDER only (e.g. if the person dragged 'Group'
        before 'Title' last time) - never width. Widths are always
        recomputed fresh in _apply_initial_column_widths() from whatever
        files are actually in the table this run, so a Group column
        sized for a long group name last session can't stick around and
        clip a short one this session (or vice versa). Using
        QHeaderView.saveState()/restoreState() for this used to persist
        the whole header as one opaque blob, including widths - that's
        the bug that caused the Group column to stay stuck at a stale
        narrow width."""
        cfg = config_mod.load_config()
        order = cfg.get("review_table_column_order")
        if not order or len(order) != self.table.columnCount():
            return
        header = self.table.horizontalHeader()
        for target_visual_index, logical_index in enumerate(order):
            current_visual_index = header.visualIndex(logical_index)
            if current_visual_index != -1 and current_visual_index != target_visual_index:
                header.moveSection(current_visual_index, target_visual_index)

    def _apply_initial_column_widths(self):
        """Sets sane starting widths instead of relying on
        resizeColumnsToContents(), which fights Stretch-mode columns and
        produces unpredictable results (columns locking in too narrow,
        e.g. Group showing only 'W...' for 'WebToon') depending on what
        happened to be in the table at the moment it's called."""
        metrics = self.table.fontMetrics()

        filename_width = max(
            (metrics.horizontalAdvance(f["filename"]) for f in self.files), default=0
        )
        self.table.setColumnWidth(COL_FILENAME, min(max(filename_width + 32, 220), 460))

        group_width = max(
            (metrics.horizontalAdvance(", ".join(f["groups"]) if f.get("groups") else (self.group_label or "-"))
             for f in self.files), default=0
        )
        self.table.setColumnWidth(COL_GROUP, min(max(group_width + 28, 90), 220))

        lang_width = max(
            (metrics.horizontalAdvance(f.get("language") or "-") for f in self.files), default=0
        )
        self.table.setColumnWidth(COL_LANGUAGE, min(max(lang_width + 28, 70), 140))

        self.table.setColumnWidth(COL_NUMBER, 90)
        self.table.setColumnWidth(COL_SIZE, 100)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Delete and not self.preview_only:
            self._remove_selected_rows()
        else:
            super().keyPressEvent(event)

    def _populate_table(self):
        self.table.blockSignals(True)
        try:
            self._populating = True
            self.table.clearContents()
            self.table.setRowCount(len(self.files))
            has_groups = True
            self.table.setColumnHidden(COL_GROUP, not has_groups)

            mono = QFont()
            mono.setStyleHint(QFont.Monospace)

            for row, f in enumerate(self.files):
                filename_item = QTableWidgetItem(f["filename"])
                filename_item.setFlags(filename_item.flags() & ~Qt.ItemIsEditable)
                filename_item.setForeground(QColor(Color.TEXT_SECONDARY))
                self.table.setItem(row, COL_FILENAME, filename_item)

                number_item = QTableWidgetItem(parser_mod.fmt_num(f["number"]))
                number_item.setTextAlignment(Qt.AlignCenter)
                number_item.setFont(mono)
                self.table.setItem(row, COL_NUMBER, number_item)

                title_item = QTableWidgetItem(f["title"] or "-")
                title_font = QFont()
                title_font.setWeight(QFont.DemiBold)
                title_item.setFont(title_font)
                self.table.setItem(row, COL_TITLE, title_item)

                lang_item = QTableWidgetItem(f.get("language") or "-")
                lang_item.setFlags(lang_item.flags() & ~Qt.ItemIsEditable)
                lang_item.setForeground(QColor(Color.TEXT_MUTED))
                self.table.setItem(row, COL_LANGUAGE, lang_item)

                if f.get("scanlator"):
                    group_str = f"Scanlator: {f['scanlator']}"
                elif f.get("groups"):
                    group_str = ", ".join(f["groups"])
                elif f.get("group_ids") == [] or not f.get("group_ids"):
                    if self.group_label and self.group_label != "Multiple / Auto-Detected":
                        group_str = self.group_label
                    else:
                        group_str = "None (no group)"
                else:
                    group_str = self.group_label or "-"
                
                group_item = QTableWidgetItem(group_str)
                group_item.setFlags(group_item.flags() & ~Qt.ItemIsEditable)
                group_item.setForeground(QColor(Color.TEXT_MUTED))
                self.table.setItem(row, COL_GROUP, group_item)

                size_item = QTableWidgetItem(util.fmt_size(f["size"]))
                size_item.setFlags(size_item.flags() & ~Qt.ItemIsEditable)
                size_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                size_item.setForeground(QColor(Color.TEXT_MUTED))
                self.table.setItem(row, COL_SIZE, size_item)

        finally:
            self.table.blockSignals(False)
            self._populating = False
        self._update_summary()

    def _update_summary(self):
        total_size = sum(f["size"] for f in self.files)
        unit = "volume" if self.upload_type == "volume" else "chapter"
        unit_plural = f"{len(self.files)} {unit}{'s' if len(self.files) != 1 else ''}"
        self.summary_label.setText(f"{unit_plural}  \u00b7  {util.fmt_size(total_size)} total")

    def _refresh_warnings(self):
        missing = parser_mod.find_missing_numbers(self.files)
        dups = parser_mod.find_duplicate_numbers(self.files)

        messages = []
        if missing:
            term = "chapters" if self.upload_type == "chapter" else "volumes"
            if len(missing) <= 15:
                messages.append(f"Missing {term} in sequence: {', '.join(map(str, missing))}")
            else:
                messages.append(f"Missing {term}: {len(missing)} {term} missing between {missing[0]} and {missing[-1]}.")
        if dups:
            term = "number" if self.upload_type == "chapter" else "volume number"
            dup_desc = ", ".join(parser_mod.fmt_num(n) for n in sorted(dups))
            messages.append(f"Duplicate {term}(s): {dup_desc} (highlighted below)")

        if messages:
            self.warning_label.setText("\u26a0  " + "   \u00b7   ".join(messages))
            self.warning_label.setVisible(True)
        else:
            self.warning_label.setVisible(False)
        self._highlight_duplicates(dups)

    def _highlight_duplicates(self, dups):
        dup_numbers = set(dups.keys())
        for row, f in enumerate(self.files):
            is_dup = f["number"] in dup_numbers
            for col in (COL_FILENAME, COL_NUMBER, COL_TITLE):
                item = self.table.item(row, col)
                if item is not None:
                    if is_dup:
                        item.setBackground(DUPLICATE_BG)
                    else:
                        item.setData(Qt.BackgroundRole, None)

    def _on_item_changed(self, item):
        if self._populating:
            return

        row = item.row()
        if row >= len(self.files) or row < 0:
            return

        f = self.files[row]

        if item.column() == COL_NUMBER:
            try:
                new_num = float(item.text())
            except ValueError:
                self.table.blockSignals(True)
                try:
                    self._populating = True
                    item.setText(parser_mod.fmt_num(f["number"]))
                finally:
                    self.table.blockSignals(False)
                    self._populating = False
                QMessageBox.warning(self, "Invalid number", "Please enter a valid number (e.g. 0, 1.5, 12).")
                return

            if f["number"] != new_num:
                f["number"] = new_num
                QTimer.singleShot(0, self._resort_and_refresh)

        elif item.column() == COL_TITLE:
            new_title = item.text().strip()
            if not new_title:
                self.table.blockSignals(True)
                try:
                    self._populating = True
                    item.setText(f["title"] or "-")
                finally:
                    self.table.blockSignals(False)
                    self._populating = False
                return
            f["title"] = new_title

    def _resort_and_refresh(self):
        self.files.sort(key=lambda x: x["number"])
        self._populate_table()
        self._refresh_warnings()

    def _selected_files(self):
        rows = sorted(set(idx.row() for idx in self.table.selectedIndexes()))
        return [self.files[r] for r in rows]

    def _remove_selected_rows(self):
        targets = self._selected_files()
        if not targets:
            return

        msg = QMessageBox(self)
        msg.setWindowTitle("Exclude files")
        msg.setText(f"Remove {len(targets)} file(s) from the upload queue?")
        yes_btn = msg.addButton(QMessageBox.Yes)
        msg.addButton(QMessageBox.No)
        msg.setDefaultButton(QMessageBox.No)
        msg.exec()

        if msg.clickedButton() == yes_btn:
            target_ids = {id(t) for t in targets}
            self.files = [f for f in self.files if id(f) not in target_ids]
            self._populate_table()
            self._refresh_warnings()

    def _on_context_menu(self, pos):
        item = self.table.itemAt(pos)
        if item is None:
            return
        row = item.row()

        selected_rows = {idx.row() for idx in self.table.selectionModel().selectedRows()}
        if row not in selected_rows:
            self.table.selectRow(row)

        menu = QMenu(self)
        if item.column() == COL_TITLE:
            pick_action = QAction("Pick title from candidates\u2026", self)
            pick_action.triggered.connect(lambda: self._open_candidate_picker(row))
            menu.addAction(pick_action)
        elif item.column() == COL_GROUP:
            edit_grp_action = QAction("Edit group(s) for this file\u2026", self)
            edit_grp_action.triggered.connect(lambda: self._edit_group_for_row(row))
            menu.addAction(edit_grp_action)
        elif item.column() == COL_LANGUAGE:
            edit_lang_action = QAction("Change language for this file\u2026", self)
            edit_lang_action.triggered.connect(lambda: self._edit_language_for_row(row))
            menu.addAction(edit_lang_action)

        language_action = QAction("Change language for selected\u2026", self)
        language_action.triggered.connect(self._on_change_language_selected)
        menu.addAction(language_action)

        group_action = QAction("Change group for selected\u2026", self)
        group_action.triggered.connect(self._on_change_group_selected)
        menu.addAction(group_action)

        scanlator_action = QAction("Set individual scanlator for selected\u2026", self)
        scanlator_action.triggered.connect(self._on_set_scanlator_selected)
        menu.addAction(scanlator_action)

        del_action = QAction("Exclude selected file(s) from upload", self)
        del_action.triggered.connect(self._remove_selected_rows)
        menu.addAction(del_action)

        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _on_cell_double_clicked(self, row, col):
        if self.preview_only or row < 0 or row >= len(self.files):
            return
        if col == COL_GROUP:
            self._edit_group_for_row(row)
        elif col == COL_LANGUAGE:
            self._edit_language_for_row(row)

    def _edit_group_for_row(self, row):
        if row < 0 or row >= len(self.files):
            return
        f = self.files[row]
        seed_groups = f.get("groups")
        seed_group_ids = f.get("group_ids")
        if not seed_groups and not seed_group_ids:
            if f.get("group_id"):
                seed_group_ids = [f["group_id"]]
            elif self.group_label and self.group_label != "-":
                seed_groups = [p.strip() for p in self.group_label.split(",") if p.strip()]
        elif not seed_group_ids and f.get("group_id"):
            seed_group_ids = [f["group_id"]]

        desc = f"{f['filename']}"
        dialog = _GroupPickerDialog(
            self.session, desc,
            current_groups=seed_groups,
            current_group_ids=seed_group_ids,
            parent=self
        )
        if dialog.exec() != QDialog.Accepted:
            return

        f["groups"] = list(dialog.resolved_group_names)
        f["group_ids"] = list(dialog.resolved_group_ids)
        f["group_id"] = dialog.resolved_group_id
        f["scanlator"] = None
        self._populate_table()

    def _edit_language_for_row(self, row):
        if row < 0 or row >= len(self.files):
            return
        f = self.files[row]
        desc = f"{f['filename']}"
        dialog = _LanguagePickerDialog(desc, current_language=f.get("language"), parent=self)
        if dialog.exec() != QDialog.Accepted or dialog.resolved_language is None:
            return
        f["language"] = dialog.resolved_language
        self._populate_table()

    def _on_change_language_selected(self):
        targets = self._selected_files()
        if not targets:
            QMessageBox.information(
                self, "No rows selected",
                "Select one or more rows in the table first (click a row, or drag to select several)."
            )
            return

        current_languages = {f.get("language") for f in targets if f.get("language")}
        current_language = current_languages.pop() if len(current_languages) == 1 else None

        desc = f"{len(targets)} selected row(s)"
        dialog = _LanguagePickerDialog(desc, current_language=current_language, parent=self)
        if dialog.exec() != QDialog.Accepted or dialog.resolved_language is None:
            return

        language = dialog.resolved_language
        for f in targets:
            f["language"] = language
        self._populate_table()
        QMessageBox.information(self, "Done", f"Updated language for {len(targets)} file(s) to \u201c{language}\u201d.")

    def _on_change_group_selected(self):
        targets = self._selected_files()
        if not targets:
            QMessageBox.information(
                self, "No rows selected",
                "Select one or more rows in the table first (click a row, or drag to select several)."
            )
            return

        seed_groups = None
        seed_group_ids = None
        first_groups = tuple(targets[0].get("groups") or [])
        if all(tuple(f.get("groups") or []) == first_groups for f in targets):
            seed_groups = targets[0].get("groups")
            seed_group_ids = targets[0].get("group_ids")
            if not seed_group_ids and targets[0].get("group_id"):
                seed_group_ids = [targets[0].get("group_id")]
            elif not seed_groups and self.group_label and self.group_label != "-":
                seed_groups = [p.strip() for p in self.group_label.split(",") if p.strip()]

        desc = f"{len(targets)} selected row(s)"
        dialog = _GroupPickerDialog(
            self.session, desc,
            current_groups=seed_groups,
            current_group_ids=seed_group_ids,
            parent=self
        )
        if dialog.exec() != QDialog.Accepted:
            return

        names = list(dialog.resolved_group_names)
        ids = list(dialog.resolved_group_ids)
        primary_id = dialog.resolved_group_id
        summary_name = dialog.resolved_group_name or "None (no group credit)"

        for f in targets:
            f["groups"] = list(names)
            f["group_ids"] = list(ids)
            f["group_id"] = primary_id
            f["scanlator"] = None
        self._populate_table()
        QMessageBox.information(self, "Done", f"Updated group for {len(targets)} file(s) to \u201c{summary_name}\u201d.")

    def _on_set_scanlator_selected(self):
        targets = self._selected_files()
        if not targets:
            QMessageBox.information(self, "No rows selected", "Select one or more rows in the table first (click a row, or drag to select several).")
            return

        desc = f"{len(targets)} selected row(s)"
        dialog = _ScanlatorPickerDialog(desc, parent=self)
        if dialog.exec() != QDialog.Accepted or dialog.scanlator_name is None:
            return

        for f in targets:
            f["scanlator"] = dialog.scanlator_name
            f["groups"] = []
            f["group_id"] = None
        self._populate_table()
        QMessageBox.information(self, "Done", f"Assigned {len(targets)} file(s) to scanlator \u201c{dialog.scanlator_name}\u201d.")

    def _open_candidate_picker(self, row):
        f = self.files[row]
        candidates = f.get("candidates") or [("Full title (as detected)", f["title"])]
        dialog = _CandidatePickerDialog(f["filename"], candidates, parent=self, number=f.get("number"))
        if dialog.exec() == QDialog.Accepted and dialog.result_title is not None:
            f["title"] = dialog.result_title
            self._populate_table()
            self._refresh_warnings()

    def _on_global_remove(self):
        dialog = _FindReplaceDialog(self.files, f"all {len(self.files)} title(s)", parent=self)
        if dialog.exec() == QDialog.Accepted and dialog.confirmed_pattern is not None:
            affected = 0
            for f in self.files:
                new_title = parser_mod.apply_removal_pattern(dialog.confirmed_pattern, f["title"])
                if new_title is not None:
                    if new_title != f["title"]:
                        affected += 1
                    f["title"] = new_title
            self._populate_table()
            self._refresh_warnings()
            QMessageBox.information(self, "Done", f"Updated {affected} title(s).")

    def _on_ranged_remove(self):
        targets = self._selected_files()
        if not targets:
            QMessageBox.information(
                self, "No rows selected",
                "Select one or more rows in the table first (click a row, or drag to select several)."
            )
            return
        dialog = _FindReplaceDialog(targets, f"{len(targets)} selected row(s)", parent=self)
        if dialog.exec() == QDialog.Accepted and dialog.confirmed_pattern is not None:
            affected = 0
            for f in targets:
                new_title = parser_mod.apply_removal_pattern(dialog.confirmed_pattern, f["title"])
                if new_title is not None:
                    if new_title != f["title"]:
                        affected += 1
                    f["title"] = new_title
            self._populate_table()
            self._refresh_warnings()
            QMessageBox.information(self, "Done", f"Updated {affected} title(s).")

    def _on_redo_selected(self):
        targets = self._selected_files()
        if not targets:
            QMessageBox.information(
                self, "No rows selected",
                "Select one or more rows in the table first (click a row, or drag to select several)."
            )
            return

        sample = targets[0]
        candidates = sample.get("candidates") or [("Full title (as detected)", sample["title"])]
        dialog = _CandidatePickerDialog(sample["filename"], candidates, parent=self, number=sample.get("number"))
        if dialog.exec() != QDialog.Accepted or dialog.result_title is None:
            return

        for f in targets:
            f_candidates = f.get("candidates") or [("Full title (as detected)", f["title"])]
            if dialog.result_kind == "custom":
                f["title"] = dialog.result_title
            elif dialog.result_kind == "custom_pattern":
                f["title"] = parser_mod.apply_custom_number_pattern(dialog.result_pattern_text, f.get("number"))
            elif dialog.result_kind == "regex_remove":
                f["title"] = parser_mod.apply_removal_pattern(dialog.result_pattern, f_candidates[0][1]) or f["title"]
            elif dialog.result_kind == "strip_zeros":
                f["title"] = parser_mod.strip_leading_zeros_in_title(f_candidates[0][1])
            else:
                idx = min(dialog.result_candidate_index, len(f_candidates) - 1)
                f["title"] = f_candidates[idx][1]

        self._populate_table()
        self._refresh_warnings()
        QMessageBox.information(self, "Done", f"Updated {len(targets)} title(s).")

    def _on_proceed(self):
        header = self.table.horizontalHeader()
        order = [header.logicalIndex(visual) for visual in range(self.table.columnCount())]

        cfg = config_mod.load_config()
        cfg["review_table_column_order"] = order
        cfg.pop("review_table_state", None)  # drop any legacy full-header blob from older saves
        config_mod.save_config(cfg)

        dups = parser_mod.find_duplicate_numbers(self.files)
        if dups:
            term = "number" if self.upload_type == "chapter" else "volume number"
            msg = QMessageBox(self)
            msg.setWindowTitle("Duplicate numbers")
            msg.setText(f"There are still duplicate {term}s. Upload anyway?\n\nDuplicated: {', '.join(parser_mod.fmt_num(n) for n in sorted(dups))}")
            yes_btn = msg.addButton(QMessageBox.Yes)
            msg.addButton(QMessageBox.No)
            msg.setDefaultButton(QMessageBox.No)
            msg.exec()
            if msg.clickedButton() != yes_btn:
                return

        self.review_finished.emit(self.files)

    def stop_background_work(self):
        pass  # no background threads on this screen