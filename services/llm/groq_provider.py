import os
import asyncio
import aiohttp
import logging
from services.llm.base import BaseLLMProvider

logger = logging.getLogger(__name__)

class GroqProvider(BaseLLMProvider):
    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model
        self.api_url = "https://api.groq.com/openai/v1/chat/completions"

    async def generate_chat_response(self, messages: list[dict], temperature: float, max_tokens: int) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.api_url, headers=headers, json=payload, timeout=60) as response:
                    response.raise_for_status()
                    data = await response.json()
                    
                    if "choices" in data and len(data["choices"]) > 0:
                        return (data["choices"][0].get("message", {}).get("content") or "").strip()
                    else:
                        logger.error("Invalid response structure from Groq API: %s", data)
                        return "I'm having trouble processing that right now. (Invalid API response)"
                        
        except asyncio.TimeoutError:
            logger.error("Groq API request timed out.")
            raise Exception("Groq API Timeout")
        except aiohttp.ClientResponseError as e:
            logger.error(f"Groq API HTTP Error {e.status}: (API Key masked)")
            raise Exception(f"Groq API Error {e.status}")
        except aiohttp.ClientError as e:
            logger.error(f"Groq API Client Error: (API Key masked)")
            raise Exception(f"Groq API Error")
        except Exception as e:
            logger.error(f"Unexpected error communicating with Groq API: (API Key masked)")
            raise Exception("Unexpected Groq Error")
