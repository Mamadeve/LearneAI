from abc import ABC, abstractmethod

class BaseLLMProvider(ABC):
    @abstractmethod
    async def generate_chat_response(self, messages: list[dict], temperature: float, max_tokens: int) -> str:
        """Generate a response given the conversation history and parameters."""
        pass
