"""Small reusable, pre-styled widgets shared across screens.

Keeping these in one place means every screen that needs a section
header, a card container, a status pill, etc. looks and behaves
identically instead of each screen inventing its own slightly
different version.
"""
import html
import logging
import threading

from PySide6.QtCore import Qt, Signal, QUrl, QObject, QByteArray, QSize, QBuffer
from PySide6.QtGui import QColor, QPainter, QPixmap, QIcon, QMovie, QPainterPath
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtWidgets import (
    QWidget, QLabel, QPushButton, QLineEdit, QVBoxLayout, QHBoxLayout, QFrame,
    QGraphicsDropShadowEffect, QSizePolicy, QToolButton
)

from . import theme, thread_is_running, workers
from .theme import Color
from .. import net
from .. import image_cache

_GLOSSY_CYAN_BUTTON_STYLE = """
QPushButton {
    color: #eafffb;
    background-color: rgba(103, 232, 249, 34);
    border: 1px solid rgba(103, 232, 249, 100);
    border-top: 1px solid rgba(180, 246, 255, 130);
    border-radius: 10px;
    font-weight: 600;
    font-size: 13px;
    padding: 6px 18px;
}
QPushButton:hover {
    background-color: rgba(103, 232, 249, 55);
    border: 1px solid rgba(103, 232, 249, 160);
    border-top: 1px solid rgba(200, 250, 255, 170);
}
QPushButton:pressed {
    background-color: rgba(103, 232, 249, 75);
    border: 1px solid rgba(103, 232, 249, 190);
}
QPushButton:disabled {
    color: rgba(234, 255, 251, 90);
    background-color: rgba(103, 232, 249, 14);
    border: 1px solid rgba(103, 232, 249, 40);
}
"""


class DialogSafeLineEdit(QLineEdit):
    """A QLineEdit for use inside a QDialog that has its own 'submit'
    button (e.g. a search box next to a Search button, sitting above an
    OK/Accept button row).

    Qt's QDialog has a fallback: if no widget claims Return/Enter as its
    default action, the dialog itself will activate an accept-role
    button on Enter - even when that key press already triggered this
    field's own returnPressed signal. That means a plain QLineEdit's
    Enter key can fire *both* its own handler (e.g. "search") and the
    dialog's accept button (e.g. "confirm") in the same keystroke.

    This subclass marks the Return/Enter key event as handled after its
    normal QLineEdit behavior (including emitting returnPressed) runs,
    so it doesn't also bubble up to the dialog's default-button
    fallback. Connect to `returnPressed` exactly as you would with a
    normal QLineEdit.
    """

    def keyPressEvent(self, event):
        super().keyPressEvent(event)
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            event.accept()


def apply_glass_cyan_button(button):
    button.setStyleSheet(_GLOSSY_CYAN_BUTTON_STYLE)
    glow = QGraphicsDropShadowEffect(button)
    glow.setBlurRadius(24)
    glow.setOffset(0, 0)
    glow.setColor(QColor(103, 232, 249, 130))
    button.setGraphicsEffect(glow)

    def _sync_glow(enabled, _glow=glow):
        _glow.setColor(QColor(103, 232, 249, 130 if enabled else 25))

    original_set_enabled = button.setEnabled

    def _set_enabled(enabled, _orig=original_set_enabled):
        _orig(enabled)
        _sync_glow(enabled)

    button.setEnabled = _set_enabled
    _sync_glow(button.isEnabled())
    return button


def heading(text, subtitle=None, parent=None):
    """A page-level heading, optionally with a muted subtitle line below it."""
    wrap = QWidget(parent)
    layout = QVBoxLayout(wrap)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)

    title = QLabel(text)
    title.setProperty("role", "heading")
    layout.addWidget(title)

    if subtitle:
        sub = QLabel(subtitle)
        sub.setProperty("role", "subheading")
        sub.setWordWrap(True)
        layout.addWidget(sub)

    return wrap


def section_label(text, parent=None):
    """Small caps-style section label, e.g. 'NETWORK & DEBUGGING'."""
    lbl = QLabel(text.upper(), parent)
    lbl.setProperty("role", "section")
    return lbl


def hint_label(text, parent=None):
    lbl = QLabel(text, parent)
    lbl.setProperty("role", "hint")
    lbl.setWordWrap(True)
    return lbl


class Card(QFrame):
    """A softly elevated container used to group related controls."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("card", "true")
        self._layout = QVBoxLayout(self)
        
        # Increased internal padding to match the softer, borderless aesthetic
        self._layout.setContentsMargins(24, 20, 24, 20) 
        self._layout.setSpacing(12)

        # Softer, slightly wider drop shadow to compensate for the removed border line
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(32)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(0, 0, 0, 80))
        self.setGraphicsEffect(shadow)

    def layout(self):
        return self._layout

    def addWidget(self, w):
        self._layout.addWidget(w)

    def addLayout(self, l):
        self._layout.addLayout(l)


class Divider(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.HLine)
        self.setFixedHeight(1)
        self.setStyleSheet(f"background-color: {Color.BORDER_SOFT}; border: none;")


class VDivider(QFrame):
    """Vertical counterpart to Divider - a thin vertical rule used to split
    a card into two side-by-side panels (e.g. search/results on the left,
    a preview on the right) instead of stacking them."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.VLine)
        self.setFixedWidth(1)
        self.setStyleSheet(f"background-color: {Color.BORDER_SOFT}; border: none;")


