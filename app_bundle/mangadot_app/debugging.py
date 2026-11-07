"""HTTP debug logging (--debug equivalent) and proxy connectivity checking.

Kept separate from net.py (browser/UA detection) and uploader.py (the
actual upload protocol) since these are cross-cutting diagnostic/setup
concerns used once at session-setup time, not part of either's core job.
"""
import logging
import logging.handlers

import requests

from . import util

_SENSITIVE_HEADERS = frozenset({"cookie", "set-cookie", "authorization", "x-auth-token", "x-session-token"})


def enable_debug_logging(log_path=None, max_bytes=10 * 1024 * 1024, backup_count=3):
    if log_path is None:
        # A bare relative filename lands in whatever the current working
        # directory happens to be - for an exe launched from a shortcut or
        # Program Files that can be somewhere read-only. Keep it beside the
        # app's other runtime state instead.
        from . import config
        config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        log_path = config.CACHE_DIR / "api_requests.log"
    log_handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=max_bytes, backupCount=backup_count, encoding='utf-8'
    )
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[log_handler],
    )


def log_request_response(response, *args, **kwargs):
    req = response.request

    logging.debug(util.strip_ansi(f"=== HTTP {req.method} {req.url} ==="))
    logging.debug("--- REQUEST HEADERS ---")
    for k, v in req.headers.items():
        if k.lower() in _SENSITIVE_HEADERS:
            logging.debug("%s: [REDACTED]", k)
        else:
            logging.debug(util.strip_ansi(f"{k}: {v}"))
    if req.body:
        try:
            body_len = len(req.body)
            logging.debug("--- REQUEST BODY (Size: %d bytes) ---", body_len)
            if body_len < 2000 and not isinstance(req.body, bytes):
                logging.debug(util.strip_ansi(req.body))
            elif isinstance(req.body, bytes):
                logging.debug("<Binary Data / File Chunk>")
        except TypeError:
            logging.debug("--- REQUEST BODY (Size: Unknown) ---")
    logging.debug("--- RESPONSE STATUS: %s %s ---", response.status_code, response.reason)
    logging.debug("--- RESPONSE HEADERS ---")
    for k, v in response.headers.items():
        if k.lower() in _SENSITIVE_HEADERS:
            logging.debug("%s: [REDACTED]", k)
        else:
            logging.debug(util.strip_ansi(f"{k}: {v}"))
    logging.debug("--- RESPONSE BODY ---")
    try:
        resp_text = response.text
        logging.debug(util.strip_ansi(f"{resp_text[:1000]}... (truncated)" if len(resp_text) > 1000 else resp_text))
    except UnicodeDecodeError:
        logging.debug("<Binary or Unreadable Response>")
    logging.debug("=" * 63 + "\n")


def check_proxy(proxy_url, verify=True, default_user_agent=None):
    test_url = "https://mangadot.net/"
    if default_user_agent is None:
        # Deferred import: net.py imports this module at its own startup,
        # so a module-level import here would be circular. Only the plain
        # constants dict is needed - no detection/network side effects.
        from . import net
        default_user_agent = net.DEFAULT_USER_AGENTS["chrome"]
    ua = default_user_agent
    try:
        r = requests.get(
            test_url,
            proxies={"http": proxy_url, "https": proxy_url},
            timeout=10,
            headers={"User-Agent": ua},
            allow_redirects=False,
            verify=verify,
        )
        if r.status_code == 200 or r.status_code == 204:
            return True, None
        elif r.status_code == 407:
            return False, "Proxy returned 407 — credentials are wrong or missing."
        else:
            return False, f"Proxy failed. Unexpected status: HTTP {r.status_code}"
    except requests.exceptions.SSLError:
        return False, (
            "SSL error through proxy. The proxy may be intercepting TLS (MITM). "
            "If you trust this proxy, disable SSL verification."
        )
    except requests.exceptions.ProxyError as e:
        # requests exception text can embed the proxy URL including any
        # user:pass@host credentials - redact before it reaches the dialog.
        return False, f"Proxy connection failed: {util.redact_proxy_url(str(e))[:80]}"
    except requests.exceptions.ConnectionError as e:
        return False, f"Could not reach proxy: {util.redact_proxy_url(str(e))[:80]}"
    except requests.exceptions.RequestException as e:
        return False, f"Proxy check error: {util.redact_proxy_url(str(e))[:80]}"
