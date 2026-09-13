"""Translation — free providers only.

  - "google": deep-translator's GoogleTranslator (keyless, no API key needed)
  - "libre":  LibreTranslate instance via httpx (URL/key from .env)

Used by the "I didn't understand" button in Las o Lus and by learning flows.
"""
from __future__ import annotations

import asyncio
import logging

import httpx

from database import crud
from utils.config import get_settings

logger = logging.getLogger(__name__)

# deep-translator wants full names for a few codes; map defensively.
_CODE_TO_NAME = {
    "fa": "persian", "zh": "chinese (simplified)", "ja": "japanese",
    "ko": "korean", "hi": "hindi", "tr": "turkish", "ru": "russian",
    "de": "german", "es": "spanish", "fr": "french", "ar": "arabic", "en": "english",
}


class TranslationError(Exception):
    pass


async def translate(text: str, target: str, source: str = "auto", user_id: int | None = None) -> str:
    """Translate `text` trying: configured provider -> google -> libre -> mymemory."""
    if not text.strip():
        return ""
    provider = get_settings().translation_provider
    if user_id is not None:
        provider = (await crud.get_api_config("translation_provider", provider)) or provider
    impls = {"google": _google, "gtx": _gtx, "libre": _libre, "mymemory": _mymemory}
    order = [provider] + [p for p in ("gtx", "google", "libre", "mymemory") if p != provider]
    last_err: Exception | None = None
    for name in order:
        try:
            return await impls[name](text, source, target)
        except Exception as exc:
            last_err = exc
            logger.warning("Translation via %s failed: %s", name, exc)
    raise TranslationError(f"All translation providers failed. Last error: {last_err}")


async def _google(text: str, source: str, target: str) -> str:
    def _run() -> str:
        from deep_translator import GoogleTranslator

        return GoogleTranslator(
            source=_norm(source), target=_norm(target)
        ).translate(text)

    result: str | None = None
    for attempt in range(3):  # Google's free endpoint is occasionally flaky
        result = await asyncio.to_thread(_run)
        if result and result.strip():
            break
        await asyncio.sleep(0.5 * (attempt + 1))
    if not result or not result.strip():
        raise TranslationError("Google returned empty translation")
    return str(result).strip()


def _norm(code: str) -> str:
    code = (code or "auto").lower()
    if code in ("auto", "en"):
        return code if code == "auto" else "en"
    return _CODE_TO_NAME.get(code, code)


async def _libre(text: str, source: str, target: str) -> str:
    s = get_settings()
    payload: dict[str, str] = {
        "q": text,
        "source": source if source != "auto" else "auto",
        "target": target,
        "format": "text",
    }
    if s.libretranslate_api_key:
        payload["api_key"] = s.libretranslate_api_key
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(s.libretranslate_url, json=payload)
        r.raise_for_status()
        result = r.json().get("translatedText", "").strip()
    if not result:
        raise TranslationError("LibreTranslate returned empty translation")
    return result


async def _gtx(text: str, source: str, target: str) -> str:
    """Direct keyless Google 'gtx' endpoint — very reliable, no library needed."""
    sl = source if source != "auto" else "auto"
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(
            "https://translate.googleapis.com/translate_a/single",
            params={"client": "gtx", "sl": sl, "tl": target, "dt": "t", "q": text},
        )
        r.raise_for_status()
        data = r.json()
    translated = "".join(seg[0] for seg in (data[0] or []) if seg and seg[0])
    if not translated.strip():
        raise TranslationError("gtx returned empty translation")
    return translated.strip()


async def _mymemory(text: str, source: str, target: str) -> str:
    src = "en" if source in ("", "auto") else source
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(
            "https://api.mymemory.translated.net/get",
            params={"q": text, "langpair": f"{src}|{target}"},
        )
        r.raise_for_status()
        result = r.json().get("responseData", {}).get("translatedText", "").strip()
    if not result or result.upper().startswith("MYMEMORY WARNING"):
        raise TranslationError("MyMemory returned no usable translation")
    return result