class StatusPill(QLabel):
    _STYLES = {
        "neutral": (Color.BG_HOVER, Color.TEXT_SECONDARY, Color.BORDER),
        "info":    (Color.ACCENT_SOFT, Color.ACCENT, Color.ACCENT_SOFT_BORDER),
        "success": (Color.SUCCESS_SOFT, Color.SUCCESS, "#215c3c"),
        "warning": (Color.WARNING_SOFT, Color.WARNING, "#5c4a1a"),
        "danger":  (Color.DANGER_SOFT, Color.DANGER, "#5c2c2c"),
        "violet":  (Color.VIOLET_SOFT, Color.VIOLET, Color.VIOLET_SOFT_BORDER),
    }
    _MAX_CHARS = 28

    def __init__(self, text="", kind="neutral", parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setTextFormat(Qt.RichText)
        self._kind = kind
        self._full_text = text
        self._detail = ""
        self._apply(kind)
        self._style_applied = True
        self._set_display_text(text)

    def _set_display_text(self, text):
        # text is always the plain (no-detail) status string here - the
        # dim byte-count fragment is layered on separately in
        # _render(), so truncation math (_MAX_CHARS) only ever has to
        # reason about plain status text, not markup.
        self._full_text = text
        self._render()

    def _render(self):
        # Truncate against the plain status text alone, so a long
        # detail string (e.g. "1024.00/2048.00MB") can never eat into
        # the status label's own character budget or get counted
        # towards the "..." cutoff.
        if len(self._full_text) > self._MAX_CHARS:
            shown = self._full_text[: self._MAX_CHARS - 1].rstrip() + "\u2026"
            self.setToolTip(self._full_text)
        else:
            shown = self._full_text
            self.setToolTip("")

        shown_html = html.escape(shown)
        if self._detail:
            # Detail (e.g. "20/40MB") rendered in a visibly dimmer color
            # than the pill's own foreground, so it reads as secondary,
            # in-progress information rather than part of the status
            # word itself.
            super().setText(
                f'{shown_html} <span style="color:{Color.TEXT_DISABLED};">'
                f'{html.escape(self._detail)}</span>'
            )
        else:
            super().setText(shown_html)

    def setText(self, text):
        self._set_display_text(text)

    def text(self):
        return self._full_text

    def set_detail(self, detail):
        """Set (or clear, with '' / None) the dim inline fragment shown
        after the status text - e.g. a live '20/40MB' readout while a
        file is uploading. Cleared automatically by set_kind() whenever
        the pill moves to a terminal state (success/danger), since a
        finished or failed row has no "so far" byte count left to show."""
        self._detail = detail or ""
        self._render()

    def detail(self):
        return self._detail

    def _apply(self, kind):
        bg, fg, border = self._STYLES.get(kind, self._STYLES["neutral"])
        self.setStyleSheet(
            f"background-color: {bg}; color: {fg}; border: 1px solid {border}; "
            f"border-radius: 9px; padding: 2px 10px; font-size: 11px; font-weight: 600;"
        )

    def set_kind(self, kind, text=None, detail=None):
        # _apply() rebuilds and reapplies this pill's whole stylesheet,
        # which forces Qt's style engine to reparse + repolish this
        # widget. On a big batch, nearly every tick calls set_kind()
        # with the SAME kind as last time (e.g. "uploading" ->
        # "uploading" with just a new percentage) - restyling on every
        # one of those was pure waste, and with ~150 rows all getting
        # their first tick within the same burst at upload start, that
        # waste compounded into severe native call-stack pressure in
        # Qt's style engine (observed as a Windows stack-overflow crash
        # right at the start of large batches, never at ~20 files).
        # Only reapply the stylesheet when the kind actually changes.
        if kind != self._kind or not self._style_applied:
            self._apply(kind)
            self._style_applied = True
        self._kind = kind
        if kind in ("success", "danger"):
            # Terminal states: the file is done or failed, there's no
            # "so far" byte count left to show, and a stale "40/40MB"
            # sitting next to "Uploaded" would just be visual noise.
            self._detail = ""
        elif detail is not None:
            self._detail = detail
        if text is not None:
            self._full_text = text
        self._render()


class StepBadge(QLabel):
    """A small numbered/labelled pill used in a horizontal progress strip
    ('1 Login  ->  2 Manga  ->  3 Attribution  ->  ...')."""

    def __init__(self, number, text, parent=None):
        super().__init__(parent)
        self.setText(f"{number}")
        self._text = text
        self.number = number
        self.setAlignment(Qt.AlignCenter)
        self.setFixedSize(22, 22)
        self.set_state("upcoming")

    def set_state(self, state):
        # state: 'upcoming' | 'current' | 'done'
        if state == "done":
            # Finished steps fill solid green (traffic-light green) rather
            # than the cyan accent - a completed stage should read as
            # unambiguously "done", distinct from "current" (still cyan).
            self.setStyleSheet(
                f"background-color: {Color.SUCCESS}; color: {Color.TEXT_ON_SUCCESS}; "
                f"border-radius: 11px; font-weight: 700; font-size: 11px;"
            )
            self.setText("\u2713")
        elif state == "current":
            self.setStyleSheet(
                f"background-color: transparent; color: {Color.ACCENT}; "
                f"border: 2px solid {Color.ACCENT}; border-radius: 11px; "
                f"font-weight: 700; font-size: 11px;"
            )
            self.setText(str(self.number))
        else:
            self.setStyleSheet(
                f"background-color: transparent; color: {Color.TEXT_MUTED}; "
                f"border: 2px solid {Color.BORDER}; border-radius: 11px; "
                f"font-weight: 700; font-size: 11px;"
            )
            self.setText(str(self.number))


class StepStrip(QWidget):
    STEPS = ["Sign in", "Manga", "Attribution", "Review", "Upload", "Done"]

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, 12, 24, 12)
        layout.setSpacing(0)

        self._badges = []
        self._connectors = []

        for i, name in enumerate(self.STEPS):
            item = QWidget()
            item.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
            item_layout = QHBoxLayout(item)
            item_layout.setContentsMargins(0, 0, 0, 0)
            item_layout.setSpacing(6)

            badge = StepBadge(i + 1, name)
            label = QLabel(name)
            label.setStyleSheet(f"color: {Color.TEXT_MUTED}; font-size: 11px; font-weight: 600;")
            label.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
            self._badges.append((badge, label))

            item_layout.addWidget(badge)
            item_layout.addWidget(label)
            layout.addWidget(item)

            if i < len(self.STEPS) - 1:
                conn = QFrame()
                conn.setFixedHeight(1)
                conn.setMinimumWidth(12)
                conn.setStyleSheet(f"background-color: {Color.BORDER};")
                self._connectors.append(conn)
                layout.addWidget(conn, 1)

        layout.addStretch(0)
        self.setFixedHeight(56)
        self.setMinimumWidth(0)
        self.set_current(0)

    def set_current(self, index):
        for i, (badge, label) in enumerate(self._badges):
            if i < index:
                badge.set_state("done")
                label.setStyleSheet(f"color: {Color.TEXT_SECONDARY}; font-size: 11px; font-weight: 600;")
            elif i == index:
                badge.set_state("current")
                label.setStyleSheet(f"color: {Color.TEXT_PRIMARY}; font-size: 11px; font-weight: 700;")
            else:
                badge.set_state("upcoming")
                label.setStyleSheet(f"color: {Color.TEXT_MUTED}; font-size: 11px; font-weight: 600;")
        for i, conn in enumerate(self._connectors):
            color = Color.ACCENT_SOFT_BORDER if i < index else Color.BORDER
            conn.setStyleSheet(f"background-color: {color};")


