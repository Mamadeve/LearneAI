import asyncio
import aiohttp
import logging
from typing import Any
from services.llm.base import BaseLLMProvider

logger = logging.getLogger(__name__)

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
            
        url = f"{GEMINI_BASE}/{self.model}:generateContent?key={self.api_key}"
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=body, timeout=60) as response:
                    response.raise_for_status()
                    data = await response.json()
                    
                    if "candidates" in data and len(data["candidates"]) > 0:
                        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
                    else:
                        logger.error("Invalid response structure from Gemini API: %s", data)
                        return "I'm having trouble processing that right now. (Invalid API response)"
                        
        except asyncio.TimeoutError:
            logger.error("Gemini API request timed out.")
            raise Exception("Gemini API Timeout")
        except aiohttp.ClientError as e:
            logger.error(f"Gemini API Client Error: {e}")
            raise Exception(f"Gemini API Error: {e}")
        except Exception as e:
            logger.error(f"Unexpected error communicating with Gemini API: {e}")
            raise
