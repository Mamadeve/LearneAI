"""Google Gemini LLM Provider — httpx-based, REST generateContent.

Endpoint : POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent
Auth     : x-goog-api-key header (keeps URLs clean, prevents key leaking in logs)
Default  : gemini-1.5-flash
"""
from __future__ import annotations

import logging
from typing import Any

import httpx
from services.llm.base import BaseLLMProvider

logger = logging.getLogger(__name__)

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiProvider(BaseLLMProvider):
    def __init__(self, api_key: str, model: str = "gemini-1.5-flash"):
        self.api_key = api_key
        self.model = model if model.startswith("gemini") else "gemini-1.5-flash"

    async def generate_chat_response(
        self,
        messages: list[dict],
        temperature: float = 0.9,
        max_tokens: int = 400,
    ) -> str:
        # Extract system instruction from messages
        system_parts = [m["content"] for m in messages if m["role"] == "system"]
        system_text = " ".join(system_parts)

        # Build Gemini-format contents (skip system messages — they go into systemInstruction)
        contents: list[dict[str, Any]] = []
        for m in messages:
            if m["role"] == "system":
                continue
            role = "user" if m["role"] == "user" else "model"
            contents.append({"role": role, "parts": [{"text": m["content"]}]})

        # Ensure there is at least one content entry
        if not contents:
            contents.append({"role": "user", "parts": [{"text": "Hello"}]})

        body: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        if system_text:
            body["systemInstruction"] = {"parts": [{"text": system_text}]}

        url = f"{GEMINI_BASE}/{self.model}:generateContent"
        headers = {
            "x-goog-api-key": self.api_key,
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, headers=headers, json=body)

            if resp.status_code != 200:
                logger.error(
                    "[Gemini] HTTP %s: %s (key=***%s)",
                    resp.status_code,
                    resp.text[:500],
                    self.api_key[-4:] if len(self.api_key) >= 4 else "????",
                )
                raise Exception(f"Gemini API returned HTTP {resp.status_code}")

            data = resp.json()

        candidates = data.get("candidates", [])
        if not candidates:
            logger.error("[Gemini] Response contained no candidates: %s", data)
            raise Exception("Gemini API returned empty candidates")

        try:
            return candidates[0]["content"]["parts"][0]["text"].strip()
        except (KeyError, IndexError, TypeError) as e:
            logger.error("[Gemini] Failed to parse response structure: %s | raw: %s", e, data)
            raise Exception("Gemini API returned unparseable response")