class EmptyState(QWidget):
    def __init__(self, icon="", title="Nothing here yet", subtitle="", parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(6)

        if icon:
            icon_lbl = QLabel(icon)
            icon_lbl.setAlignment(Qt.AlignCenter)
            icon_lbl.setStyleSheet("font-size: 32px;")
            layout.addWidget(icon_lbl)

        title_lbl = QLabel(title)
        title_lbl.setAlignment(Qt.AlignCenter)
        title_lbl.setStyleSheet(f"color: {Color.TEXT_SECONDARY}; font-weight: 600; font-size: 13px;")
        layout.addWidget(title_lbl)

        if subtitle:
            sub_lbl = QLabel(subtitle)
            sub_lbl.setAlignment(Qt.AlignCenter)
            sub_lbl.setWordWrap(True)
            sub_lbl.setStyleSheet(f"color: {Color.TEXT_MUTED}; font-size: 11px;")
            layout.addWidget(sub_lbl)


class SegmentedToggle(QWidget):
    """Compact multi-option toggle rendered as a single pill-shaped strip
    with one highlighted segment - e.g. 'Chapter #' / 'Upload time' for
    the upload table's sort mode. Deliberately not a QButtonGroup of
    separate QPushButtons: those'd need per-button style juggling to
    look like one continuous control, where this just draws N adjacent
    QToolButtons inside a single bordered QFrame and lets each one's
    :checked state (via setCheckable/setChecked, one-exclusive by hand)
    carry the active-segment styling.

    options: list of (value, label) pairs. value is whatever's passed
    to changed(value) and current(); label is the button text.
    """
    changed = Signal(object)

    def __init__(self, options, current=None, parent=None):
        super().__init__(parent)
        self._options = options
        self._current = current if current is not None else options[0][0]
        self._buttons = {}

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        frame = QFrame()
        frame.setObjectName("segmentedToggle")
        frame.setStyleSheet(
            f"QFrame#segmentedToggle {{ background-color: {Color.BG_INPUT}; "
            f"border: 1px solid {Color.BORDER}; border-radius: 8px; }}"
        )
        row = QHBoxLayout(frame)
        row.setContentsMargins(3, 3, 3, 3)
        row.setSpacing(2)

        for value, label in options:
            btn = QToolButton()
            btn.setText(label)
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setAutoRaise(True)
            btn.clicked.connect(lambda _checked, v=value: self._select(v))
            row.addWidget(btn)
            self._buttons[value] = btn

        outer.addWidget(frame)
        self._refresh_styles()

    def _refresh_styles(self):
        for value, btn in self._buttons.items():
            active = value == self._current
            btn.setChecked(active)
            if active:
                btn.setStyleSheet(
                    f"QToolButton {{ background-color: {Color.ACCENT_SOFT}; "
                    f"color: {Color.ACCENT}; border: none; border-radius: 6px; "
                    f"padding: 4px 10px; font-size: 11px; font-weight: 600; }}"
                )
            else:
                btn.setStyleSheet(
                    f"QToolButton {{ background-color: transparent; "
                    f"color: {Color.TEXT_SECONDARY}; border: none; border-radius: 6px; "
                    f"padding: 4px 10px; font-size: 11px; font-weight: 600; }}"
                    f"QToolButton:hover {{ color: {Color.TEXT_PRIMARY}; }}"
                )

    def _select(self, value):
        if value == self._current:
            # Clicking the already-active segment shouldn't re-emit
            # changed() - nothing actually changed, and callers that
            # rebuild the table on every changed() signal would do a
            # pointless relayout.
            self._refresh_styles()
            return
        self._current = value
        self._refresh_styles()
        self.changed.emit(value)

    def current(self):
        return self._current

    def set_current(self, value):
        if value == self._current:
            return
        self._current = value
        self._refresh_styles()


class StatCard(QFrame):
    """One clickable KPI tile ('119 DONE' etc). Clicking toggles this
    card as the active status filter for the upload table (see
    UploadProgressScreen._on_stat_card_clicked): clicking an inactive
    card filters the table down to just that status; clicking the
    already-active card clears the filter back to All. set_active()
    only ever changes the border/background - the label and value text
    are untouched, so a card can be re-styled as active/inactive at any
    time without losing whatever count set_value() last drew there."""
    clicked = Signal()

    def __init__(self, value="-", label="", kind="neutral", parent=None):
        super().__init__(parent)
        self.setProperty("card", "true")
        self.setObjectName("statCard")
        self._kind = kind
        self._active = False
        self.setCursor(Qt.PointingHandCursor)
        self._apply_frame_style()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(2)

        color = {
            "success": Color.SUCCESS,
            "danger": Color.DANGER,
            "warning": Color.WARNING,
            "accent": Color.ACCENT,
        }.get(kind, Color.TEXT_PRIMARY)

        self.value_label = QLabel(value)
        self.value_label.setStyleSheet(f"color: {color}; font-size: 22px; font-weight: 700;")
        layout.addWidget(self.value_label)

        self.caption_label = QLabel(label.upper())
        self.caption_label.setStyleSheet(
            f"color: {Color.TEXT_MUTED}; font-size: 10px; font-weight: 600; letter-spacing: 0.5px;"
        )
        layout.addWidget(self.caption_label)

    def _apply_frame_style(self):
        border = Color.ACCENT if self._active else Color.BORDER
        bg = Color.BG_HOVER if self._active else Color.BG_APP
        width = 2 if self._active else 1
        self.setStyleSheet(
            f"QFrame#statCard {{ background-color: {bg}; "
            f"border: {width}px solid {border}; border-radius: 9px; }}"
        )

    def set_value(self, value):
        self.value_label.setText(str(value))

    def set_active(self, active: bool):
        if active == self._active:
            return
        self._active = active
        self._apply_frame_style()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class _AvatarWorker(QObject):
    finished = Signal(object)
    
    def __init__(self, url, session=None):
        super().__init__()
        self.url = url
        self.session = session
        
    def run(self):
        data = net.fetch_image_bytes(self.session, self.url)
        self.finished.emit(data)


class ProfileCardWidget(QFrame):
    profile_ready = Signal()  
    _AVATAR_SIZE = 72

    def __init__(self, profile=None, fallback_username="", session=None, parent=None):
        super().__init__(parent)
        self.session = session 
        self.setProperty("card", "true")
        self.setObjectName("profileCard")
        self.setStyleSheet(
            f"QFrame#profileCard {{ background-color: rgba(92, 225, 230, 18); "
            f"border: 2px solid {Color.ACCENT_SOFT_BORDER}; border-radius: {theme.RADIUS_MD}px; }}"
        )
        self.setMaximumWidth(640)
        self._avatar_thread = None
        self._avatar_worker = None
        self._fallback_username = fallback_username

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(14)

        top_row = QHBoxLayout()
        top_row.setSpacing(14)

        self.avatar_label = QLabel()
        self.avatar_label.setFixedSize(self._AVATAR_SIZE, self._AVATAR_SIZE)
        self.avatar_label.setAlignment(Qt.AlignCenter)
        self.avatar_label.setStyleSheet(
            f"background-color: {Color.BG_HOVER}; border-radius: {self._AVATAR_SIZE // 2}px;"
        )
        top_row.addWidget(self.avatar_label)

        name_col = QVBoxLayout()
        name_col.setSpacing(4)

        self.name_label = QLabel(fallback_username or "Loading profile\u2026")
        self.name_label.setStyleSheet(
            f"color: {Color.TEXT_PRIMARY}; font-size: 18px; font-weight: 700;"
        )
        name_col.addWidget(self.name_label)

        self.role_pill = StatusPill("", "violet")
        self.role_pill.setVisible(False)
        name_col.addWidget(self.role_pill, alignment=Qt.AlignLeft)

        top_row.addLayout(name_col, 1)
        top_row.setAlignment(Qt.AlignVCenter)
        layout.addLayout(top_row)

        stats_row = QHBoxLayout()
        stats_row.setSpacing(10)
        self.tracked_stat = StatCard("-", "Tracked")
        self.chapters_stat = StatCard("-", "Chapters Read")
        self.completed_stat = StatCard("-", "Completed")
        self.streak_stat = StatCard("-", "Streak")
        for card in (self.tracked_stat, self.chapters_stat, self.completed_stat, self.streak_stat):
            stats_row.addWidget(card)
        layout.addLayout(stats_row)

        self.fallback_hint = hint_label(
            "Signed in, but couldn't load your profile details right now. "
            "You can still continue."
        )
        self.fallback_hint.setVisible(False)
        layout.addWidget(self.fallback_hint)

        if profile:
            self.set_profile(profile)

    def set_fetch_failed(self):
        self.name_label.setText(self._fallback_username or "")
        self.fallback_hint.setVisible(True)
        self.profile_ready.emit()

    def set_profile(self, profile):
        """profile: dict shaped like net.fetch_profile_stats()'s return value."""
        display_name = profile.get("display_name") or profile.get("username") or ""
        self.name_label.setText(display_name)

        role = profile.get("role") or ""
        if role:
            level = profile.get("level")
            self.role_pill.setText(f"{role} \u00b7 Lv {level}" if level is not None else role)
            self.role_pill.setVisible(True)
        else:
            self.role_pill.setVisible(False)

        self.tracked_stat.set_value(profile.get("manga_tracked", 0))
        self.chapters_stat.set_value(profile.get("chapters_read", 0))
        self.completed_stat.set_value(profile.get("manga_completed", 0))
        self.streak_stat.set_value(profile.get("streak", 0))
        self.profile_ready.emit()

        avatar_url = profile.get("avatar_url")
        if avatar_url:
            self._load_avatar(avatar_url)

    def _load_avatar(self, url):
        worker = _AvatarWorker(url, session=self.session)
        self._avatar_thread, self._avatar_worker = workers.run_worker(
            worker, on_finished=self._on_avatar_loaded
        )

    def stop_background_work(self):
        if self._avatar_thread is not None and thread_is_running(self._avatar_thread):
            self._avatar_thread.quit()
            self._avatar_thread.wait(2000)

    def _on_avatar_loaded(self, data):
        if data:
            pixmap = QPixmap()
            if pixmap.loadFromData(data) and not pixmap.isNull():
                self.avatar_label.setPixmap(circular_pixmap(pixmap, self._AVATAR_SIZE))


def _repolish(widget):
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    return widget


def make_primary(button):
    button.setProperty("variant", "primary")
    return _repolish(button)


def make_danger(button):
    button.setProperty("variant", "danger")
    return _repolish(button)


def make_flat(button):
    button.setProperty("variant", "flat")
    return _repolish(button)


def make_flat_link(button, color=None, hover_color=None, bold=False):
    """A borderless, background-less text-only button - the 'Dry Run' look.

    Used directly for Dry Run (crimson) and as the new standing style for
    every Continue button going forward (default flat color, bold=True).
    Pass color/hover_color to override the default flat text color (e.g.
    crimson for Dry Run).
    """
    text_color = color or Color.TEXT_SECONDARY
    hover = hover_color or Color.TEXT_PRIMARY
    weight = 700 if bold else 600
    button.setCursor(Qt.PointingHandCursor)
    button.setStyleSheet(f"""
        QPushButton {{
            background: transparent;
            border: none;
            color: {text_color};
            padding: 6px 10px;
            font-weight: {weight};
        }}
        QPushButton:hover {{
            color: {hover};
        }}
        QPushButton:disabled {{
            color: {Color.TEXT_DISABLED};
        }}
    """)
    return button


# ==============================================================================
# Icon buttons — small SVG-glyph controls (pause / resume / cancel / etc.)
# with a hover-only tooltip and no permanent text label. Used for both the
# global upload-screen controls and per-row controls, so it lives here
# rather than in upload_progress_screen.py - any screen needing a compact
# icon-only action button should reuse this instead of hand-rolling one.
# ==============================================================================

# Raw SVG source per glyph, using `currentColor` so a single string can be
# recolored per-state (normal/hover/disabled) just by changing the fill
# passed to _svg_icon() - no need for multiple copies of each path.
_ICON_PATHS = {
    # Pause: two vertical bars
    "pause": '<path d="M8 5h3v14H8zM13 5h3v14h-3z"/>',
    # Resume/play: right-pointing triangle
    "resume": '<path d="M8 5l11 7-11 7z"/>',
    # Cancel/stop: filled square
    "cancel": '<path d="M6 6h12v12H6z"/>',
    # Chevron used for compact menu triggers (row action button)
    "more": '<path d="M12 7a1.6 1.6 0 110-3.2A1.6 1.6 0 0112 7zm0 6.6a1.6 1.6 0 110-3.2 1.6 1.6 0 010 3.2zM12 20.2a1.6 1.6 0 110-3.2 1.6 1.6 0 010 3.2z"/>',
}


def _svg_icon(name, color, size=18):
    """Renders one of _ICON_PATHS into a QIcon tinted with `color`, at
    `size`x`size` px. Rebuilt on demand rather than cached, since these
    are tiny and only re-rendered when a button's enabled/hover state
    actually changes (a handful of times per session, not per frame)."""
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
        f'width="{size}" height="{size}" fill="{color}">{_ICON_PATHS[name]}</svg>'
    )
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)


