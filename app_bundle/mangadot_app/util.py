"""Small shared helpers with no natural home in auth/net/parser/uploader -
string formatting and sensitive-data redaction used by more than one module."""
import re
import urllib.parse
from pathlib import Path

_HOME_DIR_STR = str(Path.home())

COUNTRY_NAMES = {
    "KR": "South Korea", "JP": "Japan", "CN": "China", "TW": "Taiwan",
    "US": "United States", "GB": "United Kingdom", "FR": "France",
    "TH": "Thailand", "ID": "Indonesia", "VN": "Vietnam",
}
LANGUAGES = [
    ("ar", "Arabic"), ("bn", "Bengali"), ("bg", "Bulgarian"), ("my", "Burmese"),
    ("zh", "Chinese (Simplified)"), ("zh-hk", "Chinese (Traditional)"), ("cs", "Czech"),
    ("da", "Danish"), ("nl", "Dutch"), ("en", "English"), ("tl", "Filipino"),
    ("fi", "Finnish"), ("fr", "French"), ("ka", "Georgian"), ("de", "German"),
    ("el", "Greek"), ("he", "Hebrew"), ("hi", "Hindi"), ("hu", "Hungarian"),
    ("id", "Indonesian"), ("it", "Italian"), ("ja", "Japanese"), ("ko", "Korean"),
    ("la", "Latin"), ("lt", "Lithuanian"), ("ms", "Malay"), ("mn", "Mongolian"),
    ("no", "Norwegian"), ("fa", "Persian"), ("pl", "Polish"), ("pt", "Portuguese"),
    ("pt-br", "Portuguese (Brazil)"), ("ro", "Romanian"), ("ru", "Russian"),
    ("es", "Spanish"), ("es-la", "Spanish (Latin America)"), ("sv", "Swedish"),
    ("th", "Thai"), ("tr", "Turkish"), ("uk", "Ukrainian"), ("vi", "Vietnamese")
]

def format_origin(code):
    if not code:
        return ""
    return COUNTRY_NAMES.get(code.strip().upper(), code.strip().upper())


def redact_home_path(text):
    text = str(text)
    if _HOME_DIR_STR and _HOME_DIR_STR in text:
        text = text.replace(_HOME_DIR_STR, "~")
    return text


def redact_proxy_url(proxy_url):
    try:
        parsed = urllib.parse.urlsplit(proxy_url)
        if parsed.username or parsed.password:
            netloc = parsed.hostname or ""
            if parsed.port:
                netloc += f":{parsed.port}"
            return urllib.parse.urlunsplit((parsed.scheme, f"[REDACTED]@{netloc}", parsed.path, parsed.query, parsed.fragment))
        return proxy_url
    except ValueError:
        return proxy_url


_STRIP_ANSI_RE = re.compile(r'\033\[[0-9;?]*[A-Za-z]')


def strip_ansi(text):
    return _STRIP_ANSI_RE.sub('', str(text))


def fmt_size(bytes_: int) -> str:
    if bytes_ == 0:
        return "0 B"
    gb = bytes_ / (1024 ** 3)
    if gb >= 1:
        return f"{gb:.2f} GB"
    mb = bytes_ / (1024 ** 2)
    if mb >= 1:
        return f"{mb:.2f} MB"
    kb = bytes_ / 1024
    if kb >= 1:
        return f"{kb:.2f} KB"
    return f"{bytes_} B"


def fmt_duration(seconds) -> str:
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h: return f"{h}h {m}m {s}s"
    if m: return f"{m}m {s}s"
    return f"{s}s"