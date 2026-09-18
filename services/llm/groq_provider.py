"""Groq LLM Provider — httpx-based, OpenAI-compatible chat completions.

Endpoint : POST https://api.groq.com/openai/v1/chat/completions
Auth     : Bearer token via Authorization header
Default  : llama-3.3-70b-versatile
"""
from __future__ import annotations

import logging
import httpx
from services.llm.base import BaseLLMProvider

logger = logging.getLogger(__name__)


class GroqProvider(BaseLLMProvider):
    API_URL = "https://api.groq.com/openai/v1/chat/completions"

    def __init__(self, api_key: str, model: str = "llama-3.3-70b-versatile"):
        self.api_key = api_key
        self.model = model

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
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(self.API_URL, headers=headers, json=payload)

            if resp.status_code != 200:
                # Log the FULL error body so we can debug — but mask the key
                logger.error(
                    "[Groq] HTTP %s: %s (key=***%s)",
                    resp.status_code,
                    resp.text[:500],
                    self.api_key[-4:] if len(self.api_key) >= 4 else "????",
                )
                raise Exception(f"Groq API returned HTTP {resp.status_code}")

            data = resp.json()

        choices = data.get("choices", [])
        if not choices:
            logger.error("[Groq] Response contained no choices: %s", data)
            raise Exception("Groq API returned empty choices")

        return (choices[0].get("message", {}).get("content") or "").strip()