class IconButton(QToolButton):
    """A small, borderless, circular icon-only button - SVG glyph, no
    visible text, with the label shown only as a hover tooltip. Used for
    Pause/Resume/Cancel wherever a full text QPushButton would be too
    heavy (the global upload-screen action row, and per-row controls in
    the upload table).

    kind selects both the SVG glyph (from _ICON_PATHS) and the tint:
    'pause'/'resume' use the accent cyan, 'cancel' uses danger red, so a
    cancel button always reads as destructive at a glance without extra
    styling at each call site.
    """

    _TINTS = {
        "pause":  (Color.ACCENT, Color.ACCENT_HOVER),
        "resume": (Color.ACCENT, Color.ACCENT_HOVER),
        "cancel": (Color.DANGER, "#ff8a8a"),
        "more":   (Color.TEXT_SECONDARY, Color.TEXT_PRIMARY),
    }

    def __init__(self, kind, tooltip, size=32, icon_size=16, parent=None):
        super().__init__(parent)
        self._kind = kind
        self._icon_size = icon_size
        self.setToolTip(tooltip)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(size, size)
        self.setIconSize(QSize(icon_size, icon_size))
        self.setAutoRaise(True)
        self._refresh_icon()
        self.setStyleSheet(f"""
            QToolButton {{
                background-color: transparent;
                border: 1px solid transparent;
                border-radius: {size // 2}px;
            }}
            QToolButton:hover {{
                background-color: {Color.BG_HOVER};
                border: 1px solid {Color.BORDER};
            }}
            QToolButton:pressed {{
                background-color: {Color.BG_PRESSED};
            }}
            QToolButton:disabled {{
                background-color: transparent;
            }}
        """)

    def _refresh_icon(self):
        normal, _hover = self._TINTS.get(self._kind, (Color.TEXT_SECONDARY, Color.TEXT_PRIMARY))
        color = normal if self.isEnabled() else Color.TEXT_DISABLED
        self.setIcon(_svg_icon(self._kind, color, size=self._icon_size))

    def setEnabled(self, enabled):
        super().setEnabled(enabled)
        self._refresh_icon()

    def set_kind(self, kind, tooltip=None):
        """Swaps the glyph/tint in place - used to turn a row's Pause
        button into a Resume button (same slot in the layout) once that
        file reports paused, instead of swapping widgets."""
        self._kind = kind
        if tooltip is not None:
            self.setToolTip(tooltip)
        self._refresh_icon()


