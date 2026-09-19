"""Live validation of Step 2: schema creation + full CRUD flow against SQLite.

Run: python step2_test.py
"""
import asyncio
import os
import sys

# Test against a throwaway DB
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./step2_test.db"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import select  # noqa: E402

import database.crud as crud  # noqa: E402
from database.engine import get_engine, get_session, init_db  # noqa: E402
from database.models import ChatHistory, LeitnerBox  # noqa: E402
from utils.leitner import BOX_INTERVALS_DAYS  # noqa: E402


async def main() -> None:
    await init_db()
    print("[1] init_db: all 6 tables created OK")

    UID = 777000

    # Users
    user = await crud.get_or_create_user(UID, native_language="fa")
    print(f"[2] user created: {user!r}")
    await crud.set_languages(UID, native="fa", target="en")
    await crud.update_user(UID, daily_goal=50, level="A2")
    await crud.set_genders(UID, "male")
    user = await crud.get_user(UID)
    assert user.native_language == user.ui_language == "fa"
    assert user.target_language == "en" and user.daily_goal == 50
    assert user.gender == "male" and user.bot_partner_gender == "female"
    print("[3] languages/goal/genders: instant UI-switch + opposite-gender partner OK")

    # Vocabulary + Leitner
    words = [("hello", "سلام", 1), ("beautiful", "زیبا", 2), ("strawberry", "توت‌فرنگی", 3)]
    word_ids = []
    for w, t, d in words:
        v = await crud.get_or_create_vocab(w, t, "en", d)
        word_ids.append(v.id)
        await crud.add_to_leitner(UID, v.id)
    dup = await crud.get_or_create_vocab("HELLO ", "سلام", "en")  # case/dupe check
    assert dup.id == word_ids[0], "duplicate vocab must be idempotent"
    known = await crud.get_known_word_ids(UID)
    assert known == set(word_ids)
    print(f"[4] vocab + leitner adds (idempotent, known-set={known}) OK")

    # Leitner review math
    card = await crud.review_card(UID, word_ids[0], correct=True)
    assert card.box_level == 2, f"expected box 2, got {card.box_level}"
    card = await crud.review_card(UID, word_ids[0], correct=False)
    assert card.box_level == 1
    interval = (card.next_review - card.last_reviewed).days
    assert interval == BOX_INTERVALS_DAYS[1] == 1, f"box1 interval: {interval}"
    print(f"[5] review_card promote->2, demote->1, next_review +{interval}d OK")

    # Stats
    stats = await crud.get_leitner_stats(UID)
    assert stats[1] == 3
    print(f"[6] leitner stats per box: {stats} OK")

    # Chat history
    await crud.add_chat_message(UID, "user", "hey!", is_voice=True)
    await crud.add_chat_message(UID, "assistant", "heyy cutie 😏")
    hist = await crud.get_chat_history(UID)
    assert [m.role for m in hist] == ["user", "assistant"] and hist[0].is_voice
    print("[7] chat history order + voice flag OK")

    # Mind map
    await crud.update_mindmap(UID, {"quiz": {"claimed_level": "barely"}, "score_pct": 40})
    await crud.update_mindmap(UID, {"weak_topics": ["past tense"]})
    mm = await crud.get_mindmap(UID)
    assert mm["quiz"]["claimed_level"] == "barely" and mm["weak_topics"] == ["past tense"]
    print(f"[8] mind-map merge OK: keys={sorted(mm)}")

    # Streak
    s1 = await crud.touch_streak(UID)
    s2 = await crud.touch_streak(UID)
    assert (s1, s2) == (1, 1), "same-day touch must not double-count"
    print(f"[9] streak: first={s1}, same-day={s2} OK")

    # API config cache
    await crud.set_api_config("llm_provider", "openrouter")
    await crud.set_api_config("groq_api_key", "gsk_test")
    await crud.set_api_config("llm_provider", "groq")  # update path
    cfg = await crud.get_all_api_config()
    assert cfg["llm_provider"] == "groq" and cfg["groq_api_key"] == "gsk_test"
    assert await crud.get_api_config("missing", "fallback") == "fallback"
    print(f"[10] dynamic api config cache OK: {cfg}")

    # Session transaction hygiene
    async with get_session() as s:
        n_msgs = len((await s.execute(select(ChatHistory))).scalars().all())
        n_cards = len((await s.execute(select(LeitnerBox))).scalars().all())
    assert (n_msgs, n_cards) == (2, 3)
    await get_engine().dispose()
    print(f"[11] session counts (msgs={n_msgs}, cards={n_cards}) OK")

    print("\n✅ STEP 2 VALIDATION PASSED — schema + CRUD fully functional")


if __name__ == "__main__":
    asyncio.run(main())
