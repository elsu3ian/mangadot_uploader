"""Unit tests for mangadot_app.net HTML scraping and profile parsing helpers.

Run from the app_bundle directory:
    python -m unittest discover -s tests -t .
"""
import sys
import unittest
from unittest.mock import MagicMock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mangadot_app import net


class ProfileStatsScrapeTest(unittest.TestCase):
    def test_scrape_profile_stats_html_tagged(self):
        html = """
        <div class="user-header">
            <span class="pf-num font-bold">1,319</span> series
            <span class="pf-num font-bold">60,348</span> tracked
            <span class="pf-num font-bold">41,799</span> read here
            Lv <span class="pf-num">29</span> <!-- -->Sage
            <span class="pf-num font-bold">25</span> <!-- -->followers
            <span class="pf-num font-bold">13</span> following
        </div>
        """
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = html
        mock_session.get.return_value = mock_response

        stats = net._scrape_profile_stats_html(mock_session, "Anti-BDT")
        self.assertEqual(stats.get("series"), 1319)
        self.assertEqual(stats.get("tracked"), 60348)
        self.assertEqual(stats.get("read_here"), 41799)
        self.assertEqual(stats.get("level"), 29)
        self.assertEqual(stats.get("rank"), "Sage")
        self.assertEqual(stats.get("followers"), 25)
        self.assertEqual(stats.get("following"), 13)

    def test_scrape_profile_stats_html_bare_markup(self):
        html = """
        <div>
            <b>1,319</b> series
            <b>60,348</b> tracked
            <b>41,799</b> read here
            Lv 29 Sage
            <b>25</b> followers
            <b>13</b> following
        </div>
        """
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = html
        mock_session.get.return_value = mock_response

        stats = net._scrape_profile_stats_html(mock_session, "Anti-BDT")
        self.assertEqual(stats.get("series"), 1319)
        self.assertEqual(stats.get("tracked"), 60348)
        self.assertEqual(stats.get("read_here"), 41799)
        self.assertEqual(stats.get("level"), 29)
        self.assertEqual(stats.get("rank"), "Sage")
        self.assertEqual(stats.get("followers"), 25)
        self.assertEqual(stats.get("following"), 13)


class UploadHistoryApiTest(unittest.TestCase):
    def test_fetch_uploads_page_and_my_uploads(self):
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "uploads": [
                {"id": 101, "chapter_number": "1.0", "manga_id": 123},
                {"id": 102, "chapter_number": "2.0", "manga_id": 123},
            ],
            "pagination": {"total_pages": 1}
        }
        mock_session.get.return_value = mock_response

        items = net.fetch_my_uploads(mock_session, manga_id=123, upload_type="chapter")
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["id"], 101)
        self.assertEqual(items[1]["chapter_number"], "2.0")


if __name__ == "__main__":
    unittest.main()
