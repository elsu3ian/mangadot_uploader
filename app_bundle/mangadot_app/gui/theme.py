"""Central visual theme for the MangaDot Uploader GUI.

Single source of truth for colors, spacing, typography, and the global
QSS stylesheet. Every screen imports from here instead of hardcoding
ad-hoc setStyleSheet() calls, so the whole app reads as one consistent
product instead of a pile of default Qt widgets.

Usage:
    from . import theme
    app.setStyleSheet(theme.stylesheet())
    app.setFont(theme.base_font())
"""
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette


# ==============================================================================
# Palette — a dark, slightly blue-tinted neutral scale with a cyan accent
# (the same #5CE1E6 the CLI already uses for its rich-text summary headers,
# kept here so the GUI and CLI feel like the same product).
# ==============================================================================

class Color:
    # Backgrounds, darkest to lightest
    BG_APP        = "#0f1216"
    BG_BASE       = "#14181e"
    BG_SURFACE    = "#1a1f27"
    BG_RAISED     = "#212832"
    BG_HOVER      = "#262e3a"
    BG_PRESSED    = "#1a2029"
    BG_INPUT      = "#171c23"

    # Borders / separators
    BORDER        = "#2a323e"
    BORDER_SOFT   = "#232a34"
    BORDER_FOCUS  = "#5CE1E6"

    # Text
    TEXT_BRIGHT    = "#ffffff"
    TEXT_PRIMARY   = "#e8ecf1"
    TEXT_SECONDARY = "#9aa5b3"
    TEXT_MUTED     = "#6b7686"
    TEXT_DISABLED  = "#4c5561"
    TEXT_ON_ACCENT = "#062328"
    TEXT_ON_SUCCESS = "#052e16"

    # Accent (cyan) — primary actions, links, focus rings
    ACCENT         = "#5CE1E6"
    ACCENT_HOVER   = "#7CEAEE"
    ACCENT_PRESSED = "#3FC7CC"
    ACCENT_SOFT    = "#1c3438"        
    ACCENT_SOFT_BORDER = "#2f545a"

    # Semantic
    SUCCESS        = "#4ADE80"
    SUCCESS_SOFT   = "#173626"
    WARNING        = "#FBBF24"
    WARNING_SOFT   = "#3a2f12"
    DANGER         = "#F87171"
    DANGER_SOFT    = "#3a1c1c"
    INFO           = "#5CE1E6"

    # Violet - role/rank badges (e.g. moderator pills)
    VIOLET         = "#A78BFA"
    VIOLET_SOFT    = "#2a2145"
    VIOLET_SOFT_BORDER = "#4c3d80"

    # Crimson
    CRIMSON        = "#DC143C"
    CRIMSON_HOVER  = "#E8395A"
    CRIMSON_SOFT_BORDER = "#6b2436"

    # Row striping / highlight states inside tables
    ROW_ALT        = "#171c23"
    ROW_HOVER      = "#1f2731"
    ROW_SELECTED   = "#233842"
    ROW_DUPLICATE  = "#3a1f24"
    ROW_DUPLICATE_HOVER = "#452530"


RADIUS_SM = 6
RADIUS_MD = 10 
RADIUS_LG = 16 

SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 16
SPACE_LG = 24
SPACE_XL = 32


