"""Filename parsing"""
import os
import re
import json
import base64
import zipfile
from collections import Counter
from pathlib import Path
from . import util

ARCHIVE_IMAGE_EXTS = ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp', '.avif')
VALID_ARCHIVE_EXTENSIONS = ('.cbz', '.zip')
_MANGA_URL_RE = re.compile(r'mangadot\.net/manga/(\d+)', re.IGNORECASE)


def extract_manga_id_or_query(text):
    text = text.strip()
    if not text:
        return None, None
    if text.isdigit():
        return "id", int(text)
    m = _MANGA_URL_RE.search(text)
    if m:
        return "id", int(m.group(1))
    return "query", text


def guess_search_query_from_folder(folder_path):
    name = os.path.basename(os.path.normpath(folder_path))
    return name.split(" - ")[0].strip() if name else name


_LANG_CODE_IN_PARENS_RE = re.compile(r'\(([^)]+)\)$')


def extract_lang_code_from_text(text):
    """Pulls a trailing '(code)' off free-typed combo box text, e.g.
    'English (en)' -> 'en'. Falls back to the raw text if no parens
    are present, so a plain typed code like 'en' still passes through."""
    text = (text or "").strip()
    if not text:
        return text
    m = _LANG_CODE_IN_PARENS_RE.search(text)
    return m.group(1) if m else text


_LANG_LOOKUP_CACHE = None


def _language_lookup():
    """Builds (and caches) a lowercase-string -> canonical-code map covering
    every entry in util.LANGUAGES, keyed by both code and full name, e.g.
    'pt-br' -> 'pt-br' and 'portuguese (brazil)' -> 'pt-br'. Shared by every
    language-detection function below so all ~39 languages in util.LANGUAGES
    are recognized everywhere, not just whichever ones happen to be common -
    adding a new language to util.LANGUAGES is enough to make every detector
    here pick it up with no other code changes."""
    global _LANG_LOOKUP_CACHE
    if _LANG_LOOKUP_CACHE is None:
        from . import util
        lookup = {}
        for code, name in util.LANGUAGES:
            lookup[code.lower()] = code
            lookup[name.lower()] = code
        _LANG_LOOKUP_CACHE = lookup
    return _LANG_LOOKUP_CACHE


def is_known_language_code(text):
    """True if `text` (bracket/paren content, already stripped) matches a
    known language code OR full name from util.LANGUAGES - used to keep
    language tags like '[en]' or '[pt-br]' from being misread as scan-group
    names by _extract_bracket_groups/_extract_parenthesis_groups."""
    if not text:
        return False
    return text.strip().lower() in _language_lookup()


def guess_language_from_path(directory):
    if not directory:
        return None

    lang_map = _language_lookup()
    for part in reversed(Path(directory).parts):
        clean_part = part.strip().lower()
        if clean_part in lang_map:
            return lang_map[clean_part]
    return None


_LANG_TAG_IN_BRACKETS_RE = re.compile(r'\[([^\]]+)\]')
_LANG_TAG_IN_PARENS_RE = re.compile(r'\(([^)]+)\)')


def guess_language_from_filename(filename):
    """Looks for a language tag anywhere in the filename as either
    '[xx]'/'[Full Name]' or '(xx)'/'(Full Name)', matched against every
    code/name in util.LANGUAGES via _language_lookup(). Checks brackets
    first (chapter-style group syntax), then parens (volume-style), since a
    file could plausibly use either regardless of upload_type. Returns None
    if nothing in any bracket/paren matches a known language - callers fall
    back to guess_language_from_path() and then the dropdown default."""
    if not filename:
        return None
    name_no_ext = re.sub(r'\.(cbz|zip)$', '', filename, flags=re.IGNORECASE)
    lang_map = _language_lookup()

    for pattern in (_LANG_TAG_IN_BRACKETS_RE, _LANG_TAG_IN_PARENS_RE):
        for m in pattern.finditer(name_no_ext):
            content = m.group(1).strip().lower()
            if content in lang_map:
                return lang_map[content]
    return None


def detect_languages_from_files(files):
    """Per-file language detection for an already-scanned file list (the
    same {"filepath", "filename", ...} dicts scan_directory_files produces).
    For each file: try the filename tag first (most specific - this is what
    lets 'Oneshot [en].cbz' sitting next to 'Oneshot [fr].cbz' in one flat
    folder resolve correctly per-file), then fall back to the containing
    folder's path (PTsDropper's 'Manga/EN/(Title)/files' convention, via
    guess_language_from_path - already existed for the initial folder-select
    guess, just never wired to individual files before).

    Returns {norm_filepath: lang_code_or_None} - a value of None means
    neither method found a language for that file, and callers should treat
    it as "no tag detected" (fall back to the dropdown default), not as an
    error on its own."""
    result = {}
    for f in files:
        norm_path = f.get("norm_filepath") or norm_filepath(f["filepath"])
        # The file's own name (not the '<folder>/' display prefix) first, so
        # 'Asura Scans [EN]/Chapter 5 [fr].cbz' is French.
        lang = guess_language_from_filename(os.path.basename(f.get("filename", "")))
        if lang is None:
            lang = f.get("folder_language")
        if lang is None:
            lang = guess_language_from_path(os.path.dirname(f["filepath"]))
        result[norm_path] = lang
    return result


# Key for "the archives directly inside the selected folder, outside any group
# folder" in untagged_group_folders()/apply_folder_languages().
LOOSE_FILES_KEY = ""


def _has_own_language_tag(f):
    return guess_language_from_filename(os.path.basename(f.get("filename", ""))) is not None


def untagged_group_folders(files):
    """[(folder_name, file_count)] for group folders among `files` whose
    folder name carries no language tag, in folder order. When there are
    group folders, the loose files next to them that have no language tag
    of their own are listed last under LOOSE_FILES_KEY."""
    counts = {}
    loose = 0
    has_group_folders = False
    for f in files:
        if f.get("folder_group"):
            has_group_folders = True
            if not f.get("folder_language"):
                counts[f["folder_group"]] = counts.get(f["folder_group"], 0) + 1
        elif not f.get("folder_language") and not _has_own_language_tag(f):
            loose += 1
    result = sorted(counts.items(), key=lambda t: natural_sort_key(t[0]))
    if has_group_folders and loose:
        result.append((LOOSE_FILES_KEY, loose))
    return result


