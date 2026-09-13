import httpx
from typing import Any
from services.llm.base import BaseLLMProvider

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

class GeminiProvider(BaseLLMProvider):
    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model
        if not self.model.startswith("gemini"):
            self.model = "gemini-1.5-flash"

    async def generate_chat_response(self, messages: list[dict], temperature: float, max_tokens: int) -> str:
        system = " ".join(m["content"] for m in messages if m["role"] == "system")
        contents = [
            {
                "role": "user" if m["role"] in ("user", "system") else "model",
                "parts": [{"text": m["content"]}],
            }
            for m in messages
            if m["role"] != "system"
        ]
        body: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
            
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                f"{GEMINI_BASE}/{self.model}:generateContent?key={self.api_key}",
                json=body,
            )
            r.raise_for_status()
            data = r.json()
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
