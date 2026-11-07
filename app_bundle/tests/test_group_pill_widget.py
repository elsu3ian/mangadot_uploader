"""Unit tests for GroupPillWidget and group pill removal."""
import os
import sys
import unittest
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication, QPushButton
from mangadot_app.gui.widgets import GroupPillWidget
from mangadot_app.gui.theme import Color


class GroupPillWidgetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_color_has_text_bright(self):
        self.assertTrue(hasattr(Color, "TEXT_BRIGHT"))
        self.assertTrue(hasattr(Color, "TEXT_PRIMARY"))

    def test_group_pill_widget_creation_and_removal(self):
        group_data = {"id": 1026, "name": "Asura"}
        pill = GroupPillWidget(group_data, removable=True)
        self.assertIsNotNone(pill)

        # Find the delete button
        del_btn = pill.findChild(QPushButton)
        self.assertIsNotNone(del_btn)
        self.assertEqual(del_btn.text(), "✕")
        self.assertEqual(del_btn.toolTip(), "Remove group")
        self.assertEqual(del_btn.width(), 16)
        self.assertEqual(del_btn.height(), 16)
        self.assertIn("padding: 0px", del_btn.styleSheet())
        self.assertIn("margin: 0px", del_btn.styleSheet())

        # Verify clicking delete button emits removed signal
        received = []
        pill.removed.connect(lambda g: received.append(g))
        del_btn.click()

        self.assertEqual(len(received), 1)
        self.assertEqual(received[0], group_data)

    def test_group_pill_widget_non_removable(self):
        group_data = {"id": 1027, "name": "Asura Tales"}
        pill = GroupPillWidget(group_data, removable=False)
        self.assertIsNotNone(pill)

        del_btn = pill.findChild(QPushButton)
        self.assertIsNone(del_btn)


if __name__ == "__main__":
    unittest.main()
