"""Startup settings dialog."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit,
    QCheckBox, QPushButton, QDialogButtonBox, QMessageBox, QGroupBox,
    QRadioButton, QSpinBox, QButtonGroup, QFrame
)

from .. import debugging
from .widgets import heading, hint_label, make_flat, make_flat_link, GlassBox
from . import theme, thread_is_running, workers
from .theme import Color


class StartupSettingsDialog(QDialog):
    # Emitted once settings are confirmed and validated (proxy check passed,
    # or the user chose to continue anyway). Fires instead of closing the
    # dialog when `stay_open_on_accept` is set, so callers that want the
    # dialog to remain on screen (e.g. to reuse it for a second instance)
    # can listen for this rather than relying on exec()/accept() to return.
    settings_confirmed = Signal()

    def __init__(self, parent=None, stay_open_on_accept=False, session=None, username=None):
        super().__init__(parent)
        self.stay_open_on_accept = stay_open_on_accept
        self.session = session
        self.username = username or ""
        self.setWindowTitle("MangaDot Uploader \u2014 Settings")
        
        self.setFixedWidth(720)
        self.setWindowFlags(self.windowFlags() | Qt.MSWindowsFixedSizeDialogHint)

        self.proxy_url = None
        self.proxy_no_verify = False
        self.debug_enabled = False

        self.opt_mode = "disabled"
        self.opt_pingo = False
        self.opt_replace = False
        self.opt_lossy = False
        self.opt_jpeg_q = 85
        self.opt_webp_q = 85
        self.opt_threads = 4

        self.launch_mode = "normal"

        self._dark_input_style = theme.dark_input_style()

        self._proxy_test_thread = None
        self._proxy_test_worker = None
        self._accept_check_thread = None
        self._accept_check_worker = None

        self._build_ui()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 22, 24, 20)
        outer.setSpacing(14)

        outer.addWidget(heading("Before we start", "Set up networking and image optimization, then continue."))

        net_group = QGroupBox("Network & Debugging")
        net_layout = QFormLayout(net_group)
        net_layout.setSpacing(10)

        self.proxy_input = QLineEdit()
        self.proxy_input.setPlaceholderText("http://user:pass@host:port (leave blank for no proxy)")
        self.proxy_input.setStyleSheet(self._dark_input_style)
        net_layout.addRow("Proxy URL:", self.proxy_input)

        self.no_verify_checkbox = QCheckBox("Disable SSL verification (only if proxy does TLS interception)")
        self.no_verify_checkbox.setStyleSheet(self._dark_input_style)
        net_layout.addRow("", self.no_verify_checkbox)

        self.debug_checkbox = QCheckBox("Log all HTTP traffic to api_requests.log")
        self.debug_checkbox.setStyleSheet(self._dark_input_style)
        net_layout.addRow("", self.debug_checkbox)

        test_row = QHBoxLayout()
        self.test_button = make_flat(QPushButton("Test proxy connection"))
        self.test_button.clicked.connect(self._on_test_proxy)
        test_row.addWidget(self.test_button)
        self.test_result_label = QLabel("")
        self.test_result_label.setWordWrap(True)
        test_row.addWidget(self.test_result_label, 1)
        net_layout.addRow("", test_row)

        outer.addWidget(net_group)

        opt_group = QGroupBox("CBZ Optimizer")
        opt_layout = QVBoxLayout(opt_group)
        opt_layout.setSpacing(10)
        opt_layout.setContentsMargins(14, 16, 14, 14)

        mode_layout = QHBoxLayout()
        mode_layout.setSpacing(16)

        self.radio_disabled = QRadioButton("Disabled")
        self.radio_chained = QRadioButton("Optimize before uploading")
        self.radio_standalone = QRadioButton("Standalone (optimize only, no upload)")
        self.radio_disabled.setChecked(True)
        for _rb in (self.radio_disabled, self.radio_chained, self.radio_standalone):
            _rb.setStyleSheet(self._dark_input_style)

        self.mode_bg = QButtonGroup(self)
        self.mode_bg.addButton(self.radio_disabled)
        self.mode_bg.addButton(self.radio_chained)
        self.mode_bg.addButton(self.radio_standalone)
        self.mode_bg.buttonToggled.connect(self._toggle_optimizer_options)

        mode_layout.addWidget(self.radio_disabled)
        mode_layout.addWidget(self.radio_chained)
        mode_layout.addWidget(self.radio_standalone)
        mode_layout.addStretch(1) 
        opt_layout.addLayout(mode_layout)

        self.options_container = QFrame()
        self.options_container.setObjectName("optionsCard")
        self.options_container.setStyleSheet(f"""
            QFrame#optionsCard {{
                background-color: {Color.BG_BASE};
                border: 1px solid {Color.BORDER_SOFT};
                border-radius: 8px;
            }}
        """)
        options_layout = QVBoxLayout(self.options_container)
        options_layout.setContentsMargins(14, 12, 14, 12)
        options_layout.setSpacing(10)

        self.pingo_cb = QCheckBox("Use Pingo backend (if available)")
        self.replace_cb = QCheckBox("Overwrite originals (Warning: Destructive \u2014 you'll be asked to confirm)")
        self.lossy_cb = QCheckBox("Enable lossy compression (alters pixel data)")
        self.lossy_cb.toggled.connect(self._toggle_quality_spinners)
        for _cb in (self.pingo_cb, self.replace_cb, self.lossy_cb):
            _cb.setStyleSheet(self._dark_input_style)

        options_layout.addWidget(self.pingo_cb)
        options_layout.addWidget(self.replace_cb)
        options_layout.addWidget(self.lossy_cb)

        spinner_layout = QHBoxLayout()
        spinner_layout.setSpacing(8)
        spinner_layout.addWidget(QLabel("JPEG quality:"))
        self.jpeg_spin = QSpinBox()
        self.jpeg_spin.setRange(1, 95)
        self.jpeg_spin.setValue(85)
        self.jpeg_spin.setStyleSheet(self._dark_input_style)
        spinner_layout.addWidget(self.jpeg_spin)

        spinner_layout.addSpacing(10)
        spinner_layout.addWidget(QLabel("WEBP quality:"))
        self.webp_spin = QSpinBox()
        self.webp_spin.setRange(1, 100)
        self.webp_spin.setValue(85)
        self.webp_spin.setStyleSheet(self._dark_input_style)
        spinner_layout.addWidget(self.webp_spin)

        spinner_layout.addSpacing(10)
        spinner_layout.addWidget(QLabel("Threads:"))
        self.threads_spin = QSpinBox()
        self.threads_spin.setRange(1, 32)
        self.threads_spin.setValue(4)
        self.threads_spin.setStyleSheet(self._dark_input_style)
        spinner_layout.addWidget(self.threads_spin)

        spinner_layout.addStretch(1)
        options_layout.addLayout(spinner_layout)

        opt_layout.addWidget(self.options_container)

        outer.addWidget(opt_group)
        self._toggle_optimizer_options(self.radio_disabled, True)
        self._toggle_quality_spinners(False)

        history_panel = GlassBox(
            tint_rgba="rgba(92, 225, 230, 18)",
            border_color=Color.ACCENT_SOFT_BORDER,
        )
        history_row = QHBoxLayout(history_panel)
        history_row.setContentsMargins(14, 10, 14, 10)
        history_row.setSpacing(10)
        history_label = hint_label(
            "View recorded series, inspect chapter counts, or sync releases directly with MangaDot."
        )
        history_row.addWidget(history_label, 1)
        self.history_button = make_flat_link(
            QPushButton("📜 Upload History"), color=Color.ACCENT, hover_color=Color.ACCENT_HOVER
        )
        self.history_button.clicked.connect(self._on_open_upload_history)
        history_row.addWidget(self.history_button)
        outer.addWidget(history_panel)

        dry_run_panel = GlassBox(
            tint_rgba="rgba(220, 20, 60, 18)",
            border_color=Color.CRIMSON_SOFT_BORDER,
        )
        dry_run_row = QHBoxLayout(dry_run_panel)
        dry_run_row.setContentsMargins(14, 10, 14, 10)
        dry_run_row.setSpacing(10)
        dry_run_label = hint_label(
            "Just want to preview how your files will be parsed, without logging in or uploading anything?"
        )
        dry_run_row.addWidget(dry_run_label, 1)
        self.dry_run_button = make_flat_link(
            QPushButton("Dry Run"), color=Color.CRIMSON, hover_color=Color.CRIMSON_HOVER
        )
        self.dry_run_button.clicked.connect(self._on_dry_run)
        dry_run_row.addWidget(self.dry_run_button)
        outer.addWidget(dry_run_panel)

        bottom_row = QHBoxLayout()
        bottom_row.addStretch(1)

        continue_box = GlassBox(
            tint_rgba="rgba(92, 225, 230, 18)",
            border_color=Color.ACCENT_SOFT_BORDER,
        )
        continue_box_layout = QHBoxLayout(continue_box)
        continue_box_layout.setContentsMargins(14, 6, 14, 6)
        self.continue_button = make_flat_link(QPushButton("Continue"), bold=True)
        self.continue_button.setDefault(True)
        self.continue_button.clicked.connect(self._on_accept)
        continue_box_layout.addWidget(self.continue_button)
        bottom_row.addWidget(continue_box)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        bottom_row.addWidget(self.cancel_button)
        outer.addLayout(bottom_row)

        self.adjustSize()
        self.setFixedHeight(self.height())
        
        screen_geo = QGuiApplication.primaryScreen().availableGeometry()
        x = (screen_geo.width() - self.width()) // 2
        y = (screen_geo.height() - self.height()) // 2
        self.move(max(0, x), max(0, y))

    def _toggle_optimizer_options(self, *_args):
        enabled = not self.radio_disabled.isChecked()
        self.options_container.setEnabled(enabled)

    def _toggle_quality_spinners(self, checked):
        self.jpeg_spin.setEnabled(checked)
        self.webp_spin.setEnabled(checked)

    def _on_test_proxy(self):
        proxy_url = self.proxy_input.text().strip()
        if not proxy_url:
            self.test_result_label.setText("Enter a proxy URL first.")
            return

        self.test_result_label.setText("Testing\u2026")
        self.test_button.setEnabled(False)
        verify = not self.no_verify_checkbox.isChecked()
        # check_proxy() does a real network request with up to a 10s
        # timeout - running it directly here would freeze the whole
        # dialog (and the whole app, since this is modal) for that long.
        self._proxy_test_thread, self._proxy_test_worker = workers.run_callable(
            debugging.check_proxy, proxy_url, verify=verify,
            on_finished=self._on_proxy_test_result,
        )

    def _on_proxy_test_result(self, result):
        ok, err = result
        self.test_button.setEnabled(True)
        if ok:
            self.test_result_label.setText("\u2705 Proxy is reachable.")
            self.test_result_label.setStyleSheet(f"color: {Color.SUCCESS};")
        else:
            self.test_result_label.setText(f"\u274c {err}")
            self.test_result_label.setStyleSheet(f"color: {Color.DANGER};")

    def _collect_optimizer_settings(self):
        self.opt_pingo = self.pingo_cb.isChecked()
        self.opt_replace = self.replace_cb.isChecked()
        self.opt_lossy = self.lossy_cb.isChecked()
        self.opt_jpeg_q = self.jpeg_spin.value()
        self.opt_webp_q = self.webp_spin.value()
        self.opt_threads = self.threads_spin.value()

    def _on_open_upload_history(self):
        from .upload_history_dialog import UploadHistoryDialog
        dialog = UploadHistoryDialog(parent=self, session=self.session, username=self.username)
        dialog.exec()

    def _on_dry_run(self):
        self.launch_mode = "dry_run"
        self.opt_mode = "disabled"
        self.accept()

    def _on_accept(self):
        proxy_url = self.proxy_input.text().strip()
        if proxy_url:
            self.continue_button.setEnabled(False)
            self.continue_button.setText("Checking proxy\u2026")
            verify = not self.no_verify_checkbox.isChecked()
            self._accept_check_thread, self._accept_check_worker = workers.run_callable(
                debugging.check_proxy, proxy_url, verify=verify,
                on_finished=lambda result: self._finish_accept(proxy_url, result),
            )
            return

        self._finish_accept(proxy_url, (True, None))

    def _finish_accept(self, proxy_url, proxy_check_result):
        self.continue_button.setEnabled(True)
        self.continue_button.setText("Continue")

        ok, err = proxy_check_result
        if proxy_url and not ok:
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Question)
            msg.setWindowTitle("Proxy check failed")
            msg.setText(f"Proxy health check failed: {err}\n\nContinue anyway?")
            yes_btn = msg.addButton(QMessageBox.Yes)
            msg.addButton(QMessageBox.No)
            msg.setDefaultButton(QMessageBox.No)
            msg.exec()
            if msg.clickedButton() != yes_btn:
                return

        self.proxy_url = proxy_url or None
        self.proxy_no_verify = self.no_verify_checkbox.isChecked()
        self.debug_enabled = self.debug_checkbox.isChecked()
        self.launch_mode = "normal"

        if self.radio_chained.isChecked():
            self.opt_mode = "chained"
        elif self.radio_standalone.isChecked():
            self.opt_mode = "standalone"
        else:
            self.opt_mode = "disabled"

        self._collect_optimizer_settings()

        if self.stay_open_on_accept:
            self.settings_confirmed.emit()
        else:
            self.accept()

    def closeEvent(self, event):
        for thread in (self._proxy_test_thread, self._accept_check_thread):
            if thread is not None and thread_is_running(thread):
                thread.quit()
                thread.wait(2000)
        super().closeEvent(event)