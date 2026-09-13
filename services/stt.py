"""STT (speech-to-text) for voice notes.

Providers:
  - "groq": Whisper hosted on Groq (recommended — same key as LLM)
  - "hf":   Hugging Face Inference API (openai/whisper-large-v3)

Telegram voice notes are OGG/Opus — both providers accept them directly.
Provider/model/key come from the live config (.env -> api_configs -> user).
"""
from __future__ import annotations

import logging

import httpx
from groq import AsyncGroq

from services.llm import get_live_config
from utils.config import get_settings

logger = logging.getLogger(__name__)

HF_BASE = "https://api-inference.huggingface.co/models"
HF_DEFAULT_MODEL = "openai/whisper-large-v3"


class STTError(Exception):
    pass


async def transcribe(audio_bytes: bytes, filename: str = "voice_note.ogg", user_id: int | None = None) -> str:
    """Transcribe a voice note to text using the active STT provider."""
    if not audio_bytes:
        raise STTError("Empty audio payload")
    cfg = await _stt_config(user_id)
    provider = cfg["stt_provider"]
    # NOTE: any failure (bad key, HTTP error, empty transcript) triggers the
    # cross-provider fallback below — config errors are not fatal because the
    # other provider may be fully configured.
    try:
        if provider == "hf":
            return await _transcribe_hf(cfg, audio_bytes)
        return await _transcribe_groq(cfg, audio_bytes, filename)
    except Exception as exc:
        fallback = "groq" if provider == "hf" else "hf"
        logger.warning("STT provider %s failed (%s); trying %s", provider, exc, fallback)
        try:
            cfg = dict(cfg, stt_provider=fallback)
            if fallback == "hf":
                return await _transcribe_hf(cfg, audio_bytes)
            return await _transcribe_groq(cfg, audio_bytes, filename)
        except Exception as exc2:
            raise STTError(f"All STT providers failed: {exc2}") from exc2


async def _stt_config(user_id: int | None) -> dict[str, str]:
    cfg = await get_live_config(user_id) if user_id else {}
    s = get_settings()
    return {
        "stt_provider": cfg.get("stt_provider") or s.stt_provider,
        "groq_api_key": cfg.get("groq_api_key") or s.groq_api_key,
        "hf_api_token": cfg.get("hf_api_token") or s.hf_api_token,
    }


async def _transcribe_groq(cfg: dict[str, str], audio_bytes: bytes, filename: str) -> str:
    key = cfg.get("groq_api_key")
    if not key:
        raise STTError("groq_api_key not configured")
    model = get_settings().stt_model or "whisper-large-v3"
    client = AsyncGroq(api_key=key, timeout=120)
    resp = await client.audio.transcriptions.create(
        model=model,
        file=(filename, audio_bytes),
        response_format="text",
    )
    text = (resp if isinstance(resp, str) else resp.text).strip()
    if not text:
        raise STTError("Groq returned empty transcript")
    return text


async def _transcribe_hf(cfg: dict[str, str], audio_bytes: bytes) -> str:
    token = cfg.get("hf_api_token")
    if not token:
        raise STTError("hf_api_token not configured")
    model = HF_DEFAULT_MODEL
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            f"{HF_BASE}/{model}",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/octet-stream"},
            content=audio_bytes,
        )
        r.raise_for_status()
        text = r.json().get("text", "").strip()
    if not text:
        raise STTError("HF returned empty transcript")
    return text
