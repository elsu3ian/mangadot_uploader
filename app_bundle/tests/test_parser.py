"""Unit tests for mangadot_app.parser - pure filename/archive logic, no Qt, no network.

Run from the app_bundle directory:
    python -m unittest discover -s tests -t .
"""
import os
import sys
import base64
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mangadot_app import parser


class ExtractHelpersTest(unittest.TestCase):
    def test_extract_manga_id_or_query(self):
        self.assertEqual(parser.extract_manga_id_or_query("123456"), ("id", 123456))
        self.assertEqual(
            parser.extract_manga_id_or_query("https://mangadot.net/manga/99/whatever"),
            ("id", 99),
        )
        self.assertEqual(parser.extract_manga_id_or_query("Berserk"), ("query", "Berserk"))
        self.assertEqual(parser.extract_manga_id_or_query("   "), (None, None))

    def test_extract_lang_code_from_text(self):
        self.assertEqual(parser.extract_lang_code_from_text("English (en)"), "en")
        self.assertEqual(parser.extract_lang_code_from_text("en"), "en")
        self.assertEqual(parser.extract_lang_code_from_text(""), "")

    def test_guess_search_query_from_folder(self):
        self.assertEqual(parser.guess_search_query_from_folder(r"C:\lib\One Piece - Ch.1-9"),
                         "One Piece")

    def test_natural_sort_key_numeric_ordering(self):
        names = ["Ch 10.cbz", "Ch 2.cbz", "Ch 1.5.cbz"]
        self.assertEqual(sorted(names, key=parser.natural_sort_key),
                         ["Ch 1.5.cbz", "Ch 2.cbz", "Ch 10.cbz"])


class LanguageDetectionTest(unittest.TestCase):
    def test_guess_from_filename_brackets_parens(self):
        self.assertEqual(parser.guess_language_from_filename("Oneshot [fr].cbz"), "fr")
        self.assertEqual(parser.guess_language_from_filename("Vol 3 (PT-BR).zip"), "pt-br")
        self.assertEqual(parser.guess_language_from_filename("Vol 3 (French).zip"), "fr")
        self.assertIsNone(parser.guess_language_from_filename("Chapter 5.cbz"))
        self.assertIsNone(parser.guess_language_from_filename(""))

    def test_detect_languages_from_files(self):
        files = [
            {"filepath": r"C:\m\Foo [fr].cbz", "filename": "Foo [fr].cbz"},
            {"filepath": r"C:\m\Bar.cbz", "filename": "Bar.cbz"},
        ]
        result = parser.detect_languages_from_files(files)
        norm = parser.norm_filepath(files[0]["filepath"])
        self.assertEqual(result[norm], "fr")
        self.assertIsNone(result[parser.norm_filepath(files[1]["filepath"])])

    def test_is_languages_mixed(self):
        self.assertTrue(parser.is_languages_mixed({"a": "fr", "b": None}, dropdown_default="en"))
        self.assertFalse(parser.is_languages_mixed({"a": "en", "b": None}, dropdown_default="en"))
        self.assertTrue(parser.is_languages_mixed({"a": "fr", "b": "de"}, dropdown_default="fr"))
        # None default falls back to the stricter >1 check
        self.assertFalse(parser.is_languages_mixed({"a": "fr"}, dropdown_default=None))

    def test_summarize_language_counts(self):
        summary = parser.summarize_language_counts({"a": "fr", "b": "fr", "c": None})
        self.assertEqual(summary, "fr: 2 files")
        self.assertEqual(parser.summarize_language_counts({"a": None}), "")


class ParseFilenameDetailsTest(unittest.TestCase):
    def test_chapter_basic(self):
        num, candidates, groups, shape, source, ep = parser.parse_filename_details("My Manga Ch.12.cbz")
        self.assertEqual(num, 12.0)
        texts = [t for _, t in candidates]
        self.assertIn("My Manga", texts)
        self.assertIn("Chapter 12", texts)

    def test_volume(self):
        num, candidates, groups, shape, source, ep = parser.parse_filename_details(
            "Vol. 03.zip", upload_type="volume")
        self.assertEqual(num, 3.0)
        self.assertEqual(shape, "volume")
        self.assertEqual(candidates[0], ("Vol. N.NN", "Vol. 3.00"))

    def test_group_and_language_tags(self):
        num, candidates, groups, *_ = parser.parse_filename_details("[GroupA] My Manga Ch.5 [en].cbz")
        self.assertEqual(num, 5.0)
        self.assertEqual(groups, ["GroupA"])

    def test_homoglyph_cyrillic_c(self):
        # Cyrillic С must normalize to Latin C or the ch-label regex misses entirely.
        filename = "\u0421h.002.cbz"
        num, *_ = parser.parse_filename_details(filename)
        self.assertEqual(num, 2.0)

    def test_cjk_episode_label(self):
        num, *_ = parser.parse_filename_details("第12話.cbz")
        self.assertEqual(num, 12.0)

    def test_unparseable_returns_none(self):
        result = parser.parse_filename_details("no numbers here at all.cbz")
        self.assertIsNone(result[0])


