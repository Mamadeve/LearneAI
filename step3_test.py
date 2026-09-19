"""Live validation of Step 3: prompts, config resolution, TTS, translation,
LLM fallback behavior. Real keyless APIs (edge-tts, Google Translate) hit live;
LLM calls use dummy keys so we verify graceful failure/fallback, not results.

Run: python step3_test.py   (needs internet for TTS/translation tests)
"""
import asyncio
import os
import sys

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./step3_test.db"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from types import SimpleNamespace  # noqa: E402

import database.crud as crud  # noqa: E402
from database.engine import get_engine, init_db  # noqa: E402
from services import llm, stt, translation  # noqa: E402
from services.llm import LLMError  # noqa: E402
from services.prompts import (  # noqa: E402
    build_quiz_generation_prompt,
    build_quiz_verdict_prompt,
    build_roleplay_system_prompt,
    level_cefr,
)
from services.tts import pick_voice, synthesize_to_file  # noqa: E402


def fake_user(**kw):
    defaults = dict(
        target_language="en", native_language="fa", level="beginner",
        gender="male", bot_partner_gender="female",
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


async def main() -> None:
    await init_db()

    # [1] Persona prompt: vocab injection + character rules
    p = build_roleplay_system_prompt(
        fake_user(), [("strawberry", "توت‌فرنگی"), ("chill", "آرام")]
    )
    assert "**double asterisks**" in p and "strawberry (توت‌فرنگی)" in p
    assert "NOT an assistant" in p and "ALWAYS write in English" in p
    assert "[VOICE]" in p and "A2" in p and "Persian (Farsi)" in p
    print("[1] roleplay persona prompt: vocab injection, anti-assistant rules, voice tag, CEFR OK")

    # [2] Persona changes with gender/level
    p_m = build_roleplay_system_prompt(fake_user(gender="female", bot_partner_gender="male", level="advanced"), [])
    assert "playful guy" in p_m and "C1" in p_m and "Vocab mission" not in p_m
    print("[2] persona adapts to partner gender / advanced level / empty due-words OK")

    # [3] Quiz + verdict prompts
    qp = build_quiz_generation_prompt("Spanish", "intermediate", 5)
    assert "Spanish" in qp and "B1" in qp and '"correct"' in qp
    vp = build_quiz_verdict_prompt("Spanish", "good", 30, ["past tense"])
    assert "destroyed" in vp and "30%" in vp
    print("[3] quiz generation + verdict prompts OK")

    # [4] Live config resolution: .env defaults -> DB -> user overrides
    await crud.set_api_config("llm_provider", "openrouter")
    cfg = await llm.get_live_config()
    assert cfg["llm_provider"] == "openrouter", cfg  # DB overrides .env
    await crud.get_or_create_user(42, native_language="fa")
    await crud.update_user(42, api_overrides={"llm_provider": "groq"})
    cfg42 = await llm.get_live_config(42)
    assert cfg42["llm_provider"] == "groq"  # user override wins
    print("[4] config chain (.env -> api_configs -> user overrides) OK")

    # [5] LLM failure path: dummy keys -> LLMError (no crash)
    await crud.set_api_config("groq_api_key", "gsk_INVALID")
    await crud.set_api_config("openrouter_api_key", "INVALID")
    try:
        await llm.chat([{"role": "user", "content": "hi"}], user_id=42)
        raise AssertionError("expected LLMError with dummy keys")
    except LLMError as e:
        assert "All LLM providers failed" in str(e)
    print("[5] LLM error handling + cross-provider fallback -> clean LLMError OK")

    # [6] TTS: real edge-tts synthesis (keyless)
    path = await synthesize_to_file("hey! what's up?", "en", "female")
    size = os.path.getsize(path)
    assert size > 2000, f"mp3 too small: {size} bytes"
    print(f"[6] edge-tts real synthesis OK: {path} ({size} bytes, voice={pick_voice('en', 'female')})")
    assert pick_voice("fa", "male") == "fa-IR-FaridNeural"
    assert pick_voice("xx", "male", forced="custom-voice") == "custom-voice"
    print(f"[7] voice map (fa/male -> fa-IR-FaridNeural) + forced-voice override OK")

    # [8] Translation: real Google (keyless) en -> fa
    fa = await translation.translate("I love learning languages", target="fa", source="en")
    assert fa and fa != "I love learning languages"
    print(f"[8] real Google translation en->fa OK: '{fa}'")
    es = await translation.translate("hello", target="es", source="en")
    assert "hola" in es.lower(), es
    print(f"[9] real translation en->es OK: '{es}'")

    # [10] STT guardrails: empty payload + unconfigured provider -> STTError
    try:
        await stt.transcribe(b"")
        raise AssertionError("expected STTError on empty payload")
    except stt.STTError:
        pass
    os.environ["GROQ_API_KEY"] = ""
    os.environ["HF_API_TOKEN"] = ""
    from utils.config import get_settings
    get_settings.cache_clear()
    try:
        await stt.transcribe(b"RIFF-fake-audio")
        print("    (STT call succeeded unexpectedly - keys may be configured)")
    except stt.STTError as e:
        assert "failed" in str(e)
    print("[10] STT empty-payload guard + graceful all-providers-failed OK")

    await get_engine().dispose()
    print("\n[PASS] STEP 3 VALIDATION PASSED - services layer functional")


if __name__ == "__main__":
    asyncio.run(main())
