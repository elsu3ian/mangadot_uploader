"""Unit tests for MainWindow._load_title_review and group assignment."""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication, QWidget
from mangadot_app import parser as parser_mod
import main


class MainTitleReviewTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _create_mock_window(self):
        mock_settings = MagicMock()
        mock_settings.launch_mode = "dry_run"
        mock_settings.opt_mode = "off"
        return main.MainWindow(mock_settings)

    @patch("main.TitleReviewScreen")
    def test_load_title_review_uses_os_normpath_without_error(self, mock_screen_cls):
        mock_widget = QWidget()
        mock_widget.review_finished = MagicMock()
        mock_widget.back_requested = MagicMock()
        mock_screen_cls.return_value = mock_widget

        window = self._create_mock_window()
        test_file = {"filepath": "c:/test/manga/ch1.cbz", "title": "Ch 1"}
        window._group_config = {
            "per_file_group_map": {os.path.normpath("c:/test/manga/ch1.cbz"): [1026]},
            "per_file_group_names": {os.path.normpath("c:/test/manga/ch1.cbz"): ["Asura"]}
        }
        
        # Calling _load_title_review must not raise NameError: name 'os' is not defined
        window._load_title_review([test_file])
        
        self.assertEqual(test_file.get("group_ids"), [1026])
        self.assertEqual(test_file.get("groups"), ["Asura"])
        mock_screen_cls.assert_called_once()
        window.close()

    @patch("main.TitleReviewScreen")
    def test_windows_cased_filepath_resolves_normalized_group_names(self, mock_screen_cls):
        mock_widget = QWidget()
        mock_widget.review_finished = MagicMock()
        mock_widget.back_requested = MagicMock()
        mock_screen_cls.return_value = mock_widget

        window = self._create_mock_window()
        raw_path = r"E:\Scrap\Manga\Ch 01 [Asura Scan].cbz"
        norm_key = parser_mod.norm_filepath(raw_path)  # lowercased on Windows

        test_file = {"filepath": raw_path, "title": "Ch 01"}
        window._group_config = {
            "group_name": "Multiple / Auto-Detected",
            "per_file_group_map": {norm_key: [17425, 1026]},
            "per_file_group_names": {norm_key: ["Asura Scans", "Asura"]}
        }

        window._load_title_review([test_file])

        # Must resolve to assigned groups and NOT "Multiple / Auto-Detected"
        self.assertEqual(test_file.get("group_ids"), [17425, 1026])
        self.assertEqual(test_file.get("groups"), ["Asura Scans", "Asura"])
        window.close()

    @patch("main.TitleReviewScreen")
    def test_mixed_mode_fallback_never_assigns_multiple_autodetected_as_group_name(self, mock_screen_cls):
        mock_widget = QWidget()
        mock_widget.review_finished = MagicMock()
        mock_widget.back_requested = MagicMock()
        mock_screen_cls.return_value = mock_widget

        window = self._create_mock_window()
        test_file = {"filepath": r"E:\Scrap\Manga\Unassigned.cbz", "title": "Unassigned"}
        window._group_config = {
            "group_name": "Multiple / Auto-Detected",
            "per_file_group_map": {},
            "per_file_group_names": {}
        }

        window._load_title_review([test_file])

        # Must not be overwritten with ["Multiple / Auto-Detected"]
        self.assertNotEqual(test_file.get("groups"), ["Multiple / Auto-Detected"])
        window.close()


if __name__ == "__main__":
    unittest.main()
