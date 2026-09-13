import httpx
from services.llm.base import BaseLLMProvider

class OpenRouterProvider(BaseLLMProvider):
    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    async def generate_chat_response(self, messages: list[dict], temperature: float, max_tokens: int) -> str:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens
                }
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip()