class GlassBox(QFrame):
    """The bordered, translucent-tinted panel originally built for the Dry
    Run callout - a QFrame with an rgba background tint and a 2px solid
    border, corners rounded at RADIUS_MD. Reused for any button that should
    sit inside this same box shape (Dry Run in crimson, Continue in cyan),
    with only the tint/border color swapped between call sites so the two
    boxes read as a matched pair rather than two different components.
    """

    def __init__(self, tint_rgba, border_color, parent=None):
        super().__init__(parent)
        self.setObjectName("glassBox")
        self.setStyleSheet(f"""
            QFrame#glassBox {{
                background-color: {tint_rgba};
                border: 2px solid {border_color};
                border-radius: {theme.RADIUS_MD}px;
            }}
        """)


def circular_pixmap(source: QPixmap, size: int) -> QPixmap:
    """Returns a circular-cropped copy of source, scaled to size x size."""
    scaled = source.scaled(size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    result = QPixmap(size, size)
    result.fill(Qt.transparent)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.Antialiasing)
    path_rect = result.rect()
    from PySide6.QtGui import QPainterPath
    path = QPainterPath()
    path.addEllipse(0, 0, size, size)
    painter.setClipPath(path)
    x = (size - scaled.width()) // 2
    y = (size - scaled.height()) // 2
    painter.drawPixmap(x, y, scaled)
    painter.end()
    return result

def attach_combo_dots_overlay(combo):
    """Injects the custom cyan dots overlay to fix the invisible arrow bug."""
    dots = QLabel("\u22ef", combo)
    dots.setAttribute(Qt.WA_TransparentForMouseEvents)
    dots.setAlignment(Qt.AlignCenter)
    dots.setStyleSheet(
        f"color: {Color.ACCENT}; background: transparent; font-size: 15px; font-weight: 700;"
    )

    def _position_dots():
        w = combo.width()
        h = combo.height()
        dots.setFixedSize(28, h)
        dots.move(w - 28, 0)
        dots.show()
        dots.raise_()

    class _ComboResizeFilter(QObject):
        def eventFilter(_self, watched, event):
            if event.type() in (event.Type.Resize, event.Type.Show, event.Type.Polish):
                _position_dots()
            return False

    resize_filter = _ComboResizeFilter(combo)
    combo._dots_resize_filter = resize_filter
    combo.installEventFilter(resize_filter)
    _position_dots()
    return dots


# ==============================================================================
# Animated (WebP/GIF) image support
# ==============================================================================

def _looks_animated(data: bytes) -> bool:
    """Cheap sniff for whether raw image bytes are an animated WebP or GIF,
    without fully decoding them first. Static images (a plain PNG-in-WebP
    frame, a JPEG, etc.) should never pay for a QMovie - a QPixmap is both
    cheaper and doesn't leave a running timer around.
    """
    if not data:
        return False
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        # An animated WebP carries an 'ANIM' chunk in its RIFF container.
        return b"ANIM" in data[:200] or b"ANIM" in data
    if data[:6] in (b"GIF87a", b"GIF89a"):
        # Multiple Image Descriptor blocks (0x2C) => more than one frame.
        return data.count(b"\x2c") > 1
    return False


class AnimatedImageLabel(QLabel):
    """A QLabel that plays animated WebP/GIF bytes via QMovie, and falls
    back to a plain QPixmap for static images. Supports an optional
    rounded-rect (or fully circular) clip mask applied every frame.

    This exists because the site's avatars and cover photos can be
    animated WebPs, and Qt's default pixmap loading only ever shows the
    first frame - QMovie is Qt's actual animation driver and (confirmed
    on this PySide6 build) supports both 'gif' and 'webp'.
    """

    def __init__(self, width: int, height: int, radius: int = 0, parent=None):
        super().__init__(parent)
        self._w = width
        self._h = height
        self._radius = radius  # 0 = square corners, width//2 with width==height = circle
        self._movie = None
        self._raw_frame = None
        self.setFixedSize(width, height)
        self.setAlignment(Qt.AlignCenter)
        self.setScaledContents(False)

    def set_radius(self, radius: int):
        self._radius = radius
        if self._raw_frame is not None:
            self._apply_frame(self._raw_frame)

    def set_target_size(self, width: int, height: int):
        """Update the size frames are scaled/cropped into, and re-render
        the current frame at the new size. setFixedSize() alone only
        changes the widget's on-screen size - it does NOT change what
        size _apply_frame() scales into, so without this a resized label
        keeps rendering into whatever size it was constructed with.
        """
        if width <= 0 or height <= 0:
            return
        self._w = width
        self._h = height
        self.setFixedSize(width, height)
        if self._raw_frame is not None:
            self._apply_frame(self._raw_frame)

    def set_bytes(self, data: bytes):
        """Load new image bytes, animated or static."""
        self._stop_movie()

        if not data:
            self.clear()
            self._raw_frame = None
            return

        if _looks_animated(data):
            movie = QMovie(self)
            fmt = b"WEBP" if data[:4] == b"RIFF" else b"GIF"
            movie.setFormat(fmt)
            self._movie_buffer = QByteArray(data)  # keep alive - QMovie doesn't own it
            self._qbuffer = QBuffer(self._movie_buffer)
            self._qbuffer.open(QBuffer.ReadOnly)
            movie.setDevice(self._qbuffer)
            movie.setCacheMode(QMovie.CacheAll)
            # isValid() alone isn't enough - it can return True for data
            # QMovie recognizes the container/header of but can't actually
            # decode any frames from (confirmed: truncated/corrupt WebP
            # bytes come back isValid()=True, frameCount()=0). A movie
            # with zero frames would just show nothing while silently
            # "succeeding", so frameCount() > 0 is the real check.
            if movie.isValid() and movie.frameCount() != 0:
                self._movie = movie
                movie.frameChanged.connect(self._on_frame_changed)
                movie.start()
                logging.debug(
                    "AnimatedImageLabel: playing %s animation, %d bytes, %d frame(s)",
                    fmt.decode(), len(data), movie.frameCount(),
                )
                return
            # QMovie rejected the data, or accepted it but found no
            # frames - log why, then fall through to the static-image
            # path as a best-effort fallback (it'll only show frame 1,
            # but that's better than nothing).
            logging.warning(
                "AnimatedImageLabel: QMovie could not play %s data (%d bytes) - "
                "valid=%s frameCount=%d error=%s; falling back to static frame",
                fmt.decode(), len(data), movie.isValid(), movie.frameCount(),
                movie.lastErrorString(),
            )

        pixmap = QPixmap()
        if pixmap.loadFromData(data) and not pixmap.isNull():
            self._apply_frame(pixmap)
        else:
            logging.warning(
                "AnimatedImageLabel: QPixmap could not decode %d bytes "
                "(header=%r) - leaving label blank",
                len(data), data[:16],
            )
            self.clear()

    def _on_frame_changed(self, _frame_index):
        if self._movie is not None:
            self._apply_frame(self._movie.currentPixmap())

    def _apply_frame(self, pixmap: QPixmap):
        self._raw_frame = pixmap
        scaled = pixmap.scaled(
            self._w, self._h, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
        )
        if self._radius <= 0:
            # Center-crop to exact size with square corners.
            result = QPixmap(self._w, self._h)
            result.fill(Qt.transparent)
            painter = QPainter(result)
            painter.setRenderHint(QPainter.Antialiasing)
            x = (self._w - scaled.width()) // 2
            y = (self._h - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)
            painter.end()
            self.setPixmap(result)
            return

        result = QPixmap(self._w, self._h)
        result.fill(Qt.transparent)
        painter = QPainter(result)
        painter.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(0, 0, self._w, self._h, self._radius, self._radius)
        painter.setClipPath(path)
        x = (self._w - scaled.width()) // 2
        y = (self._h - scaled.height()) // 2
        painter.drawPixmap(x, y, scaled)
        painter.end()
        self.setPixmap(result)

    def _stop_movie(self):
        if self._movie is not None:
            self._movie.stop()
            self._movie.frameChanged.disconnect(self._on_frame_changed)
            self._movie.deleteLater()
            self._movie = None

    def stop(self):
        self._stop_movie()


