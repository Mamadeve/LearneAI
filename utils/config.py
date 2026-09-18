"""Typed application settings, loaded from .env (pydantic-settings).

Everything under the DYNAMIC API section of .env is only the *initial*
value — the admin panel (Step 5) can override these at runtime via the
`api_configs` DB table (see database/models.py::ApiConfig).
"""
from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---------- Bot Core ----------
    bot_token: str = ""
    admin_ids: str = ""  # comma-separated telegram IDs

    # ---------- HF Spaces / Webhook ----------
    app_url: str = ""
    enable_anti_sleep: bool = True

    # ---------- Database ----------
    database_url: str = "sqlite+aiosqlite:///./learneai.db"

    # ---------- LLM ----------
    llm_provider: str = "groq"  # "groq" | "gemini"
    llm_model: str = "gemma2-9b-it"
    groq_api_key: str = ""
    gemini_api_key: str = ""

    # ---------- STT ----------
    stt_provider: str = "groq"  # "groq" | "hf"
    stt_model: str = "whisper-large-v3"
    hf_api_token: str = ""

    # ---------- TTS ----------
    tts_provider: str = "edge"
    tts_default_voice: str = ""  # empty = auto-pick per target language

    # ---------- Translation ----------
    translation_provider: str = "google"  # "google" | "libre"
    libretranslate_url: str = "https://libretranslate.com/translate"
    libretranslate_api_key: str = ""

    # ---------- Helpers ----------
    @property
    def admin_id_list(self) -> List[int]:
        return [int(x) for x in self.admin_ids.replace(" ", "").split(",") if x.strip().isdigit()]

    def is_admin(self, telegram_id: int) -> bool:
        return telegram_id in self.admin_id_list


@lru_cache
def get_settings() -> Settings:
    """Cached singleton so .env is parsed exactly once per process."""
    return Settings()