def apply_folder_languages(files, folder_languages):
    """Applies {folder_name: lang} chosen for untagged group folders: each
    file in such a folder gets 'folder_language' unless its own filename
    has a language tag (that tag wins). Returns {norm_filepath: lang} for
    the files the choice applied to."""
    applied = {}
    for f in files:
        lang = folder_languages.get(f.get("folder_group") or LOOSE_FILES_KEY)
        if not lang or f.get("folder_language"):
            continue  # folder_language: a tagged group folder or a language folder
        if _has_own_language_tag(f):
            continue
        f["folder_language"] = lang
        applied[f.get("norm_filepath") or norm_filepath(f["filepath"])] = lang
    return applied


def is_languages_mixed(per_file_language_map, dropdown_default=None):
    """True if per-file language detection found ANYTHING worth surfacing
    to the user before silently falling back to the dropdown - either (a)
    two or more different detected languages, which is unambiguous, or (b)
    even just ONE detected language, if it differs from dropdown_default.
    (b) matters because a single tagged file mixed in among untagged ones
    (e.g. one '[fr]' file next to three plain-named files) is exactly the
    case the mixed-language popup exists to catch - if only case (a) were
    checked, that lone 'fr' detection would silently be discarded in favor
    of the dropdown ('en'), because {'fr'} alone has length 1, not > 1.
    dropdown_default=None (unknown/not passed) falls back to the stricter
    len > 1 check only, for any caller that hasn't been updated to pass it."""
    detected = {v for v in per_file_language_map.values() if v}
    if len(detected) > 1:
        return True
    if len(detected) == 1 and dropdown_default is not None:
        only_lang = next(iter(detected))
        return only_lang != dropdown_default
    return False


def summarize_language_counts(per_file_language_map):
    """Human-readable 'pt-br: 1 file, fr: 1 file, ...' breakdown of detected
    (non-None) languages, sorted by count descending then code, for display
    in the mixed-language confirmation dialog. Files with no detected
    language are excluded here too - the caller reports the untagged count
    separately since it's a different kind of fact ('how many', not 'which
    language')."""
    counts = {}
    for lang in per_file_language_map.values():
        if lang:
            counts[lang] = counts.get(lang, 0) + 1
    if not counts:
        return ""
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return ", ".join(f"{code}: {n} file{'s' if n != 1 else ''}" for code, n in ordered)

def norm_filepath(path):
    return os.path.normcase(os.path.normpath(path))


def natural_sort_key(s):
    def encode(text):
        value = float(text)
        if value < 0:
            inverted = 10 ** 12 + value
            return f"0{inverted:015.4f}"
        return f"1{value:015.4f}"

    return [encode(text) if re.match(r'^\d+(?:\.\d+)?$', text) else text.lower()
            for text in re.split(r'(\d+(?:\.\d+)?)', str(s))]


def encode_tus_metadata(meta_dict):
    pairs = []
    for k, v in meta_dict.items():
        if v is None: continue
        if isinstance(v, list):
            val_str = json.dumps(v)
        elif isinstance(v, float) and v.is_integer():
            val_str = str(int(v))
        else:
            val_str = str(v)
        encoded_val = base64.b64encode(val_str.encode('utf-8')).decode('utf-8')
        pairs.append(f"{k} {encoded_val}")
    return ",".join(pairs)


def _extract_bracket_groups(name_without_ext):
    bracket_re = re.compile(r'\[([A-Za-z0-9][^\]]*?)\]')
    raw_groups = []
    clean_name = name_without_ext
    for m in bracket_re.finditer(name_without_ext):
        content = m.group(1).strip()
        # A bracket whose ENTIRE content is a known language code/name
        # (e.g. '[en]', '[pt-br]') is a language tag, not a scan-group
        # credit - skip it here so it doesn't get picked up as a group AND
        # leave it in clean_name untouched (language stripping, if wanted,
        # is a separate concern for the language-detection callers, not
        # this function). A bracket with a language code alongside other
        # text (e.g. '[SomeGroup, en]') still only skips the 'en' segment
        # below, so mixed brackets keep working as group credits.
        names = [n.strip() for n in content.split(',') if n.strip()]
        names = [n for n in names if not is_known_language_code(n)]
        if not names:
            continue
        raw_groups.extend(names)
        clean_name = clean_name.replace(m.group(0), '')
    return raw_groups, clean_name.strip(' -_')


def _extract_parenthesis_groups(name_without_ext):
    paren_re = re.compile(r'\(([A-Za-z0-9][^\)]*?)\)')
    raw_groups = []
    clean_name = name_without_ext
    for m in paren_re.finditer(name_without_ext):
        content = m.group(1).strip()
        if not content or re.match(r'^\d{4}$', content): continue
        names = [n.strip() for n in content.split(',') if n.strip()]
        names = [n for n in names if not is_known_language_code(n)]
        if not names:
            continue
        raw_groups.extend(names)
        clean_name = clean_name.replace(m.group(0), '')
    return raw_groups, clean_name.strip(' -_')


def parse_custom_regex_input(raw):
    renames = []
    extractor = None
    if not raw:
        return renames, extractor

    parts = [p for p in raw.split(';;') if p.strip()]
    for part in parts:
        if '->' in part:
            pattern, replacement = part.split('->', 1)
            pattern = pattern.strip().strip("'\"")
            replacement = replacement.strip().strip("'\"")
            if pattern:
                try:
                    compiled = re.compile(pattern)
                    compiled.sub(replacement, "")
                    renames.append((pattern, replacement))
                except re.error:
                    continue
        else:
            pattern = part.strip().strip("'\"")
            if pattern:
                try:
                    compiled = re.compile(pattern, re.IGNORECASE)
                    if compiled.groups >= 1:
                        extractor = compiled
                except re.error:
                    continue

    return renames, extractor


