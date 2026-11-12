"""Asks which language each group subfolder is in, for group folders whose
name carries no language tag ('Asura Scans' rather than 'Asura Scans [EN]')."""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QGridLayout, QLabel, QComboBox, QDialogButtonBox, QPushButton,
)

from .. import util
from ..parser import LOOSE_FILES_KEY
from .theme import Color
from .widgets import hint_label, section_label, attach_combo_dots_overlay


_COMBO_STYLE = f"""
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
"""


def _language_combo(selected):
    combo = QComboBox()
    combo.setStyleSheet(_COMBO_STYLE)
    for code, name in util.LANGUAGES:
        combo.addItem(f"{name} ({code})", code)
    idx = combo.findData(selected)
    combo.setCurrentIndex(idx if idx >= 0 else 0)
    attach_combo_dots_overlay(combo)
    return combo


class FolderLanguageDialog(QDialog):
    """folders: [(folder_name, file_count)]. After accept(),
    `languages` is {folder_name: language_code}."""

    def __init__(self, folders, default_language, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Language of folders")
        self.languages = {}
        self._combos = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(10)
        layout.addWidget(hint_label(
            "These have no language tag. Pick the language of each one. "
            "(Name a folder like 'Asura Scans [EN]' and it won't be asked.)"
        ))

        layout.addWidget(section_label("SET ALL TO"))
        self.all_combo = _language_combo(default_language)
        apply_all = QPushButton("Apply to all")
        apply_all.setAutoDefault(False)
        apply_all.clicked.connect(self._apply_all)
        row = QGridLayout()
        row.addWidget(self.all_combo, 0, 0)
        row.addWidget(apply_all, 0, 1)
        row.setColumnStretch(0, 1)
        layout.addLayout(row)

        layout.addWidget(section_label("PER FOLDER"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        for i, (name, count) in enumerate(folders):
            files_text = f"({count} file{'s' if count != 1 else ''})"
            if name == LOOSE_FILES_KEY:
                label = QLabel(f"\U0001F4C4 Files outside folders  {files_text}")
            else:
                label = QLabel(f"\U0001F4C1 {name}  {files_text}")
            combo = _language_combo(default_language)
            grid.addWidget(label, i, 0)
            grid.addWidget(combo, i, 1)
            self._combos[name] = combo
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)
        layout.addStretch(1)

        buttons = QDialogButtonBox()
        ok = buttons.addButton("Continue", QDialogButtonBox.AcceptRole)
        ok.setDefault(True)
        buttons.addButton("Back", QDialogButtonBox.RejectRole)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.resize(520, min(260 + 44 * len(folders), 640))

    def _apply_all(self):
        code = self.all_combo.currentData()
        for combo in self._combos.values():
            combo.setCurrentIndex(combo.findData(code))

    def _on_accept(self):
        self.languages = {name: combo.currentData() for name, combo in self._combos.items()}
        self.accept()
