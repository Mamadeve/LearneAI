from groq import AsyncGroq
from services.llm.base import BaseLLMProvider

class GroqProvider(BaseLLMProvider):
    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    async def generate_chat_response(self, messages: list[dict], temperature: float, max_tokens: int) -> str:
        client = AsyncGroq(api_key=self.api_key, timeout=60)
        resp = await client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return (resp.choices[0].message.content or "").strip()
