from database import crud
from services.prompts import build_roleplay_system_prompt

class ContextBuilder:
    @staticmethod
    async def build_messages(user, user_text: str) -> list[dict]:
        """Memory-agnostic context compiler. Assembles persona, user level, and vocab mission."""
        cards = await crud.get_due_cards(user.id, limit=5)
        due = [(c.vocab.word, c.vocab.translation) for c in cards]
        
        system_prompt = build_roleplay_system_prompt(user, due)
        
        msgs = [{"role": "system", "content": system_prompt}]
        for h in await crud.get_chat_history(user.id, limit=10):
            msgs.append({
                "role": "assistant" if h.role == "assistant" else "user",
                "content": h.content,
            })
        msgs.append({"role": "user", "content": user_text})
        return msgs