def dark_input_style() -> str:
    """Shared override stylesheet for form controls sitting on a darker
    surface than the app background (e.g. a dialog card) - QLineEdit,
    QSpinBox, QCheckBox, and QRadioButton tinted to Color.BG_APP with an
    accent-soft border, matching the global QSS in stylesheet() but meant
    to be applied locally via setStyleSheet() on individual widgets.

    This exists so screens don't each hand-roll their own near-identical
    dark-input QSS block (which silently drifts from this file whenever
    the palette changes here but not in the copy). Any screen needing a
    darker-than-default input control should call this instead of
    defining its own version.
    """
    return f"""
        QLineEdit {{
            background-color: {Color.BG_APP};
            color: {Color.TEXT_PRIMARY};
            border: 1px solid {Color.ACCENT_SOFT_BORDER};
            border-radius: {RADIUS_SM}px;
            padding: 7px 10px;
            selection-background-color: {Color.ACCENT_SOFT};
        }}
        QLineEdit:hover {{
            border-color: {Color.ACCENT_SOFT_BORDER};
        }}
        QLineEdit:focus {{
            border: 1px solid {Color.ACCENT};
        }}
        QLineEdit:disabled {{
            color: {Color.TEXT_DISABLED};
            background-color: {Color.BG_SURFACE};
            border-color: {Color.BORDER};
        }}
        QSpinBox, QDoubleSpinBox, QComboBox {{
            background-color: {Color.BG_APP};
            color: {Color.TEXT_PRIMARY};
            border: 1px solid {Color.ACCENT_SOFT_BORDER};
            border-radius: {RADIUS_SM}px;
            padding: 6px 8px;
            selection-background-color: {Color.ACCENT_SOFT};
        }}
        QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
            border: 1px solid {Color.ACCENT};
        }}
        QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{
            color: {Color.TEXT_DISABLED};
            background-color: {Color.BG_SURFACE};
            border-color: {Color.BORDER};
        }}
        QComboBox::drop-down {{
            border: none;
            width: 26px;
        }}
        QComboBox QAbstractItemView {{
            background-color: {Color.BG_RAISED};
            border: 1px solid {Color.BORDER};
            border-radius: {RADIUS_SM}px;
            color: {Color.TEXT_PRIMARY};
            selection-background-color: {Color.ACCENT_SOFT};
            selection-color: {Color.TEXT_PRIMARY};
            outline: none;
            padding: 4px;
        }}
        QCheckBox, QRadioButton {{
            spacing: 8px;
            color: {Color.TEXT_PRIMARY};
            background: transparent;
        }}
        QCheckBox:disabled, QRadioButton:disabled {{
            color: {Color.TEXT_DISABLED};
        }}
        QCheckBox::indicator {{
            background-color: {Color.BG_APP};
            border: 1px solid {Color.ACCENT_SOFT_BORDER};
            border-radius: 3px;
            width: 15px;
            height: 15px;
        }}
        QCheckBox::indicator:checked {{
            background-color: {Color.ACCENT};
            border: 1px solid {Color.ACCENT};
        }}
        QCheckBox::indicator:disabled {{
            background-color: {Color.BG_SURFACE};
            border-color: {Color.BORDER};
        }}
        QRadioButton::indicator {{
            background-color: {Color.BG_APP};
            border: 1px solid {Color.ACCENT_SOFT_BORDER};
            border-radius: 8px;
            width: 15px;
            height: 15px;
        }}
        QRadioButton::indicator:checked {{
            background-color: {Color.ACCENT};
            border: 1px solid {Color.ACCENT};
        }}
        QRadioButton::indicator:disabled {{
            background-color: {Color.BG_SURFACE};
            border-color: {Color.BORDER};
        }}
    """


def base_font() -> QFont:
    """App-wide default font. Falls back gracefully through a short list
    of common, clean UI faces so this looks intentional on Windows,
    macOS, and Linux alike without bundling a font file."""
    families = QFontDatabase.families()
    preferred = ["Segoe UI Variable", "Segoe UI", "Inter", "SF Pro Text",
                 "Ubuntu", "Noto Sans", "Cantarell"]
    chosen = next((f for f in preferred if f in families), None)
    font = QFont(chosen) if chosen else QFont()
    font.setPointSize(10)
    return font


def mono_font() -> QFont:
    families = QFontDatabase.families()
    preferred = ["Cascadia Mono", "Consolas", "JetBrains Mono", "SF Mono",
                 "Ubuntu Mono", "DejaVu Sans Mono", "Menlo"]
    chosen = next((f for f in preferred if f in families), None)
    font = QFont(chosen) if chosen else QFont("Monospace")
    font.setStyleHint(QFont.Monospace)
    font.setPointSize(10)
    return font