def validate_custom_regex_input(raw):
    warnings = []
    if not raw:
        return warnings
    parts = [p for p in raw.split(';;') if p.strip()]
    for part in parts:
        if '->' in part:
            pattern, replacement = part.split('->', 1)
            pattern = pattern.strip().strip("'\"")
            if pattern:
                try:
                    re.compile(pattern).sub(replacement.strip().strip("'\""), "")
                except re.error as e:
                    warnings.append(f"Invalid custom regex rule '{part.strip()}': {e}")
        else:
            pattern = part.strip().strip("'\"")
            if pattern:
                try:
                    compiled = re.compile(pattern, re.IGNORECASE)
                    if compiled.groups < 1:
                        warnings.append(f"Custom regex '{pattern}' has no capture group () - nothing to extract.")
                except re.error as e:
                    warnings.append(f"Invalid custom regex pattern '{pattern}': {e}")
    return warnings


# Cyrillic/Greek characters that are visually identical or near-identical to Latin
# letters and can accidentally end up in filenames (e.g. pasted from a source using
# a different keyboard layout or font). Without normalizing these, a filename like
# "Сh.002" (Cyrillic С) fails to match the chapter/episode label regex entirely,
# since it only recognizes Latin "ch"/"chapter"/"episode"/"ep".
_HOMOGLYPH_MAP = {
    'А': 'A', 'а': 'a', 'В': 'B', 'С': 'C', 'с': 'c', 'Е': 'E', 'е': 'e',
    'Н': 'H', 'І': 'I', 'і': 'i', 'Ѕ': 'S', 'О': 'O', 'о': 'o', 'Р': 'P',
    'р': 'p', 'Т': 'T', 'т': 't', 'Х': 'X', 'х': 'x', 'Ү': 'Y',
}
_HOMOGLYPH_TABLE = str.maketrans(_HOMOGLYPH_MAP)


def normalize_homoglyphs(text):
    return text.translate(_HOMOGLYPH_TABLE)


def strip_leading_zeros_in_title(text):
    return re.sub(r'\b0+(\d+)\b', r'\1', text)


_CUSTOM_PATTERN_PLACEHOLDER_RE = re.compile(r'(?i)(?<![A-Za-z0-9])N(?![A-Za-z0-9])')


def custom_pattern_has_placeholder(pattern_text):
    """True if pattern_text contains a standalone N placeholder (case-insensitive,
    not part of a longer word like 'Number' or 'Nova')."""
    return bool(_CUSTOM_PATTERN_PLACEHOLDER_RE.search(pattern_text))


def apply_custom_number_pattern(pattern_text, number):
    """Fill a user-defined title pattern (e.g. 'Scene N', 'Part N: Awakening')
    with a specific chapter/volume number, replacing the first standalone
    'N' placeholder. If the pattern has no placeholder, the number is
    appended to the end instead (e.g. 'wassup' -> 'wassup 1'), so every
    typed word still gets a unique, ordered title."""
    formatted = fmt_num(number)
    if _CUSTOM_PATTERN_PLACEHOLDER_RE.search(pattern_text):
        return _CUSTOM_PATTERN_PLACEHOLDER_RE.sub(formatted, pattern_text, count=1)
    return f"{pattern_text} {formatted}"


def compile_removal_pattern(pattern_input):
    looks_like_regex = bool(re.search(r'\\[dwsSDWbB]|[*+?^$|]|\{\d*,?\d*\}', pattern_input))
    if looks_like_regex:
        try:
            re.compile(pattern_input)
            return pattern_input
        except re.error:
            return re.escape(pattern_input)
    return re.escape(pattern_input)


def apply_removal_pattern(pattern, text):
    try:
        result = re.sub(pattern, "", text, flags=re.IGNORECASE).strip()
        result = re.sub(r'\(\s*\)|\[\s*\]', '', result)
        result = re.sub(r'\s{2,}', ' ', result).strip(' -_')
        return result if result else None
    except re.error:
        return None


