"""Unit tests for MangaDot logo asset integrity."""
import os
import sys
import unittest
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtGui import QPainter, QImage


class LogoAssetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_logo_asset_exists_and_is_valid_svg(self):
        assets_dir = Path(__file__).resolve().parents[1] / "mangadot_app" / "assets"
        for fname in ["mangadotnet-purple.svg", "mangadot_official_animated_admin_fix_2.svg"]:
            logo_path = assets_dir / fname
            self.assertTrue(logo_path.exists(), f"{fname} must exist")
            
            # Verify QSvgWidget can load and render the asset
            widget = QSvgWidget(str(logo_path))
            self.assertTrue(widget.renderer().isValid(), f"{fname} must be a valid SVG")
            
            # Verify it has the official 1000x201 dimensions (~5:1 aspect ratio)
            default_size = widget.renderer().defaultSize()
            self.assertEqual(default_size.width(), 1000)
            self.assertEqual(default_size.height(), 201)

            # Verify no chibi mascot embedded and no pattern-wrapped use tags
            content = logo_path.read_text(encoding="utf-8")
            self.assertNotIn("mascotClip", content)
            self.assertNotIn("<pattern id=\"pattern_girl_reading\"", content)
            self.assertIn("xlink:href=", content)

            # Verify offscreen painting without crashing
            img = QImage(1000, 201, QImage.Format_ARGB32)
            img.fill(0)
            p = QPainter(img)
            widget.renderer().render(p)
            p.end()
            self.assertFalse(img.isNull())


if __name__ == "__main__":
    unittest.main()