def dark_palette() -> QPalette:
    """A QPalette backstop so native dialogs (QFileDialog, QMessageBox
    chrome, menus) still look dark even before/outside the QSS applies."""
    p = QPalette()
    p.setColor(QPalette.Window, QColor(Color.BG_APP))
    p.setColor(QPalette.WindowText, QColor(Color.TEXT_PRIMARY))
    p.setColor(QPalette.Base, QColor(Color.BG_INPUT))
    p.setColor(QPalette.AlternateBase, QColor(Color.ROW_ALT))
    p.setColor(QPalette.ToolTipBase, QColor(Color.ACCENT_SOFT))
    p.setColor(QPalette.ToolTipText, QColor(Color.TEXT_PRIMARY))
    p.setColor(QPalette.Text, QColor(Color.TEXT_PRIMARY))
    p.setColor(QPalette.Button, QColor(Color.BG_RAISED))
    p.setColor(QPalette.ButtonText, QColor(Color.TEXT_PRIMARY))
    p.setColor(QPalette.BrightText, QColor(Color.DANGER))
    p.setColor(QPalette.Link, QColor(Color.ACCENT))
    p.setColor(QPalette.Highlight, QColor(Color.ACCENT))
    p.setColor(QPalette.HighlightedText, QColor(Color.TEXT_ON_ACCENT))
    p.setColor(QPalette.PlaceholderText, QColor(Color.TEXT_MUTED))
    p.setColor(QPalette.Disabled, QPalette.Text, QColor(Color.TEXT_DISABLED))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(Color.TEXT_DISABLED))
    p.setColor(QPalette.Disabled, QPalette.WindowText, QColor(Color.TEXT_DISABLED))
    return p