def parse_filename_details(filename, upload_type="chapter", chapter_naming="extract",
                            custom_regex=None, strip_groups=False, custom_renames=None):
    name_no_ext = re.sub(r'\.(cbz|zip)$', '', filename, flags=re.IGNORECASE)

    if upload_type == "volume":
        raw_groups, name_clean = _extract_parenthesis_groups(name_no_ext)
    else:
        raw_groups, name_clean = _extract_bracket_groups(name_no_ext)

    if not strip_groups:
        name_clean = name_no_ext

    if custom_renames:
        for pattern, replacement in custom_renames:
            try:
                name_clean = re.sub(pattern, replacement, name_clean, flags=re.IGNORECASE)
            except re.error:
                continue

    custom_extracted_title = None
    if custom_regex:
        try:
            extractor = custom_regex if hasattr(custom_regex, 'search') else re.compile(custom_regex, re.IGNORECASE)
            m = extractor.search(name_no_ext)
            if m and extractor.groups >= 1:
                extracted = m.group(1).strip()
                if extracted:
                    custom_extracted_title = extracted
        except re.error:
            pass

    num = None
    num_source = None
    episode_label_num = None
    num_came_from_episode_label = False

    if upload_type == "volume":
        num_pattern = r'(?i)(?:(?:\b|_)?(?:volume|vol)|(?:\b|_)v)[\.\-_\s]*(\d+(?:\.\d+)?)'
    else:
        num_pattern = (
            r"(?i)(?:(?:\b|_)?"
            r"(?:chap['\-]?t?er|chapter|chap|ch"
            r'|kapitel|kap'
            r'|chapitre'
            r'|cap[ií]tulo|cap'
            r'|episode|ep)'
            r'|(?:\b|_)c)'
            r'[\.\-_\s]*(\d+(?:\.\d+)?)'
        )

    matches = list(re.finditer(num_pattern, normalize_homoglyphs(name_clean)))

    if upload_type != "volume" and not matches:
        cjk_pattern = (
            r'第?\s*(\d+(?:\.\d+)?)\s*(?:章|話|话|回)'   
            r'|제?\s*(\d+(?:\.\d+)?)\s*(?:화|장)'          
        )
        cjk_matches = list(re.finditer(cjk_pattern, name_clean))
        if cjk_matches:
            class _CjkMatch:
                def __init__(self, m):
                    self._m = m
                    self._num = m.group(1) or m.group(2)
                def group(self, i):
                    return self._m.group(0) if i == 0 else self._num
                def start(self):
                    return self._m.start()
                def end(self):
                    return self._m.end()
            matches = [_CjkMatch(m) for m in cjk_matches]

    if len(matches) > 1:
        num = float(matches[0].group(1))
        num_source = "sequence_index"
        episode_label_num = float(matches[-1].group(1))

        if 'ep' in matches[-1].group(0).lower() or 'episode' in matches[-1].group(0).lower() or '화' in matches[-1].group(0).lower():
            num_came_from_episode_label = True
        name_clean = name_clean[:matches[0].start()] + name_clean[matches[0].end():]

    elif len(matches) == 1:
        val = float(matches[0].group(1))
        matched_str = matches[0].group(0).lower()
        has_explicit_label = bool(re.search(r'(?i)chapter|ch\b|episode|ep\b|章|話|话|回|화|장', matched_str))
        
        is_bare_sequence_prefix = bool(re.fullmatch(r'ch\d+', matched_str)) and not has_explicit_label

        if matches[0].start() == 0 and is_bare_sequence_prefix:
            num = val
            num_source = "sequence_index"
            episode_label_num = None
        else:
            num = val
            num_source = "chapter_or_volume_label"
            episode_label_num = val
            if 'ep' in matched_str or 'episode' in matched_str or '화' in matched_str:
                num_came_from_episode_label = True

        name_clean = name_clean[:matches[0].start()] + name_clean[matches[0].end():]
    else:
        leading_prefix_match = re.match(r'^0*(\d+(?:\.\d+)?)[\s\-_\.]+', name_clean)
        if leading_prefix_match:
            num = float(leading_prefix_match.group(1))
            num_source = "fallback"
            name_clean = name_clean[:leading_prefix_match.start()] + name_clean[leading_prefix_match.end():]
        else:
            all_nums = [(m.group(1), m) for m in re.finditer(r'(?<!\d)(\d+(?:\.\d+)?)(?!\d)', name_clean)]
            if all_nums:
                valid_nums = [n for n in all_nums if not (len(n[0]) == 4 and n[0].startswith(('19', '20')))]
                target = valid_nums[-1] if valid_nums else all_nums[-1]
                num = float(target[0])
                num_source = "fallback"
                name_clean = name_clean[:target[1].start()] + name_clean[target[1].end():]

    if num is None:
        return None, [], raw_groups, None, None, None

    if upload_type == "volume":
        return num, [("Vol. N.NN", f"Vol. {num:.2f}")], raw_groups, "volume", num_source, None
    if chapter_naming == "preset":
        return num, [("Chapter N", f"Chapter {num:g}")], raw_groups, "preset", num_source, episode_label_num

    had_season = bool(re.search(r'(?i)[\(\[\s]*s(?:eason)?[\.\-_\s]*\d+[\)\]\s]*', name_clean))
    had_episode_label = episode_label_num is not None
    had_chapter_label = (not num_came_from_episode_label and upload_type != "volume" and
                          bool(re.search(r'(?i)(?:\b|_)?(?:chapter|ch|kapitel|kap|chapitre|cap[ií]tulo|cap|章|話|话|回|장)[\.\-_\s]*\d+(?:\.\d+)?', name_clean)))
    had_leading_prefix = bool(re.match(r'^0*\d+[\s\-_\.]+', name_clean))

    def wash_title(s):
        s = s.replace('_', ' ')
        s = re.sub(r'\s+[\.\~\|]+', ' - ', s)
        s = re.sub(r'\bv\d+\b', '', s, flags=re.IGNORECASE)
        s = re.sub(r'^[\s\-\.\~\|]+|[\s\-\.\~\|]+$', '', s)
        s = re.sub(r'\s{2,}', ' ', s)
        s = re.sub(r'\s+-\s+', ' - ', s)
        return s.strip()

    minimal_wash = wash_title(name_clean)

    def _season_bracketed_sub(m):
        season_num = int(m.group(1))
        trailing = m.group(2).strip()
        tag = f" (S{season_num}) "
        return f"{tag}{trailing} " if trailing else tag

    name_clean = re.sub(
        r'(?i)[\(\[]\s*s(?:eason)?[\.\-_\s]*(\d+)\s*([^\)\]]*)[\)\]]',
        _season_bracketed_sub,
        name_clean
    )

    name_clean = re.sub(
        r'(?i)(?<!\()(?:\b|_)s(?:eason)?[\.\-_\s]*(\d+)\b',
        lambda m: f" (S{int(m.group(1))}) ",
        name_clean
    )
    name_clean = re.sub(r'(?i)(?:\b|_)?(?:episode|ep|화)[\.\-_\s]*(\d+(?:\.\d+)?)', lambda m: f" Episode {float(m.group(1)):g} ", name_clean)

    candidates = []
    seen_texts = set()

    def add_candidate(label, text):
        text = text.strip()
        if text and text not in seen_texts:
            candidates.append((label, text))
            seen_texts.add(text)

    washed_full = wash_title(name_clean)
    default_label = "Full title (as detected)"

    if not washed_full:
        fallback_word = "Episode" if had_episode_label or re.search(r'(?i)(episode|ep|화)', filename) else "Chapter"
        add_candidate(default_label, f"{fallback_word} {num:g}")
    else:
        add_candidate(default_label, washed_full)

        if had_episode_label and "Episode " in washed_full:
            no_ep = re.sub(r'(?i)Episode\s*\d+(?:\.\d+)?[\s\-\.\~\|]*', '', washed_full)
            no_ep = wash_title(no_ep)
            add_candidate("Without episode label", no_ep)

        if had_chapter_label:
            no_ch = re.sub(r'(?i)(?:\b|_)?(?:chapter|ch|kapitel|kap|chapitre|cap[ií]tulo|cap|章|話|话|回|장)[\.\-_\s]*\d+(?:\.\d+)?[\s\-\.\~\|]*', '', washed_full)
            no_ch = wash_title(no_ch)
            add_candidate("Without chapter label", no_ch)

        if had_season:
            no_season = re.sub(r'(?i)\(S\d+\)\s*', '', washed_full)
            no_season = wash_title(no_season)
            add_candidate("Without season tag", no_season)

            if had_episode_label:
                bare = re.sub(r'(?i)\(S\d+\)\s*', '', washed_full)
                bare = re.sub(r'(?i)Episode\s*\d+(?:\.\d+)?[\s\-\.\~\|]*', '', bare)
                bare = wash_title(bare)
                add_candidate("Bare title only", bare)

        if had_leading_prefix:
            def _strip_leading_prefix(text):
                stripped = re.sub(r'^0*\d+[\s\-_\.]+', '', text)
                return wash_title(stripped)

            for label, text in list(candidates):
                no_prefix = _strip_leading_prefix(text)
                if no_prefix != text:
                    if label == default_label:
                        add_candidate("Without leading number", no_prefix)
                    else:
                        add_candidate(f"{label}, without leading number", no_prefix)

    if had_season or had_episode_label or had_chapter_label or had_leading_prefix:
        add_candidate("Minimal (only number removed)", minimal_wash)

    if upload_type != "volume":
        add_candidate("Chapter N", f"Chapter {num:g}")
        add_candidate("Episode N", f"Episode {num:g}")

    if custom_extracted_title:
        candidates = [(l, t) for l, t in candidates if t != custom_extracted_title]
        candidates.insert(0, ("Custom regex extraction", custom_extracted_title))

    if not candidates:
        candidates = [(default_label, f"Chapter {num:g}")]

    shape_key = (f"season={had_season}|episode_label={had_episode_label}|"
                 f"chapter_label={had_chapter_label}|leading_prefix={had_leading_prefix}|"
                 f"custom={bool(custom_extracted_title)}")

    return num, candidates, raw_groups, shape_key, num_source, episode_label_num