class CustomRegexTest(unittest.TestCase):
    def test_parse_custom_regex_input(self):
        renames, extractor = parser.parse_custom_regex_input("Foo -> Bar;;(\\d+)")
        self.assertEqual(renames, [("Foo", "Bar")])
        self.assertIsNotNone(extractor)
        self.assertEqual(extractor.groups, 1)

    def test_validate_custom_regex_input_warnings(self):
        warnings = parser.validate_custom_regex_input("([unclosed;;\\d+")
        self.assertEqual(len(warnings), 2)
        self.assertIn("Invalid", warnings[0])
        self.assertIn("no capture group", warnings[1])
        no_group = parser.validate_custom_regex_input("\\d+")
        self.assertEqual(len(no_group), 1)
        self.assertIn("no capture group", no_group[0])

    def test_apply_custom_number_pattern(self):
        self.assertEqual(parser.apply_custom_number_pattern("Scene N", 3), "Scene 3")
        self.assertEqual(parser.apply_custom_number_pattern("Part", 2), "Part 2")

    def test_removal_pattern_roundtrip(self):
        literal = parser.compile_removal_pattern("GroupXYZ")
        self.assertEqual(parser.apply_removal_pattern(literal, "GroupXYZ Title"), "Title")
        regexy = parser.compile_removal_pattern(r"\[.*?\]")
        self.assertEqual(regexy, r"\[.*?\]")
        self.assertEqual(parser.apply_removal_pattern(regexy, "[GroupA] Title"), "Title")


class TusMetadataTest(unittest.TestCase):
    def test_encode_tus_metadata(self):
        encoded = parser.encode_tus_metadata({"filename": "a.cbz", "num": 2.0, "tags": ["x", "y"], "skip": None})
        pairs = dict(p.split(" ", 1) for p in encoded.split(","))
        self.assertNotIn("skip", pairs)
        self.assertEqual(base64.b64decode(pairs["filename"]).decode(), "a.cbz")
        self.assertEqual(base64.b64decode(pairs["num"]).decode(), "2")
        self.assertEqual(base64.b64decode(pairs["tags"]).decode(), json.dumps(["x", "y"]))


class NumberingTest(unittest.TestCase):
    def test_find_missing_numbers(self):
        files = [{"number": 1.0}, {"number": 2.0}, {"number": 5.0}, {"number": 6.5}]
        self.assertEqual(parser.find_missing_numbers(files), [3, 4])

    def test_find_duplicate_numbers(self):
        files = [{"number": 1.0}, {"number": 1.0}, {"number": 2.0}]
        dupes = parser.find_duplicate_numbers(files)
        self.assertEqual(list(dupes.keys()), [1.0])
        self.assertEqual(len(dupes[1.0]), 2)

    def test_parse_number_ranges(self):
        valid = {103, 104, 105, 110}
        picked, unmatched = parser.parse_number_ranges("103-105,110", valid_numbers=valid)
        self.assertEqual(picked, valid)
        self.assertEqual(unmatched, [])

        picked, unmatched = parser.parse_number_ranges("999", valid_numbers=valid)
        self.assertEqual(picked, set())
        self.assertEqual(unmatched, ["999"])

        picked, unmatched = parser.parse_number_ranges("1-3")
        self.assertEqual(picked, {1, 2, 3})

    def test_detect_episode_drift(self):
        parsed = [
            {"filename": "a", "number": 1.0, "episode_label_num": 1.0},
            {"filename": "b", "number": 2.0, "episode_label_num": None},
            {"filename": "c", "number": 3.0, "episode_label_num": 2.0},
        ]
        drift = parser.detect_episode_drift(parsed)
        self.assertIsNotNone(drift)
        self.assertTrue(drift["consistent"])
        self.assertEqual(drift["example_episode_label"], 2.0)
        self.assertIsNone(parser.detect_episode_drift(
            [{"filename": "a", "number": 1.0, "episode_label_num": 1.0}]))

    def test_apply_episode_drift_correction_reset(self):
        parsed = [
            {"filename": "a", "candidates": [], "number": 1.0, "episode_label_num": 1.0},
            {"filename": "b", "candidates": [], "number": 2.0, "episode_label_num": None},
            {"filename": "c", "candidates": [], "number": 3.0, "episode_label_num": 2.0},
        ]
        parser.apply_episode_drift_correction(parsed, "reset")
        by_name = {f["filename"]: f["number"] for f in parsed}
        # 'c' trusts its Episode label; unlabeled 'b' splits the gap between them.
        self.assertEqual(by_name["c"], 2.0)
        self.assertEqual(by_name["b"], 1.5)
        self.assertEqual(by_name["a"], 1.0)


