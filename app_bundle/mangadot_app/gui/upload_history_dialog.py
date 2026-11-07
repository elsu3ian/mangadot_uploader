"""Upload History dialog: displays tracked series, chapter counts, groups,
and provides direct links/API sync with MangaDot (e.g. /user/{username}/uploads).
"""
import os
import json
import logging
import webbrowser
from typing import Optional, List, Dict, Any

from PySide6.QtCore import Qt, Signal, QObject, QThread, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QWidget, QFrame,
    QMessageBox, QAbstractItemView, QSpacerItem, QSizePolicy
)

from .. import config as config_mod
from .. import net
from . import theme, workers, thread_is_running
from .theme import Color
from .widgets import heading, hint_label, make_flat, make_flat_link, GlassBox, StatCard, StatusPill


class _ApiSyncWorker(QObject):
    """Background worker to fetch user's live uploads from MangaDot's cloud API (/api/uploads/mine)
    and enrich series metadata without freezing UI."""
    progress = Signal(int, int, str)  # current, total, title
    finished = Signal()

    def __init__(self, series_list: List[Dict[str, Any]], session=None, username: str = ""):
        super().__init__()
        self.series_list = list(series_list or [])
        self.session = session
        self.username = username or ""
        self._stopped = False

    def stop(self):
        self._stopped = True

    def run(self):
        import requests
        sess = self.session
        if sess is None:
            sess = requests.Session()

        # Step 1: Query MangaDot cloud uploads (/api/uploads/mine)
        self.progress.emit(0, 0, "Querying MangaDot /api/uploads/mine...")
        cloud_uploads = []
        try:
            cloud_uploads = net.fetch_my_uploads(sess, limit=100, max_pages=15)
        except Exception as e:
            logging.debug("_ApiSyncWorker: fetch_my_uploads error: %s", e)

        if cloud_uploads and not self._stopped:
            # Group uploads by manga_id
            by_manga: Dict[Any, Dict[str, Any]] = {}
            for u in cloud_uploads:
                mid = u.get("manga_id")
                if not mid:
                    continue
                m_entry = by_manga.setdefault(mid, {
                    "manga_id": mid,
                    "title": u.get("manga_title") or f"Manga #{mid}",
                    "groups": set(),
                    "chapters": set(),
                    "origin": u.get("language") or "N/A",
                })
                grp = u.get("group_name") or u.get("scanlator_name")
                if grp:
                    m_entry["groups"].add(grp)
                ch_num = u.get("volume_number") if u.get("type") == "volume" else u.get("chapter_number")
                if ch_num is not None:
                    m_entry["chapters"].add(str(ch_num))

            for mid, m_data in by_manga.items():
                if self._stopped:
                    break
                config_mod.db_record_series(
                    manga_id=mid,
                    title=m_data["title"],
                    origin=m_data.get("origin"),
                    groups=list(m_data["groups"]),
                    chapters_pushed=list(m_data["chapters"]),
                    username=self.username or None,
                )

        # Step 2: Fetch full details for all recorded series to enrich metadata
        current_tracked = config_mod.get_all_tracked_series()
        total = len(current_tracked)
        for idx, item in enumerate(current_tracked):
            if self._stopped:
                break
            mid = item.get("manga_id")
            if not mid:
                continue

            self.progress.emit(idx + 1, total, item.get("title") or f"Manga #{mid}")
            try:
                details = net.fetch_manga_full_details(mid, sess)
                if details:
                    updates = {
                        "title": details.get("title"),
                        "alt_titles": details.get("alt_titles") or ([details.get("alt_title")] if details.get("alt_title") else []),
                        "origin": details.get("origin"),
                        "cover_url": details.get("cover_url"),
                        "mangadot_url": details.get("manga_url"),
                    }
                    config_mod.db_update_series_metadata(mid, updates)
            except Exception as e:
                logging.debug("Sync worker error for %s: %s", mid, e)

        self.finished.emit()