def validate_archive(filepath):
    try:
        with zipfile.ZipFile(filepath) as zf:
            namelist = zf.namelist()
            file_names = (n for n in namelist if not n.endswith('/'))
            has_any = False
            has_image = False
            for n in file_names:
                has_any = True
                if n.lower().endswith(ARCHIVE_IMAGE_EXTS):
                    has_image = True
                    break
            if not has_any:
                return "archive is empty"
            if not has_image:
                return "no image files inside"
    except zipfile.BadZipFile:
        return "not a valid ZIP/CBZ archive"
    except (OSError, EOFError) as e:
        return f"unreadable archive ({str(e)[:40]})"
    return None


def fmt_num(n):
    return str(int(n)) if isinstance(n, (int, float)) and float(n) == int(n) else str(n)


def parse_number_ranges(text, valid_numbers=None):
    result = set()
    unmatched = []
    valid_set = set(valid_numbers) if valid_numbers is not None else None

    def _to_num(s):
        s = s.strip()
        try:
            return int(s) if float(s) == int(float(s)) else float(s)
        except ValueError:
            return None

    for raw_token in text.split(","):
        token = raw_token.strip()
        if not token:
            continue
        if "-" in token[1:]:  # skip leading '-' for negative-safety, not expected but harmless
            left, _, right = token.partition("-")
            lo, hi = _to_num(left), _to_num(right)
            if lo is None or hi is None:
                unmatched.append(token)
                continue
            if lo > hi:
                lo, hi = hi, lo
            if valid_set is not None:
                matches = {n for n in valid_set if lo <= n <= hi}
                if not matches:
                    unmatched.append(token)
                result |= matches
            else:
                # No known valid set - expand integer range only
                if isinstance(lo, float) or isinstance(hi, float):
                    unmatched.append(token)
                else:
                    result |= set(range(int(lo), int(hi) + 1))
        else:
            n = _to_num(token)
            if n is None:
                unmatched.append(token)
                continue
            if valid_set is not None and n not in valid_set:
                unmatched.append(token)
                continue
            result.add(n)

    return result, unmatched


def detect_episode_drift(parsed):
    drift_detected = any(
        item.get("episode_label_num") is not None and item["episode_label_num"] != item["number"]
        for item in parsed
    )
    has_real_labels = any(item.get("episode_label_num") is not None for item in parsed)

    if not drift_detected or not has_real_labels:
        return None

    conflicts = [item for item in parsed if item.get("episode_label_num") is not None and item["episode_label_num"] != item["number"]]
    if not conflicts:
        return None

    drifts = [item['number'] - item['episode_label_num'] for item in conflicts]
    distinct_drifts = sorted(set(round(d, 4) for d in drifts))

    return {
        "conflicts": conflicts,
        "distinct_drifts": distinct_drifts,
        "consistent": len(distinct_drifts) == 1,
        "example_filename": conflicts[0]['filename'],
        "example_file_index": conflicts[0]['number'],
        "example_episode_label": conflicts[0]['episode_label_num'],
        "affected_count": len(conflicts),
    }


