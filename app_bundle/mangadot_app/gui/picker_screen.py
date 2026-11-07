"""Folder + manga picker screen."""
import os
import webbrowser
from pathlib import Path
from PySide6.QtCore import Qt, Signal, QObject, QPoint, QRect, QSize
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit, QLabel,
    QFileDialog, QListWidget, QListWidgetItem, QSpinBox, QFormLayout, QComboBox,
    QCheckBox, QScrollArea, QFrame, QRadioButton, QButtonGroup,
    QSizePolicy, QGroupBox, QDialog, QMessageBox, QTextEdit, QLayout, QStyle
)
from PySide6.QtGui import QPixmap, QIcon

from .. import net
from .. import config as config_mod
from .. import parser as parser_mod
from .. import util
from . import thread_is_running, workers
from . import theme
from .theme import Color
from .widgets import (
    heading, section_label, hint_label, make_flat_link, GlassBox, attach_combo_dots_overlay
)

_ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
_FAVICON_PATH = _ASSETS_DIR / "favicon.ico"


class _FlowLayout(QLayout):
    def __init__(self, parent=None, margin=0, hSpacing=6, vSpacing=6):
        super().__init__(parent)
        self._items = []
        self.setContentsMargins(margin, margin, margin, margin)
        self.hSpace = hSpacing
        self.vSpace = vSpacing

    def addItem(self, item):
        self._items.append(item)

    def horizontalSpacing(self):
        if self.hSpace >= 0:
            return self.hSpace
        return self.smartSpacing(QStyle.PM_LayoutHorizontalSpacing)

    def verticalSpacing(self):
        if self.vSpace >= 0:
            return self.vSpace
        return self.smartSpacing(QStyle.PM_LayoutVerticalSpacing)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientations()

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self.doLayout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self.doLayout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    def doLayout(self, rect, testOnly):
        x, y = rect.x(), rect.y()
        lineHeight = 0
        for item in self._items:
            wid = item.widget()
            spaceX = self.horizontalSpacing()
            if spaceX == -1:
                spaceX = wid.style().layoutSpacing(QSizePolicy.PushButton, QSizePolicy.PushButton, Qt.Horizontal)
            spaceY = self.verticalSpacing()
            if spaceY == -1:
                spaceY = wid.style().layoutSpacing(QSizePolicy.PushButton, QSizePolicy.PushButton, Qt.Vertical)
            
            nextX = x + item.sizeHint().width() + spaceX
            if nextX - spaceX > rect.right() and lineHeight > 0:
                x = rect.x()
                y = y + lineHeight + spaceY
                nextX = x + item.sizeHint().width() + spaceX
                lineHeight = 0

            if not testOnly:
                item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))

            x = nextX
            lineHeight = max(lineHeight, item.sizeHint().height())

        return y + lineHeight - rect.y()

    def smartSpacing(self, pm):
        parent = self.parent()
        if not parent:
            return -1
        elif parent.isWidgetType():
            return parent.style().pixelMetric(pm, None, parent)
        else:
            return parent.spacing()


class TitledCard(QGroupBox):
    def __init__(self, title, object_name, parent=None):
        super().__init__(title, parent)
        self.setObjectName(object_name)
        self._layout = QVBoxLayout(self)
        
        self._layout.setContentsMargins(12, 18, 12, 8)
        self._layout.setSpacing(8)
        self.setStyleSheet(f"""
            QGroupBox#{object_name} {{
                background-color: {Color.BG_SURFACE};
                border: 1px solid {Color.BORDER};
                border-radius: {theme.RADIUS_LG}px;
                margin-top: 8px;
                padding: 0px; 
                font-weight: 600;
            }}
            QGroupBox#{object_name}::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 12px;
                top: 0px;
                padding: 0 6px;
                color: {Color.TEXT_SECONDARY};
                background-color: {Color.BG_SURFACE};
            }}
        """)

    def layout(self):
        return self._layout

    def addWidget(self, w):
        self._layout.addWidget(w)

    def addLayout(self, l):
        self._layout.addLayout(l)


class _DetailsWorker(QObject):
    finished = Signal(object, object)

    def __init__(self, session, manga_id):
        super().__init__()
        self.session = session
        self.manga_id = manga_id

    def run(self):
        details = net.fetch_manga_full_details(self.manga_id, self.session)
        cover_bytes = None
        cover_url = details.get("cover_url") if details else None
        if cover_url:
            cover_bytes = net.fetch_image_bytes(self.session, cover_url)
        self.finished.emit(details, cover_bytes)


class _MangaBakaSearchWorker(QObject):
    finished = Signal(list, object)

    def __init__(self, query):
        super().__init__()
        self.query = query

    def run(self):
        results, error = net.search_mangabaka(self.query)
        self.finished.emit(results, error)


class _ThumbnailWorker(QObject):
    finished = Signal(object, object)

    def __init__(self, row_key, url):
        super().__init__()
        self.row_key = row_key
        self.url = url

    def run(self):
        self.finished.emit(self.row_key, net.fetch_image_bytes(None, self.url))


class _ImageFetchWorker(QObject):
    finished = Signal(str, object) 

    def __init__(self, target, url):
        super().__init__()
        self.target = target
        self.url = url

    def run(self):
        self.finished.emit(self.target, net.fetch_image_bytes(None, self.url))


def _search_manga_by_kind(session, kind, value):
    """Runs a manga search either by direct ID lookup or free-text query,
    matching the branching that used to live in the now-removed
    _SearchWorker.run(). Returns a list of result dicts either way, so it
    can be wrapped directly in a workers.CallableWorker."""
    if kind == "id":
        title, cover_url = net.fetch_manga_brief(value, session)
        if title:
            return [{"id": value, "title": title, "status": "", "_cover_url": cover_url}]
        return []
    return net.search_manga(value, session)


def web_label(text):
    lbl = QLabel(text.upper())
    lbl.setStyleSheet(f"color: {Color.TEXT_SECONDARY}; font-weight: 700; font-size: 11px; letter-spacing: 0.5px;")
    return lbl