def stylesheet() -> str:
    C = Color
    return f"""
/* ============================== Base ============================== */
QWidget {{
    background-color: {C.BG_APP};
    color: {C.TEXT_PRIMARY};
    selection-background-color: {C.ACCENT_SOFT};
    selection-color: {C.TEXT_PRIMARY};
}}

QMainWindow, QDialog {{
    background-color: {C.BG_APP};
}}

QToolTip {{
    background-color: {C.ACCENT_SOFT};
    color: {C.TEXT_PRIMARY};
    border: 1px solid {C.ACCENT_SOFT_BORDER};
    border-radius: {RADIUS_SM}px;
    padding: 6px 10px;
}}

/* ============================== Labels ============================== */
QLabel {{
    background: transparent;
    color: {C.TEXT_PRIMARY};
}}
QLabel[role="heading"] {{
    font-size: 20px;
    font-weight: 700;
    color: {C.TEXT_PRIMARY};
}}
QLabel[role="subheading"] {{
    font-size: 13px;
    color: {C.TEXT_SECONDARY};
}}
QLabel[role="section"] {{
    font-size: 12px;
    font-weight: 600;
    color: {C.TEXT_SECONDARY};
    letter-spacing: 0.5px;
}}
QLabel[role="muted"] {{
    color: {C.TEXT_MUTED};
}}
QLabel[role="hint"] {{
    color: {C.TEXT_MUTED};
    font-style: italic;
    font-size: 11px;
}}
QLabel[role="success"] {{ color: {C.SUCCESS}; }}
QLabel[role="warning"] {{ color: {C.WARNING}; }}
QLabel[role="danger"]  {{ color: {C.DANGER}; }}
QLabel[role="accent"]  {{ color: {C.ACCENT}; font-weight: 600; }}

/* =========================== Buttons =========================== */
QPushButton {{
    background-color: {C.BG_RAISED};
    color: {C.TEXT_PRIMARY};
    border: 1px solid {C.BORDER};
    border-radius: {RADIUS_MD}px;
    padding: 8px 18px;
    font-weight: 600;
}}
QPushButton:hover {{
    background-color: {C.BG_HOVER};
    border-color: {C.ACCENT_SOFT_BORDER};
}}
QPushButton:pressed {{
    background-color: {C.BG_PRESSED};
}}
QPushButton:disabled {{
    color: {C.TEXT_DISABLED};
    background-color: {C.BG_SURFACE};
    border-color: {C.BORDER_SOFT};
}}
QPushButton:focus {{
    border: 1px solid {C.ACCENT};
}}

QPushButton[variant="primary"] {{
    background-color: {C.ACCENT};
    color: {C.TEXT_ON_ACCENT};
    border: 1px solid {C.ACCENT};
}}
QPushButton[variant="primary"]:hover {{
    background-color: {C.ACCENT_HOVER};
    border-color: {C.ACCENT_HOVER};
}}
QPushButton[variant="primary"]:pressed {{
    background-color: {C.ACCENT_PRESSED};
    border-color: {C.ACCENT_PRESSED};
}}
QPushButton[variant="primary"]:disabled {{
    background-color: {C.BG_SURFACE};
    color: {C.TEXT_DISABLED};
    border-color: {C.BORDER_SOFT};
}}

QPushButton[variant="danger"] {{
    background-color: transparent;
    color: {C.DANGER};
    border: 1px solid #5a2c2c;
}}
QPushButton[variant="danger"]:hover {{
    background-color: {C.DANGER_SOFT};
    border-color: {C.DANGER};
}}

QPushButton[variant="flat"] {{
    background-color: transparent;
    border: 1px solid transparent;
    color: {C.TEXT_SECONDARY};
    padding: 6px 10px;
}}
QPushButton[variant="flat"]:hover {{
    color: {C.TEXT_PRIMARY};
    background-color: {C.BG_HOVER};
}}

/* ====================== Line edits / spin boxes ====================== */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background-color: {C.BG_INPUT};
    color: {C.TEXT_PRIMARY};
    border: 1px solid {C.BORDER};
    border-radius: {RADIUS_SM}px;
    padding: 7px 10px;
    selection-background-color: {C.ACCENT_SOFT};
}}
QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover {{
    border-color: {C.ACCENT_SOFT_BORDER};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border: 1px solid {C.ACCENT};
}}
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled {{
    color: {C.TEXT_DISABLED};
    background-color: {C.BG_SURFACE};
}}
QLineEdit[echoMode="2"] {{
    lineedit-password-character: 9679;
}}

QComboBox::drop-down {{
    border: none;
    width: 26px;
}}
QComboBox QAbstractItemView {{
    background-color: {C.BG_RAISED};
    border: 1px solid {C.BORDER};
    border-radius: {RADIUS_SM}px;
    color: {C.TEXT_PRIMARY};
    selection-background-color: {C.ACCENT_SOFT};
    selection-color: {C.TEXT_PRIMARY};
    outline: none;
    padding: 4px;
}}

QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    width: 18px;
    background: transparent;
    border: none;
}}

/* =============================== Checkboxes / radios =============================== */
QCheckBox, QRadioButton {{
    spacing: 8px;
    color: {C.TEXT_PRIMARY};
    background: transparent;
}}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 17px;
    height: 17px;
    border: 1px solid {C.BORDER};
    background-color: {C.BG_INPUT};
}}
QCheckBox::indicator {{
    border-radius: 4px;
}}
QRadioButton::indicator {{
    border-radius: 9px;
}}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{
    border-color: {C.ACCENT};
}}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background-color: {C.ACCENT};
    border-color: {C.ACCENT};
}}
QCheckBox:disabled, QRadioButton:disabled {{
    color: {C.TEXT_DISABLED};
}}

/* =============================== Group boxes =============================== */
QGroupBox {{
    background-color: {C.BG_SURFACE};
    border: 1px solid {C.BORDER};
    border-radius: {RADIUS_MD}px;
    margin-top: 14px;
    padding: 16px 14px 14px 14px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    top: 2px;
    padding: 0 6px;
    color: {C.TEXT_SECONDARY};
    background-color: {C.BG_APP};
}}

/* =============================== Frames / cards =============================== */
QFrame[card="true"] {{
    background-color: {C.BG_SURFACE};
    border: none; 
    border-radius: {RADIUS_LG}px;
}}

/* =============================== Tables =============================== */
QTableWidget, QTableView {{
    background-color: {C.BG_SURFACE};
    alternate-background-color: {C.ROW_ALT};
    border: 1px solid {C.BORDER};
    border-radius: {RADIUS_MD}px;
    gridline-color: {C.BORDER_SOFT};
    color: {C.TEXT_PRIMARY};
    outline: none;
    selection-background-color: {C.ROW_SELECTED};
    selection-color: {C.TEXT_PRIMARY};
}}
QTableWidget::item, QTableView::item {{
    padding: 7px 8px;
    border: none;
}}
QTableWidget::item:selected, QTableView::item:selected {{
    background-color: {C.ROW_SELECTED};
    color: {C.TEXT_PRIMARY};
}}
QTableWidget::item:hover {{
    background-color: {C.ROW_HOVER};
}}
QHeaderView::section {{
    background-color: {C.BG_RAISED};
    color: {C.TEXT_SECONDARY};
    padding: 9px 8px;
    border: none;
    border-bottom: 1px solid {C.BORDER};
    border-right: 1px solid {C.BORDER_SOFT};
    font-weight: 600;
    font-size: 11px;
    letter-spacing: 0.3px;
}}
QHeaderView::section:first {{
    border-top-left-radius: {RADIUS_MD}px;
}}
QHeaderView::section:last {{
    border-right: none;
}}
QTableCornerButton::section {{
    background-color: {C.BG_RAISED};
    border: none;
    border-bottom: 1px solid {C.BORDER};
}}

/* =============================== Lists =============================== */
QListWidget, QListView {{
    background-color: {C.BG_APP}; 
    border: none; 
    border-radius: {RADIUS_MD}px;
    color: {C.TEXT_PRIMARY};
    outline: none;
    padding: 4px;
}}
QListWidget::item, QListView::item {{
    padding: 8px 10px;
    border-radius: {RADIUS_SM}px;
    margin: 1px 2px;
}}
QListWidget::item:hover, QListView::item:hover {{
    background-color: {C.ROW_HOVER};
}}
QListWidget::item:selected, QListView::item:selected {{
    background-color: {C.ACCENT_SOFT};
    color: {C.TEXT_PRIMARY};
    border: 1px solid {C.ACCENT_SOFT_BORDER};
}}

QListWidget#TransparentList {{
    background-color: transparent;
    border: none;
    outline: none;
    padding: 0px;
}}
QListWidget#TransparentList::item {{
    background-color: {C.BG_SURFACE};
    border: 1px solid {C.BORDER};
    border-radius: {RADIUS_MD}px;
    margin: 2px 0px 6px 0px;
    padding: 0px;
}}
QListWidget#TransparentList::item:hover {{
    background-color: {C.BG_HOVER};
    border-color: {C.ACCENT_SOFT_BORDER};
}}
QListWidget#TransparentList::item:selected {{
    background-color: {C.ACCENT_SOFT};
    border: 1px solid {C.ACCENT};
}}

/* =============================== Scrollbars =============================== */
QScrollBar:vertical {{
    background: transparent;
    width: 12px;
    margin: 0px 2px 0px 0px;
}}
QScrollBar::handle:vertical {{
    background: {C.BORDER};
    min-height: 24px;
    border-radius: 5px;
}}
QScrollBar::handle:vertical:hover {{
    background: {C.ACCENT_SOFT_BORDER};
}}
QScrollBar::sub-line:vertical, QScrollBar::add-line:vertical {{
    width: 0px;
    height: 0px;
    background: none;
    border: none;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: none;
}}

QScrollBar:horizontal {{
    background: transparent;
    height: 12px;
    margin: 0px 0px 2px 0px;
}}
QScrollBar::handle:horizontal {{
    background: {C.BORDER};
    min-width: 24px;
    border-radius: 5px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {C.ACCENT_SOFT_BORDER};
}}
QScrollBar::sub-line:horizontal, QScrollBar::add-line:horizontal {{
    width: 0px;
    height: 0px;
    background: none;
    border: none;
}}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background: none;
}}

/* =============================== Progress bars =============================== */
QProgressBar {{
    background-color: {C.BG_INPUT};
    border: 1px solid {C.BORDER};
    border-radius: {RADIUS_SM}px;
    text-align: center;
    color: {C.TEXT_SECONDARY};
    font-size: 10px;
    font-weight: 600;
    min-height: 18px;
}}
QProgressBar::chunk {{
    background-color: {C.ACCENT};
    border-radius: {RADIUS_SM - 1}px;
}}
QProgressBar[state="success"]::chunk {{ background-color: {C.SUCCESS}; }}
QProgressBar[state="danger"]::chunk  {{ background-color: {C.DANGER}; }}
QProgressBar[state="warning"]::chunk {{ background-color: {C.WARNING}; }}

/* =============================== Menus =============================== */
QMenu {{
    background-color: {C.BG_RAISED};
    border: 1px solid {C.BORDER};
    border-radius: {RADIUS_MD}px;
    padding: 6px;
    color: {C.TEXT_PRIMARY};
}}
QMenu::item {{
    padding: 7px 24px 7px 14px;
    border-radius: {RADIUS_SM}px;
}}
QMenu::item:selected {{
    background-color: {C.ACCENT_SOFT};
    color: {C.TEXT_PRIMARY};
}}
QMenu::separator {{
    height: 1px;
    background: {C.BORDER};
    margin: 6px 8px;
}}

/* =============================== Message boxes / dialogs =============================== */
QMessageBox {{
    background-color: {C.BG_BASE};
}}
QDialogButtonBox QPushButton {{
    min-width: 84px;
}}

/* =============================== Stacked widget / pages =============================== */
QStackedWidget {{
    background-color: {C.BG_APP};
}}

/* =============================== Splitters =============================== */
QSplitter::handle {{
    background-color: {C.BORDER};
}}

/* =============================== Form layout labels =============================== */
QFormLayout QLabel {{
    color: {C.TEXT_SECONDARY};
}}
"""