def apply_episode_drift_correction(parsed, mode):
    if mode == "continuous":
        return  # Bypass drift correction entirely; the chXXXX prefixes handle the exact order

    for item in parsed:
        item["original_num"] = item["number"]

    ordered = sorted(parsed, key=lambda x: x["original_num"])

    for item in ordered:
        if item.get("episode_label_num") is not None:
            item["number"] = item["episode_label_num"]

    i = 0
    while i < len(ordered):
        if ordered[i].get("episode_label_num") is None:
            start = i
            while i < len(ordered) and ordered[i].get("episode_label_num") is None:
                i += 1
            prev_val = ordered[start - 1]["number"] if start > 0 else 0.0
            block = ordered[start:i]
            n = len(block)
            if i < len(ordered) and ordered[i]["number"] > prev_val:
                next_val = ordered[i]["number"]
            else:
                # No next labeled item (trailing run at the end of the list, or
                # the file list started with unlabeled items) - leave enough
                # room for the whole block to count up sequentially rather than
                # collapsing everything into a 1.0-wide gap.
                next_val = prev_val + n + 1.0

            gap = next_val - prev_val

            if n == 1:
                block[0]["number"] = round(prev_val + gap / 2, 6)
            elif gap >= n + 1:
                # There's enough room to continue sequential whole numbers
                # (prev_val + 1, prev_val + 2, ...) without reaching next_val.
                # This is the right treatment for a long run of unlabeled files
                # that are really just sequential chapters without an explicit
                # "Chapter N" label in the filename - not a small cluster of
                # specials squeezed between two labeled chapters, which is what
                # the decimal (.1/.2/.3...) scheme below is for.
                for k, item in enumerate(block):
                    item["number"] = round(prev_val + (k + 1), 6)
            else:
                # Multiple unlabeled items in this gap: number them prev.1, prev.2, prev.3...
                # in file order, but only as many decimal places as needed to fit
                # strictly within the available gap without colliding with next_val.
                pad = 2 if n > 9 else 1
                base = int(prev_val)
                step = 1 / (10 ** pad)
                for k, item in enumerate(block):
                    frac = (k + 1) * step
                    proposed = round(base + frac, pad + 4)
                    # Guard against overshooting into or past the next real label
                    # (can happen if prev_val's fractional part is already close
                    # to next_val, e.g. prev=9.9, next=10.0).
                    if proposed >= next_val:
                        # Fall back to splitting the remaining gap evenly instead.
                        proposed = round(prev_val + gap * (k + 1) / (n + 1), 6)
                    item["number"] = proposed
        else:
            i += 1

    # Fix the desynced text titles
    for item in ordered:
        old_num = item["original_num"]
        new_num = item["number"]
        if old_num != new_num:
            updated_candidates = []
            for label, text in item["candidates"]:
                text = re.sub(rf'(?i)(Chapter|Episode)\s+{old_num:g}\b', rf'\g<1> {new_num:g}', text)
                updated_candidates.append((label, text))
            item["candidates"] = updated_candidates


# Folder names never treated as group folders: the optimizer's own output.
GROUP_FOLDER_IGNORE = {"optimized"}


def find_group_subfolders(directory):
    """Immediate subfolders of `directory` that directly contain .cbz/.zip
    archives, e.g. 'Solo Leveling/Asura Scans/ch001.cbz'. Each such folder's
    name is treated as the group that released the archives inside it -
    unless the name is a language ('EN', 'French'), in which case it's a
    language folder (see is_language_folder).

    Returns [(folder_name, folder_path, archive_count)], natural-sorted.
    Hidden folders and the optimizer's 'optimized' output are skipped."""
    found = []
    try:
        entries = list(os.scandir(directory))
    except OSError:
        return []
    for e in entries:
        try:
            if not e.is_dir() or e.name.startswith(".") or e.name.lower() in GROUP_FOLDER_IGNORE:
                continue
            count = sum(1 for c in os.scandir(e.path)
                        if c.is_file() and c.name.lower().endswith(VALID_ARCHIVE_EXTENSIONS))
        except OSError:
            continue
        if count:
            found.append((e.name, e.path, count))
    found.sort(key=lambda t: natural_sort_key(t[0]))
    return found


_FOLDER_TAG_RE = re.compile(r"[\[(]\s*([^\])]+?)\s*[\])]")
_FOLDER_LANG_SUFFIX_RE = re.compile(r"^(.*\S)\s+[-|]\s+([A-Za-z][A-Za-z-]*)$")


def split_group_folder_name(folder_name):
    """Splits a subfolder name into (group_name, language_code):
      'Asura Scans [EN]'      -> ('Asura Scans', 'en')
      'Asura Scans (French)'  -> ('Asura Scans', 'fr')
      'Asura Scans - es'      -> ('Asura Scans', 'es')
      'EN' / 'Spanish'        -> (None, 'en') / (None, 'es')   a pure language folder
      'Official [HQ]'         -> ('Official [HQ]', None)        no language tag
    Only a bracket/paren tag (or a ' - xx' suffix) that is a known language
    is taken out; any other tag stays part of the group name."""
    lookup = _language_lookup()
    name = (folder_name or "").strip()
    if not name:
        return None, None
    if name.lower() in lookup:
        return None, lookup[name.lower()]
    lang = None

    def _take(m):
        nonlocal lang
        code = lookup.get(m.group(1).strip().lower())
        if code and lang is None:
            lang = code
            return " "
        return m.group(0)

    rest = _FOLDER_TAG_RE.sub(_take, name)
    if lang is None:
        m = _FOLDER_LANG_SUFFIX_RE.match(name)
        if m and m.group(2).strip().lower() in lookup:
            rest, lang = m.group(1), lookup[m.group(2).strip().lower()]
    if lang is None:
        return name, None
    rest = re.sub(r"\s+", " ", rest).strip(" -_|.,")
    return (rest or None), lang


def is_language_folder(folder_name):
    """'EN', 'fr', 'Spanish'... - a subfolder named only after a language
    holds that language's files rather than one group's."""
    return split_group_folder_name(folder_name)[0] is None


def group_folder_names(directory):
    """Names of the subfolders that count as group folders (not language folders)."""
    return [name for name, _, _ in find_group_subfolders(directory) if not is_language_folder(name)]


def list_upload_archives(directory):
    """Every archive an upload of `directory` covers: the ones directly inside
    it plus the ones in its group/language subfolders (normalized paths)."""
    paths = []
    folders = [directory] + [p for _, p, _ in find_group_subfolders(directory)]
    for folder in folders:
        try:
            for e in os.scandir(folder):
                if e.is_file() and e.name.lower().endswith(VALID_ARCHIVE_EXTENSIONS):
                    paths.append(norm_filepath(e.path))
        except OSError:
            continue
    return paths