class _BannerImageWorker(QObject):
    """Fetches avatar + cover bytes off the UI thread.

    Runs both fetches concurrently (two threads) rather than one after
    the other, and emits each image's signal the moment THAT fetch
    finishes rather than waiting for both - avatar and cover are
    independent images from independent URLs, so there's no reason a
    slow cover fetch should hold up an avatar that already arrived (or
    vice versa). Previously this fetched avatar_bytes then cover_bytes
    sequentially and only emitted once, at the end, with both - on the
    sign-in screen that showed up as the whole profile card's text
    rendering immediately (see set_profile) while the avatar and cover
    both stayed blank for however long the SLOWER of the two images
    took, even if the other had already downloaded."""
    avatar_ready = Signal(object)
    cover_ready = Signal(object)
    finished = Signal()  # no payload - run_worker's thread-teardown wiring needs this

    def __init__(self, avatar_url, cover_url, session=None):
        super().__init__()
        self.avatar_url = avatar_url
        self.cover_url = cover_url
        self.session = session

    def run(self):
        threads = []
        if self.avatar_url:
            t = threading.Thread(target=self._fetch_and_emit, args=(self.avatar_url, self.avatar_ready), daemon=True)
            t.start()
            threads.append(t)
        if self.cover_url:
            t = threading.Thread(target=self._fetch_and_emit, args=(self.cover_url, self.cover_ready), daemon=True)
            t.start()
            threads.append(t)
        for t in threads:
            t.join()
        self.finished.emit()

    def _fetch_and_emit(self, url, signal):
        data = net.fetch_image_bytes(self.session, url)
        signal.emit(data)


