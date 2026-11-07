"""Login screen."""
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QObject, QTimer, QSize
from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QComboBox, QFrame, QSizePolicy
)
from PySide6.QtSvgWidgets import QSvgWidget

from .. import auth
from .. import debugging
from . import thread_is_running
from .widgets import heading, hint_label, StatusPill, make_flat_link, GlassBox
from .theme import Color

_ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
_LOGO_PATH = _ASSETS_DIR / "mangadotnet-purple.svg"

STATUS_KIND = {
    "success": "success",
    "no_cookies": "neutral",
    "not_recognized": "warning",
    "error": "danger",
}

STATUS_LABELS = {
    "success": "Logged in",
    "no_cookies": "No saved login found",
    "not_recognized": "Cookies found, but not recognized",
    "error": "Failed",
}


class _AuthWorker(QObject):
    browser_attempted = Signal(dict)
    cdp_launch_message = Signal(str)
    finished = Signal(object, list)

    def __init__(self, session, browsers=None):
        super().__init__()
        self.session = session
        self.browsers = browsers

    def run(self):
        winner, results = auth.try_all_browsers(
            self.session,
            browsers=self.browsers,
            on_cdp_launch=self.cdp_launch_message.emit,
            progress_callback=self.browser_attempted.emit
        )
        self.finished.emit(winner, results)