def _scan_one_folder(folder, upload_type, chapter_naming, custom_regex, strip_groups, custom_renames,
                     parsed, errors, display_prefix="", folder_group=None, folder_group_name=None,
                     folder_language=None):
    with os.scandir(folder) as it:
        for entry in it:
            if not entry.is_file() or not entry.name.lower().endswith(VALID_ARCHIVE_EXTENSIONS):
                continue

            # Parse the bare filename; the display/key name carries the folder so
            # 'Asura Scans/ch001.cbz' and 'Official/ch001.cbz' never collide.
            filename = display_prefix + entry.name

            num, candidates, file_groups, shape_key, num_source, episode_label_num = parse_filename_details(
                entry.name, upload_type, chapter_naming, custom_regex, strip_groups, custom_renames
            )

            if num is None:
                errors.append(f"Could not detect {upload_type} number from '{filename}'. Skipping.")
                continue

            item = {
                "entry": entry, "filepath": entry.path, "filename": filename,
                "number": num, "candidates": candidates, "groups": file_groups,
                "shape_key": shape_key, "num_source": num_source,
                "episode_label_num": episode_label_num,
            }
            if folder_group:
                # The folder is the attribution; bracket tags inside it don't apply.
                # folder_group is the folder's own name (unique per folder, so
                # 'Asura Scans [EN]' and 'Asura Scans [FR]' stay apart); the
                # displayed group drops the language tag.
                item["folder_group"] = folder_group
                item["groups"] = [folder_group_name or folder_group]
            if folder_language:
                item["folder_language"] = folder_language
            parsed.append(item)


def scan_directory_files(directory, upload_type, chapter_naming="extract",
                          custom_regex=None, strip_groups=False, custom_renames=None):
    """Scans the archives directly inside `directory`, plus those inside its
    group subfolders (see find_group_subfolders). Files from a subfolder get
    filename '<folder>/<name>' and, for a group folder, 'folder_group'."""
    parsed = []
    errors = []

    if not directory or not os.path.isdir(directory):
        return [], [f"Invalid or missing directory: {directory}"]

    try:
        _scan_one_folder(directory, upload_type, chapter_naming, custom_regex, strip_groups,
                         custom_renames, parsed, errors)
    except OSError as e:
        return [], [f"Error scanning directory {directory}: {e}"]

    for folder_name, folder_path, _ in find_group_subfolders(directory):
        group_name, folder_lang = split_group_folder_name(folder_name)
        try:
            _scan_one_folder(folder_path, upload_type, chapter_naming, custom_regex, strip_groups,
                             custom_renames, parsed, errors, display_prefix=f"{folder_name}/",
                             folder_group=folder_name if group_name else None,
                             folder_group_name=group_name, folder_language=folder_lang)
        except OSError as e:
            errors.append(f"Error scanning folder '{folder_name}': {e}")

    parsed.sort(key=lambda x: x["number"])
    return parsed, errors


def finalize_file_entries(parsed):
    for item in parsed:
        if "title" not in item:
            candidates = item.get("candidates") or []
            item["title"] = candidates[0][1] if candidates else item.get("filename", "")
        if "size" not in item:
            try:
                item["size"] = item["entry"].stat().st_size
            except (OSError, KeyError):
                item["size"] = 0
        # The raw os.DirEntry object was only ever needed for the fast
        # stat().st_size lookup just above - it must NOT survive past
        # this point. It isn't JSON-serializable, and these same dicts
        # eventually flow into save_paused_upload()/update_paused_upload()
        # (paused_upload.json). Leaving "entry" in place made every save
        # after the first one silently fail (caught, logged, swallowed),
        # so paused/completed state stopped persisting at all without
        # any visible error.
        item.pop("entry", None)
    return parsed


def scan_directory_files_auto(directory, upload_type, chapter_naming="extract",
                               custom_regex=None, strip_groups=False, custom_renames=None,
                               drift_mode="reset"):
    parsed, errors = scan_directory_files(
        directory, upload_type, chapter_naming, custom_regex, strip_groups, custom_renames
    )
    if upload_type == "chapter":
        drift = detect_episode_drift(parsed)
        if drift is not None:
            apply_episode_drift_correction(parsed, drift_mode)
            parsed.sort(key=lambda x: x["number"])
    finalize_file_entries(parsed)
    return parsed, errors


def group_by_shape(parsed):
    """Groups parsed items by their shape_key."""
    groups = {}
    for item in parsed:
        groups.setdefault(item.get("shape_key"), []).append(item)
    return groups


def list_archive_targets(directory):
    """Fast, synchronous directory scan - just names, no I/O on file contents."""
    targets = []
    try:
        for e in os.scandir(directory):
            if e.is_file() and e.name.lower().endswith(VALID_ARCHIVE_EXTENSIONS):
                targets.append(e.path)
    except OSError:
        return []
    targets.sort(key=natural_sort_key)
    return targets


def group_search_queries(name):
    # 'Asura Scans [EN]' (a group folder with a language tag) searches as 'Asura Scans' first.
    group_part, _lang = split_group_folder_name(name)
    if group_part and group_part != name:
        return group_search_queries(group_part) + [name]
    queries = [name]
    if not re.search(r'\s', name):
        camel = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', name)
        if camel != name:
            queries.append(camel)
        queries.extend(name[:i] + ' ' + name[i:] for i in range(1, min(len(name), 7)))
    return queries


def detect_groups_from_filenames(directory, upload_type="chapter"):
    valid_ext = VALID_ARCHIVE_EXTENSIONS
    counter = {}
    per_file = {}

    try:
        filenames = [f for f in os.listdir(directory) if f.lower().endswith(valid_ext)]
    except OSError:
        return [], {}

    for filename in filenames:
        filepath = norm_filepath(os.path.join(directory, filename))
        name = re.sub(r'\.(cbz|zip)$', '', filename, flags=re.IGNORECASE)

        found, _ = _extract_parenthesis_groups(name) if upload_type == "volume" else _extract_bracket_groups(name)

        if found:
            per_file[filepath] = found
            key = frozenset(n.lower() for n in found)
            prev_count, prev_names = counter.get(key, (0, found))
            counter[key] = (prev_count + 1, prev_names)

    # Group subfolders: every archive inside 'Asura Scans/' is credited to
    # 'Asura Scans' (bracket tags inside a group folder are not used).
    for folder_name, folder_path, _ in find_group_subfolders(directory):
        if is_language_folder(folder_name):
            continue
        try:
            names_in_folder = [f for f in os.listdir(folder_path) if f.lower().endswith(valid_ext)]
        except OSError:
            continue
        for filename in names_in_folder:
            per_file[norm_filepath(os.path.join(folder_path, filename))] = [folder_name]
        key = frozenset([folder_name.lower()])
        prev_count, prev_names = counter.get(key, (0, [folder_name]))
        counter[key] = (prev_count + len(names_in_folder), prev_names)

    if not counter:
        return [], {}

    all_unique_names = list({name for _, names in counter.values() for name in names})
    return all_unique_names, per_file


