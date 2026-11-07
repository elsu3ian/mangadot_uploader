"""Upfront file-subset picker"""
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QRadioButton, QButtonGroup, QListWidget, QListWidgetItem, QStackedWidget,
    QDialog, QFrame, QSizePolicy
)

from .. import parser as parser_mod
from . import theme
from .widgets import Card, heading, section_label, hint_label, make_flat_link, GlassBox, StatusPill
from .theme import Color
from .title_review_screen import _CandidatePickerDialog


class _FullWidthList(QListWidget):
    """A QListWidget whose items are kept sized to the viewport's full
    width on resize (rather than the default fixed/content-based sizing).

    Takes row_height and an optional on_row_resized(row_widget) callback
    via the constructor rather than closing over an enclosing screen
    instance - the previous version was defined inside
    SubsetPickerScreen._build_ui() specifically because its resizeEvent
    read self.ROW_HEIGHT and called self._reelide_row(...) on the
    enclosing SubsetPickerScreen. That closure is what actually required
    the nesting; passing both as constructor arguments instead removes
    that dependency, so this can live at module level and be reused by
    any screen that needs the same full-width-row behavior.
    """

    def __init__(self, row_height, on_row_resized=None, parent=None):
        super().__init__(parent)
        self._row_height = row_height
        self._on_row_resized = on_row_resized

    def resizeEvent(self, event):
        super().resizeEvent(event)
        w = self.viewport().width()
        for i in range(self.count()):
            it = self.item(i)
            if it is not None:
                it.setSizeHint(QSize(w, self._row_height))
                row_widget = self.itemWidget(it)
                if row_widget is not None and self._on_row_resized is not None:
                    self._on_row_resized(row_widget)