class UploadHistoryDialog(QDialog):
    """Interactive Upload History Viewer and MangaDot Cloud Sync Manager."""

    def __init__(self, parent=None, session=None, username: Optional[str] = None):
        super().__init__(parent)
        self.session = session
        self.username = username or ""
        self.setWindowTitle("MangaDot Uploader \u2014 Upload History")
        self.resize(1080, 680)
        self.setMinimumSize(920, 520)

        self._dark_input_style = theme.dark_input_style()
        self._all_series: List[Dict[str, Any]] = []
        self._filtered_series: List[Dict[str, Any]] = []

        self._sync_thread: Optional[QThread] = None
        self._sync_worker: Optional[_ApiSyncWorker] = None

        self._build_ui()
        self._load_data()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 20, 22, 18)
        outer.setSpacing(14)

        # 1. Header
        outer.addWidget(heading(
            "Upload History & Cloud Sync",
            "View recorded series, check uploaded chapters, and manage your releases on MangaDot."
        ))

        # 2. Stat Cards Row
        stats_row = QHBoxLayout()
        stats_row.setSpacing(12)

        self.stat_series = StatCard("0", "Series Tracked", kind="accent")
        self.stat_chapters = StatCard("0", "Chapters Uploaded", kind="success")
        
        user_display = self.username or "elsu"
        self.stat_user = StatCard(user_display, "Active Account", kind="neutral")
        self.stat_user.clicked.connect(self._on_open_user_uploads)

        stats_row.addWidget(self.stat_series)
        stats_row.addWidget(self.stat_chapters)
        stats_row.addWidget(self.stat_user)
        outer.addLayout(stats_row)

        # 3. Filter & Action Bar
        action_row = QHBoxLayout()
        action_row.setSpacing(10)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍  Search by title, alt title, manga ID, or group...")
        self.search_input.setStyleSheet(self._dark_input_style)
        self.search_input.textChanged.connect(self._apply_filter)
        action_row.addWidget(self.search_input, 1)

        self.btn_open_uploads = make_flat_link(
            QPushButton("🌐 Open My MangaDot Uploads"),
            color=Color.ACCENT,
            hover_color=Color.ACCENT_HOVER
        )
        self.btn_open_uploads.clicked.connect(self._on_open_user_uploads)
        action_row.addWidget(self.btn_open_uploads)

        self.btn_sync = make_flat(QPushButton("🔄 Sync from MangaDot API"))
        self.btn_sync.clicked.connect(self._on_sync_from_api)
        action_row.addWidget(self.btn_sync)

        outer.addLayout(action_row)

        # 4. Main Data Table
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "Origin", "Title & Alt Titles", "Manga ID", "Groups", "Chapters", "Last Uploaded", "Actions"
        ])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)  # Origin
        self.table.setColumnWidth(0, 85)

        header.setSectionResizeMode(1, QHeaderView.Stretch)  # Title
        
        header.setSectionResizeMode(2, QHeaderView.Fixed)  # Manga ID
        self.table.setColumnWidth(2, 95)

        header.setSectionResizeMode(3, QHeaderView.Fixed)  # Groups
        self.table.setColumnWidth(3, 140)

        header.setSectionResizeMode(4, QHeaderView.Fixed)  # Chapters
        self.table.setColumnWidth(4, 110)

        header.setSectionResizeMode(5, QHeaderView.Fixed)  # Uploaded At
        self.table.setColumnWidth(5, 145)

        header.setSectionResizeMode(6, QHeaderView.Fixed)  # Actions
        self.table.setColumnWidth(6, 215)

        outer.addWidget(self.table, 1)

        # 5. Bottom Status and Control Row
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(10)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet(f"color: {Color.TEXT_SECONDARY}; font-size: 12px;")
        bottom_row.addWidget(self.status_label)
        bottom_row.addStretch(1)

        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.accept)
        bottom_row.addWidget(self.close_btn)

        outer.addLayout(bottom_row)

    def _load_data(self):
        """Loads all tracked series from storage and populates the table."""
        self._all_series = config_mod.get_all_tracked_series()

        # Update stats
        total_series = len(self._all_series)
        total_chapters = sum(s.get("total_chapters", 0) for s in self._all_series)

        self.stat_series.set_value(f"{total_series:,}")
        self.stat_chapters.set_value(f"{total_chapters:,}")

        # Auto-detect username if we don't have it yet
        if not self.username:
            for s in self._all_series:
                if s.get("username"):
                    self.username = s["username"]
                    break
        user_display = self.username or "elsu"
        self.stat_user.set_value(user_display)

        self._apply_filter()

    def _apply_filter(self):
        query = self.search_input.text().strip().lower()
        if not query:
            self._filtered_series = list(self._all_series)
        else:
            filtered = []
            for s in self._all_series:
                title = str(s.get("title") or "").lower()
                mid = str(s.get("manga_id") or "").lower()
                alts = " ".join(str(a) for a in (s.get("alt_titles") or [])).lower()
                groups = " ".join(str(g) for g in (s.get("groups") or [])).lower()
                origin = str(s.get("origin") or "").lower()

                if query in title or query in mid or query in alts or query in groups or query in origin:
                    filtered.append(s)
            self._filtered_series = filtered

        self._populate_table()

    def _populate_table(self):
        self.table.setRowCount(0)
        self.table.setRowCount(len(self._filtered_series))

        for row, s in enumerate(self._filtered_series):
            mid = s.get("manga_id")
            title = s.get("title") or f"Manga #{mid}"
            alt_titles = s.get("alt_titles") or []
            origin = (s.get("origin") or "N/A").upper()
            groups = s.get("groups") or []
            total_chs = s.get("total_chapters") or len(s.get("uploaded_chapters") or [])
            timestamp = s.get("last_uploaded_at") or "-"
            uploaded_chs = s.get("uploaded_chapters") or []

            # Column 0: Origin Pill
            origin_kind = "neutral"
            flag = "🌐 "
            if origin in ("KR", "KOREA", "KOREAN"):
                origin_kind = "violet"
                flag = "🇰🇷 "
            elif origin in ("JP", "JAPAN", "JAPANESE"):
                origin_kind = "danger"
                flag = "🇯🇵 "
            elif origin in ("CN", "CHINA", "CHINESE"):
                origin_kind = "warning"
                flag = "🇨🇳 "
            elif origin in ("EN", "ENGLISH"):
                origin_kind = "info"
                flag = "🇬🇧 "

            origin_pill = StatusPill(f"{flag}{origin}", kind=origin_kind)
            origin_container = self._center_widget(origin_pill)
            self.table.setCellWidget(row, 0, origin_container)

            # Column 1: Title & Alt Titles
            title_widget = QWidget()
            t_layout = QVBoxLayout(title_widget)
            t_layout.setContentsMargins(8, 6, 8, 6)
            t_layout.setSpacing(2)

            title_lbl = QLabel(title)
            title_lbl.setStyleSheet(f"color: {Color.ACCENT}; font-weight: 700; font-size: 13px;")
            title_lbl.setWordWrap(True)
            t_layout.addWidget(title_lbl)

            if alt_titles:
                alt_txt = ", ".join(str(a) for a in alt_titles[:3])
                if len(alt_titles) > 3:
                    alt_txt += f" (+{len(alt_titles) - 3} more)"
                alt_lbl = QLabel(alt_txt)
                alt_lbl.setStyleSheet(f"color: {Color.TEXT_MUTED}; font-size: 11px; font-style: italic;")
                alt_lbl.setWordWrap(True)
                t_layout.addWidget(alt_lbl)

            self.table.setCellWidget(row, 1, title_widget)

            # Column 2: Manga ID
            id_item = QTableWidgetItem(str(mid))
            id_item.setTextAlignment(Qt.AlignCenter)
            id_item.setForeground(QColor(Color.TEXT_SECONDARY))
            self.table.setItem(row, 2, id_item)

            # Column 3: Groups
            group_txt = ", ".join(str(g) for g in groups) if groups else "-"
            grp_item = QTableWidgetItem(group_txt)
            grp_item.setTextAlignment(Qt.AlignCenter)
            grp_item.setForeground(QColor(Color.TEXT_SECONDARY))
            self.table.setItem(row, 3, grp_item)

            # Column 4: Chapters Pill
            ch_pill = StatusPill(f"{total_chs} ch", kind="success" if total_chs > 0 else "neutral")
            if uploaded_chs:
                summary_preview = ", ".join(str(c) for c in uploaded_chs[:20])
                if len(uploaded_chs) > 20:
                    summary_preview += f" ... (+{len(uploaded_chs) - 20} more)"
                ch_pill.setToolTip(f"Uploaded chapters ({total_chs}):\n{summary_preview}")
            ch_container = self._center_widget(ch_pill)
            self.table.setCellWidget(row, 4, ch_container)

            # Column 5: Last Uploaded
            time_item = QTableWidgetItem(str(timestamp))
            time_item.setTextAlignment(Qt.AlignCenter)
            time_item.setForeground(QColor(Color.TEXT_MUTED))
            self.table.setItem(row, 5, time_item)

            # Column 6: Action Buttons
            act_widget = QWidget()
            act_layout = QHBoxLayout(act_widget)
            act_layout.setContentsMargins(6, 4, 6, 4)
            act_layout.setSpacing(6)

            btn_page = make_flat_link(QPushButton("📖 Series"), color=Color.TEXT_PRIMARY)
            btn_page.setFixedHeight(28)
            btn_page.clicked.connect(lambda _, m=mid: webbrowser.open(f"https://mangadot.net/manga/{m}"))
            act_layout.addWidget(btn_page)

            btn_manage = make_flat_link(QPushButton("📤 Manage"), color=Color.ACCENT)
            btn_manage.setFixedHeight(28)
            user_target = self.username or "elsu"
            btn_manage.clicked.connect(
                lambda _, u=user_target, m=mid: webbrowser.open(f"https://mangadot.net/user/{u}/uploads?series={m}")
            )
            act_layout.addWidget(btn_manage)

            self.table.setCellWidget(row, 6, act_widget)
            self.table.setRowHeight(row, 54 if alt_titles else 46)

        self.status_label.setText(f"Showing {len(self._filtered_series)} of {len(self._all_series)} tracked series")

    def _center_widget(self, widget: QWidget) -> QWidget:
        wrap = QWidget()
        lay = QHBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setAlignment(Qt.AlignCenter)
        lay.addWidget(widget)
        return wrap

    def _on_open_user_uploads(self):
        user = self.username or "elsu"
        url = f"https://mangadot.net/user/{user}/uploads"
        webbrowser.open(url)

    def _on_sync_from_api(self):
        if self._sync_thread is not None and thread_is_running(self._sync_thread):
            QMessageBox.information(self, "Sync in Progress", "Metadata sync is already running in background.")
            return

        self.btn_sync.setEnabled(False)
        self.status_label.setText("Starting API sync with MangaDot...")

        self._sync_thread = QThread()
        self._sync_worker = _ApiSyncWorker(self._all_series, session=self.session, username=self.username)
        self._sync_worker.moveToThread(self._sync_thread)

        self._sync_thread.started.connect(self._sync_worker.run)
        self._sync_worker.progress.connect(self._on_sync_progress)
        self._sync_worker.finished.connect(self._on_sync_finished)

        self._sync_thread.start()

    def _on_sync_progress(self, current: int, total: int, title: str):
        if total > 0:
            self.status_label.setText(f"Syncing [{current}/{total}]: {title[:40]}...")
        else:
            self.status_label.setText(title)

    def _on_sync_finished(self):
        self.btn_sync.setEnabled(True)
        self.status_label.setText("✅ MangaDot API sync completed successfully.")
        
        if self._sync_thread is not None:
            self._sync_thread.quit()
            self._sync_thread.wait(2000)
            self._sync_thread = None
            self._sync_worker = None

        # Reload table with updated metadata
        self._load_data()

    def closeEvent(self, event):
        if self._sync_worker is not None:
            self._sync_worker.stop()
        if self._sync_thread is not None and thread_is_running(self._sync_thread):
            self._sync_thread.quit()
            self._sync_thread.wait(1500)
        super().closeEvent(event)
