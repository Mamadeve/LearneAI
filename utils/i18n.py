"""i18n — dynamic per-user text loading from locales/<lang>.json.

- Texts are looked up with dotted keys: t(lang, "start.level_q", target=...)
- `{placeholders}` are filled with str.format kwargs.
- Missing languages/files fall back to English; missing keys return the key
  itself (loud but debuggable).
- Locale files are cached and hot-reloadable via reload_locales().
"""
from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any

logger = logging.getLogger(__name__)

LOCALES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "locales"
)

DEFAULT_LANG = "en"

# Languages with dedicated locale files; everything else falls back to English.
SUPPORTED_LANGS = ("en", "fa")

_cache: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()


def _load_file(lang: str) -> dict[str, Any]:
    path = os.path.join(LOCALES_DIR, f"{lang}.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as exc:
        logger.error("Failed to load locale %s: %s", lang, exc)
        return {}


def load(lang: str) -> dict[str, Any]:
    lang = (lang or DEFAULT_LANG).lower()
    with _lock:
        if lang not in _cache:
            data = _load_file(lang) or _load_file(DEFAULT_LANG)
            _cache[lang] = data
        return _cache[lang]


def reload_locales() -> None:
    """Drop cache (useful after admins add new locale files)."""
    with _lock:
        _cache.clear()


def t(lang: str, key: str, **kwargs: Any) -> str:
    """Translate a dotted key, e.g. t('fa', 'start.goal_q')."""
    lang = (lang or DEFAULT_LANG).lower()
    tree = load(lang)
    node: Any = tree
    for part in key.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            # try English fallback before giving up
            node = None
            break
    if node is None or isinstance(node, dict):
        fallback_tree = load(DEFAULT_LANG)
        node = fallback_tree
        for part in key.split("."):
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                return key  # loud fallback: return the key itself
    text = str(node)
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, IndexError):
            pass  # leave placeholders as-is rather than crash
    return text


def supported(code: str) -> bool:
    return (code or "").lower() in SUPPORTED_LANGS
