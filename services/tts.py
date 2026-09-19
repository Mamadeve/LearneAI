"""TTS via edge-tts (free, keyless Microsoft neural voices).

Voice is picked from the TARGET language + the bot partner's user_gender so the
"Las o Lus" partner sounds consistent. Voice name can be forced via .env
(TTS_DEFAULT_VOICE) or the admin panel (api_configs key "tts_default_voice").
"""
from __future__ import annotations

import logging
import os
import uuid

import edge_tts

logger = logging.getLogger(__name__)

VOICE_DIR = "voice_cache"

VOICE_BY_LANGUAGE: dict[str, dict[str, str]] = {
    "en": {"female": "en-US-JennyNeural", "male": "en-US-GuyNeural"},
    "fa": {"female": "fa-IR-DilaraNeural", "male": "fa-IR-FaridNeural"},
    "es": {"female": "es-ES-ElviraNeural", "male": "es-ES-AlvaroNeural"},
    "fr": {"female": "fr-FR-DeniseNeural", "male": "fr-FR-HenriNeural"},
    "de": {"female": "de-DE-KatjaNeural", "male": "de-DE-ConradNeural"},
    "ar": {"female": "ar-SA-ZariyahNeural", "male": "ar-SA-HamedNeural"},
    "tr": {"female": "tr-TR-EmelNeural", "male": "tr-TR-AhmetNeural"},
    "ru": {"female": "ru-RU-SvetlanaNeural", "male": "ru-RU-DmitryNeural"},
    "zh": {"female": "zh-CN-XiaoxiaoNeural", "male": "zh-CN-YunxiNeural"},
    "ja": {"female": "ja-JP-NanamiNeural", "male": "ja-JP-KeitaNeural"},
    "ko": {"female": "ko-KR-SoonBokNeural", "male": "ko-KR-InJoonNeural"},
    "hi": {"female": "hi-IN-SwaraNeural", "male": "hi-IN-MadhurNeural"},
}
DEFAULT_VOICE = "en-US-JennyNeural"


def pick_voice(language: str, partner_gender: str = "female", forced: str = "") -> str:
    if forced:
        return forced
    table = VOICE_BY_LANGUAGE.get(language, VOICE_BY_LANGUAGE["en"])
    return table.get(partner_gender.lower(), table["female"])


async def synthesize_to_file(
    text: str,
    language: str,
    partner_gender: str = "female",
    *,
    voice: str = "",
    out_dir: str = VOICE_DIR,
) -> str:
    """Generate an MP3 and return its absolute path."""
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.abspath(os.path.join(out_dir, f"{uuid.uuid4().hex}.mp3"))
    chosen = pick_voice(language, partner_gender, voice)
    comm = edge_tts.Communicate(text, chosen)
    await comm.save(path)
    logger.debug("TTS: %s chars -> %s (%s)", len(text), path, chosen)
    return path


async def synthesize_to_bytes(
    text: str,
    language: str,
    partner_gender: str = "female",
    *,
    voice: str = "",
) -> bytes:
    """Generate an MP3 in memory (handy for sending via aiogram FSInputFile-free)."""
    chosen = pick_voice(language, partner_gender, voice)
    comm = edge_tts.Communicate(text, chosen)
    chunks: list[bytes] = []
    async for chunk in comm.stream():
        if chunk["type"] == "audio":
            chunks.append(chunk["data"])
    return b"".join(chunks)
