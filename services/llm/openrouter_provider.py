import asyncio
import aiohttp
import logging
from services.llm.base import BaseLLMProvider

logger = logging.getLogger(__name__)

class OpenRouterProvider(BaseLLMProvider):
    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    async def generate_chat_response(self, messages: list[dict], temperature: float, max_tokens: int) -> str:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=60
                ) as r:
                    r.raise_for_status()
                    data = await r.json()
                    
                    if "choices" in data and len(data["choices"]) > 0:
                        return (data["choices"][0].get("message", {}).get("content") or "").strip()
                    else:
                        logger.error("Invalid response structure from OpenRouter API: %s", data)
                        return "I'm having trouble processing that right now. (Invalid API response)"
                        
        except asyncio.TimeoutError:
            logger.error("OpenRouter API request timed out.")
            raise Exception("OpenRouter API Timeout")
        except aiohttp.ClientResponseError as e:
            logger.error(f"OpenRouter API HTTP Error {e.status}: (API Key masked)")
            raise Exception(f"OpenRouter API Error {e.status}")
        except aiohttp.ClientError as e:
            logger.error(f"OpenRouter API Client Error: (API Key masked)")
            raise Exception(f"OpenRouter API Error")
        except Exception as e:
            logger.error(f"Unexpected error communicating with OpenRouter API: (API Key masked)")
            raise Exception("Unexpected OpenRouter Error")