def is_groups_mixed(per_file_names):
    unique_group_sets = set(frozenset(v) for v in per_file_names.values())
    return len(unique_group_sets) > 1


def distinct_group_sets(per_file_names):
    """The distinct sets of group names seen across per-file detections,
    sorted for stable display (e.g. in a 'detected mixed groups' summary)."""
    unique_sets = set(frozenset(v) for v in per_file_names.values())
    return sorted(unique_sets, key=lambda s: sorted(s))


def resolve_per_file_group_ids(per_file_names, name_to_group):
    """Map each file's detected group *names* to resolved group *ids*, using
    an already-resolved name -> group dict. name_to_group can map a name to
    a single group dict ({"id": 1, ...}) or a list of group dicts
    [{"id": 1, ...}, {"id": 2, ...}] for joint scanlations.
    Files with no resolved names are omitted."""
    result = {}
    for filepath, fnames in per_file_names.items():
        ids = []
        for n in fnames:
            if n in name_to_group:
                entry = name_to_group[n]
                if isinstance(entry, list):
                    for g in entry:
                        if isinstance(g, dict) and g.get("id") is not None:
                            if g["id"] not in ids:
                                ids.append(g["id"])
                        elif isinstance(g, int) and g not in ids:
                            ids.append(g)
                elif isinstance(entry, dict) and entry.get("id") is not None:
                    if entry["id"] not in ids:
                        ids.append(entry["id"])
                elif isinstance(entry, int) and entry not in ids:
                    ids.append(entry)
        if ids:
            result[filepath] = ids
    return result


def resolve_per_file_group_names(per_file_names, name_to_group):
    """Map each file's detected group *names* to resolved display *names*
    (e.g. 'RESET SCANS', 'Realm Scans')."""
    result = {}
    for filepath, fnames in per_file_names.items():
        names = []
        for n in fnames:
            if n in name_to_group:
                entry = name_to_group[n]
                if isinstance(entry, list):
                    for g in entry:
                        gname = g.get("name") if isinstance(g, dict) else str(g)
                        if gname and gname not in names:
                            names.append(gname)
                elif isinstance(entry, dict) and entry.get("name"):
                    if entry["name"] not in names:
                        names.append(entry["name"])
                elif isinstance(entry, str) and entry not in names:
                    names.append(entry)
        if names:
            result[filepath] = names
    return result


def auto_match_group(name, search_results, matched_query=None):
    candidates = {name.lower()}
    if matched_query:
        candidates.add(matched_query.lower())
    exact = [g for g in search_results if g.get("name", "").lower() in candidates]
    if len(exact) == 1:
        return exact[0]
    return None


def find_missing_numbers(files):
    int_numbers = []
    for f in files:
        n = f["number"]
        try:
            if n == int(n):
                int_numbers.append(int(n))
        except (ValueError, OverflowError):
            pass
    int_numbers = sorted(set(int_numbers))
    missing = []
    if len(int_numbers) > 1:
        for i in range(len(int_numbers) - 1):
            if int_numbers[i + 1] - int_numbers[i] > 1:
                missing.extend(range(int_numbers[i] + 1, int_numbers[i + 1]))
    return missing


def find_duplicate_numbers(files):
    """Numbers used by more than one file *for the same group*. Chapter 5 in
    'Asura Scans/' and chapter 5 in 'Official/' are two groups' releases of
    the same chapter, not a duplicate."""
    by_key = {}
    for f in files:
        by_key.setdefault((f.get("folder_group"), f["number"]), []).append(f)
    dups = {}
    for (_, number), flist in by_key.items():
        if len(flist) > 1:
            dups.setdefault(number, []).extend(flist)
    return dups

def filter_detected_groups(per_file_names, approved_tags):
    """Filters the raw filename group map to only include user-approved tags."""
    approved_set = {n.lower() for n in approved_tags}
    filtered_map = {}
    for filepath, tags in per_file_names.items():
        kept = [t for t in tags if t.lower() in approved_set]
        if kept:
            filtered_map[filepath] = kept
    return filtered_map

def apply_tag_filter_to_files(files, approved_tags):
    """Strips rejected bracket tags from the finalized files list."""
    approved_set = {n.lower() for n in approved_tags}
    for f in files:
        f["groups"] = [g for g in f.get("groups", []) if g.lower() in approved_set]
    return files

def build_upload_routing_maps(files, base_group_map, base_language_map=None):
    """Extracts per-file scanlator, group, and language overrides set during
    review. base_language_map seeds the result the same way base_group_map
    already does for groups - callers pass in whatever the pre-review
    detection/confirmation step (detect_languages_from_files +
    the mixed-language popup) resolved, and any row a user then edits in
    Review (f["language"] set via the Language column's picker dialog)
    overrides that seed for just that file, exactly like f["group_id"]
    already overrides base_group_map above.

    Returns (per_file_group, per_file_scanlator, per_file_language). A file
    with no language override AND nothing in base_language_map simply has
    no entry in per_file_language - callers (process_uploads, the dedup-DB
    write) already know to fall back to the batch-wide language default for
    any file missing from this map, same convention as the other two maps."""
    per_file_group = dict(base_group_map or {})
    per_file_scanlator = {}
    per_file_language = dict(base_language_map or {})

    for f in files:
        norm_path = norm_filepath(f["filepath"])
        if f.get("scanlator"):
            per_file_scanlator[norm_path] = f["scanlator"]
            if norm_path in per_file_group:
                del per_file_group[norm_path]
        elif f.get("group_ids") is not None:
            per_file_group[norm_path] = list(f["group_ids"])
        elif f.get("group_id"):
            per_file_group[norm_path] = [f["group_id"]]

        if f.get("language"):
            per_file_language[norm_path] = f["language"]

    return per_file_group, per_file_scanlator, per_file_language