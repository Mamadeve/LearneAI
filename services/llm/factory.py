import logging
from services.llm.base import BaseLLMProvider
from services.llm.groq_provider import GroqProvider
from services.llm.gemini_provider import GeminiProvider
from services.llm.openrouter_provider import OpenRouterProvider
from database import crud
from utils.config import get_settings

logger = logging.getLogger(__name__)

CORE_KEYS = ("llm_provider", "llm_model", "groq_api_key", "gemini_api_key", "openrouter_api_key", "stt_provider", "hf_api_token")

class LLMError(Exception):
    pass

async def get_live_config(user_id: int | None = None) -> dict[str, str]:
    """Resolve effective API config: .env -> DB cache -> user overrides."""
    s = get_settings()
    cfg: dict[str, str] = {
        "llm_provider": s.llm_provider,
        "llm_model": s.llm_model,
        "groq_api_key": s.groq_api_key,
        "gemini_api_key": s.gemini_api_key,
        "openrouter_api_key": getattr(s, "openrouter_api_key", ""),
        "stt_provider": s.stt_provider,
        "hf_api_token": s.hf_api_token,
    }
    cfg.update({k: v for k, v in (await crud.get_all_api_config()).items() if k in CORE_KEYS})
    if user_id is not None:
        user = await crud.get_user(user_id)
        if user:
            if user.selected_model_id:
                # Map selected_model_id to provider and model
                provider_map = {
                    "gemini": ("gemini", "gemini-1.5-flash"),
                    "groq": ("groq", "llama-3.1-8b-instant"),
                    "openrouter": ("openrouter", "openai/gpt-4o")
                }
                if user.selected_model_id in provider_map:
                    cfg["llm_provider"], cfg["llm_model"] = provider_map[user.selected_model_id]
                
            if user.api_overrides:
                cfg.update({k: str(v) for k, v in user.api_overrides.items() if k in CORE_KEYS})
    return cfg

class LLMFactory:
    @staticmethod
    def create_provider(provider_name: str, cfg: dict) -> BaseLLMProvider:
        if provider_name == "groq":
            return GroqProvider(api_key=cfg.get("groq_api_key", ""), model=cfg.get("llm_model", "llama-3.1-8b-instant"))
        elif provider_name == "gemini":
            return GeminiProvider(api_key=cfg.get("gemini_api_key", ""), model=cfg.get("llm_model", "gemini-1.5-flash"))
        elif provider_name == "openrouter":
            return OpenRouterProvider(api_key=cfg.get("openrouter_api_key", ""), model=cfg.get("llm_model", "openai/gpt-4o"))
        else:
            # Fallback to free Gemini
            return GeminiProvider(api_key=cfg.get("gemini_api_key", ""), model="gemini-1.5-flash")

async def chat(messages: list[dict], user_id: int | None = None, *, temperature: float = 0.9, max_tokens: int = 400) -> str:
    cfg = await get_live_config(user_id)
    primary_name = cfg.get("llm_provider", "groq")
    
    order = [primary_name, "gemini", "groq"]
    # Deduplicate while preserving order
    seen = set()
    unique_order = [x for x in order if not (x in seen or seen.add(x))]
    
    last_err = None
    for provider_name in unique_order:
        try:
            provider = LLMFactory.create_provider(provider_name, cfg)
            return await provider.generate_chat_response(messages, temperature, max_tokens)
        except Exception as exc:
            last_err = exc
            logger.warning("LLM provider %s failed, trying next: %s", provider_name, exc)
            
    raise LLMError(f"All LLM providers failed. Last error: {last_err}")
    
async def generate_quiz(target_language: str, claimed_level: str, n_questions: int = 5) -> list[dict]:
    """Ask the LLM for a placement quiz; robust JSON parsing included."""
    from services.prompts import build_quiz_generation_prompt
    import json, re

    raw = await chat(
        [{"role": "user", "content": build_quiz_generation_prompt(target_language, claimed_level, n_questions)}],
        temperature=0.8,
        max_tokens=1200,
    )
    raw = re.sub(r"^```(json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
    start, end = raw.find("["), raw.rfind("]")
    if start == -1 or end == -1:
        raise LLMError("Quiz response contained no JSON array")
    questions = json.loads(raw[start : end + 1])
    if not isinstance(questions, list) or not questions:
        raise LLMError("Quiz JSON parsed empty")
    return questions
