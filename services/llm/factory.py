"""LLM Factory — provider resolution, fallback chain, and unified ask_llm interface.

Public API consumed by the rest of the application:
  - ask_llm(messages, system_prompt=None, ...) -> str
  - chat(messages, ...) -> str             (backward compat alias)
  - generate_quiz(...) -> list[dict]
  - get_live_config(user_id) -> dict
"""
from __future__ import annotations

import json
import logging
import re

from database import crud
from services.llm.base import BaseLLMProvider
from services.llm.gemini_provider import GeminiProvider
from services.llm.groq_provider import GroqProvider
from services.llm.openrouter_provider import OpenRouterProvider
from utils.config import get_settings

logger = logging.getLogger(__name__)

CORE_KEYS = (
    "llm_provider", "llm_model",
    "groq_api_key", "gemini_api_key", "openrouter_api_key",
    "stt_provider", "hf_api_token",
)

# Deprecated Groq model names that will 404
_DEPRECATED_GROQ_MODELS = {
    "llama3-8b-8192",
    "llama3-70b-8192",
    "mixtral-8x7b-32768",
    "llama-3.1-8b-instant",
}


class LLMError(Exception):
    pass


# ---------------------------------------------------------------------------
# Config Resolution
# ---------------------------------------------------------------------------

async def get_live_config(user_id: int | None = None) -> dict[str, str]:
    """Resolve effective API config: .env -> DB cache -> user overrides."""
    s = get_settings()
    cfg: dict[str, str] = {
        "llm_provider": s.llm_provider,
        "llm_model": s.llm_model,
        "groq_api_key": s.groq_api_key,
        "gemini_api_key": s.gemini_api_key,
        "openrouter_api_key": getattr(s, "openrouter_api_key", ""),
        "stt_provider": s.stt_provider,
        "hf_api_token": s.hf_api_token,
    }
    cfg.update({k: v for k, v in (await crud.get_all_api_config()).items() if k in CORE_KEYS})

    if user_id is not None:
        user = await crud.get_user(user_id)
        if user:
            if user.selected_model_id:
                provider_map = {
                    "gemini": ("gemini", "gemini-1.5-flash-latest"),
                    "groq": ("groq", "llama-3.1-8b-instant"),
                    "openrouter": ("openrouter", "openai/gpt-4o"),
                }
                if user.selected_model_id in provider_map:
                    cfg["llm_provider"], cfg["llm_model"] = provider_map[user.selected_model_id]

            if user.api_overrides:
                cfg.update({k: str(v) for k, v in user.api_overrides.items() if k in CORE_KEYS})

    # Auto-fix deprecated Groq model names
    if cfg.get("llm_model") in _DEPRECATED_GROQ_MODELS:
        logger.warning("Deprecated Groq model '%s' replaced with 'llama-3.1-8b-instant'", cfg["llm_model"])
        cfg["llm_model"] = "llama-3.1-8b-instant"

    return cfg


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

class LLMFactory:
    @staticmethod
    def create_provider(provider_name: str, cfg: dict) -> BaseLLMProvider:
        if provider_name == "groq":
            return GroqProvider(
                api_key=cfg.get("groq_api_key", ""),
                model=cfg.get("llm_model", "llama-3.1-8b-instant"),
            )
        elif provider_name == "gemini":
            return GeminiProvider(
                api_key=cfg.get("gemini_api_key", ""),
                model=cfg.get("llm_model", "gemini-1.5-flash-latest"),
            )
        elif provider_name == "openrouter":
            return OpenRouterProvider(
                api_key=cfg.get("openrouter_api_key", ""),
                model=cfg.get("llm_model", "openai/gpt-4o"),
            )
        else:
            # Unknown provider → fall back to Gemini (free tier)
            return GeminiProvider(
                api_key=cfg.get("gemini_api_key", ""),
                model="gemini-1.5-flash-latest",
            )


# ---------------------------------------------------------------------------
# Unified Public Interface
# ---------------------------------------------------------------------------

async def ask_llm(
    messages: list[dict],
    system_prompt: str | None = None,
    *,
    user_id: int | None = None,
    temperature: float = 0.9,
    max_tokens: int = 400,
) -> str:
    """Unified entry point for ALL LLM calls in the application.

    - Prepends system_prompt as a system message if provided.
    - Tries the user's primary provider first, then falls back through the chain.
    - Returns a friendly error string (never crashes the handler) if ALL providers fail.
    """
    if system_prompt:
        messages = [{"role": "system", "content": system_prompt}] + messages

    cfg = await get_live_config(user_id)
    primary = cfg.get("llm_provider", "groq")

    # Build deduplicated fallback order: primary → groq → gemini
    order: list[str] = []
    for name in [primary, "groq", "gemini"]:
        if name not in order:
            order.append(name)

    last_err: Exception | None = None
    for provider_name in order:
        try:
            provider = LLMFactory.create_provider(provider_name, cfg)
            result = await provider.generate_chat_response(messages, temperature, max_tokens)
            if result:
                return result
        except Exception as exc:
            last_err = exc
            logger.warning("[LLM Fallback] %s failed: %s — trying next provider", provider_name, exc)

    # All providers failed — return a user-friendly message instead of crashing
    logger.error("ALL LLM providers failed. Last error: %s", last_err)
    return "Sorry, I'm having trouble thinking right now 😵‍💫 Please try again in a moment!"


# Backward-compatible alias so existing `llm.chat(...)` calls keep working
async def chat(
    messages: list[dict],
    user_id: int | None = None,
    *,
    temperature: float = 0.9,
    max_tokens: int = 400,
) -> str:
    return await ask_llm(messages, user_id=user_id, temperature=temperature, max_tokens=max_tokens)


async def generate_quiz(target_language: str, claimed_level: str, n_questions: int = 5) -> list[dict]:
    """Ask the LLM for a placement quiz; robust JSON parsing included."""
    from services.prompts import build_quiz_generation_prompt

    raw = await ask_llm(
        [{"role": "user", "content": build_quiz_generation_prompt(target_language, claimed_level, n_questions)}],
        temperature=0.8,
        max_tokens=1200,
    )
    raw = re.sub(r"^```(json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
    start, end = raw.find("["), raw.rfind("]")
    if start == -1 or end == -1:
        raise LLMError("Quiz response contained no JSON array")
    questions = json.loads(raw[start : end + 1])
    if not isinstance(questions, list) or not questions:
        raise LLMError("Quiz JSON parsed empty")
    return questions