class ProfileBannerWidget(QFrame):
    """Full-bleed profile banner matching the site's own profile header:
    a cover photo (animation-capable) filling the whole widget, a dark
    gradient fade toward the bottom, and the avatar/name/stats/bio laid
    over it in the site's own arrangement.

    This is a separate widget from ProfileCardWidget on purpose - that
    one stays a small boxed card wherever it's already used; this one is
    for the "takes up the whole page" placement.
    """
    profile_ready = Signal()

    _AVATAR_SIZE = 96
    _AVATAR_RADIUS = 18
    _MIN_HEIGHT = 340

    def __init__(self, profile=None, fallback_username="", session=None, parent=None):
        super().__init__(parent)
        self.session = session
        self._fallback_username = fallback_username
        self._image_thread = None
        self._image_worker = None
        self._pending_cache_username = ""

        self.setObjectName("profileBanner")
        self.setMinimumHeight(self._MIN_HEIGHT)
        self.setStyleSheet(
            f"QFrame#profileBanner {{ background-color: {Color.BG_BASE}; "
            f"border: 1px solid {Color.BORDER}; border-radius: {theme.RADIUS_MD}px; }}"
        )
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # Cover photo fills the whole frame; the gradient and the
        # text/avatar overlay are layered on top of it as manually
        # positioned children (kept in sync with the frame's size in
        # resizeEvent AND set once here at construction time, so there's
        # no window where cover_label sits at its stale 10x10 default
        # geometry before the widget has ever been resized/shown).
        #
        # A QStackedLayout(StackAll) was tried here instead and reverted:
        # confirmed by direct pixel testing that Qt does not actually
        # alpha-composite translucent StackAll layers on top of each
        # other - the top layer's stylesheet background painted fully
        # opaque regardless of its rgba alpha, hiding everything below
        # it. Manual child widgets with real geometry render correctly
        # (also confirmed via grab()/render() pixel sampling), so that's
        # what's kept here.
        self.cover_label = AnimatedImageLabel(10, 10, radius=0, parent=self)
        self.cover_label.setStyleSheet(f"background-color: {Color.BG_RAISED}; border: none;")

        self._gradient_overlay = QWidget(self)
        self._gradient_overlay.setAttribute(Qt.WA_TransparentForMouseEvents)
        # Deliberately NOT setting WA_TranslucentBackground here - confirmed
        # by direct testing that it silently prevents this widget's rgba()
        # qlineargradient stylesheet from painting its varying alpha at all
        # (every stop's alpha effectively became "fully see-through",
        # collapsing the whole dark-light-dark fade to nothing). The
        # gradient's own per-stop alpha values already make it non-opaque
        # where it needs to be, so this attribute isn't needed here the
        # way it is for overlay/header (which have no gradient of their
        # own and rely on it to avoid painting an opaque background).
        self._apply_gradient_style()

        self.overlay = QWidget(self)
        # Same reasoning as _gradient_overlay above: force this to be
        # genuinely transparent so it can't silently paint an opaque
        # background over cover_label on platforms/styles where an
        # unstyled QWidget doesn't default to transparent.
        self.overlay.setAttribute(Qt.WA_TranslucentBackground)
        self.overlay.setStyleSheet("background: transparent;")
        self._overlay_layout = QVBoxLayout(self.overlay)
        self._overlay_base_bottom_margin = 20
        self._overlay_layout.setContentsMargins(24, 0, 24, self._overlay_base_bottom_margin)
        self._overlay_layout.setSpacing(0)
        self._overlay_layout.addStretch(3)
        overlay_layout = self._overlay_layout  # local alias, rest of __init__ unchanged below

        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(18)
        bottom_row.setAlignment(Qt.AlignBottom)

        self.avatar_label = AnimatedImageLabel(
            self._AVATAR_SIZE, self._AVATAR_SIZE, radius=self._AVATAR_RADIUS
        )
        self.avatar_label.setStyleSheet(
            f"background-color: {Color.BG_HOVER}; border-radius: {self._AVATAR_RADIUS}px;"
        )

        text_col = QVBoxLayout()
        text_col.setSpacing(6)

        self.kicker_label = QLabel((fallback_username and "READER") or "")
        self.kicker_label.setStyleSheet(
            "color: rgba(232,236,241,0.45); font-size: 11px; font-weight: 500; "
            "letter-spacing: 3px; background: transparent;"
        )
        text_col.addWidget(self.kicker_label)

        self.name_label = QLabel(fallback_username or "Loading profile\u2026")
        self.name_label.setStyleSheet(
            "color: #ffffff; font-size: 34px; font-weight: 900; background: transparent;"
        )
        text_col.addWidget(self.name_label)

        self.stats_label = QLabel("")
        self.stats_label.setTextFormat(Qt.RichText)
        self.stats_label.setStyleSheet(
            "color: rgba(232,236,241,0.7); font-size: 14px; background: transparent;"
        )
        text_col.addWidget(self.stats_label)

        self.social_label = QLabel("")
        self.social_label.setTextFormat(Qt.RichText)
        self.social_label.setStyleSheet(
            "color: rgba(232,236,241,0.45); font-size: 12px; background: transparent;"
        )
        text_col.addWidget(self.social_label)

        text_col.addSpacing(4)

        self.bio_pill = QLabel("")
        self.bio_pill.setWordWrap(True)
        self.bio_pill.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.bio_pill.setStyleSheet(
            "color: rgba(232,236,241,0.85); font-size: 12px; background: rgba(0,0,0,0.35); "
            "border-radius: 14px; padding: 7px 14px;"
        )
        self.bio_pill.setVisible(False)
        text_col.addWidget(self.bio_pill)

        bottom_row.addWidget(self.avatar_label, alignment=Qt.AlignBottom)
        bottom_row.addLayout(text_col, 1)
        overlay_layout.addLayout(bottom_row)

        self.fallback_hint = hint_label(
            "Signed in, but couldn't load your profile details right now. "
            "You can still continue."
        )
        self.fallback_hint.setVisible(False)
        self.fallback_hint.setStyleSheet(
            self.fallback_hint.styleSheet() + " background: transparent;"
        )
        overlay_layout.addWidget(self.fallback_hint)
        overlay_layout.addStretch(1)
        self.cover_label.lower()
        self._gradient_overlay.stackUnder(self.overlay)
        self.overlay.raise_()
        self._sync_layer_geometry()

        if profile:
            self.set_profile(profile)

    def _apply_gradient_style(self):
        self._gradient_overlay.setStyleSheet(
            "background: qlineargradient(x1:0, y1:0, x2:0, y2:1, "
            "stop:0 rgba(8,8,10,175), "
            "stop:0.12 rgba(8,8,10,80), "
            "stop:0.25 rgba(8,8,10,15), "
            "stop:0.45 rgba(8,8,10,40), "
            "stop:0.65 rgba(8,8,10,130), "
            "stop:0.85 rgba(8,8,10,210), "
            "stop:1 rgba(8,8,10,245));"
        )

    def _sync_layer_geometry(self):
        rect = self.contentsRect()
        if rect.width() <= 0 or rect.height() <= 0:
            return
        self.cover_label.set_target_size(rect.width(), rect.height())
        self.cover_label.set_radius(int(theme.RADIUS_MD))
        self.cover_label.move(rect.topLeft())
        self._gradient_overlay.setGeometry(rect)
        self.overlay.setGeometry(rect)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_layer_geometry()

    def reserve_bottom_space(self, extra_px: int):
        """Adds extra_px of bottom margin on top of the banner's own base
        margin, so content (currently just the bio pill) never lays out
        underneath something floating on top of the banner from outside
        - e.g. ProfileLoginPage's Continue button. Safe to call before
        the widget has a real size; the layout re-flows on the next
        resizeEvent/show.
        """
        margins = self._overlay_layout.contentsMargins()
        self._overlay_layout.setContentsMargins(
            margins.left(), margins.top(), margins.right(),
            self._overlay_base_bottom_margin + max(0, extra_px)
        )

    def set_fetch_failed(self):
        self.name_label.setText(self._fallback_username or "")
        self.fallback_hint.setVisible(True)
        self.profile_ready.emit()

    def set_profile(self, profile):
        """profile: dict shaped like net.fetch_profile_stats()'s return value."""
        display_name = profile.get("display_name") or profile.get("username") or ""
        self.name_label.setText(html.escape(display_name))
        role = (profile.get("role") or "READER").upper()
        rank = html.escape(profile.get("rank") or "")
        self.kicker_label.setTextFormat(Qt.RichText)
        kicker_text = f"<span style='color:#a855f7; font-weight:700;'>\u25c6 {html.escape(role)}</span>"
        if rank:
            kicker_text += f"  \u00b7  <span style='color:#38bdf8; font-weight:600;'>{rank}</span>"
        self.kicker_label.setText(kicker_text)

        series = profile.get("series", 0)
        tracked = profile.get("tracked", 0)
        read_here = profile.get("read_here", 0)
        completed = profile.get("completed") or profile.get("manga_completed") or 0
        level = profile.get("level")
        streak = profile.get("streak", 0)

        parts = [
            f"<b style='color:#ffffff;'>{series:,}</b> series",
            f"<b style='color:#ffffff;'>{tracked:,}</b> tracked",
            f"<b style='color:#ffffff;'>{read_here:,}</b> read here",
        ]
        if completed:
            parts.append(f"<b style='color:#ffffff;'>{completed:,}</b> completed")
        if level is not None:
            parts.append(f"Lv <b style='color:#ffffff;'>{level}</b>")
        if streak:
            parts.append(f"<span style='color:#fbbf24;'>\U0001f525 {streak} day streak</span>")
        self.stats_label.setText("  \u00b7  ".join(parts))

        followers = profile.get("followers", 0)
        following = profile.get("following", 0)
        self.social_label.setText(
            f"<b style='color:#ffffff;'>{followers:,}</b> followers    <b style='color:#ffffff;'>{following:,}</b> following"
        )

        bio = profile.get("bio", "")
        if bio:
            self.bio_pill.setText(html.escape(bio))
            self.bio_pill.setVisible(True)
        else:
            self.bio_pill.setVisible(False)

        self.profile_ready.emit()

        avatar_url = profile.get("avatar_url")
        cover_url = profile.get("cover_url")
        username = profile.get("username") or ""
        if avatar_url or cover_url:
            self._load_images(username, avatar_url, cover_url)

    def _load_images(self, username, avatar_url, cover_url):
        # Cache check is synchronous disk I/O but deliberately not
        # farmed off to a worker thread - it's a local file read, not a
        # network call, so it's fast enough to not be worth the
        # complexity, and doing it inline means a fully-cached profile
        # (the common case: same user signing in again) paints
        # immediately with zero network round-trip and zero perceived
        # delay, instead of still going through the same worker-thread
        # dance as a cold fetch. See image_cache.get_cached's docstring
        # for why matching the URL is sufficient to guarantee the
        # cached bytes are still the CURRENT picture, not a stale one.
        cached_avatar, cached_cover = image_cache.get_cached(username, avatar_url, cover_url)
        if cached_avatar:
            self.avatar_label.set_bytes(cached_avatar)
        if cached_cover:
            self.cover_label.set_bytes(cached_cover)

        # Only fetch over the network whatever the cache didn't have -
        # a cache hit on one image (e.g. cover changed but avatar
        # didn't) shouldn't force a redundant re-download of the other.
        fetch_avatar_url = None if cached_avatar else avatar_url
        fetch_cover_url = None if cached_cover else cover_url
        if not fetch_avatar_url and not fetch_cover_url:
            logging.debug("ProfileBannerWidget: both images served from cache for %r, no fetch needed", username)
            return

        logging.debug(
            "ProfileBannerWidget: fetching images - avatar_url=%r cover_url=%r (cache covered: avatar=%s cover=%s)",
            fetch_avatar_url, fetch_cover_url, bool(cached_avatar), bool(cached_cover),
        )
        self._pending_cache_username = username
        worker = _BannerImageWorker(fetch_avatar_url, fetch_cover_url, session=self.session)
        # Connecting straight to self's bound methods (not through
        # run_worker's on_finished/_MainThreadRelay machinery) is safe
        # here specifically because self is a real QObject with genuine
        # GUI-thread affinity (a QFrame that's never moved to another
        # thread) - see _MainThreadRelay's docstring in workers.py for
        # why that distinction matters: Qt's AutoConnection can tell a
        # bound QObject method needs queuing across threads, but can't
        # tell that for a bare function/lambda, which is the case the
        # relay exists to handle.
        worker.avatar_ready.connect(self._on_avatar_ready)
        worker.cover_ready.connect(self._on_cover_ready)
        self._image_thread, self._image_worker = workers.run_worker(
            worker, on_finished=None
        )

    def _on_avatar_ready(self, avatar_bytes):
        logging.debug(
            "ProfileBannerWidget: avatar arrived - %s",
            f"{len(avatar_bytes)} bytes" if avatar_bytes else "None/empty",
        )
        if avatar_bytes:
            self.avatar_label.set_bytes(avatar_bytes)
            image_cache.store(self._pending_cache_username, "avatar", self._image_worker.avatar_url, avatar_bytes)

    def _on_cover_ready(self, cover_bytes):
        logging.debug(
            "ProfileBannerWidget: cover arrived - %s",
            f"{len(cover_bytes)} bytes" if cover_bytes else "None/empty",
        )
        if cover_bytes:
            self.cover_label.set_bytes(cover_bytes)
            image_cache.store(self._pending_cache_username, "cover", self._image_worker.cover_url, cover_bytes)

    def stop_background_work(self):
        if self._image_thread is not None and thread_is_running(self._image_thread):
            self._image_thread.quit()
            self._image_thread.wait(2000)
        self.avatar_label.stop()
        self.cover_label.stop()