class LoginScreen(QDialog):
    login_succeeded = Signal(str, object, object)
    content_resized = Signal()

    def __init__(self, parent=None, proxy_url=None, proxy_no_verify=False, debug_enabled=False):
        super().__init__(parent)
        self.setWindowTitle("Signing in\u2026")
        self.setWindowFlags(Qt.Dialog | Qt.WindowTitleHint | Qt.CustomizeWindowHint)
        self.setModal(False)
        self.setFixedWidth(560)

        from .. import net
        self.session = net.create_base_session(proxy_url, proxy_no_verify, debug_enabled)

        self._thread = None
        self._worker = None
        self._build_ui()
        self._start_scan()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setAlignment(Qt.AlignHCenter)

        wrap = QWidget()
        wrap.setMaximumWidth(560)
        wrap_layout = QVBoxLayout(wrap)
        wrap_layout.setSpacing(16)

        brand_row = QHBoxLayout()
        brand_row.setAlignment(Qt.AlignCenter)
        brand = QSvgWidget(str(_LOGO_PATH))
        brand.setFixedSize(160, 32)
        brand_row.addWidget(brand)
        wrap_layout.addLayout(brand_row)

        head = heading("Sign in", None)
        head.layout().setAlignment(Qt.AlignCenter)
        head.findChild(QLabel).setAlignment(Qt.AlignCenter)
        wrap_layout.addWidget(head)

        self.status_label = QLabel("Looking for a saved login in your browsers\u2026")
        self.status_label.setWordWrap(True)
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setProperty("role", "subheading")
        wrap_layout.addWidget(self.status_label)

        self.attempt_list = QListWidget()
        self.attempt_list.setObjectName("TransparentList")
        self.attempt_list.setFrameShape(QFrame.NoFrame)
        self.attempt_list.setFocusPolicy(Qt.NoFocus)
        self.attempt_list.setSelectionMode(QListWidget.NoSelection)
        self.attempt_list.setMaximumHeight(220)
        self.attempt_list.setSpacing(8)
        self.attempt_list.setVisible(False)
        wrap_layout.addWidget(self.attempt_list)

        self.retry_row = QWidget()
        retry_layout = QHBoxLayout(self.retry_row)
        retry_layout.setContentsMargins(0, 6, 0, 0)
        retry_layout.setSpacing(8)

        retry_label = QLabel("Try a specific browser:")
        retry_label.setProperty("role", "muted")
        self.browser_combo = QComboBox()
        self.browser_combo.addItems([b.title() for b in auth.ALL_BROWSER_CHOICES])
        self.retry_button = QPushButton("Retry")
        self.retry_button.clicked.connect(self._on_manual_retry)

        retry_layout.addWidget(retry_label)
        retry_layout.addWidget(self.browser_combo, 1)
        retry_layout.addWidget(self.retry_button)
        self.retry_row.setVisible(False)
        wrap_layout.addWidget(self.retry_row)

        bottom_row = QHBoxLayout()
        bottom_row.addStretch(1)
        continue_box = GlassBox(
            tint_rgba="rgba(92, 225, 230, 18)",
            border_color=Color.ACCENT_SOFT_BORDER,
        )
        continue_box_layout = QHBoxLayout(continue_box)
        continue_box_layout.setContentsMargins(14, 6, 14, 6)
        self.continue_button = make_flat_link(QPushButton("Continue"), bold=True)
        self.continue_button.setEnabled(False)
        self.continue_button.clicked.connect(self._on_continue)
        continue_box_layout.addWidget(self.continue_button)
        self.continue_box = continue_box
        self.continue_box.setVisible(False)
        bottom_row.addWidget(continue_box)
        wrap_layout.addLayout(bottom_row)

        outer.addStretch(1)
        outer.addWidget(wrap)
        outer.addStretch(1)

        self._winner = None

    def _add_attempt_row(self, result):
        kind = STATUS_KIND.get(result["status"], "neutral")
        label = STATUS_LABELS.get(result["status"], result["status"])
        browser_name = result["browser"].title()

        item = QListWidgetItem()
        item.setSizeHint(QSize(0, 52))

        row_widget = QWidget()
        row_widget.setObjectName("TransparentListRowWidget")
        row_widget.setStyleSheet("QWidget#TransparentListRowWidget { background-color: transparent; border: none; }")
        
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(16, 0, 16, 0)
        row_layout.setSpacing(16)

        name_label = QLabel(browser_name)
        name_label.setFixedWidth(70)
        name_label.setStyleSheet("font-weight: 600; background: transparent;")
        row_layout.addWidget(name_label)

        pill = StatusPill(label, kind)
        row_layout.addWidget(pill)

        # Build the full string for the tooltip first
        full_detail = ""
        if result["status"] in ("error", "not_recognized") and result.get("error_message"):
            full_detail = result["error_message"]
        if result.get("chromium_hint"):
            full_detail = (full_detail + "  \u2014  " if full_detail else "") + "try the (cdp) version of this browser"
        
        if full_detail:
            # Create a truncated version for the visible label
            display_detail = full_detail
            if len(display_detail) > 120:
                display_detail = display_detail[:119].rstrip() + "\u2026"

            detail_label = QLabel(display_detail)
            detail_label.setProperty("role", "hint")
            detail_label.setStyleSheet("background: transparent;")
            detail_label.setToolTip(full_detail)  # This enables the hover text
            row_layout.addWidget(detail_label, stretch=1)
        else:
            row_layout.addStretch(1)

        if not self.attempt_list.isVisible():
            self.attempt_list.setVisible(True)
        
        self.attempt_list.addItem(item)
        self.attempt_list.setItemWidget(item, row_widget)
        self.attempt_list.scheduleDelayedItemsLayout()
        self.adjustSize()
        self.content_resized.emit()

    def _start_scan(self, browsers=None):
        if self._thread is not None and thread_is_running(self._thread):
            return

        self.attempt_list.clear()
        self.attempt_list.setVisible(False)
        self.retry_row.setVisible(False)
        self.continue_box.setVisible(False)
        self.continue_button.setEnabled(False)
        self.status_label.setText("Looking for a saved login in your browsers\u2026")

        self._thread = QThread()
        self._worker = _AuthWorker(self.session, browsers=browsers)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.browser_attempted.connect(self._add_attempt_row)
        self._worker.cdp_launch_message.connect(self._on_cdp_launch_message)
        self._worker.finished.connect(self._on_scan_finished)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)

        self._thread.start()

    def _on_cdp_launch_message(self, message):
        self.status_label.setText(message)

    def _on_scan_finished(self, winner, results):
        if winner:
            self._winner = winner
            self.status_label.setText(f"\u2705 Logged in as {winner['username']} via {winner['browser'].title()}")
            self.continue_button.setEnabled(True)
            QTimer.singleShot(0, self._on_continue)
        else:
            self.status_label.setText(
                "Couldn't find a saved MangaDot login automatically. "
                "Make sure you're logged in to MangaDot in one of your browsers, "
                "or pick one below to try again."
            )
            self.retry_row.setVisible(True)
            self.continue_box.setVisible(True)
        self.adjustSize()
        self.content_resized.emit()

    def _on_manual_retry(self):
        chosen_display = self.browser_combo.currentText()
        chosen = next(
            (b for b in auth.ALL_BROWSER_CHOICES if b.title() == chosen_display),
            chosen_display.lower()
        )
        self.retry_row.setVisible(False)
        self.status_label.setText(f"Trying {chosen_display}\u2026")
        self._start_scan(browsers=[chosen])

    def _on_continue(self):
        if self._winner:
            self.login_succeeded.emit(
                self._winner["username"], self._winner["user_id"], self.session
            )

    def stop_background_work(self):
        if self._thread is not None and thread_is_running(self._thread):
            self._thread.quit()
            self._thread.wait(3000)