class RoutingMapsTest(unittest.TestCase):
    def test_build_upload_routing_maps(self):
        one = r"C:\a\One.cbz"
        two = r"C:\a\Two.cbz"
        three = r"C:\a\Three.cbz"
        four = r"C:\a\Four.cbz"
        files = [
            {"filepath": one, "scanlator": "ScanCo", "language": "fr", "group_id": None},
            {"filepath": two, "scanlator": None, "language": None, "group_id": "42"},
            {"filepath": three, "scanlator": None, "language": None, "group_ids": [101, 202]},
            {"filepath": four, "scanlator": None, "language": None, "group_ids": []},
        ]
        base_groups = {parser.norm_filepath(two): ["7"], parser.norm_filepath(four): ["99"]}
        base_langs = {parser.norm_filepath(two): "en"}
        groups, scanlators, langs = parser.build_upload_routing_maps(files, base_groups, base_langs)

        self.assertEqual(scanlators.get(parser.norm_filepath(one)), "ScanCo")
        self.assertNotIn(parser.norm_filepath(one), groups)
        self.assertEqual(groups.get(parser.norm_filepath(two)), ["42"])
        self.assertEqual(groups.get(parser.norm_filepath(three)), [101, 202])
        self.assertEqual(groups.get(parser.norm_filepath(four)), [])
        self.assertEqual(langs.get(parser.norm_filepath(one)), "fr")
        self.assertEqual(langs.get(parser.norm_filepath(two)), "en")

    def test_multi_group_bracket_extraction(self):
        raw, clean = parser._extract_bracket_groups("Chapter 1 [Scan A, Scan B]")
        self.assertEqual(raw, ["Scan A", "Scan B"])
        self.assertEqual(clean, "Chapter 1")

        raw2, clean2 = parser._extract_bracket_groups("Chapter 2 [Scan A][Scan B]")
        self.assertEqual(raw2, ["Scan A", "Scan B"])
        self.assertEqual(clean2, "Chapter 2")

        raw3, clean3 = parser._extract_bracket_groups("Chapter 3 [001 Scans]")
        self.assertEqual(raw3, ["001 Scans"])
        self.assertEqual(clean3, "Chapter 3")


class ScanDirectoryTest(unittest.TestCase):
    def _make_cbz(self, path):
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("page.png", b"\x89PNG\r\n\x1a\nfake-image-bytes")

    def test_scan_finalize_and_validate(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("Series Ch.1.cbz", "Series Ch.2.cbz"):
                self._make_cbz(os.path.join(tmp, name))
            with open(os.path.join(tmp, "notes.txt"), "w") as f:
                f.write("ignored")

            parsed, errors = parser.scan_directory_files(tmp, "chapter")
            self.assertEqual(errors, [])
            self.assertEqual(len(parsed), 2)
            self.assertEqual([f["number"] for f in parsed], [1.0, 2.0])

            finalized = parser.finalize_file_entries(parsed)
            for f in finalized:
                self.assertNotIn("entry", f)          # DirEntry must not survive finalize
                self.assertGreater(f["size"], 0)      # and its stat was used before removal
                self.assertTrue(f["title"])

            good = [f for f in finalized if f["number"] == 1.0][0]
            self.assertIsNone(parser.validate_archive(good["filepath"]))

            bad = os.path.join(tmp, "broken.zip")
            with open(bad, "w") as f:
                f.write("this is not a zip file")
            self.assertIn("not a valid ZIP/CBZ archive", parser.validate_archive(bad))

    def test_scan_invalid_directory(self):
        parsed, errors = parser.scan_directory_files(r"Z:\definitely-missing-dir", "chapter")
        self.assertEqual(parsed, [])
        self.assertEqual(len(errors), 1)


if __name__ == "__main__":
    unittest.main()
