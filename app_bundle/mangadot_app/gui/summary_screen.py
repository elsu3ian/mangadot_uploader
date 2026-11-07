"""Post-upload summary screen."""
import webbrowser
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QAbstractItemView, QHeaderView, QSizePolicy, QButtonGroup
)
from PySide6.QtGui import QPixmap
from PySide6.QtSvgWidgets import QSvgWidget

from .. import parser as parser_mod
from ..parser import norm_filepath
from .. import util
from . import theme
from .widgets import heading, StatCard, hint_label, GlassBox, make_flat_link
from .theme import Color

COL_NUMBER = 0
COL_TITLE = 1
COL_GROUP = 2


def _format_origin(code):
    # Single source of truth for the country table lives in util.py -
    # this module used to carry its own verbatim copy that could drift.
    return util.format_origin(code)


class SummaryScreen(QWidget):
    done_requested = Signal()
    upload_again_requested = Signal()

    def __init__(self, manga_id, upload_type, username, group_label,
                 all_files, failed_set, elapsed, per_file_group_map=None,
                 per_file_scanlator_map=None, is_group_upload=None,
                 batch_group_ids=None, parent=None):
        super().__init__(parent)
        self.manga_id = manga_id
        self.upload_type = upload_type
        self.username = username
        self.group_label = group_label
        self.all_files = all_files
        self.failed_set = failed_set
        self.elapsed = elapsed
        self.chapter_map = {}
        self.per_file_group_map = per_file_group_map or {}
        self.per_file_scanlator_map = per_file_scanlator_map or {}
        self.is_group_upload = is_group_upload
        self.batch_group_ids = batch_group_ids or []

        # Table sort order for the uploaded-chapters list below - mirrors
        # the site's own Newest/Oldest toggle (see the chapter list on a
        # manga page). "newest" = highest chapter/volume number first
        # (matches the old hardcoded behavior); "oldest" = chapter-number
        # ascending, i.e. natural reading order.
        self._sort_order = "newest"

        self._cover_pixmap_source = None

        self._build_ui()

    def _attribution_display_for(self, f):
        """What to show in the Group column for one successfully-uploaded
        file - reflecting what was actually attributed on upload, not
        just what the filename happened to contain.

        f["groups"] is the raw bracket-tag text extracted from the
        filename at parse time (e.g. "[SomeGroup]") and is never updated
        to reflect whether that tag actually resolved to a real group on
        the site. Showing it directly (the old behavior) meant a file
        whose tag failed to resolve - and which the user explicitly
        chose to upload without a group for - would still display that
        original tag text in the summary, looking exactly like a
        successful attribution. This checks the actual per-file
        resolution data from the group-config step instead.
        """
        if self.is_group_upload is False:
            # Individual scanlator mode: one name applies to everything,
            # unless a specific file had a per-file override set during
            # review. Never affected by the bracket-tag resolution bug -
            # there's no auto-detection step to silently fail here.
            norm_path = norm_filepath(f["filepath"]) if f.get("filepath") else None
            if norm_path and norm_path in self.per_file_scanlator_map:
                return self.per_file_scanlator_map[norm_path]
            return self.group_label or "-"

        if self.is_group_upload is True:
            norm_path = norm_filepath(f["filepath"]) if f.get("filepath") else None
            has_per_file_override = bool(norm_path and self.per_file_group_map.get(norm_path))
            has_batch_group = bool(self.batch_group_ids)
            if has_per_file_override:
                # This file was explicitly re-pointed at a different group
                # during review (see title_review_screen._on_change_group_
                # selected), which sets f["groups"] and f["group_id"]
                # together from the same resolved dialog result - so
                # f["groups"] is trustworthy here, unlike the raw
                # filename-parsed bracket tag the docstring above warns
                # about. Show the file's own group rather than the
                # whole-batch label, since they can now legitimately
                # differ within one upload.
                if f.get("groups"):
                    return ", ".join(f["groups"])
                return self.group_label or "-"
            if has_batch_group:
                # No per-file override: this file correctly inherits the
                # uniform whole-batch group that applies to every
                # unoverridden file (see uploader.py's process_uploads,
                # which unions batch-level group_ids into every chunk).
                return self.group_label or "-"
            # No per-file override AND no batch-level group at all: this
            # file genuinely uploaded with no group attribution.
            return "No group (unresolved)"

        # is_group_upload is None: caller didn't pass the new attribution
        # data (e.g. an older/unmigrated call site). Fall back to the
        # previous behavior rather than mislabel every row.
        return ", ".join(f["groups"]) if f.get("groups") else (self.group_label or "-")

    def _build_sort_toggle(self):
        """Two-button Newest/Oldest segmented toggle for the uploaded-
        chapters table, matching the equivalent control on the site's own
        chapter list. Returns a layout ready to drop into the header row."""
        row = QHBoxLayout()
        row.setSpacing(0)

        self._sort_group = QButtonGroup(self)
        self._sort_group.setExclusive(True)

        toggle_box = GlassBox(tint_rgba="rgba(92, 225, 230, 10)", border_color=Color.ACCENT_SOFT_BORDER)
        toggle_layout = QHBoxLayout(toggle_box)
        toggle_layout.setContentsMargins(3, 3, 3, 3)
        toggle_layout.setSpacing(2)

        def _make_toggle_button(label, order):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setChecked(order == self._sort_order)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    border: none;
                    border-radius: {theme.RADIUS_SM}px;
                    color: {Color.TEXT_SECONDARY};
                    padding: 5px 12px;
                    font-weight: 600;
                }}
                QPushButton:checked {{
                    background-color: {Color.ACCENT_SOFT};
                    color: {Color.ACCENT};
                }}
                QPushButton:hover:!checked {{
                    color: {Color.TEXT_PRIMARY};
                }}
            """)
            btn.clicked.connect(lambda: self._on_sort_changed(order))
            self._sort_group.addButton(btn)
            toggle_layout.addWidget(btn)
            return btn

        self._sort_newest_btn = _make_toggle_button("Newest", "newest")
        self._sort_oldest_btn = _make_toggle_button("Oldest", "oldest")

        row.addWidget(toggle_box)
        return row

    def _on_sort_changed(self, order):
        if order == self._sort_order:
            return
        self._sort_order = order
        self._populate_uploaded_table()

    def _populate_uploaded_table(self):
        """(Re)fills the uploaded-chapters table from self._successful_files
        in the currently-selected sort order. Safe to call again after the
        toggle changes - just rebuilds the rows in place."""
        ordered = sorted(
            self._successful_files,
            key=lambda x: x["number"],
            reverse=(self._sort_order == "newest"),
        )

        self.uploaded_table.setRowCount(len(ordered))
        for row, f in enumerate(ordered):
            unit = "Ch." if self.upload_type == "chapter" else "Vol."
            num_str = f"{unit} {parser_mod.fmt_num(f['number'])}"
            group_str = self._attribution_display_for(f)

            item_num = QTableWidgetItem(num_str)
            item_num.setData(Qt.UserRole, float(f["number"]))
            self.uploaded_table.setItem(row, COL_NUMBER, item_num)
            self.uploaded_table.setItem(row, COL_TITLE, QTableWidgetItem(f["title"]))
            self.uploaded_table.setItem(row, COL_GROUP, QTableWidgetItem(group_str))

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 20, 28, 24)
        outer.setSpacing(16)

        total = len(self.all_files)
        uploaded = total - len(self.failed_set)
        all_ok = not self.failed_set

        successful_files = [f for f in self.all_files if f["filename"] not in self.failed_set]
        self._successful_files = successful_files
        
        total_bytes = sum(f.get("size", 0) for f in self._successful_files)
        avg_speed = (total_bytes / self.elapsed) if self.elapsed > 0 else 0
        speed_str = f"{util.fmt_size(avg_speed)}/s"

        # ---- Header Section with Inline Logo ----
        header_vbox = QVBoxLayout()
        header_vbox.setSpacing(4)
        header_vbox.setAlignment(Qt.AlignHCenter)

        header_top_hbox = QHBoxLayout()
        header_top_hbox.setAlignment(Qt.AlignHCenter)
        header_top_hbox.setSpacing(8)

        title_lbl = QLabel("\U0001F389 Upload completed on" if all_ok else "Upload finished with some failures")
        title_lbl.setProperty("role", "heading")
        header_top_hbox.addWidget(title_lbl, 0, Qt.AlignVCenter)

        if all_ok:
            _ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
            _LOGO_PATH = _ASSETS_DIR / "mangadotnet-purple.svg"
            logo = QSvgWidget(str(_LOGO_PATH))
            logo.setFixedSize(120, 24)
            
            logo.setCursor(Qt.PointingHandCursor)
            logo.mousePressEvent = lambda _: webbrowser.open("https://mangadot.net")
            
            header_top_hbox.addWidget(logo, 0, Qt.AlignVCenter)

        header_vbox.addLayout(header_top_hbox)

        subtitle_lbl = QLabel(f"{uploaded} of {total} {self.upload_type}(s) processed in {util.fmt_duration(self.elapsed)}.")
        subtitle_lbl.setProperty("role", "subheading")
        subtitle_lbl.setAlignment(Qt.AlignHCenter)
        header_vbox.addWidget(subtitle_lbl)

        outer.addLayout(header_vbox)

        # ---- Middle Section: Cover + Metadata + Synopsis (Left) & Stats/Action (Right) ----
        middle_row = QHBoxLayout()
        middle_row.setSpacing(24)

        left_vbox = QVBoxLayout()
        left_vbox.setSpacing(12)

        cover_meta_hbox = QHBoxLayout()
        cover_meta_hbox.setSpacing(16)

        # 1. Cover (Top-aligned)
        self.cover_label = QLabel()
        self.cover_label.setMinimumSize(90, 130)
        self.cover_label.setMaximumSize(120, 170)
        self.cover_label.setScaledContents(False)
        self.cover_label.setAlignment(Qt.AlignCenter)
        self.cover_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.cover_label.setStyleSheet(
            f"background-color: {Color.BG_INPUT}; border: 1px solid {Color.BORDER}; "
            f"border-radius: {theme.RADIUS_SM}px; color: {Color.TEXT_MUTED}; font-size: 11px;"
        )
        self.cover_label.setText("Loading\u2026")
        cover_meta_hbox.addWidget(self.cover_label, 0, Qt.AlignTop)

        # 2. Metadata (Top-aligned next to cover)
        meta_col = QVBoxLayout()
        meta_col.setSpacing(4)
        meta_col.setAlignment(Qt.AlignTop)
        
        self.title_label = QLabel("Fetching manga details\u2026")
        self.title_label.setProperty("role", "muted")
        self.title_label.setWordWrap(True)
        meta_col.addWidget(self.title_label)
        
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        meta_col.addWidget(self.status_label)
        
        self.genre_label = QLabel("")
        self.genre_label.setWordWrap(True)
        meta_col.addWidget(self.genre_label)
        
        self.origin_label = QLabel("")
        self.origin_label.setWordWrap(True)
        meta_col.addWidget(self.origin_label)

        self.author_label = QLabel("")
        self.author_label.setWordWrap(True)
        meta_col.addWidget(self.author_label)

        self.artist_label = QLabel("")
        self.artist_label.setWordWrap(True)
        meta_col.addWidget(self.artist_label)

        self.rating_label = QLabel("")
        self.rating_label.setWordWrap(True)
        meta_col.addWidget(self.rating_label)

        self.attribution_label = QLabel(f"<b><i>Attribution:</i></b> {self.group_label or '-'}")
        self.attribution_label.setWordWrap(True)
        meta_col.addWidget(self.attribution_label)

        cover_meta_hbox.addLayout(meta_col, 1)
        left_vbox.addLayout(cover_meta_hbox)

        # 3. Synopsis (Single line under cover + metadata)
        self.synopsis_label = QLabel("")
        self.synopsis_label.setWordWrap(False)
        self.synopsis_label.setProperty("role", "muted")
        left_vbox.addWidget(self.synopsis_label)
        left_vbox.addStretch(1)

        middle_row.addLayout(left_vbox, 1)
        middle_row.setAlignment(left_vbox, Qt.AlignTop)

        # 4. Stats & Action (Right)
        right_col = QVBoxLayout()
        right_col.setSpacing(16)
        right_col.setAlignment(Qt.AlignTop | Qt.AlignRight)

        stats_row = QHBoxLayout()
        stats_row.setSpacing(10)
        stats_row.addWidget(StatCard(str(uploaded), "Uploaded", kind="success"))
        stats_row.addWidget(StatCard(util.fmt_duration(self.elapsed), "Time taken", kind="accent"))
        stats_row.addWidget(StatCard(speed_str, "Avg Speed", kind="neutral"))
        right_col.addLayout(stats_row)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        
        # New Edit Uploads Button
        edit_box = GlassBox(
            tint_rgba="rgba(92, 225, 230, 18)", 
            border_color=Color.ACCENT_SOFT_BORDER,
        )
        edit_box_layout = QHBoxLayout(edit_box)
        edit_box_layout.setContentsMargins(14, 6, 14, 6)
        
        self.edit_manga_button = make_flat_link(QPushButton("Edit uploads"), bold=True)
        self.edit_manga_button.clicked.connect(
            lambda: webbrowser.open(f"https://mangadot.net/user/{self.username}/uploads?series={self.manga_id}")
        )
        edit_box_layout.addWidget(self.edit_manga_button)
        button_row.addWidget(edit_box)

        # Existing Open Manga Page Button
        proceed_box = GlassBox(
            tint_rgba="rgba(74, 222, 128, 18)", 
            border_color=Color.SUCCESS, 
        )
        proceed_box_layout = QHBoxLayout(proceed_box)
        proceed_box_layout.setContentsMargins(14, 6, 14, 6)
        
        self.open_manga_button = make_flat_link(QPushButton("Open manga page"), bold=True)
        self.open_manga_button.clicked.connect(
            lambda: webbrowser.open(f"https://mangadot.net/manga/{self.manga_id}")
        )
        proceed_box_layout.addWidget(self.open_manga_button)
        button_row.addWidget(proceed_box)

        right_col.addLayout(button_row)
        middle_row.addLayout(right_col, 0)
        middle_row.setAlignment(right_col, Qt.AlignTop)

        outer.addLayout(middle_row)

        if self.failed_set:
            fail_label = QLabel(
                "<b>Failed:</b> " + ", ".join(sorted(self.failed_set)[:10]) +
                (f"  (+{len(self.failed_set) - 10} more)" if len(self.failed_set) > 10 else "")
            )
            fail_label.setWordWrap(True)
            fail_label.setProperty("role", "warning")
            outer.addWidget(fail_label)

        list_header_row = QHBoxLayout()
        list_header_row.addWidget(
            hint_label("Uploaded chapters below \u2014 double-click any row to open it on MangaDot."), 1
        )
        list_header_row.addLayout(self._build_sort_toggle())
        outer.addLayout(list_header_row)

        # ---- Table Section ----
        self.uploaded_table = QTableWidget()
        self.uploaded_table.setColumnCount(3)
        self.uploaded_table.setHorizontalHeaderLabels(["Number", "Title", "Group"])
        self.uploaded_table.verticalHeader().setVisible(False)
        self.uploaded_table.verticalHeader().setDefaultSectionSize(32)
        self.uploaded_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.uploaded_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.uploaded_table.setAlternatingRowColors(True)
        self.uploaded_table.setShowGrid(False)
        
        self.uploaded_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        header = self.uploaded_table.horizontalHeader()
        header.setSectionResizeMode(COL_NUMBER, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(COL_TITLE, QHeaderView.Stretch)
        header.setSectionResizeMode(COL_GROUP, QHeaderView.ResizeToContents)
        header.setHighlightSections(False)

        self._populate_uploaded_table()

        self.uploaded_table.itemDoubleClicked.connect(self._on_row_double_clicked)
        outer.addWidget(self.uploaded_table, 1)

        bottom_row = QHBoxLayout()
        
        # --- Upload Again Button (Left) ---
        again_box = GlassBox(
            tint_rgba="rgba(92, 225, 230, 18)",
            border_color=Color.ACCENT_SOFT_BORDER,
        )
        again_box_layout = QHBoxLayout(again_box)
        again_box_layout.setContentsMargins(14, 6, 14, 6)
        self.upload_again_button = make_flat_link(QPushButton("Upload again"), bold=True)
        self.upload_again_button.clicked.connect(self.upload_again_requested.emit)
        again_box_layout.addWidget(self.upload_again_button)
        bottom_row.addWidget(again_box)
        
        # --- Spacer pushes everything else to the right ---
        bottom_row.addStretch(1)
        
        # --- Close Button (Right) ---
        self.close_button = QPushButton("Close")
        self.close_button.setCursor(Qt.PointingHandCursor)
        self.close_button.setAutoDefault(False)
        self.close_button.setStyleSheet(f"""
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
        self.close_button.clicked.connect(self.done_requested.emit)
        
        bottom_row.addWidget(self.close_button)
        outer.addLayout(bottom_row)

    def set_details(self, details, cover_bytes, chapter_map):
        self.chapter_map = chapter_map

        if not details:
            self.title_label.setText("Could not load details for this manga.")
            self.cover_label.setText("No cover")
            return

        from html import escape

        accent = Color.ACCENT
        title_html = f"<span style='font-size:15px; font-weight:700; color:{accent};'>{escape(details['title'])}</span>"
        if details.get("alt_title"):
            title_html += f"<br><i style='color:{Color.TEXT_MUTED};'>{escape(details['alt_title'])}</i>"
        self.title_label.setText(title_html)

        self.status_label.setText(f"<b><i>Status:</i></b> <span style='color:{Color.SUCCESS};'>{escape(str(details['status']).upper())}</span>")

        if details.get("genres"):
            self.genre_label.setText("<b><i>Genres:</i></b> " + escape(", ".join(details["genres"])))
        else:
            self.genre_label.setText(f"<b><i>Genres:</i></b> <span style='color:{Color.TEXT_MUTED};'>(not found: genres)</span>")

        if details.get("origin"):
            self.origin_label.setText(f"<b><i>Origin:</i></b> {escape(_format_origin(details['origin']))}")
        else:
            self.origin_label.setText(f"<b><i>Origin:</i></b> <span style='color:{Color.TEXT_MUTED};'>(not found: origin)</span>")

        if details.get("authors"):
            self.author_label.setText(f"<b><i>Author:</i></b> {escape(details['authors'])}")
        else:
            self.author_label.setText(f"<b><i>Author:</i></b> <span style='color:{Color.TEXT_MUTED};'>(not found: author)</span>")

        if details.get("artists"):
            self.artist_label.setText(f"<b><i>Artist:</i></b> {escape(details['artists'])}")
        else:
            self.artist_label.setText(f"<b><i>Artist:</i></b> <span style='color:{Color.TEXT_MUTED};'>(not found: artist)</span>")

        if details.get("rating"):
            self.rating_label.setText(f"<b><i>Rating:</i></b> <b><i style='color:{Color.WARNING};'>{escape(details['rating'])}</i></b>")
        else:
            self.rating_label.setText(f"<b><i>Rating:</i></b> <span style='color:{Color.TEXT_MUTED};'>(not found: rating)</span>")

        if details.get("description"):
            desc = details["description"].strip().replace("\n", " ")
            if len(desc) > 130:
                desc = desc[:130].rsplit(" ", 1)[0] + "\u2026"
            self.synopsis_label.setText(f"<span style='color:{Color.TEXT_SECONDARY};'>{escape(desc)}</span>")
        else:
            self.synopsis_label.setText(f"<span style='color:{Color.TEXT_MUTED};'>(not found: synopsis)</span>")

        if cover_bytes:
            pixmap = QPixmap()
            if pixmap.loadFromData(cover_bytes):
                self._cover_pixmap_source = pixmap
                self._rescale_cover_pixmap()
            else:
                self._cover_pixmap_source = None
                self.cover_label.setText("No cover")
        else:
            self._cover_pixmap_source = None
            self.cover_label.setText("No cover")

    def _rescale_cover_pixmap(self):
        if not self._cover_pixmap_source:
            return
        target_size = self.cover_label.size()
        if target_size.width() <= 0 or target_size.height() <= 0:
            return
        self.cover_label.setPixmap(
            self._cover_pixmap_source.scaled(
                target_size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
            )
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._rescale_cover_pixmap()

    def _on_row_double_clicked(self, item):
        row = item.row()
        col0_item = self.uploaded_table.item(row, COL_NUMBER)
        if not col0_item:
            return

        raw_num = col0_item.data(Qt.UserRole)
        if raw_num is None:
            return

        chapter_num_str = f"{round(float(raw_num), 4):g}"
        chapter_id = self.chapter_map.get(chapter_num_str)

        if chapter_id:
            endpoint = "volume" if self.upload_type == "volume" else "chapter"
            webbrowser.open(f"https://mangadot.net/{endpoint}/{chapter_id}?source=user")
        else:
            webbrowser.open(f"https://mangadot.net/manga/{self.manga_id}")