class SubsetPickerScreen(QWidget):
    selection_finished = Signal(list)
    back_requested = Signal()

    def __init__(self, parsed_files, upload_type="chapter", parent=None):
        super().__init__(parent)
        self.parsed_files = parsed_files
        self.upload_type = upload_type
        self._build_ui()

    def _build_ui(self):
        unit = "volume" if self.upload_type == "volume" else "chapter"
        unit_plural = f"{unit}{'s' if len(self.parsed_files) != 1 else ''}"

        outer = QVBoxLayout(self)
        
        # THE FIX: Reduced outer margins so the Cards naturally expand outward 
        # and take up ~3% more of the application window!
        outer.setContentsMargins(16, 16, 16, 20) 
        outer.setSpacing(18)

        outer.addWidget(heading(
            "Choose which files to upload",
            f"Found {len(self.parsed_files)} {unit_plural} in this folder."
        ))

        # --- Card 1: Upload Plan (Naming Config) ---
        plan_card = Card()
        plan_card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        plan_card.addWidget(section_label("Upload plan"))

        naming_header_row = QHBoxLayout()
        self.naming_count_label = QLabel("")
        self.naming_count_label.setProperty("role", "subheading")
        
        naming_header_row.addWidget(self.naming_count_label)
        naming_header_row.addStretch(1)
        naming_hint = hint_label("Double-click a group to change its title.")
        naming_hint.setWordWrap(False)
        naming_header_row.addWidget(naming_hint)
        plan_card.addLayout(naming_header_row)

        self.naming_list = _FullWidthList(row_height=self.ROW_HEIGHT, on_row_resized=self._reelide_row)
        self.naming_list.setFrameShape(QFrame.NoFrame)
        self.naming_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.naming_list.itemDoubleClicked.connect(self._on_naming_group_picked)
        self.naming_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        plan_card.addWidget(self.naming_list)
        
        outer.addWidget(plan_card)

        # --- Card 2: Chapter Selection ---
        subset_card = Card()
        subset_card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        subset_card.addWidget(section_label("Chapter selection"))

        mode_row = QHBoxLayout()
        mode_row.setSpacing(16)
        self.mode_group = QButtonGroup(self)
        self.radio_all = QRadioButton(f"Upload all {len(self.parsed_files)} file(s)")
        self.radio_range = QRadioButton("Choose a range")
        self.radio_all.setChecked(True)
        
        for i, rb in enumerate((self.radio_all, self.radio_range)):
            self.mode_group.addButton(rb, i)
            mode_row.addWidget(rb)
            
        mode_row.addStretch(1)
        self.mode_group.idClicked.connect(self._on_mode_changed)
        subset_card.addLayout(mode_row)

        class _CurrentPageStack(QStackedWidget):
            def sizeHint(self):
                w = self.currentWidget()
                return w.sizeHint() if w else super().sizeHint()

            def minimumSizeHint(self):
                w = self.currentWidget()
                return w.minimumSizeHint() if w else super().minimumSizeHint()

        self.subset_pages = _CurrentPageStack()
        self.subset_pages.currentChanged.connect(lambda _i: self.subset_pages.updateGeometry())
        self.subset_pages.setStyleSheet("QStackedWidget { background: transparent; }")

        all_page = QWidget()
        all_page.setStyleSheet("background: transparent;")
        all_layout = QVBoxLayout(all_page)
        all_layout.setContentsMargins(0, 4, 0, 0)
        all_layout.addWidget(hint_label("Every detected file will be queued for upload."))
        self.subset_pages.addWidget(all_page)

        range_page = QWidget()
        range_page.setStyleSheet("background: transparent;")
        range_layout = QVBoxLayout(range_page)
        range_layout.setContentsMargins(0, 4, 0, 0)
        range_layout.setSpacing(8)

        range_row = QHBoxLayout()
        range_row.addWidget(QLabel(f"{unit.title()}s:"))
        self.range_input = QLineEdit()
        self.range_input.setPlaceholderText("e.g. 103-108,110,115-117")
        self.range_input.textChanged.connect(self._on_range_changed)
        range_row.addWidget(self.range_input, 1)
        range_layout.addLayout(range_row)

        self.range_summary = hint_label("Type a range above to preview what will be selected.")
        range_layout.addWidget(self.range_summary)
        self.subset_pages.addWidget(range_page)

        subset_card.addWidget(self.subset_pages)
        outer.addWidget(subset_card)

        self._populate_naming_list()

        # Absorbs the leftover vertical space in the (fixed-size) window
        # between the cards and the Back/Continue row - without this, the
        # stretch that used to sit AFTER bottom_row (see below) left an
        # empty gap floating between the last card and the button row
        # instead of pushing content to fill the window naturally, since
        # both cards above are QSizePolicy.Fixed height and this screen's
        # actual content is shorter than the window on most file counts.
        outer.addStretch(1)

        # --- Bottom Action Row ---
        bottom_row = QHBoxLayout()
        
        self.back_button = QPushButton("Back")
        self.back_button.clicked.connect(self.back_requested.emit)
        bottom_row.addWidget(self.back_button)
        
        bottom_row.addStretch(1)
        
        self.error_label = QLabel("")
        self.error_label.setProperty("role", "danger")
        bottom_row.addWidget(self.error_label)
        
        continue_box = GlassBox(
            tint_rgba="rgba(92, 225, 230, 18)",
            border_color="#2f545a",
        )
        continue_box_layout = QHBoxLayout(continue_box)
        continue_box_layout.setContentsMargins(14, 6, 14, 6)
        
        self.continue_button = make_flat_link(QPushButton("Continue"), bold=True)
        self.continue_button.clicked.connect(self._on_continue)
        continue_box_layout.addWidget(self.continue_button)
        
        bottom_row.addWidget(continue_box)
        
        outer.addLayout(bottom_row)

    def _on_mode_changed(self, idx):
        self.subset_pages.setCurrentIndex(idx)
        self.error_label.setText("")

    def _on_range_changed(self, text):
        text = text.strip()
        if not text:
            self.range_summary.setText("Type a range above to preview what will be selected.")
            return
        valid_numbers = [f["number"] for f in self.parsed_files]
        matched, unmatched = parser_mod.parse_number_ranges(text, valid_numbers=valid_numbers)
        if not matched and not unmatched:
            self.range_summary.setText("Nothing entered yet.")
            return
        parts = []
        if matched:
            parts.append(f"{len(matched)} file(s) matched")
        if unmatched:
            parts.append(f"{len(unmatched)} token(s) not recognized: {', '.join(unmatched[:6])}")
        
        self.range_summary.setProperty("role", "warning" if unmatched else "muted")
        self.range_summary.setText("  \u00b7  ".join(parts))

    def _populate_naming_list(self):
        self.naming_list.clear()
        self._shape_groups = parser_mod.group_by_shape(self.parsed_files)

        ordered_keys = sorted(
            self._shape_groups.keys(),
            key=lambda k: min(f["number"] for f in self._shape_groups[k])
        )

        pattern_count = len(ordered_keys)
        self.naming_count_label.setText(
            f"{pattern_count} naming pattern{'s' if pattern_count != 1 else ''} detected"
        )

        for shape_key in ordered_keys:
            group_items = self._shape_groups[shape_key]
            self._add_naming_row(shape_key, group_items)

        content_height = pattern_count * self.ROW_HEIGHT + 12
        capped_height = min(max(content_height, self.ROW_HEIGHT + 12), 320)
        self.naming_list.setMinimumHeight(capped_height)
        self.naming_list.setMaximumHeight(capped_height)
        self.naming_list.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

    ROW_HEIGHT = 54

    def _build_naming_row_widget(self, group_items):
        representative = group_items[0]
        count = len(group_items)
        unit = "volume" if self.upload_type == "volume" else "chapter"
        unit_label = f"{unit}{'s' if count != 1 else ''}"

        row = QWidget()
        row.setStyleSheet("background: transparent;")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(10, 0, 10, 0)
        row_layout.setSpacing(12)

        badge = StatusPill(str(count), "info")
        badge.setToolTip(f"{count} {unit_label}")
        row_layout.addWidget(badge, 0, Qt.AlignVCenter)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setAlignment(Qt.AlignVCenter) 
        
        title_label = QLabel(f"<b>{representative['title']}</b>")
        text_col.addWidget(title_label)

        example_label = QLabel()
        example_label.setProperty("role", "muted")
        full_example_text = f"e.g. {representative['filename']}"
        
        available = self._example_column_width()
        metrics = example_label.fontMetrics()
        example_label.setText(metrics.elidedText(full_example_text, Qt.ElideMiddle, available))
        example_label.setToolTip(full_example_text)
        example_label.setProperty("full_text", full_example_text)
        text_col.addWidget(example_label)
        
        row_layout.addLayout(text_col, 1)

        chevron = QLabel("\u203a")
        chevron.setProperty("role", "muted")
        row_layout.addWidget(chevron, 0, Qt.AlignVCenter)

        return row

    _ROW_MARGINS = 20  
    _ROW_SPACING = 24  
    _CHEVRON_WIDTH = 14
    _BADGE_WIDTH_ESTIMATE = 34

    def _example_column_width(self):
        list_width = self.naming_list.viewport().width() or self.naming_list.width()
        reserved = self._ROW_MARGINS + self._ROW_SPACING + self._CHEVRON_WIDTH + self._BADGE_WIDTH_ESTIMATE
        return max(list_width - reserved, 60)

    def _reelide_row(self, row_widget):
        for child in row_widget.findChildren(QLabel):
            full_text = child.property("full_text")
            if full_text:
                available = self._example_column_width()
                metrics = child.fontMetrics()
                child.setText(metrics.elidedText(full_text, Qt.ElideMiddle, available))

    def _add_naming_row(self, shape_key, group_items, row=None):
        list_item = QListWidgetItem()
        list_item.setData(Qt.UserRole, shape_key)
        row_widget = self._build_naming_row_widget(group_items)
        if row is None:
            self.naming_list.addItem(list_item)
        else:
            self.naming_list.insertItem(row, list_item)
        list_item.setSizeHint(QSize(self.naming_list.viewport().width(), self.ROW_HEIGHT))
        self.naming_list.setItemWidget(list_item, row_widget)

    def _on_naming_group_picked(self, list_item):
        from PySide6.QtWidgets import QInputDialog, QMessageBox # Local import to keep top clean

        shape_key = list_item.data(Qt.UserRole)
        group_items = self._shape_groups.get(shape_key) or []
        if not group_items:
            return
        representative = group_items[0]
        candidates = representative.get("candidates") or [("Full title (as detected)", representative["title"])]

        dialog = _CandidatePickerDialog(representative["filename"], candidates, parent=self, number=representative.get("number"))
        if dialog.exec() != QDialog.Accepted or dialog.result_title is None:
            return

        # Confirm scope before applying the change to the group
        target_items = group_items
        if len(group_items) > 1:
            range_text, ok = QInputDialog.getText(
                self,
                "Apply to specific files",
                f"This group contains {len(group_items)} file(s).\n\n"
                f"Enter the chapter/volume numbers to apply this title to (e.g. 1-5, 8),\n"
                f"or leave blank to apply it to all {len(group_items)} file(s):"
            )
            if not ok:
                return  # User clicked Cancel
                
            if range_text.strip():
                valid_numbers = [f["number"] for f in group_items]
                matched, unmatched = parser_mod.parse_number_ranges(range_text.strip(), valid_numbers=valid_numbers)
                if not matched:
                    QMessageBox.warning(self, "No matching files", "None of the numbers entered matched a file in this group. Please check the range and try again.")
                    return
                target_items = [f for f in group_items if f["number"] in matched]
        # ----------------------------------------------------------------------

        for f in target_items:
            f_candidates = f.get("candidates") or [("Full title (as detected)", f["title"])]
            if dialog.result_kind == "candidate":
                idx = min(dialog.result_candidate_index, len(f_candidates) - 1)
                f["title"] = f_candidates[idx][1]
            elif dialog.result_kind == "regex_remove":
                f["title"] = parser_mod.apply_removal_pattern(dialog.result_pattern, f_candidates[0][1]) or f["title"]
            elif dialog.result_kind == "strip_zeros":
                f["title"] = parser_mod.strip_leading_zeros_in_title(f_candidates[0][1])
            elif dialog.result_kind == "custom":
                f["title"] = dialog.result_title
            elif dialog.result_kind == "custom_pattern":
                f["title"] = parser_mod.apply_custom_number_pattern(dialog.result_pattern_text, f.get("number"))

        row = self.naming_list.row(list_item)
        self.naming_list.takeItem(row)
        self._add_naming_row(shape_key, group_items, row=row)

    def _on_continue(self):
        mode = self.mode_group.checkedId()
        self.error_label.setText("")

        if mode == 0:
            selected = list(self.parsed_files)
        elif mode == 1:
            text = self.range_input.text().strip()
            if not text:
                self.error_label.setText("Enter a range, or switch to \u201cUpload all\u201d.")
                return
            valid_numbers = [f["number"] for f in self.parsed_files]
            matched, unmatched = parser_mod.parse_number_ranges(text, valid_numbers=valid_numbers)
            if not matched:
                self.error_label.setText("That range didn't match any files.")
                return
            selected = [f for f in self.parsed_files if f["number"] in matched]
        else:
            selected = list(self.parsed_files)

        selected.sort(key=lambda x: x["number"])
        self.selection_finished.emit(selected)

    def stop_background_work(self):
        pass