"""Groq LLM Provider — httpx-based, OpenAI-compatible chat completions.

Endpoint : POST https://api.groq.com/openai/v1/chat/completions
Auth     : Bearer token via Authorization header
Default  : openai/gpt-oss-20b (with automatic model fallback)
"""
from __future__ import annotations

import logging
import os

import httpx

from services.llm.base import BaseLLMProvider

logger = logging.getLogger(__name__)

# Ordered list of active models on the Groq account.
# The provider will try each one in sequence on retryable HTTP errors.
ACTIVE_MODELS: list[str] = [
    "openai/gpt-oss-20b",
    "qwen/qwen3.8-27b",
    "openai/gpt-oss-120b",
    "groq/compound-mini",
]

# HTTP status codes that trigger an automatic retry with the next model
_RETRYABLE_STATUSES = {400, 404, 429}


class GroqProvider(BaseLLMProvider):
    API_URL = "https://api.groq.com/openai/v1/chat/completions"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
    ):
        self.api_key = (api_key or os.getenv("GROQ_API_KEY", "")).strip()
        self.model = (model or os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")).strip()

    async def generate_chat_response(
        self,
        messages: list[dict],
        temperature: float = 0.9,
        max_tokens: int = 400,
    ) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # Build the trial order: requested model first, then remaining ACTIVE_MODELS
        trial_order: list[str] = [self.model]
        for m in ACTIVE_MODELS:
            if m not in trial_order:
                trial_order.append(m)

        masked_key = f"***{self.api_key[-4:]}" if len(self.api_key) >= 4 else "***?"

        async with httpx.AsyncClient(timeout=60) as client:
            last_status: int | None = None
            last_body: str = ""

            for model_name in trial_order:
                payload = {
                    "model": model_name,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                }

                resp = await client.post(self.API_URL, headers=headers, json=payload)

                if resp.status_code == 200:
                    data = resp.json()
                    choices = data.get("choices", [])
                    if not choices:
                        logger.error("[Groq] model=%s returned no choices: %s", model_name, data)
                        raise Exception(f"Groq API returned empty choices for model {model_name}")
                    return (choices[0].get("message", {}).get("content") or "").strip()

                # Retryable error → log and try the next model
                last_status = resp.status_code
                last_body = resp.text
                if resp.status_code in _RETRYABLE_STATUSES:
                    logger.warning(
                        "[Groq] model=%s returned HTTP %s (retryable) — trying next model. Body: %s (key=%s)",
                        model_name, resp.status_code, last_body, masked_key,
                    )
                    continue

                # Non-retryable error (e.g. 401, 500) → fail immediately
                logger.error(
                    "[Groq] model=%s HTTP %s (non-retryable): %s (key=%s)",
                    model_name, resp.status_code, last_body, masked_key,
                )
                raise Exception(f"Groq API returned HTTP {resp.status_code}")

        # All models exhausted on retryable errors
        logger.error(
            "[Groq] All %d models exhausted. Last HTTP %s: %s (key=%s)",
            len(trial_order), last_status, last_body, masked_key,
        )
        raise Exception(f"Groq API: all models failed (last HTTP {last_status})")