class _CreateFromMangaBakaDialog(QDialog):
    _THUMB_W, _THUMB_H = 40, 56

    def __init__(self, session, dark_input_style, prefill_query="", parent=None):
        super().__init__(parent)
        self.session = session
        self.created_id = None
        self.created_title = None
        self._pending_metadata = None
        
        self._threads = []
        self._workers = []
        self._thumb_threads = []
        self._thumb_workers = []
        self._search_row_widgets = {}
        
        self._selected_genres = set()
        self._genre_btns = {}
        self._alt_titles = []
        self._dark_input_style = dark_input_style

        self.setWindowTitle("Create manga from MangaBaka")
        self.setStyleSheet(f"QDialog {{ background-color: {Color.BG_APP}; }}")
        
        if parent and parent.windowIcon() and not parent.windowIcon().isNull():
            self.setWindowIcon(parent.windowIcon())
        elif _FAVICON_PATH.exists():
            self.setWindowIcon(QIcon(str(_FAVICON_PATH)))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        top_widget = QWidget()
        top_widget.setObjectName("TopWidget")
        top_widget.setStyleSheet(f"QWidget#TopWidget {{ background-color: transparent; border: none; }}")
        top_layout = QVBoxLayout(top_widget)
        top_layout.setContentsMargins(20, 20, 20, 10)
        top_layout.setSpacing(10)

        top_layout.addWidget(hint_label("Search MangaBaka by title, or paste a series URL below."))
        search_row = QHBoxLayout()
        search_row.setSpacing(10)
        
        self.mb_search_input = QLineEdit()
        self.mb_search_input.setPlaceholderText("Series title\u2026")
        if prefill_query and not prefill_query.strip().lower().startswith(("http://", "https://")):
            self.mb_search_input.setText(prefill_query.strip())
        self.mb_search_input.setStyleSheet(self._dark_input_style)
        self.mb_search_input.returnPressed.connect(self._on_mangabaka_search)
        
        self.mb_search_glass = GlassBox(tint_rgba="rgba(92, 225, 230, 18)", border_color=Color.ACCENT_SOFT_BORDER)
        self.mb_search_glass.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        search_glass_layout = QHBoxLayout(self.mb_search_glass)
        search_glass_layout.setContentsMargins(16, 4, 16, 4)
        self.mb_search_btn = make_flat_link(QPushButton("Search"), color=Color.ACCENT, hover_color=Color.ACCENT_HOVER, bold=True)
        self.mb_search_btn.clicked.connect(self._on_mangabaka_search)
        search_glass_layout.addWidget(self.mb_search_btn)
        
        search_row.addWidget(self.mb_search_input, 1)
        search_row.addWidget(self.mb_search_glass)
        top_layout.addLayout(search_row)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setProperty("role", "muted")
        top_layout.addWidget(self.status_label)

        self.view_existing_btn = make_flat_link(QPushButton("View existing manga instead"))
        self.view_existing_btn.setVisible(False)
        self.view_existing_btn.clicked.connect(self._on_view_existing)
        top_layout.addWidget(self.view_existing_btn)

        self.search_container = QWidget()
        self.search_container.setObjectName("SearchContainer")
        self.search_container.setStyleSheet(f"QWidget#SearchContainer {{ background-color: transparent; border: none; }}")
        search_layout = QVBoxLayout(self.search_container)
        search_layout.setContentsMargins(20, 0, 20, 20)
        search_layout.setSpacing(8)
        
        self.results_label = section_label("RESULTS")
        search_layout.addWidget(self.results_label)
        
        self.mb_results_list = QListWidget()
        self.mb_results_list.setFrameShape(QFrame.NoFrame)
        self.mb_results_list.setObjectName("ResultsList")
        self.mb_results_list.itemClicked.connect(self._on_mangabaka_result_clicked)
        self.mb_results_list.setSpacing(8)
        self.mb_results_list.setStyleSheet(f"""
            QListWidget#ResultsList {{
                background-color: transparent;
                border: none;
                outline: none;
            }}
            QListWidget#ResultsList::item {{
                background-color: {Color.BG_SURFACE};
                border: 1px solid {Color.BORDER};
                border-radius: {theme.RADIUS_MD}px;
            }}
            QListWidget#ResultsList::item:hover {{
                background-color: {Color.BG_HOVER};
                border-color: {Color.ACCENT_SOFT_BORDER};
            }}
            QListWidget#ResultsList::item:selected {{
                background-color: {Color.ACCENT_SOFT};
                border: 1px solid {Color.ACCENT};
            }}
        """)
        search_layout.addWidget(self.mb_results_list)

        self.form_scroll = QScrollArea()
        self.form_scroll.setWidgetResizable(True)
        self.form_scroll.setFrameShape(QFrame.NoFrame)
        self.form_scroll.setObjectName("FormScrollArea")
        self.form_scroll.setStyleSheet("QScrollArea#FormScrollArea { background: transparent; border: none; } QWidget#scrollAreaWidgetContents { background: transparent; border: none; }")
        self.form_scroll.setVisible(False)
        
        self.form_widget = QWidget()
        self.form_widget.setObjectName("scrollAreaWidgetContents")
        self._build_form()
        self.form_scroll.setWidget(self.form_widget)

        self.footer_widget = QWidget()
        self.footer_widget.setObjectName("FooterWidget")
        self.footer_widget.setStyleSheet(f"QWidget#FooterWidget {{ background-color: transparent; border: none; }}")
        footer_layout = QHBoxLayout(self.footer_widget)
        footer_layout.setContentsMargins(20, 10, 20, 20)
        footer_layout.setSpacing(16)
        
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setCursor(Qt.PointingHandCursor)
        self.cancel_btn.setAutoDefault(False)
        self.cancel_btn.clicked.connect(self.reject)
        self.cancel_btn.setStyleSheet(f"background-color: transparent; color: {Color.TEXT_PRIMARY}; border: 1px solid {Color.BORDER}; border-radius: {theme.RADIUS_SM}px; padding: 6px 18px;")
        
        self.create_glass = GlassBox(tint_rgba="rgba(92, 225, 230, 18)", border_color=Color.ACCENT_SOFT_BORDER)
        self.create_glass.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        create_glass_layout = QHBoxLayout(self.create_glass)
        create_glass_layout.setContentsMargins(16, 4, 16, 4)
        self.create_btn = make_flat_link(QPushButton("Create Manga"), color=Color.ACCENT, hover_color=Color.ACCENT_HOVER, bold=True)
        self.create_btn.setAutoDefault(False)
        self.create_btn.setEnabled(False)
        self.create_btn.clicked.connect(self._on_create)
        create_glass_layout.addWidget(self.create_btn)
        
        footer_layout.addStretch(1)
        footer_layout.addWidget(self.cancel_btn)
        footer_layout.addWidget(self.create_glass)

        layout.addWidget(top_widget, 0)
        layout.addWidget(self.search_container, 1)
        layout.addWidget(self.form_scroll, 1)
        layout.addWidget(self.footer_widget, 0)

        self._switch_to_search()

        if self.mb_search_input.text().strip():
            self._on_mangabaka_search()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if self.form_scroll.isVisible():
                if self.alt_input.hasFocus():
                    self._add_alt_title_from_input()
                    event.accept()
                    return
                event.ignore()
                return
        super().keyPressEvent(event)

    def _center_window(self):
        if self.parentWidget():
            parent_geo = self.parentWidget().window().geometry()
            my_geo = self.geometry()
            x = parent_geo.x() + (parent_geo.width() - my_geo.width()) // 2
            y = parent_geo.y() + (parent_geo.height() - my_geo.height()) // 2
            self.move(max(0, x), max(0, y))

    def _switch_to_search(self):
        self.form_scroll.setVisible(False)
        self.footer_widget.setVisible(False)
        self.search_container.setVisible(True)
        self.resize(600, 420)
        self._center_window()

    def _switch_to_review(self):
        self.search_container.setVisible(False)
        self.form_scroll.setVisible(True)
        self.footer_widget.setVisible(True)
        self.resize(950, 700)
        self._center_window()

    def _build_form(self):
        base_layout = QVBoxLayout(self.form_widget)
        base_layout.setContentsMargins(20, 0, 20, 10)
        
        card_frame = QFrame()
        card_frame.setObjectName("MetadataOuterCard")
        card_frame.setStyleSheet(f"QFrame#MetadataOuterCard {{ background-color: {Color.BG_SURFACE}; border: 1px solid {Color.BORDER}; border-radius: {theme.RADIUS_LG}px; }}")
        base_layout.addWidget(card_frame)

        form_layout = QHBoxLayout(card_frame)
        form_layout.setContentsMargins(24, 24, 24, 24)
        form_layout.setSpacing(32)

        left_col = QVBoxLayout()
        left_col.setAlignment(Qt.AlignTop)
        left_col.setSpacing(24)
        
        left_widget = QWidget()
        left_widget.setObjectName("LeftColumnWidget")
        left_widget.setStyleSheet("QWidget#LeftColumnWidget { background-color: transparent; border: none; }")
        left_widget.setFixedWidth(220)
        left_widget.setLayout(left_col)
        left_col.setContentsMargins(0, 0, 0, 0)

        cover_layout = QVBoxLayout()
        cover_layout.setSpacing(8)
        
        cover_header_row = QHBoxLayout()
        cover_header_row.setContentsMargins(0, 0, 0, 0)
        cover_header_row.addWidget(web_label("COVER"))
        cover_header_row.addStretch(1)
        clear_cover_btn = make_flat_link(QPushButton("CLEAR"), color=Color.TEXT_MUTED, hover_color=Color.TEXT_PRIMARY)
        clear_cover_btn.clicked.connect(lambda: self.cover_url_input.setText(""))
        cover_header_row.addWidget(clear_cover_btn)
        cover_layout.addLayout(cover_header_row)
        
        self.cover_preview_box = QLabel("NO COVER URL")
        self.cover_preview_box.setObjectName("CoverPreview")
        self.cover_preview_box.setAlignment(Qt.AlignCenter)
        self.cover_preview_box.setFixedSize(220, 310)
        self.cover_preview_box.setScaledContents(True)
        self.cover_preview_box.setStyleSheet(f"QLabel#CoverPreview {{ background-color: {Color.BG_INPUT}; color: {Color.TEXT_MUTED}; border: 1px dashed {Color.BORDER_SOFT}; border-radius: {theme.RADIUS_MD}px; font-size: 10px; font-weight: 600; letter-spacing: 0.5px; }}")
        cover_layout.addWidget(self.cover_preview_box)
        
        cover_actions_row = QHBoxLayout()
        cover_url_btn = make_flat_link(QPushButton("🌐 FROM URL"), color=Color.TEXT_MUTED, hover_color=Color.TEXT_PRIMARY)
        cover_url_btn.setStyleSheet(cover_url_btn.styleSheet() + " font-size: 10px; font-weight: 700;")
        cover_actions_row.addWidget(cover_url_btn)
        cover_actions_row.addStretch(1)
        cover_layout.addLayout(cover_actions_row)

        self.cover_url_input = QLineEdit()
        self.cover_url_input.setPlaceholderText("https://...")
        self.cover_url_input.setStyleSheet(self._dark_input_style)
        self.cover_url_input.textChanged.connect(lambda text: self._trigger_image_fetch("cover", text))
        cover_layout.addWidget(self.cover_url_input)
        cover_url_btn.clicked.connect(self.cover_url_input.setFocus)
        left_col.addLayout(cover_layout)

        banner_layout = QVBoxLayout()
        banner_layout.setSpacing(8)
        
        banner_header_row = QHBoxLayout()
        banner_header_row.setContentsMargins(0, 0, 0, 0)
        banner_header_row.addWidget(web_label("BANNER"))
        banner_header_row.addStretch(1)
        clear_banner_btn = make_flat_link(QPushButton("CLEAR"), color=Color.TEXT_MUTED, hover_color=Color.TEXT_PRIMARY)
        clear_banner_btn.clicked.connect(lambda: self.banner_url_input.setText(""))
        banner_header_row.addWidget(clear_banner_btn)
        banner_layout.addLayout(banner_header_row)
        
        self.banner_preview_box = QLabel("NO BANNER URL")
        self.banner_preview_box.setObjectName("BannerPreview")
        self.banner_preview_box.setAlignment(Qt.AlignCenter)
        self.banner_preview_box.setFixedSize(220, 80)
        self.banner_preview_box.setScaledContents(True)
        self.banner_preview_box.setStyleSheet(f"QLabel#BannerPreview {{ background-color: {Color.BG_INPUT}; color: {Color.TEXT_MUTED}; border: 1px dashed {Color.BORDER_SOFT}; border-radius: {theme.RADIUS_MD}px; font-size: 10px; font-weight: 600; letter-spacing: 0.5px; }}")
        banner_layout.addWidget(self.banner_preview_box)
        
        banner_actions_row = QHBoxLayout()
        banner_url_btn = make_flat_link(QPushButton("🌐 FROM URL"), color=Color.TEXT_MUTED, hover_color=Color.TEXT_PRIMARY)
        banner_url_btn.setStyleSheet(banner_url_btn.styleSheet() + " font-size: 10px; font-weight: 700;")
        banner_actions_row.addWidget(banner_url_btn)
        banner_actions_row.addStretch(1)
        banner_layout.addLayout(banner_actions_row)

        self.banner_url_input = QLineEdit()
        self.banner_url_input.setPlaceholderText("https://...")
        self.banner_url_input.setStyleSheet(self._dark_input_style)
        self.banner_url_input.textChanged.connect(lambda text: self._trigger_image_fetch("banner", text))
        banner_layout.addWidget(self.banner_url_input)

        banner_url_btn.clicked.connect(self.banner_url_input.setFocus)
        left_col.addLayout(banner_layout)

        form_layout.addWidget(left_widget)

        right_col = QVBoxLayout()
        right_col.setAlignment(Qt.AlignTop)
        right_col.setSpacing(16)

        title_layout = QVBoxLayout()
        title_layout.setSpacing(6)
        title_layout.addWidget(web_label("Title"))
        self.title_input = QLineEdit()
        self.title_input.setStyleSheet(self._dark_input_style)
        title_layout.addWidget(self.title_input)
        right_col.addLayout(title_layout)

        status_origin_layout = QHBoxLayout()
        status_col = QVBoxLayout()
        status_col.setSpacing(6)
        status_col.addWidget(web_label("Status"))
        self.status_combo = QComboBox()
        self.status_combo.addItems(["Ongoing", "Completed", "Hiatus", "Cancelled", "Unknown"])
        self.status_combo.setStyleSheet(self._dark_input_style)
        attach_combo_dots_overlay(self.status_combo)
        status_col.addWidget(self.status_combo)
        status_origin_layout.addLayout(status_col, 1)

        origin_col = QVBoxLayout()
        origin_col.setSpacing(6)
        origin_col.addWidget(web_label("Country of Origin"))
        self.origin_combo = QComboBox()
        self.origin_combo.addItems(["Unknown", "Japan (JP)", "South Korea (KR)", "China (CN)", "Taiwan (TW)"])
        self.origin_combo.setStyleSheet(self._dark_input_style)
        attach_combo_dots_overlay(self.origin_combo)
        origin_col.addWidget(self.origin_combo)
        status_origin_layout.addLayout(origin_col, 1)
        right_col.addLayout(status_origin_layout)

        desc_layout = QVBoxLayout()
        desc_layout.setSpacing(6)
        desc_layout.addWidget(web_label("Description"))
        self.desc_input = QTextEdit()
        self.desc_input.setStyleSheet(f"background-color: {Color.BG_INPUT}; color: {Color.TEXT_PRIMARY}; border: 1px solid {Color.BORDER}; border-radius: {theme.RADIUS_SM}px; padding: 7px;")
        self.desc_input.setMinimumHeight(100)
        self.desc_input.setMaximumHeight(140) 
        desc_layout.addWidget(self.desc_input)
        right_col.addLayout(desc_layout)

        genres_layout = QVBoxLayout()
        genres_layout.setSpacing(6)
        genres_layout.addWidget(web_label("Genres"))
        
        self.genre_chips_widget = QWidget()
        self.genre_chips_widget.setObjectName("GenreChipsWidget")
        self.genre_chips_widget.setStyleSheet("QWidget#GenreChipsWidget { background-color: transparent; border: none; }")
        self.genre_chips_layout = _FlowLayout(margin=0, hSpacing=6, vSpacing=6)
        self.genre_chips_widget.setLayout(self.genre_chips_layout)
        genres_layout.addWidget(self.genre_chips_widget)

        self.genre_search_input = QLineEdit()
        self.genre_search_input.setPlaceholderText("Search genres...")
        self.genre_search_input.setStyleSheet(self._dark_input_style)
        genres_layout.addWidget(self.genre_search_input)

        genre_scroll = QScrollArea()
        genre_scroll.setWidgetResizable(True)
        genre_scroll.setMaximumHeight(200)
        genre_scroll.setObjectName("GenreScrollArea")
        genre_scroll.setStyleSheet("QScrollArea#GenreScrollArea { border: none; background-color: transparent; }")
        
        genre_grid_container = QWidget()
        genre_grid_container.setObjectName("GenreGridContainer")
        genre_grid_container.setStyleSheet("QWidget#GenreGridContainer { background-color: transparent; border: none; }")
        genre_grid_layout = QVBoxLayout(genre_grid_container)
        genre_grid_layout.setContentsMargins(10, 10, 10, 10)
        genre_grid_layout.setSpacing(12)
        
        for group, tags in net.GENRE_TAXONOMY.items():
            grp_lbl = QLabel(group)
            grp_lbl.setStyleSheet(f"color: {Color.TEXT_MUTED}; font-weight: 600; font-size: 11px;")
            genre_grid_layout.addWidget(grp_lbl)
            
            flow = _FlowLayout(margin=0, hSpacing=6, vSpacing=6)
            for tag in tags:
                btn = QPushButton(tag)
                btn.setCheckable(True)
                btn.setCursor(Qt.PointingHandCursor)
                btn.toggled.connect(lambda checked, t=tag, b=btn: self._on_genre_toggled(t, b, checked))
                self._update_tag_btn_style(btn, False)
                flow.addWidget(btn)
                if tag not in self._genre_btns:
                    self._genre_btns[tag] = []
                self._genre_btns[tag].append(btn)
            
            flow_widget = QWidget()
            flow_widget.setObjectName("GenreFlowWidget")
            flow_widget.setStyleSheet("QWidget#GenreFlowWidget { background-color: transparent; border: none; }")
            flow_widget.setLayout(flow)
            genre_grid_layout.addWidget(flow_widget)
            
        genre_scroll.setWidget(genre_grid_container)
        genres_layout.addWidget(genre_scroll)
        right_col.addLayout(genres_layout)

        alt_layout = QVBoxLayout()
        alt_layout.setSpacing(6)
        alt_layout.addWidget(web_label("Alt Titles"))
        
        self.alt_chips_widget = QWidget()
        self.alt_chips_widget.setObjectName("AltChipsWidget")
        self.alt_chips_widget.setStyleSheet("QWidget#AltChipsWidget { background-color: transparent; border: none; }")
        self.alt_chips_layout = _FlowLayout(margin=0, hSpacing=6, vSpacing=6)
        self.alt_chips_widget.setLayout(self.alt_chips_layout)
        alt_layout.addWidget(self.alt_chips_widget)

        alt_input_row = QHBoxLayout()
        self.alt_input = QLineEdit()
        self.alt_input.setPlaceholderText("Add alt title...")
        self.alt_input.setStyleSheet(self._dark_input_style)
        self.alt_input.returnPressed.connect(self._add_alt_title_from_input)
        
        self.alt_add_btn = QPushButton("+ Add")
        self.alt_add_btn.setCursor(Qt.PointingHandCursor)
        self.alt_add_btn.setAutoDefault(False)
        self.alt_add_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {Color.BG_RAISED};
                color: {Color.TEXT_PRIMARY};
                border: 1px solid {Color.BORDER};
                border-radius: {theme.RADIUS_SM}px;
                padding: 7px 14px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: {Color.BG_HOVER};
                border-color: {Color.ACCENT};
                color: {Color.ACCENT};
            }}
        """)
        self.alt_add_btn.clicked.connect(self._add_alt_title_from_input)
        
        alt_input_row.addWidget(self.alt_input, 1)
        alt_input_row.addWidget(self.alt_add_btn)
        alt_layout.addLayout(alt_input_row)
        right_col.addLayout(alt_layout)

        auth_art_layout = QHBoxLayout()
        
        auth_col = QVBoxLayout()
        auth_col.setSpacing(6)
        auth_col.addWidget(web_label("Authors"))
        self.authors_input = QLineEdit()
        self.authors_input.setStyleSheet(self._dark_input_style)
        auth_col.addWidget(self.authors_input)
        auth_art_layout.addLayout(auth_col, 1)

        art_col = QVBoxLayout()
        art_col.setSpacing(6)
        art_col.addWidget(web_label("Artists"))
        self.artists_input = QLineEdit()
        self.artists_input.setStyleSheet(self._dark_input_style)
        art_col.addWidget(self.artists_input)
        auth_art_layout.addLayout(art_col, 1)
        
        right_col.addLayout(auth_art_layout)

        id_layout = QHBoxLayout()
        
        al_col = QVBoxLayout()
        al_col.setSpacing(6)
        al_col.addWidget(web_label("Anilist ID"))
        self.anilist_input = QLineEdit()
        self.anilist_input.setStyleSheet(self._dark_input_style)
        al_col.addWidget(self.anilist_input)
        id_layout.addLayout(al_col, 1)

        mu_col = QVBoxLayout()
        mu_col.setSpacing(6)
        mu_col.addWidget(web_label("MangaUpdates ID"))
        self.mu_input = QLineEdit()
        self.mu_input.setStyleSheet(self._dark_input_style)
        mu_col.addWidget(self.mu_input)
        id_layout.addLayout(mu_col, 1)
        
        right_col.addLayout(id_layout)

        src_layout = QVBoxLayout()
        src_layout.setSpacing(6)
        src_layout.addWidget(web_label("Source URL (optional)"))
        self.source_input = QLineEdit()
        self.source_input.setStyleSheet(self._dark_input_style)
        src_layout.addWidget(self.source_input)
        right_col.addLayout(src_layout)

        form_layout.addLayout(right_col, 1)

    def _trigger_image_fetch(self, target, url):
        url = url.strip()
        if not url:
            if target == "cover":
                self.cover_preview_box.setPixmap(QPixmap())
                self.cover_preview_box.setText("NO COVER URL")
            else:
                self.banner_preview_box.setPixmap(QPixmap())
                self.banner_preview_box.setText("NO BANNER URL")
            return

        workers.prune_finished(self._threads, self._workers)
        worker = _ImageFetchWorker(target, url)
        thread, worker = workers.run_worker(worker, on_finished=self._on_image_fetched)
        self._threads.append(thread)
        self._workers.append(worker)

    def _on_image_fetched(self, target, image_bytes):
        if not image_bytes:
            return
            
        pixmap = QPixmap()
        if pixmap.loadFromData(image_bytes):
            if target == "cover":
                self.cover_preview_box.setText("")
                self.cover_preview_box.setPixmap(pixmap)
            elif target == "banner":
                self.banner_preview_box.setText("")
                self.banner_preview_box.setPixmap(pixmap)

    def _update_tag_btn_style(self, btn, checked):
        if checked:
            btn.setStyleSheet(f"background-color: {Color.ACCENT}; color: {Color.TEXT_ON_ACCENT}; border: 1px solid {Color.ACCENT}; border-radius: {theme.RADIUS_SM}px; padding: 4px 10px; font-weight: 600;")
        else:
            btn.setStyleSheet(f"background-color: {Color.BG_RAISED}; color: {Color.TEXT_PRIMARY}; border: 1px solid {Color.BORDER}; border-radius: {theme.RADIUS_SM}px; padding: 4px 10px;")

    def _on_genre_toggled(self, tag, btn, checked):
        if checked:
            self._selected_genres.add(tag)
        else:
            self._selected_genres.discard(tag)
            
        for b in self._genre_btns.get(tag, []):
            b.blockSignals(True)
            b.setChecked(checked)
            self._update_tag_btn_style(b, checked)
            b.blockSignals(False)
            
        self._refresh_genre_chips()

    def _refresh_genre_buttons(self):
        for tag, btns in self._genre_btns.items():
            checked = any(tag.lower() == str(sg).lower() for sg in self._selected_genres)
            if checked:
                self._selected_genres.add(tag) 
                
            for b in btns:
                b.blockSignals(True)
                b.setChecked(checked)
                self._update_tag_btn_style(b, checked)
                b.blockSignals(False)
                
        self._refresh_genre_chips()

    def _refresh_genre_chips(self):
        while self.genre_chips_layout.count():
            item = self.genre_chips_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for tag in sorted(self._selected_genres):
            chip = QPushButton(f"{tag}  ✕")
            chip.setCursor(Qt.PointingHandCursor)
            chip.setStyleSheet(f"background-color: transparent; color: {Color.TEXT_PRIMARY}; border: 1px solid {Color.BORDER}; border-radius: {theme.RADIUS_SM}px; padding: 4px 10px; font-weight: 600;")
            chip.clicked.connect(lambda _, t=tag: self._on_genre_toggled(t, None, False))
            self.genre_chips_layout.addWidget(chip)

    def _add_alt_title_from_input(self):
        title = self.alt_input.text().strip()
        if title and title not in self._alt_titles:
            self._alt_titles.append(title)
            self._refresh_alt_titles()
        self.alt_input.clear()

    def _remove_alt_title(self, title):
        if title in self._alt_titles:
            self._alt_titles.remove(title)
            self._refresh_alt_titles()

    def _refresh_alt_titles(self):
        while self.alt_chips_layout.count():
            item = self.alt_chips_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for title in self._alt_titles:
            chip = QPushButton(f"{title}  ✕")
            chip.setCursor(Qt.PointingHandCursor)
            chip.setStyleSheet(f"background-color: transparent; color: {Color.TEXT_PRIMARY}; border: 1px solid {Color.BORDER}; border-radius: {theme.RADIUS_SM}px; padding: 4px 10px; font-weight: 600;")
            chip.clicked.connect(lambda _, t=title: self._remove_alt_title(t))
            self.alt_chips_layout.addWidget(chip)

    def _busy(self, is_busy, message=""):
        self.mb_search_btn.setEnabled(not is_busy)
        self.mb_search_input.setEnabled(not is_busy)
        self.create_btn.setEnabled(not is_busy)
        if message:
            self.status_label.setText(message)

    def _on_mangabaka_search(self):
        query = self.mb_search_input.text().strip()
        if not query:
            return
            
        if self.form_scroll.isVisible():
            self._switch_to_search()
            
        self._busy(True)
        self.mb_results_list.clear()
        self._search_row_widgets.clear()
        searching_item = QListWidgetItem("Searching MangaBaka\u2026")
        searching_item.setFlags(Qt.NoItemFlags)
        self.mb_results_list.addItem(searching_item)

        worker = _MangaBakaSearchWorker(query)
        self._run_worker(worker, self._on_mangabaka_search_finished)

    def _on_mangabaka_search_finished(self, results, error):
        self._busy(False)
        self.mb_results_list.clear()
        self._search_row_widgets.clear()

        if error:
            placeholder = QListWidgetItem(f"Search failed: {error}")
            placeholder.setFlags(Qt.NoItemFlags)
            self.mb_results_list.addItem(placeholder)
            return

        if not results:
            placeholder = QListWidgetItem("No results \u2014 try a different title.")
            placeholder.setFlags(Qt.NoItemFlags)
            self.mb_results_list.addItem(placeholder)
            
            manual_item = QListWidgetItem("➕ Create a blank manual entry in app")
            manual_item.setData(Qt.UserRole, {"_action": "manual_entry"})
            self.mb_results_list.addItem(manual_item)

            web_item = QListWidgetItem("🌐 Open mangadot.net/add-manga in browser")
            web_item.setData(Qt.UserRole, {"_action": "open_website"})
            self.mb_results_list.addItem(web_item)
            return

        for manga in results:
            self._add_mangabaka_result_row(manga)

    def _add_mangabaka_result_row(self, manga):
        row_key = manga["id"]
        item = QListWidgetItem()
        item.setData(Qt.UserRole, manga)
        
        item.setSizeHint(QSize(0, 84)) 

        row_widget = QWidget()
        row_widget.setObjectName("ResultRowWidget")
        row_widget.setStyleSheet("QWidget#ResultRowWidget { background-color: transparent; border: none; }")
        
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(16, 0, 16, 0)
        row_layout.setSpacing(16)

        cover_label = QLabel()
        cover_label.setFixedSize(self._THUMB_W, self._THUMB_H)
        cover_label.setAlignment(Qt.AlignCenter)
        cover_label.setStyleSheet(
            f"background-color: {Color.BG_INPUT}; border: 1px solid {Color.BORDER}; "
            f"border-radius: {theme.RADIUS_SM}px; color: {Color.TEXT_MUTED}; font-size: 9px;"
        )
        cover_label.setText("\u2026")
        
        row_layout.addWidget(cover_label, alignment=Qt.AlignVCenter)

        text_col = QVBoxLayout()
        text_col.setAlignment(Qt.AlignVCenter)
        text_col.setSpacing(2)
        title = str(manga.get("title", "")).strip()
        if len(title) > 70:
            title = title[:70].rsplit(" ", 1)[0] + "\u2026"
        title_label = QLabel(title)
        title_label.setWordWrap(True)
        title_label.setStyleSheet("font-weight: 600; background-color: transparent;")
        text_col.addWidget(title_label)

        status = str(manga.get("status") or "").strip()
        if status and status.lower() != "unknown":
            status_label = QLabel(status.title())
            status_label.setProperty("role", "muted")
            status_label.setStyleSheet("background-color: transparent;")
            text_col.addWidget(status_label)

        row_layout.addLayout(text_col, 1)

        self.mb_results_list.addItem(item)
        self.mb_results_list.setItemWidget(item, row_widget)

        self._search_row_widgets[row_key] = cover_label

        cover_url = manga.get("cover_url")
        if cover_url:
            self._load_thumbnail(row_key, cover_url)
        else:
            cover_label.setText("No\ncover")

    def _load_thumbnail(self, row_key, url):
        workers.prune_finished(self._thumb_threads, self._thumb_workers)
        worker = _ThumbnailWorker(row_key, url)
        thread, worker = workers.run_worker(worker, on_finished=self._on_thumbnail_loaded)
        self._thumb_threads.append(thread)
        self._thumb_workers.append(worker)

    def _on_thumbnail_loaded(self, row_key, cover_bytes):
        cover_label = self._search_row_widgets.get(row_key)
        if cover_label is None:
            return
        if cover_bytes:
            pixmap = QPixmap()
            if pixmap.loadFromData(cover_bytes):
                cover_label.setText("")
                cover_label.setPixmap(
                    pixmap.scaled(
                        self._THUMB_W, self._THUMB_H,
                        Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
                    )
                )
                return
        cover_label.setText("No\ncover")

    def _on_mangabaka_result_clicked(self, item):
        manga = item.data(Qt.UserRole)
        if not manga:
            return

        if manga.get("_action") == "open_website":
            webbrowser.open("https://mangadot.net/add-manga")
            return
            
        if manga.get("_action") == "manual_entry":
            self._pending_metadata = {}
            self.view_existing_btn.setVisible(False)
            
            self.title_input.setText("")
            self.desc_input.setPlainText("")
            self.status_combo.setCurrentIndex(0)
            self.origin_combo.setCurrentIndex(0)
            
            self._selected_genres.clear()
            self._refresh_genre_buttons()
            
            self._alt_titles.clear()
            self._refresh_alt_titles()
            
            self.authors_input.setText("")
            self.artists_input.setText("")
            self.anilist_input.setText("")
            self.mu_input.setText("")
            self.source_input.setText("")
            
            self.cover_url_input.setText("")
            self.banner_url_input.setText("")
            self.cover_preview_box.setPixmap(QPixmap())
            self.cover_preview_box.setText("NO COVER URL")
            self.banner_preview_box.setPixmap(QPixmap())
            self.banner_preview_box.setText("NO BANNER URL")
            
            self.create_btn.setEnabled(True)
            self._switch_to_review()
            return
            
        self._pending_metadata = None
        self.view_existing_btn.setVisible(False)
        self._switch_to_review()
        
        self._busy(True, f"Fetching \u201c{manga.get('title', '')}\u201d from MangaBaka\u2026")
        worker = workers.CallableWorker(net.fetch_mangabaka_metadata, manga["mangabaka_url"], self.session)
        self._run_worker(worker, self._on_fetch_finished)

    def _run_worker(self, worker, on_finished):
        workers.prune_finished(self._threads, self._workers)
        thread, worker = workers.run_worker(worker, on_finished=on_finished)
        self._threads.append(thread)
        self._workers.append(worker)

    def _on_fetch_finished(self, result):
        self._busy(False)

        if not result.get("ok"):
            self.status_label.setText(f"Couldn't fetch that series: {result.get('error', 'unknown error')}")
            self._switch_to_search()
            return

        if result.get("duplicate"):
            self._existing_id = result.get("id")
            self.status_label.setText(f"\u201c{result.get('title')}\u201d already exists on MangaDot.")
            self.view_existing_btn.setVisible(True)
            self.create_btn.setEnabled(False)
            self._switch_to_search()
            return

        parsed = net.parse_mangabaka_for_ui(result["data"])
        self._pending_metadata = result["data"]
        self.status_label.setText("")

        self.title_input.setText(parsed["title"])
        self.desc_input.setPlainText(parsed["description"])

        idx = self.status_combo.findText(parsed["status"])
        self.status_combo.setCurrentIndex(idx if idx >= 0 else 0)

        idx = self.origin_combo.findText(parsed["origin_val"])
        self.origin_combo.setCurrentIndex(idx if idx >= 0 else 0)

        self._selected_genres = set(parsed["genres"])
        self._refresh_genre_buttons()

        self._alt_titles = parsed["alt_titles"]
        self._refresh_alt_titles()

        self.authors_input.setText(parsed["authors"])
        self.artists_input.setText(parsed["artists"])
        self.anilist_input.setText(parsed["anilist_id"])
        self.mu_input.setText(parsed["mangaupdates_id"])
        self.source_input.setText(parsed["source_url"])
        self.cover_url_input.setText(parsed["cover_url"])
        self.banner_url_input.setText(parsed["banner_url"])

        self.create_btn.setEnabled(True)

    def _on_view_existing(self):
        self.created_id = getattr(self, "_existing_id", None)
        self.created_title = self.status_label.text()
        super().reject()

    def _on_create(self):
        if self._pending_metadata is None:
            return
            
        ui_data = {
            "title": self.title_input.text(),
            "description": self.desc_input.toPlainText(),
            "status": self.status_combo.currentText(),
            "origin": self.origin_combo.currentText(),
            "genres": list(self._selected_genres),
            "alt_titles": list(self._alt_titles),
            "authors": self.authors_input.text(),
            "artists": self.artists_input.text(),
            "anilist_id": self.anilist_input.text(),
            "mangaupdates_id": self.mu_input.text(),
            "source_url": self.source_input.text(),
            "cover_url": self.cover_url_input.text(),
            "banner_url": self.banner_url_input.text()
        }
        
        metadata = dict(self._pending_metadata)
        metadata.update(net.format_ui_for_mangabaka(ui_data))

        self._busy(True, "Creating on MangaDot\u2026")
        worker = workers.CallableWorker(net.create_manga_from_mangabaka, metadata, self.session)
        self._run_worker(worker, self._on_create_finished)

    def _on_create_finished(self, result):
        self._busy(False)
        if not result.get("ok"):
            self.status_label.setText(f"Couldn't create it: {result.get('error', 'unknown error')}")
            self.create_btn.setEnabled(True)
            return
        self.created_id = result.get("id")
        self.created_title = result.get("title")
        self.accept()

    def stop_background_work(self):
        for t in list(self._threads):
            if thread_is_running(t):
                t.quit()
                t.wait(2000)
        for t in list(self._thumb_threads):
            if thread_is_running(t):
                t.quit()
                t.wait(2000)

    def closeEvent(self, event):
        self.stop_background_work()
        super().closeEvent(event)


class PickerScreen(QWidget):
    picker_finished = Signal(str, int, str, str, int, str, str, str, bool, int, bool)

    def __init__(self, session=None, username="", parent=None):
        if isinstance(username, QWidget) and parent is None:
            parent = username
            username = ""
        super().__init__(parent)
        self.session = session
        self.username = username or ""
        self.selected_manga_id = None
        self.selected_manga_title = None
        self.selected_manga_details = None
        self._selected_cover_bytes = None
        self._threads = []
        self._workers = []

        cfg = config_mod.load_config()
        saved_lang = cfg.get("language", "en")
        saved_threads = cfg.get("threads", 5)

        muted_color = Color.TEXT_MUTED.replace("#", "%23")
        
        self._dark_input_style = f"""
            QComboBox, QLineEdit, QSpinBox {{
                background-color: {Color.BG_APP};
                color: {Color.TEXT_PRIMARY};
                border: 1px solid {Color.BORDER};
                border-radius: {theme.RADIUS_SM}px;
                padding: 7px 10px;
                selection-background-color: {Color.ACCENT_SOFT};
            }}
            QComboBox:hover, QLineEdit:hover, QSpinBox:hover {{
                border-color: {Color.ACCENT_SOFT_BORDER};
            }}
            QComboBox:focus, QLineEdit:focus, QSpinBox:focus {{
                border: 1px solid {Color.ACCENT};
            }}
            QComboBox::drop-down, QComboBox::drop-down:editable {{
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 28px;
                border-left: 1px solid {Color.BORDER};
                background-color: {Color.BG_RAISED};
                border-top-right-radius: {theme.RADIUS_SM}px;
                border-bottom-right-radius: {theme.RADIUS_SM}px;
            }}
            QComboBox::drop-down:hover {{
                background-color: {Color.BG_HOVER};
            }}
            QComboBox::down-arrow {{
                image: url("data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxNiIgaGVpZ2h0PSIxNiIgdmlld0JveD0iMCAwIDI0IDI0IiBmaWxsPSJub25lIiBzdHJva2U9IiM1Q0UxRTYiIHN0cm9rZS13aWR0aD0iMi41IiBzdHJva2UtbGluZWNhcD0icm91bmQiIHN0cm9rZS1saW5lam9pbj0icm91bmQiPjxwb2x5bGluZSBwb2ludHM9IjYgOSAxMiAxNSAxOCA5Ii8+PC9zdmc+");
                width: 14px;
                height: 14px;
            }}
            QComboBox::down-arrow:editable {{
                image: none;
                width: 0px;
                height: 0px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {Color.BG_RAISED};
                border: 1px solid {Color.BORDER};
                border-radius: {theme.RADIUS_SM}px;
                color: {Color.TEXT_PRIMARY};
                selection-background-color: {Color.ACCENT_SOFT};
                selection-color: {Color.TEXT_PRIMARY};
                outline: none;
                padding: 4px;
            }}
            QComboBox QAbstractItemView QScrollBar:vertical {{
                background: transparent;
                width: 12px;
                margin: 2px;
            }}
            QComboBox QAbstractItemView QScrollBar::handle:vertical {{
                background: {Color.BORDER};
                min-height: 24px;
                border-radius: 5px;
            }}
            QComboBox QAbstractItemView QScrollBar::handle:vertical:hover {{
                background: {Color.ACCENT_SOFT_BORDER};
            }}
            QComboBox QAbstractItemView QScrollBar::add-line:vertical,
            QComboBox QAbstractItemView QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            QComboBox QAbstractItemView QScrollBar::add-page:vertical,
            QComboBox QAbstractItemView QScrollBar::sub-page:vertical {{
                background: none;
            }}
        """

        outer_screen_layout = QVBoxLayout(self)
        outer_screen_layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("background: transparent;")
        # NOT setAlignment(Qt.AlignHCenter) - that flag's job is purely
        # horizontal centering of `content` when it's narrower than the
        # viewport, but combined with setWidgetResizable(True) it's a
        # known source of vertical content jump/misplacement in Qt when
        # the viewport suddenly becomes much larger than the content's
        # natural size (e.g. manually maximizing this window past its
        # default 1172x602) - the heading was observed sliding up under
        # the step strip instead of staying anchored at a fixed top
        # margin. Horizontal centering isn't actually needed from the
        # scroll area itself here: `content`'s own QVBoxLayout below
        # already stretches to fill available width via its margins, so
        # removing this only drops the (buggy) extra centering behavior.
        outer_screen_layout.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)

        outer = QVBoxLayout(content)
        outer.setContentsMargins(28, 12, 28, 12)
        outer.setSpacing(10)

        header_row = QHBoxLayout()
        header_row.setSpacing(12)
        header_row.addWidget(heading("Choose what to upload", "Pick a folder of chapters, then match it to the manga on MangaDot."), 1)

        self.btn_upload_history = make_flat_link(
            QPushButton("\U0001F4DC  Upload History"),
            color=Color.ACCENT,
            hover_color=Color.ACCENT_HOVER,
            bold=True
        )
        self.btn_upload_history.setCursor(Qt.PointingHandCursor)
        self.btn_upload_history.clicked.connect(self._open_upload_history)

        history_glass = GlassBox(
            tint_rgba="rgba(92, 225, 230, 18)",
            border_color=Color.ACCENT_SOFT_BORDER,
        )
        history_glass.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        history_glass_layout = QHBoxLayout(history_glass)
        history_glass_layout.setContentsMargins(12, 4, 12, 4)
        history_glass_layout.addWidget(self.btn_upload_history)
        header_row.addWidget(history_glass, 0, Qt.AlignVCenter)

        outer.addLayout(header_row)

        # ---- Folder card ----
        folder_card = TitledCard("Source folder", "folderCard")
        folder_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        
        folder_row = QHBoxLayout()
        folder_row.setSpacing(10)
        self.folder_btn = QPushButton("\U0001F4C1  Browse\u2026")
        self.folder_btn.setCursor(Qt.PointingHandCursor)
        self.folder_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {Color.BG_APP};
                color: {Color.TEXT_PRIMARY};
                border: 1px solid {Color.BORDER};
                border-radius: {theme.RADIUS_MD}px;
                padding: 8px 18px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: {Color.BG_HOVER};
                border-color: {Color.ACCENT_SOFT_BORDER};
            }}
            QPushButton:pressed {{
                background-color: {Color.BG_PRESSED};
            }}
        """)
        self.folder_btn.clicked.connect(self._select_folder)
        self.folder_label = QLabel("No folder selected yet.")
        self.folder_label.setProperty("role", "muted")
        self.folder_label.setWordWrap(True)
        folder_row.addWidget(self.folder_btn)
        folder_row.addWidget(self.folder_label, 1)
        folder_card.addLayout(folder_row)
        outer.addWidget(folder_card)

        # ---- Manga search + preview card ----
        search_card = TitledCard("Match to a manga on MangaDot", "searchCard")

        split_row = QHBoxLayout()
        split_row.setSpacing(12)

        left_col = QVBoxLayout()
        left_col.setSpacing(6)

        search_row = QHBoxLayout()
        search_row.setSpacing(6)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Title, numeric ID, or a mangadot.net/manga/... link")
        self.search_input.setStyleSheet(self._dark_input_style)
        self.search_input.returnPressed.connect(self._search_manga)
        
        self.search_glass = GlassBox(tint_rgba="rgba(92, 225, 230, 18)", border_color=Color.ACCENT_SOFT_BORDER)
        self.search_glass.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        search_glass_layout = QHBoxLayout(self.search_glass)
        search_glass_layout.setContentsMargins(16, 4, 16, 4)
        self.search_btn = make_flat_link(QPushButton("Search"), color=Color.ACCENT, hover_color=Color.ACCENT_HOVER, bold=True)
        self.search_btn.clicked.connect(self._search_manga)
        search_glass_layout.addWidget(self.search_btn)
        
        search_row.addWidget(self.search_input, 1)
        search_row.addWidget(self.search_glass)
        left_col.addLayout(search_row)

        left_col.addWidget(section_label("RESULTS"))
        self.results_list = QListWidget()
        self.results_list.setMinimumHeight(150)
        self.results_list.itemClicked.connect(self._on_manga_selected)
        self.results_list.setStyleSheet(f"""
            QListWidget {{
                background-color: {Color.BG_APP};
                border: 1px solid {Color.BORDER};
                border-radius: {theme.RADIUS_MD}px;
                color: {Color.TEXT_PRIMARY};
                outline: none;
                padding: 4px;
            }}
            QListWidget::item {{
                padding: 8px 10px;
                border-radius: {theme.RADIUS_SM}px;
                margin: 1px 2px;
            }}
            QListWidget::item:hover {{
                background-color: {Color.ROW_HOVER};
            }}
            QListWidget::item:selected {{
                background-color: {Color.ACCENT_SOFT};
            }}
        """)
        left_col.addWidget(self.results_list, 1)

        left_col_widget = QWidget()
        left_col_widget.setLayout(left_col)
        split_row.addWidget(left_col_widget, 1)

        preview_box = QGroupBox("Preview")
        preview_box.setObjectName("previewBox")
        preview_box.setStyleSheet(f"""
            QGroupBox#previewBox {{
                background-color: {Color.BG_SURFACE};
                border: 1px solid {Color.BORDER};
                border-radius: {theme.RADIUS_MD}px;
                margin-top: 14px;
                padding: 10px;
                font-weight: 600;
            }}
            QGroupBox#previewBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 12px;
                top: 2px;
                padding: 0 6px;
                color: {Color.TEXT_SECONDARY};
                background-color: {Color.BG_SURFACE};
            }}
        """)
        right_col = QVBoxLayout(preview_box)
        right_col.setSpacing(6)

        preview_top_row = QHBoxLayout()
        preview_top_row.setSpacing(10)
        preview_top_row.setAlignment(Qt.AlignTop)

        self.cover_label = QLabel()
        # Fixed size, not setMinimumSize + Expanding - the previous
        # combination let this label (and therefore the rescaled cover
        # pixmap drawn into it via _rescale_cover_pixmap/resizeEvent)
        # grow with the window, which is exactly what made the cover
        # image visibly balloon in size after a manual window resize.
        # Now that the whole window is a fixed size (see MainWindow.
        # setFixedSize in main.py), there's no longer any reason for this
        # label to be resizable at all - matches cover_preview_box
        # elsewhere in this file, which was already correctly
        # setFixedSize(220, 310) for the same reason.
        self.cover_label.setFixedSize(80, 115)
        self.cover_label.setScaledContents(False)
        self.cover_label.setAlignment(Qt.AlignCenter)
        self.cover_label.setStyleSheet(
            f"background-color: {Color.BG_INPUT}; border: 1px solid {Color.BORDER}; "
            f"border-radius: {theme.RADIUS_SM}px; color: {Color.TEXT_MUTED}; font-size: 11px;"
        )
        self.cover_label.setText("No cover")
        self._cover_pixmap_source = None
        preview_top_row.addWidget(self.cover_label, 0)

        title_status_col = QVBoxLayout()
        title_status_col.setSpacing(2)
        self.title_label = QLabel("Select a result to preview it here.")
        self.title_label.setProperty("role", "muted")
        self.title_label.setWordWrap(True)
        title_status_col.addWidget(self.title_label)
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        title_status_col.addWidget(self.status_label)
        self.genre_label = QLabel("")
        self.genre_label.setWordWrap(True)
        title_status_col.addWidget(self.genre_label)

        self.origin_label = QLabel("")
        self.origin_label.setWordWrap(True)
        title_status_col.addWidget(self.origin_label)

        self.author_label = QLabel("")
        self.author_label.setWordWrap(True)
        title_status_col.addWidget(self.author_label)

        self.artist_label = QLabel("")
        self.artist_label.setWordWrap(True)
        title_status_col.addWidget(self.artist_label)

        self.rating_label = QLabel("")
        self.rating_label.setWordWrap(True)
        title_status_col.addWidget(self.rating_label)

        title_status_col.addStretch(1)
        preview_top_row.addLayout(title_status_col, 1)

        right_col.addLayout(preview_top_row)

        self.synopsis_label = QLabel("")
        self.synopsis_label.setWordWrap(True)
        self.synopsis_label.setProperty("role", "muted")
        self.synopsis_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.synopsis_label.setTextInteractionFlags(Qt.TextBrowserInteraction)
        right_col.addWidget(self.synopsis_label)

        right_col.addStretch(1)

        split_row.addWidget(preview_box, 1)

        search_card.addLayout(split_row)
        outer.addWidget(search_card)

        # ---- Upload configuration card ----
        config_card = TitledCard("Upload settings", "configCard")
        config_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        config_layout = QFormLayout()
        config_layout.setSpacing(8)
        config_layout.setLabelAlignment(Qt.AlignLeft)

        self.upload_type_combo = QComboBox()
        self.upload_type_combo.addItems(["chapter", "volume"])
        self.upload_type_combo.currentTextChanged.connect(self._on_upload_type_changed)
        self.upload_type_combo.setStyleSheet(self._dark_input_style)
        self.upload_type_combo_dots = attach_combo_dots_overlay(self.upload_type_combo)

        # Editable Language ComboBox
        self.lang_combo = QComboBox()
        self.lang_combo.setEditable(True)
        self.lang_combo.setMinimumWidth(180)
        self.lang_combo.setStyleSheet(self._dark_input_style)
        # The popup for an editable QComboBox is promoted to its own
        # top-level window. On some Windows/Qt combos, a styled
        # QAbstractItemView on that popup ends up with WA_TranslucentBackground
        # set (inherited default) but nothing actually painting the
        # translucent region, so the popup exists and takes keyboard
        # input but never draws — items are invisible even though
        # arrow-key navigation still works. Forcing an opaque,
        # auto-filled background on the popup's top-level window fixes it.
        popup_view = self.lang_combo.view()
        popup_view.setAttribute(Qt.WA_TranslucentBackground, False)
        popup_view.setAutoFillBackground(True)
        popup_window = popup_view.window()
        popup_window.setAttribute(Qt.WA_TranslucentBackground, False)
        popup_window.setAutoFillBackground(True)

        self.lang_combo_dots = attach_combo_dots_overlay(self.lang_combo)

        for code, name in util.LANGUAGES:
            self.lang_combo.addItem(f"{name} ({code})", code)
            
        match_idx = -1
        for i in range(self.lang_combo.count()):
            if self.lang_combo.itemData(i) == saved_lang:
                match_idx = i
                break
        if match_idx >= 0:
            self.lang_combo.setCurrentIndex(match_idx)
        else:
            self.lang_combo.setEditText(saved_lang)

        self.THREAD_CAP_SAFE = 30
        self.THREAD_CAP_MAX = 90

        saved_unlocked = bool(cfg.get("threads_unlocked", False))

        self.thread_spinner = QSpinBox()
        self.thread_spinner.setRange(1, self.THREAD_CAP_MAX if saved_unlocked else self.THREAD_CAP_SAFE)
        self.thread_spinner.setStyleSheet(self._dark_input_style)
        self.thread_spinner.setFixedWidth(56)
        try:
            self.thread_spinner.setValue(int(saved_threads))
        except (ValueError, TypeError):
            self.thread_spinner.setValue(5)

        self.thread_unlock_cb = QCheckBox("Unlock\nmax (90)")
        self.thread_unlock_cb.setStyleSheet(self._compact_checkbox_style())
        self.thread_unlock_cb.setToolTip(
            "Raises the thread cap from 30 to 90. High thread counts can trigger rate-limiting "
            "or get your account flagged for abuse \u2014 only do this if you know what you're doing."
        )
        self.thread_warning_label = QLabel("\u26a0\ufe0f High thread counts risk rate-limits / account flags")
        self.thread_warning_label.setProperty("role", "warning")
        self.thread_warning_label.setVisible(saved_unlocked)
        if saved_unlocked:
            # Restore silently (no re-confirmation) since the user already
            # confirmed this choice in a previous session.
            self.thread_unlock_cb.blockSignals(True)
            self.thread_unlock_cb.setChecked(True)
            self.thread_unlock_cb.blockSignals(False)
        self.thread_unlock_cb.toggled.connect(self._on_thread_unlock_toggled)

        self.timeout_spinner = QSpinBox()
        self.timeout_spinner.setRange(1, 300)
        self.timeout_spinner.setValue(60)
        self.timeout_spinner.setSuffix(" s")
        self.timeout_spinner.setStyleSheet(self._dark_input_style)
        self.timeout_spinner.setFixedWidth(64)

        self.skip_verify_cb = QCheckBox("Skip\nverification")
        self.skip_verify_cb.setStyleSheet(self._compact_checkbox_style())
        self.skip_verify_cb.setToolTip(
            "Mark each file done as soon as it finishes uploading, without polling MangaDot "
            "to confirm it landed under the right chapter/group. Faster and avoids "
            "\u201cVerification timeout reached\u201d failures on large batches, but a file that "
            "silently failed server-side won't be caught here \u2014 double check the manga page after."
        )
        self.skip_verify_cb.setChecked(True)
        self.skip_verify_cb.toggled.connect(self._on_skip_verify_toggled)
        self.timeout_spinner.setEnabled(False)

        row1 = QHBoxLayout()
        row1.addWidget(self.upload_type_combo)
        row1.addSpacing(18)
        row1.addWidget(QLabel("Language:"))
        row1.addWidget(self.lang_combo)
        row1.addSpacing(18)
        row1.addWidget(QLabel("Threads:"))
        row1.addWidget(self.thread_spinner)
        row1.addSpacing(4)
        row1.addWidget(self.thread_unlock_cb)
        row1.addSpacing(14)
        row1.addWidget(QLabel("Verify timeout:"))
        row1.addWidget(self.timeout_spinner)
        row1.addSpacing(4)
        row1.addWidget(self.skip_verify_cb)
        row1.addStretch(1)
        config_layout.addRow("Type / language / speed:", row1)
        config_layout.addRow("", self.thread_warning_label)

        config_card.addLayout(config_layout)
        outer.addWidget(config_card)

        # ---- Chapter naming card ----
        self.naming_card = TitledCard("Chapter naming", "namingCard")
        self.naming_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        mode_row = QHBoxLayout()
        mode_row.setSpacing(16)
        self.naming_group = QButtonGroup(self)
        self.radio_preset = QRadioButton("Force \u201cChapter N\u201d")
        self.radio_extract = QRadioButton("Auto-detect title (recommended)")
        self.radio_advanced = QRadioButton("Auto-detect \u2014 advanced")
        self.radio_extract.setChecked(True)
        for i, rb in enumerate((self.radio_preset, self.radio_extract, self.radio_advanced)):
            self.naming_group.addButton(rb, i)
            mode_row.addWidget(rb)
        mode_row.addStretch(1)
        self.naming_group.idClicked.connect(self._on_naming_mode_changed)
        self.naming_card.addLayout(mode_row)

        self.naming_hint = hint_label(
            "Titles are guessed from each filename automatically. You'll still get to review "
            "and edit every title on the next screen."
        )
        self.naming_card.addWidget(self.naming_hint)

        self.advanced_panel = QWidget()
        adv_layout = QVBoxLayout(self.advanced_panel)
        adv_layout.setContentsMargins(0, 6, 0, 0)
        adv_layout.setSpacing(6)

        regex_row = QHBoxLayout()
        regex_row.addWidget(QLabel("Custom regex:"))
        self.regex_input = QLineEdit()
        self.regex_input.setPlaceholderText("pattern->replace;;(extract)")
        regex_row.addWidget(self.regex_input, 1)
        adv_layout.addLayout(regex_row)
        adv_layout.addWidget(hint_label(
            "Use a capture group ( ) to extract a title, or Find->Replace segments separated by ;; "
            "to rename before detection."
        ))

        self.strip_groups_cb = QCheckBox("Strip bracket/parenthesis groups before detection")
        adv_layout.addWidget(self.strip_groups_cb)

        self.advanced_panel.setVisible(False)
        self.naming_card.addWidget(self.advanced_panel)

        outer.addWidget(self.naming_card)

        # ---- Continue ----
        bottom_row = QHBoxLayout()
        bottom_row.addStretch(1)
        continue_box = GlassBox(
            tint_rgba="rgba(92, 225, 230, 18)",
            border_color=Color.ACCENT_SOFT_BORDER,
        )
        continue_box_layout = QHBoxLayout(continue_box)
        continue_box_layout.setContentsMargins(14, 6, 14, 6)
        self.continue_btn = make_flat_link(QPushButton("Continue"), bold=True)
        self.continue_btn.setEnabled(False)
        self.continue_btn.clicked.connect(self._on_continue)
        continue_box_layout.addWidget(self.continue_btn)
        bottom_row.addWidget(continue_box)
        outer.addLayout(bottom_row)
        
        outer.addStretch(1)

    def _on_naming_mode_changed(self, idx):
        self.advanced_panel.setVisible(idx == 2)
        if idx == 0:
            self.naming_hint.setText("Every chapter is titled plainly as \u201cChapter 12\u201d, \u201cChapter 13\u201d, etc. \u2014 no title guessing at all.")
        elif idx == 1:
            self.naming_hint.setText(
                "Titles are guessed from each filename automatically. You'll still get to review "
                "and edit every title on the next screen."
            )
        else:
            self.naming_hint.setText(
                "Same auto-detection, plus an optional custom regex and/or stripping bracket tags "
                "before titles are guessed."
            )

    def _on_thread_unlock_toggled(self, checked):
        if checked:
            resp = QMessageBox.warning(
                self,
                "Unlock max thread count?",
                f"This raises the thread cap from {self.THREAD_CAP_SAFE} to {self.THREAD_CAP_MAX}.\n\n"
                "Running that many threads can trigger rate-limiting or get your account "
                "flagged for abuse. Only continue if you know what you're doing.\n\n"
                f"Enable {self.THREAD_CAP_MAX} threads?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if resp != QMessageBox.Yes:
                self.thread_unlock_cb.blockSignals(True)
                self.thread_unlock_cb.setChecked(False)
                self.thread_unlock_cb.blockSignals(False)
                return
            self.thread_spinner.setRange(1, self.THREAD_CAP_MAX)
            self.thread_warning_label.setVisible(True)
        else:
            self.thread_spinner.setRange(1, self.THREAD_CAP_SAFE)
            if self.thread_spinner.value() > self.THREAD_CAP_SAFE:
                self.thread_spinner.setValue(self.THREAD_CAP_SAFE)
            self.thread_warning_label.setVisible(False)

    def _on_skip_verify_toggled(self, checked):
        # Verify timeout is meaningless once verification itself is
        # skipped - grey the spinner out rather than leaving a
        # now-inert control sitting there looking editable.
        self.timeout_spinner.setEnabled(not checked)

    def _compact_checkbox_style(self) -> str:
        """Smaller indicator box + smaller, dimmer, two-line label text
        than the shared _dark_input_style checkboxes. Used for the two
        secondary opt-in toggles crammed into row1 (thread unlock, skip
        verification) - at full single-line size that row was wide
        enough to push "Skip verification" past the right edge of the
        window (see screenshot). Labels are passed as "Word1\\nWord2"
        (see the two QCheckBox(...) calls above) and stacked here rather
        than left on one line, since a single-line shrink alone wasn't
        enough width savings - two short lines is a much narrower
        footprint than one long line even at a smaller font. These are
        advanced/occasional-use options, not primary controls, so
        visually receding them is also the more honest hierarchy - the
        main knobs (type, language, threads, timeout) stay full size."""
        return f"""
            QCheckBox {{
                spacing: 4px;
                color: {Color.TEXT_MUTED};
                background: transparent;
                font-size: 9px;
                line-height: 100%;
            }}
            QCheckBox:disabled {{
                color: {Color.TEXT_DISABLED};
            }}
            QCheckBox::indicator {{
                background-color: {Color.BG_APP};
                border: 1px solid {Color.ACCENT_SOFT_BORDER};
                border-radius: 3px;
                width: 10px;
                height: 10px;
            }}
            QCheckBox::indicator:checked {{
                background-color: {Color.ACCENT};
                border: 1px solid {Color.ACCENT};
            }}
            QCheckBox::indicator:disabled {{
                background-color: {Color.BG_SURFACE};
                border-color: {Color.BORDER};
            }}
        """

    def _on_upload_type_changed(self, text):
        is_volume = text == "volume"
        self.naming_card.setVisible(not is_volume)

    def _current_chapter_naming(self):
        idx = self.naming_group.checkedId()
        if idx == 0:
            return "preset"
        return "extract"

    def _select_folder(self):
        cfg = config_mod.load_config()
        start_dir = cfg.get("library", "")

        directory = QFileDialog.getExistingDirectory(self, "Select Manga Folder", start_dir)
        if directory:
            config_mod.remember_library(directory)
            self.folder_label.setText(directory)
            self.folder_label.setProperty("role", "")
            self.folder_label.setStyleSheet("")
            
            guessed_query = parser_mod.guess_search_query_from_folder(directory)
            if guessed_query:
                self.search_input.setText(guessed_query)
                self._search_manga()
                
            guessed_lang = parser_mod.guess_language_from_path(directory)
            if guessed_lang:
                match_idx = -1
                for i in range(self.lang_combo.count()):
                    if self.lang_combo.itemData(i) == guessed_lang:
                        match_idx = i
                        break
                if match_idx >= 0:
                    self.lang_combo.setCurrentIndex(match_idx)
                else:
                    self.lang_combo.setEditText(guessed_lang)

    def _search_manga(self):
        text = self.search_input.text()
        kind, value = parser_mod.extract_manga_id_or_query(text)
        if kind is None or not self.session:
            return

        self.results_list.clear()
        self.results_list.addItem("Searching\u2026")
        self.search_btn.setEnabled(False)

        workers.prune_finished(self._threads, self._workers)

        thread, worker = workers.run_callable(
            _search_manga_by_kind, self.session, kind, value,
            on_finished=self._on_search_finished,
        )
        self._threads.append(thread)
        self._workers.append(worker)

    def _on_search_finished(self, results):
        self.search_btn.setEnabled(True)
        self.results_list.clear()
        if results:
            for manga in results:
                title = str(manga.get("title", "")).strip()
                if len(title) > 80:
                    title = title[:80].rsplit(" ", 1)[0] + "\u2026"
                meta_bits = [f"ID {manga['id']}"]
                if manga.get("status"):
                    meta_bits.append(str(manga["status"]))
                item = QListWidgetItem(f"{title}\n{'  \u00b7  '.join(meta_bits)}")
                item.setData(Qt.UserRole, manga)
                self.results_list.addItem(item)
        else:
            placeholder = QListWidgetItem("No results found \u2014 try a different search.")
            placeholder.setFlags(Qt.NoItemFlags)
            self.results_list.addItem(placeholder)

            create_item = QListWidgetItem("\u2795  Not on MangaDot yet? Create from MangaBaka\u2026")
            create_item.setData(Qt.UserRole, {"_action": "create_from_mangabaka"})
            self.results_list.addItem(create_item)

    def _open_create_from_mangabaka(self):
        if not self.session:
            return
        dialog = _CreateFromMangaBakaDialog(
            self.session, self._dark_input_style,
            prefill_query=self.search_input.text(), parent=self
        )
        accepted = dialog.exec()
        new_id, new_title = dialog.created_id, dialog.created_title
        dialog.stop_background_work()

        if accepted == QDialog.Accepted and new_id:
            QMessageBox.information(self, "Created", f"\u201c{new_title}\u201d was created on MangaDot.")
            self.results_list.clear()
            item = QListWidgetItem(f"{new_title}\nID {new_id}")
            item.setData(Qt.UserRole, {"id": new_id, "title": new_title, "status": ""})
            self.results_list.addItem(item)
            self._on_manga_selected(item)

    def _on_manga_selected(self, item):
        manga_data = item.data(Qt.UserRole)
        if not manga_data:
            return
        if manga_data.get("_action") == "create_from_mangabaka":
            self._open_create_from_mangabaka()
            return
        self.selected_manga_id = manga_data["id"]
        self.selected_manga_title = manga_data.get("title") or None
        self.continue_btn.setEnabled(True)

        self.title_label.setText("Loading details\u2026")
        self.status_label.setText("")
        self.genre_label.setText("")
        self.synopsis_label.setText("")
        self.origin_label.setText("")
        self.author_label.setText("")
        self.artist_label.setText("")
        self.rating_label.setText("")
        self._cover_pixmap_source = None
        self.cover_label.setText("Loading\u2026")

        workers.prune_finished(self._threads, self._workers)

        worker = _DetailsWorker(self.session, self.selected_manga_id)
        thread, worker = workers.run_worker(worker, on_finished=self._on_details_finished)
        self._threads.append(thread)
        self._workers.append(worker)

    def _on_details_finished(self, details, cover_bytes):
        if not details:
            self.title_label.setText("Could not load details for this manga.")
            self.status_label.setText("")
            self.genre_label.setText("")
            self.synopsis_label.setText("")
            self.origin_label.setText("")
            self.author_label.setText("")
            self.artist_label.setText("")
            self.rating_label.setText("")
            self._cover_pixmap_source = None
            self.cover_label.setText("No cover")
            return

        from html import escape

        accent = Color.ACCENT
        title_html = f"<span style='font-size:15px; font-weight:700; color:{accent};'>{escape(details['title'])}</span>"
        if details.get("alt_title"):
            title_html += f"<br><i style='color:{Color.TEXT_MUTED};'>{escape(details['alt_title'])}</i>"
        self.title_label.setText(title_html)
        self.selected_manga_title = details.get("title") or self.selected_manga_title
        self.selected_manga_details = details

        self.status_label.setText(f"<b><i>Status:</i></b> {escape(str(details['status']).upper())}")

        if details.get("genres"):
            self.genre_label.setText("<b><i>Genres:</i></b> " + escape(", ".join(details["genres"])))
        else:
            self.genre_label.setText(f"<b><i>Genres:</i></b> <span style='color:{Color.TEXT_MUTED};'>(not found: genres)</span>")

        if details.get("description"):
            desc = details["description"].strip()
            if len(desc) > 420:
                desc = desc[:420].rsplit(" ", 1)[0] + "\u2026"
            self.synopsis_label.setText(f"<span style='color:{Color.TEXT_SECONDARY};'>{escape(desc)}</span>")
        else:
            self.synopsis_label.setText(f"<span style='color:{Color.TEXT_MUTED};'>(not found: synopsis)</span>")

        if details.get("origin"):
            self.origin_label.setText(
                f"<b><i>Origin:</i></b> {escape(util.format_origin(details['origin']))}"
            )
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
            self.rating_label.setText(
                f"<b><i>Rating:</i></b> "
                f"<b><i style='color:{Color.WARNING};'>{escape(details['rating'])}</i></b>"
            )
        else:
            self.rating_label.setText(f"<b><i>Rating:</i></b> <span style='color:{Color.TEXT_MUTED};'>(not found: rating)</span>")

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

    def _on_continue(self):
        folder = self.folder_label.text()
        if not folder or not os.path.isdir(folder) or not self.selected_manga_id:
            return

        current_idx = self.lang_combo.currentIndex()
        if current_idx >= 0 and self.lang_combo.itemText(current_idx) == self.lang_combo.currentText():
            lang = self.lang_combo.itemData(current_idx)
        else:
            lang = parser_mod.extract_lang_code_from_text(self.lang_combo.currentText())
        lang = lang or "en"

        threads = self.thread_spinner.value()

        cfg = config_mod.load_config()
        cfg["language"] = lang
        cfg["threads"] = threads
        cfg["threads_unlocked"] = self.thread_unlock_cb.isChecked()
        config_mod.save_config(cfg)

        upload_type = self.upload_type_combo.currentText()
        chapter_naming = self._current_chapter_naming() if upload_type == "chapter" else "extract"
        regex_text = self.regex_input.text().strip() if self.radio_advanced.isChecked() else ""
        strip_groups = self.strip_groups_cb.isChecked() if self.radio_advanced.isChecked() else False

        self.picker_finished.emit(
            folder,
            self.selected_manga_id,
            self.selected_manga_title or "",
            lang,
            threads,
            upload_type,
            chapter_naming,
            regex_text,
            strip_groups,
            self.timeout_spinner.value(),
            self.skip_verify_cb.isChecked()
        )

    def stop_background_work(self):
        for thread in self._threads:
            if thread_is_running(thread):
                thread.quit()
                thread.wait(2000)

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

    def _open_upload_history(self):
        from .upload_history_dialog import UploadHistoryDialog
        dialog = UploadHistoryDialog(parent=self.window(), session=self.session, username=getattr(self, "username", ""))
        dialog.exec()