class ProfileLoginPage(QWidget):
    """Full-window post-login page: the ProfileBannerWidget fills the
    entire page edge-to-edge, with the brand/status-pill header and the
    Continue button floating as transparent overlays on top of it (top
    and bottom respectively) rather than sitting in the layout as their
    own boxed rows above/below the banner.

    main.py only needs to construct this, connect continue_clicked and
    profile_ready, and call set_profile()/set_fetch_failed() on it - all
    the overlay positioning and widget wiring lives here so main.py stays
    an orchestrator instead of doing layout work.
    """
    continue_clicked = Signal()
    profile_ready = Signal()

    def __init__(self, logo_path, username="", browser_name="", session=None, parent=None):
        super().__init__(parent)

        self.banner = ProfileBannerWidget(fallback_username=username, session=session, parent=self)
        self.banner.profile_ready.connect(self._on_profile_ready)

        # --- floating header: brand + "Logged in as..." pill -----------
        self.header = QWidget(self)
        # Same fix as ProfileBannerWidget's overlay/gradient widgets: force
        # genuine transparency so this can't silently paint an opaque
        # background over the banner underneath it.
        self.header.setAttribute(Qt.WA_TranslucentBackground)
        self.header.setStyleSheet("background: transparent;")
        header_layout = QVBoxLayout(self.header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(10)
        header_layout.setAlignment(Qt.AlignHCenter)

        brand_widget = QSvgWidget(str(logo_path))
        brand_widget.setFixedSize(160, 32)  # matches the official SVG's 1000:201 aspect ratio
        header_layout.addWidget(brand_widget, alignment=Qt.AlignHCenter)

        confirmation_text = (
            f"Logged in as {username} via {browser_name}" if browser_name
            else f"Logged in as {username}"
        )
        self.confirmation_pill = StatusPill(confirmation_text, "success")
        header_layout.addWidget(self.confirmation_pill, alignment=Qt.AlignHCenter)

        # --- floating footer: Continue button --------------------------
        self.continue_box = GlassBox(
            tint_rgba="rgba(92, 225, 230, 18)",
            border_color=Color.ACCENT_SOFT_BORDER,
            parent=self,
        )
        continue_box_layout = QHBoxLayout(self.continue_box)
        continue_box_layout.setContentsMargins(14, 6, 14, 6)
        self.continue_button = make_flat_link(QPushButton("Continue"), bold=True)
        self.continue_button.setEnabled(False)  # enabled once profile_ready fires
        self.continue_button.clicked.connect(self.continue_clicked.emit)
        continue_box_layout.addWidget(self.continue_button)

        self.header.raise_()
        self.continue_box.raise_()

    def _on_profile_ready(self):
        self.continue_button.setEnabled(True)
        self.profile_ready.emit()

    def set_profile(self, profile):
        self.banner.set_profile(profile)

    def set_fetch_failed(self):
        self.banner.set_fetch_failed()

    def stop_background_work(self):
        self.banner.stop_background_work()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        rect = self.contentsRect()
        margin = 20
        self.banner.setGeometry(rect)

        self.header.adjustSize()
        header_x = (rect.width() - self.header.width()) // 2
        self.header.move(header_x, margin)
        self.header.raise_()

        self.continue_box.adjustSize()
        cont_x = (rect.width() - self.continue_box.width()) // 2
        cont_y = rect.height() - self.continue_box.height() - margin
        self.continue_box.move(cont_x, cont_y)
        self.continue_box.raise_()
        self.banner.reserve_bottom_space(self.continue_box.height() + margin)


class GroupPillWidget(QFrame):
    """Reusable visual pill for assigned groups with an optional delete (✕) button."""
    removed = Signal(dict)

    def __init__(self, group, removable=True, parent=None):
        super().__init__(parent)
        self.group = group
        self.setStyleSheet(
            f"QFrame {{ background-color: {Color.ACCENT_SOFT}; "
            f"border: 1px solid {Color.ACCENT_SOFT_BORDER}; "
            f"border-radius: 12px; }}"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 3, 8 if removable else 10, 3)
        layout.setSpacing(6)

        name = group.get("name") or (f"ID {group.get('id')}" if group.get("id") else "Unknown")
        lbl = QLabel(name)
        lbl.setStyleSheet(f"color: {Color.TEXT_PRIMARY}; font-weight: 600; font-size: 12px; background: transparent; border: none;")
        layout.addWidget(lbl)

        if removable:
            del_btn = QPushButton("✕")
            del_btn.setToolTip("Remove group")
            del_btn.setFixedSize(16, 16)
            del_btn.setCursor(Qt.PointingHandCursor)
            del_btn.setStyleSheet(
                f"QPushButton {{ background: transparent; border: none; padding: 0px; margin: 0px; "
                f"color: {Color.TEXT_SECONDARY}; font-size: 11px; font-weight: bold; text-align: center; }}"
                f"QPushButton:hover {{ color: {Color.DANGER}; }}"
            )
            del_btn.clicked.connect(lambda *_: self.removed.emit(self.group))
            layout.addWidget(del_btn)


_GroupPillWidget = GroupPillWidget