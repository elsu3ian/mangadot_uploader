"""Unit tests for mangadot_app.util helpers. No Qt, no network.

Run from the app_bundle directory:
    python -m unittest discover -s tests -t .
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mangadot_app import util


class FmtTest(unittest.TestCase):
    def test_fmt_size(self):
        self.assertEqual(util.fmt_size(0), "0 B")
        self.assertEqual(util.fmt_size(512), "512 B")
        self.assertEqual(util.fmt_size(1024 * 1024), "1.00 MB")
        self.assertEqual(util.fmt_size(int(1.5 * 1024 ** 3)), "1.50 GB")

    def test_fmt_duration(self):
        self.assertEqual(util.fmt_duration(45), "45s")
        self.assertEqual(util.fmt_duration(125), "2m 5s")
        self.assertEqual(util.fmt_duration(3661), "1h 1m 1s")


class RedactionTest(unittest.TestCase):
    def test_redact_proxy_url_hides_credentials(self):
        self.assertEqual(
            util.redact_proxy_url("http://user:secret@proxy.example.com:8080"),
            "http://[REDACTED]@proxy.example.com:8080",
        )
        # No credentials -> unchanged
        self.assertEqual(
            util.redact_proxy_url("http://proxy.example.com:8080"),
            "http://proxy.example.com:8080",
        )

    def test_redact_home_path(self):
        text = f"traceback at {util._HOME_DIR_STR}\\manga\\x.cbz"
        redacted = util.redact_home_path(text)
        self.assertNotIn(util._HOME_DIR_STR, redacted)
        self.assertIn("~", redacted)


class MiscTest(unittest.TestCase):
    def test_strip_ansi(self):
        self.assertEqual(util.strip_ansi("\x1b[31mred\x1b[0m plain"), "red plain")

    def test_format_origin(self):
        self.assertEqual(util.format_origin("KR"), "South Korea")
        self.assertEqual(util.format_origin("kr"), "South Korea")
        self.assertEqual(util.format_origin("ZZ"), "ZZ")
        self.assertEqual(util.format_origin(""), "")
        self.assertEqual(util.format_origin(None), "")


if __name__ == "__main__":
    unittest.main()
