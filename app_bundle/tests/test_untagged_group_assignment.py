"""Unit tests for untagged chapter batch group assignment and unassigned warnings."""
import os
import sys
import unittest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication, QMessageBox, QWidget
from PySide6.QtCore import Qt
from mangadot_app.gui.group_config_dialog import GroupConfigScreen, _UNTAGGED_TARGET
from mangadot_app.gui.title_review_screen import TitleReviewScreen
from mangadot_app import parser as parser_mod
import main


class UntaggedGroupAssignmentTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        # Create 2 tagged files and 3 untagged files
        self.tagged_1 = os.path.join(self.test_dir, "[Alpha Scans] ch01.cbz")
        self.tagged_2 = os.path.join(self.test_dir, "[Alpha Scans] ch02.cbz")
        self.untagged_1 = os.path.join(self.test_dir, "ch0003 - Chapter 003.cbz")
        self.untagged_2 = os.path.join(self.test_dir, "ch0004 - Chapter 004.cbz")
        self.untagged_3 = os.path.join(self.test_dir, "ch0005 - Chapter 005.cbz")
        for p in [self.tagged_1, self.tagged_2, self.untagged_1, self.untagged_2, self.untagged_3]:
            with open(p, "wb") as f:
                f.write(b"PK\x05\x06" + b"\x00" * 18)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_detection_identifies_untagged_files_and_adds_to_list(self):
        screen = GroupConfigScreen(MagicMock(), self.test_dir)
        self.assertEqual(len(screen._untagged_files), 3)
        self.assertIn("Alpha Scans", screen._detected_names)

        # Check detected_list contains _UNTAGGED_TARGET
        items = [screen.detected_list.item(i).data(Qt.UserRole) for i in range(screen.detected_list.count())]
        self.assertIn("Alpha Scans", items)
        self.assertIn(_UNTAGGED_TARGET, items)
        screen.stop_background_work()
        screen.close()

    def test_assigning_group_to_untagged_target_maps_all_untagged_files(self):
        screen = GroupConfigScreen(MagicMock(), self.test_dir)
        # Simulate auto-resolution of Alpha Scans
        screen._apply_group_choice_to_target({"id": 100, "name": "Alpha Scans"}, target_name="Alpha Scans")

        # Now assign group to _UNTAGGED_TARGET
        screen._apply_group_choice_to_target({"id": 200, "name": "Beta Scans"}, target_name=_UNTAGGED_TARGET)

        emitted_payload = []
        screen.config_finished.connect(lambda p: emitted_payload.append(p))
        screen._on_continue()

        self.assertEqual(len(emitted_payload), 1)
        cfg = emitted_payload[0]
        self.assertTrue(cfg["is_group_upload"])
        pf_map = cfg["per_file_group_map"]
        pf_names = cfg["per_file_group_names"]

        # All 3 untagged files must be mapped to Beta Scans (ID 200)
        for uf in screen._untagged_files:
            self.assertEqual(pf_map.get(uf), [200])
            self.assertEqual(pf_names.get(uf), ["Beta Scans"])

        # Tagged files must be mapped to Alpha Scans (ID 100)
        norm_t1 = parser_mod.norm_filepath(self.tagged_1)
        self.assertEqual(pf_map.get(norm_t1), [100])
        self.assertEqual(pf_names.get(norm_t1), ["Alpha Scans"])
        screen.stop_background_work()
        screen.close()

    def test_unassigned_untagged_files_triggers_warning_on_continue(self):
        screen = GroupConfigScreen(MagicMock(), self.test_dir)
        # Only resolve Alpha Scans, leave untagged files unassigned
        screen._apply_group_choice_to_target({"id": 100, "name": "Alpha Scans"}, target_name="Alpha Scans")

        emitted_payload = []
        screen.config_finished.connect(lambda p: emitted_payload.append(p))

        # Simulate user clicking "Go back and assign group"
        with patch.object(QMessageBox, "exec", return_value=0), \
             patch.object(QMessageBox, "clickedButton") as mock_clicked:
            # We want clickedButton to return the go_back button so it returns early
            mock_clicked.side_effect = lambda: screen.findChildren(QMessageBox)[-1].buttons()[0] if screen.findChildren(QMessageBox) else None
            # Or simply:
            def fake_clicked(msg_box):
                return msg_box.buttons()[0]
            with patch.object(QMessageBox, "clickedButton", side_effect=lambda: None):
                # When clickedButton() == go_back_btn, it returns
                pass

        # Cleaner way: patch QMessageBox so it doesn't show a real dialog and simulates clicking go_back_btn
        with patch("mangadot_app.gui.group_config_dialog.QMessageBox") as mock_msg_cls:
            mock_box = MagicMock()
            mock_btn = MagicMock()
            mock_box.addButton.return_value = mock_btn
            mock_box.clickedButton.return_value = mock_btn
            mock_msg_cls.return_value = mock_box
            mock_msg_cls.Warning = QMessageBox.Warning
            mock_msg_cls.RejectRole = QMessageBox.RejectRole
            mock_msg_cls.AcceptRole = QMessageBox.AcceptRole
            screen._on_continue()

        # Did not emit because user elected to go back
        self.assertEqual(len(emitted_payload), 0)
        # Search target should now be set to _UNTAGGED_TARGET
        self.assertEqual(screen._active_target_name, _UNTAGGED_TARGET)
        screen.stop_background_work()
        screen.close()

    @patch("main.TitleReviewScreen")
    def test_force_single_group_overrides_both_tagged_and_untagged_files(self, mock_screen_cls):
        mock_widget = QWidget()
        mock_widget.review_finished = MagicMock()
        mock_widget.back_requested = MagicMock()
        mock_screen_cls.return_value = mock_widget

        screen = GroupConfigScreen(MagicMock(), self.test_dir)
        # Enable force single group
        screen._on_force_single_group_toggled(True)
        screen._apply_group_choice_to_target({"id": 999, "name": "Global Group"})

        emitted_payload = []
        screen.config_finished.connect(lambda p: emitted_payload.append(p))
        screen._on_continue()

        self.assertEqual(len(emitted_payload), 1)
        cfg = emitted_payload[0]
        self.assertEqual(cfg["group_ids"], [999])
        self.assertEqual(cfg["group_name"], "Global Group")
        self.assertEqual(cfg["per_file_group_map"], {})

        # Test MainWindow assigns global group to all files
        mock_settings = MagicMock()
        mock_settings.launch_mode = "dry_run"
        mock_settings.opt_mode = "off"
        window = main.MainWindow(mock_settings)
        window._group_config = cfg

        files = [
            {"filepath": self.tagged_1, "title": "Ch 1"},
            {"filepath": self.untagged_1, "title": "Ch 3"}
        ]
        window._load_title_review(files)

        self.assertEqual(files[0]["group_ids"], [999])
        self.assertEqual(files[0]["groups"], ["Global Group"])
        self.assertEqual(files[1]["group_ids"], [999])
        self.assertEqual(files[1]["groups"], ["Global Group"])
        window.close()
        screen.stop_background_work()
        screen.close()

    def test_title_review_screen_displays_none_no_group_for_unassigned_chapters(self):
        files = [
            {"filepath": self.tagged_1, "filename": "ch01.cbz", "title": "Chapter 1", "size": 1024, "number": 1, "groups": ["Alpha Scans"], "group_ids": [100]},
            {"filepath": self.untagged_1, "filename": "ch03.cbz", "title": "Chapter 3", "size": 1024, "number": 3, "groups": [], "group_ids": []}
        ]
        review = TitleReviewScreen(files, group_label="Multiple / Auto-Detected", session=MagicMock())
        # Row 0 has Alpha Scans
        self.assertEqual(review.table.item(0, 4).text(), "Alpha Scans")
        # Row 1 must show 'None (no group)' and NOT 'Multiple / Auto-Detected'
        self.assertEqual(review.table.item(1, 4).text(), "None (no group)")
        review.close()

    def test_untagged_files_assigned_via_fallback_group_does_not_warn(self):
        # Create a directory with ONLY untagged files
        untagged_dir = tempfile.mkdtemp()
        try:
            for fname in ["ch0001 - chapter 000.cbz", "ch0002 - chapter 001.cbz"]:
                with open(os.path.join(untagged_dir, fname), "wb") as f:
                    f.write(b"PK\x05\x06" + b"\x00" * 18)

            screen = GroupConfigScreen(MagicMock(), untagged_dir)
            self.assertEqual(len(screen._untagged_files), 2)
            self.assertEqual(len(screen._detected_names), 0)

            # User picks group via fallback (target_name=None)
            screen._apply_group_choice_to_target({"id": 9210, "name": "KeiichiCAT"})
            self.assertEqual(screen._resolved_group_ids, [9210])

            emitted = []
            screen.config_finished.connect(lambda p: emitted.append(p))

            # _on_continue must NOT trigger warning popup and must emit immediately
            with patch("mangadot_app.gui.group_config_dialog.QMessageBox") as mock_msg:
                screen._on_continue()
                # QMessageBox warning should NOT be instantiated
                mock_msg.assert_not_called()

            self.assertEqual(len(emitted), 1)
            cfg = emitted[0]
            self.assertEqual(cfg["group_ids"], [9210])
            self.assertEqual(cfg["group_name"], "KeiichiCAT")
            # All untagged files are mapped
            for uf in screen._untagged_files:
                self.assertEqual(cfg["per_file_group_map"][uf], [9210])
                self.assertEqual(cfg["per_file_group_names"][uf], ["KeiichiCAT"])

            screen.stop_background_work()
            screen.close()
        finally:
            shutil.rmtree(untagged_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
