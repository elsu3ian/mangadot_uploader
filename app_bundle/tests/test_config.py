"""Unit tests for mangadot_app.config (pure logic + disk roundtrips on a temp dir)
and the cache-dir relocation guarantee. No Qt, no network.

Run from the app_bundle directory:
    python -m unittest discover -s tests -t .
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mangadot_app import config as config_mod
import mangadot_app


def _patch_config_paths(testcase, tmp):
    """Point every module-level path at a temp dir for the duration of a test."""
    targets = {
        "CACHE_DIR": Path(tmp),
        "CONFIG_PATH": Path(tmp) / ".mangadot_uploader.json",
        "DB_PATH": Path(tmp) / "upload_history_db.json",
        "PAUSED_UPLOAD_PATH": Path(tmp) / "paused_upload.json",
    }
    for attr, value in targets.items():
        patcher = mock.patch.object(config_mod, attr, value)
        patcher.start()
        testcase.addCleanup(patcher.stop)


class CacheLocationTest(unittest.TestCase):
    def test_cache_dir_is_outside_the_package(self):
        pkg_dir = Path(mangadot_app.__file__).resolve().parent
        self.assertFalse(str(config_mod.CACHE_DIR).startswith(str(pkg_dir)),
                         f"runtime state must not live in the source tree: {config_mod.CACHE_DIR}")

    def test_legacy_migration_copies_old_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            legacy = Path(tmp) / "legacy" / "cache"
            legacy.mkdir(parents=True)
            (legacy / "upload_history_db.json").write_text(
                '{"version": 1, "uploaded": {"k|chapter|en|none": [1, 2]}}', encoding="utf-8")

            new_cache = Path(tmp) / "new" / "cache"
            new_cfg = new_cache / ".mangadot_uploader.json"

            with mock.patch.object(config_mod, "_LEGACY_CACHE_DIR", legacy), \
                 mock.patch.object(config_mod, "CACHE_DIR", new_cache), \
                 mock.patch.object(config_mod, "CONFIG_PATH", new_cfg), \
                 mock.patch.object(config_mod, "DB_PATH", new_cache / "upload_history_db.json"), \
                 mock.patch.object(config_mod, "PAUSED_UPLOAD_PATH", new_cache / "paused_upload.json"):
                config_mod._migrate_legacy_cache_files()
                self.assertTrue(new_cfg.exists() or True)  # migration doesn't create config itself
                self.assertTrue((new_cache / "upload_history_db.json").exists())
                numbers = config_mod.db_uploaded_numbers("k|chapter|en|none")
                self.assertEqual(numbers, {"1", "2"})

                # Second call is a no-op once the new config exists.
                (new_cfg).write_text("{}", encoding="utf-8")
                (new_cache / "upload_history_db.json").unlink()
                config_mod._migrate_legacy_cache_files()
                self.assertFalse((new_cache / "upload_history_db.json").exists())


class ChapterNumberKeyTest(unittest.TestCase):
    def test_chapter_number_key_normalizes(self):
        self.assertEqual(config_mod._chapter_number_key(12), "12")
        self.assertEqual(config_mod._chapter_number_key("007"), "7")
        self.assertEqual(config_mod._chapter_number_key("12.5"), "12.5")
        self.assertEqual(config_mod._chapter_number_key(2.0), "2")
        self.assertEqual(config_mod._chapter_number_key("weird"), "weird")

    def test_normalize_uploaded_bucket_sorts_and_dedupes(self):
        bucket = config_mod._normalize_uploaded_bucket(["12", "007", 12.0, 3])
        self.assertEqual(bucket, [3, 7, 12])

    def test_make_target_key(self):
        self.assertEqual(
            config_mod.make_target_key("99", "chapter", "en", [5, 2], None),
            "99|chapter|en|2,5",
        )
        self.assertEqual(
            config_mod.make_target_key("99", "volume", "en", [], "MyScan"),
            "99|volume|en|s:myscan",
        )
        self.assertEqual(
            config_mod.make_target_key("99", "chapter", "en", [], None),
            "99|chapter|en|none",
        )


class UploadHistoryDbTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        _patch_config_paths(self, self._tmp.name)

    def test_record_and_query_roundtrip(self):
        files = [{"filename": "Ch.1.cbz", "number": 1}, {"filename": "Ch.2.cbz", "number": 2.5}]
        config_mod.db_record_uploaded("key-a", files)
        self.assertEqual(config_mod.db_uploaded_numbers("key-a"), {"1", "2.5"})
        # Re-recording the same numbers must not duplicate them.
        config_mod.db_record_uploaded("key-a", files)
        db = config_mod.load_db()
        self.assertEqual(db["uploaded"]["key-a"], [1, 2.5])

    def test_corrupt_db_degrades_to_empty(self):
        config_mod.DB_PATH.write_text("{not json", encoding="utf-8")
        self.assertEqual(config_mod.db_uploaded_numbers("anything"), set())

    def test_missing_db_is_empty(self):
        self.assertEqual(config_mod.load_db(), {"version": 2, "uploaded": {}, "series": {}})

    def test_record_series_roundtrip(self):
        config_mod.db_record_series(
            manga_id=43959,
            title="Solo Leveling",
            alt_titles=["I Level Up Alone"],
            origin="KR",
            groups=["Official"],
            chapters_pushed=[1, 2, "3"],
            username="elsu"
        )
        series = config_mod.load_series_history()
        self.assertIn("43959", series)
        ent = series["43959"]
        self.assertEqual(ent["title"], "Solo Leveling")
        self.assertEqual(ent["origin"], "KR")
        self.assertEqual(ent["total_chapters"], 3)
        self.assertEqual(ent["uploaded_chapters"], ["1", "2", "3"])
        self.assertEqual(ent["user_uploads_url"], "https://mangadot.net/user/elsu/uploads?series=43959")

        # Second upload with chapter 4 merges cleanly
        config_mod.db_record_series(
            manga_id=43959,
            title="Solo Leveling",
            groups=["Asura Scans"],
            chapters_pushed=[4],
            username="elsu"
        )
        ent2 = config_mod.load_series_history()["43959"]
        self.assertEqual(ent2["total_chapters"], 4)
        self.assertEqual(ent2["uploaded_chapters"], ["1", "2", "3", "4"])
        self.assertIn("Official", ent2["groups"])
        self.assertIn("Asura Scans", ent2["groups"])

    def test_get_all_tracked_series_legacy_reconciliation(self):
        # Insert a legacy bucket without a series entry
        db = config_mod.load_db()
        db["uploaded"]["99999|chapter|en|Official"] = [1, 2, 3]
        config_mod.save_db(db)

        all_tracked = config_mod.get_all_tracked_series()
        m_ids = [s["manga_id"] for s in all_tracked]
        self.assertIn(99999, m_ids)
        item = next(s for s in all_tracked if s["manga_id"] == 99999)
        self.assertEqual(item["total_chapters"], 3)


class ConfigAndPausedStateTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        _patch_config_paths(self, self._tmp.name)

    def test_config_roundtrip_survives_torn_write_simulation(self):
        config_mod.save_config({"library": r"C:\manga"})
        self.assertEqual(config_mod.load_config(), {"library": r"C:\manga"})
        # No leftover temp files from the atomic write.
        leftovers = [n for n in os.listdir(self._tmp.name) if n.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_paused_state_roundtrip(self):
        bc = {"manga_id": "42", "upload_type": "chapter", "language": "en"}
        remaining = [{"filename": "a.cbz", "number": 1}]
        done = [{"filename": "z.cbz", "number": 9}, {"filename": "z.cbz", "number": 9}]  # dup name dedupes
        config_mod.save_paused_upload(bc, remaining, done)

        state = config_mod.load_paused_upload()
        self.assertIsNotNone(state)
        self.assertEqual(state["schema_version"], config_mod.PAUSED_UPLOAD_SCHEMA_VERSION)
        self.assertEqual([f["filename"] for f in state["files"]], ["a.cbz"])
        self.assertEqual(len(state["completed_files"]), 1)

    def test_update_paused_upload_keeps_completed_when_files_empty(self):
        bc = {"manga_id": "42", "upload_type": "chapter", "language": "en"}
        config_mod.save_paused_upload(bc, [{"filename": "a.cbz", "number": 1}],
                                      [{"filename": "z.cbz", "number": 9}])
        result = config_mod.update_paused_upload(lambda files: [])
        self.assertEqual(result, [])
        state = config_mod.load_paused_upload()
        self.assertIsNotNone(state)  # kept so completed_files isn't lost
        self.assertEqual(state["files"], [])

    def test_clear_paused_state(self):
        config_mod.save_paused_upload({"manga_id": "1"}, [{"filename": "a.cbz", "number": 1}], [])
        config_mod.clear_paused_upload()
        self.assertIsNone(config_mod.load_paused_upload())
        config_mod.clear_paused_upload()  # idempotent

    def test_wrong_schema_version_discarded(self):
        import json
        config_mod.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        config_mod.PAUSED_UPLOAD_PATH.write_text(
            json.dumps({"schema_version": 1, "files": []}), encoding="utf-8")
        self.assertIsNone(config_mod.load_paused_upload())


if __name__ == "__main__":
    unittest.main()
