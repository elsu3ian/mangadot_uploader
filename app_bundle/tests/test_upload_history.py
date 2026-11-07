"""Unit tests for UploadHistoryDialog and rich series tracking.
"""
import os
import sys
import unittest
from pathlib import Path

# Ensure offscreen Qt
os.environ["QT_QPA_PLATFORM"] = "offscreen"

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication

from mangadot_app import config as config_mod
from mangadot_app.gui.upload_history_dialog import UploadHistoryDialog


class UploadHistoryDialogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_dialog_creation_and_search_filter(self):
        # Seed test data
        config_mod.db_record_series(
            manga_id=98765,
            title="Tower of Testing",
            alt_titles=["Testing Tower", "Sinui Tap"],
            origin="KR",
            groups=["Official"],
            chapters_pushed=[1, 2, 3],
            username="elsu"
        )

        dialog = UploadHistoryDialog(username="elsu")
        self.assertIsNotNone(dialog)
        self.assertTrue(dialog.table.rowCount() > 0)

        # Search for unique title
        dialog.search_input.setText("Tower of Testing")
        self.assertEqual(dialog.table.rowCount(), 1)

        # Search for ID
        dialog.search_input.setText("98765")
        self.assertEqual(dialog.table.rowCount(), 1)

        # Search for non-existent text
        dialog.search_input.setText("NonExistentStringXYZ123")
        self.assertEqual(dialog.table.rowCount(), 0)

        # Clear search
        dialog.search_input.setText("")
        self.assertTrue(dialog.table.rowCount() > 0)

    def test_picker_screen_upload_history_button(self):
        from mangadot_app.gui.picker_screen import PickerScreen
        picker = PickerScreen(username="elsu")
        self.assertTrue(hasattr(picker, "btn_upload_history"))
        self.assertEqual(picker.username, "elsu")
        picker.close()

    def test_api_sync_worker_cloud_uploads(self):
        from unittest.mock import patch, MagicMock
        from mangadot_app.gui.upload_history_dialog import _ApiSyncWorker

        mock_uploads = [
            {
                "manga_id": 55555,
                "manga_title": "Cloud Manga",
                "chapter_number": "10",
                "type": "chapter",
                "language": "en",
                "group_name": "CloudScan",
            },
            {
                "manga_id": 55555,
                "manga_title": "Cloud Manga",
                "chapter_number": "11",
                "type": "chapter",
                "language": "en",
                "group_name": "CloudScan",
            }
        ]

        with patch("mangadot_app.net.fetch_my_uploads", return_value=mock_uploads):
            with patch("mangadot_app.net.fetch_manga_full_details", return_value={"title": "Cloud Manga", "origin": "KR"}):
                worker = _ApiSyncWorker(series_list=[], session=MagicMock(), username="elsu")
                worker.run()

        series = config_mod.get_all_tracked_series()
        cloud_m = next((s for s in series if s.get("manga_id") == 55555), None)
        self.assertIsNotNone(cloud_m)
        self.assertEqual(cloud_m["title"], "Cloud Manga")
        self.assertIn("10", cloud_m.get("uploaded_chapters", []))
        self.assertIn("11", cloud_m.get("uploaded_chapters", []))


if __name__ == "__main__":
    unittest.main()
