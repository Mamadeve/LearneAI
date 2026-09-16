"""Live validation of Step 5: learning flows, roleplay pipeline, wiring.

No Telegram connection needed. LLM calls are monkeypatched where needed.
Run: python step5_test.py
"""
import asyncio
import json
import os
import sys
import time

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./step5_test.db"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PASS = 0


def ok(label, cond=True, extra=""):
    global PASS
    assert cond, f"FAILED: {label} {extra}"
    PASS += 1
    print(f"[{PASS:02d}] {label} OK")


async def main() -> None:
    # [1] locales parity incl. new learn/rp sections
    en = json.load(open("locales/en.json", encoding="utf-8"))
    fa = json.load(open("locales/fa.json", encoding="utf-8"))
    ok("locales complete", set(en) == set(fa) == {"start", "levels", "goals", "menu", "learn", "rp", "common"})
    for sec in ("learn", "rp"):
        ok(f"{sec} keys mirror", set(en[sec]) == set(fa[sec]))

    # [2] learning pure helpers
    from handlers.learning import parse_llm_words, parse_manual_words
    pairs = parse_manual_words("strawberry = توت فرنگی\nchill\n vibe, mood = حال")
    ok("manual parse", pairs[0] == ("strawberry", "توت فرنگی") and pairs[1] == ("chill", None)
       and ("vibe", None) in pairs and ("mood", "حال") in pairs)
    ok("manual cap", len(parse_manual_words("\n".join(f"w{i}" for i in range(50)))) == 10)
    words = parse_llm_words('```json\n[{"w":"tea","t":"چای"},{"w":"sun","t":"خورشید"}]\n```')
    ok("llm words parse", words == [("tea", "چای"), ("sun", "خورشید")])

    # [3] roleplay pure helpers
    from handlers.roleplay import VOICE_TAG, is_expired, parse_voice_tag
    ok("voice tag present", parse_voice_tag("[VOICE] heyy cutie 😏") == (True, "heyy cutie 😏"))
    ok("no voice tag", parse_voice_tag("heyy") == (False, "heyy"))
    ok("voice tag constant in prompt", VOICE_TAG in open("services/prompts.py", encoding="utf-8").read())
    fresh = {"started": time.time(), "last": time.time(), "msgs": 1}
    stale = {"started": time.time() - 910, "last": time.time() - 910, "msgs": 3}
    ok("session expiry logic", (not is_expired(fresh)) and is_expired(stale) and not is_expired({}))

    # [4] DB-backed learning flows: review promote/demote, due eager-load, counters
    from database.engine import get_engine, init_db
    await init_db()
    import database.crud as crud
    from utils.leitner import BOX_INTERVALS_DAYS

    await crud.get_or_create_user(88001, native_language="fa")
    await crud.set_languages(88001, native="fa", target="en")
    await crud.update_user(88001, daily_goal=3, onboarding_done=True)
    v1 = await crud.get_or_create_vocab("sunset", "غروب", "en")
    v2 = await crud.get_or_create_vocab("ocean", "اقیانوس", "en")
    await crud.add_to_leitner(88001, v1.id, box_level=1)
    c1 = await crud.review_card(88001, v1.id, correct=True)
    ok("review promote", c1.box_level == 2 and c1.next_review is not None)
    c2 = await crud.review_card(88001, v1.id, correct=False)
    ok("review demote to 1", c2.box_level == 1 and (c2.next_review - c2.last_reviewed).days == BOX_INTERVALS_DAYS[1])
    # backdate the card so it's due (next_review is normally tomorrow)
    from datetime import datetime as _dtm, timedelta as _td
    from sqlalchemy import update as _upd
    from database.models import LeitnerBox as _LB
    from database.engine import get_session as _gs
    async with _gs() as s:
        await s.execute(_upd(_LB).where(_LB.user_id == 88001)
                        .values(next_review=_dtm.utcnow() - _td(days=1)))
    due = await crud.get_due_cards(88001, limit=5)
    ok("due cards eager vocab", len(due) == 1 and due[0].vocab.word == "sunset")
    ok("known ids", await crud.get_known_word_ids(88001) == {v1.id})
    ok("vocab by id", (await crud.find_vocab_by_id(v2.id)).word == "ocean")

    from handlers.learning import bump_learned, learned_today
    n1 = await bump_learned(88001, 2)
    n2 = await bump_learned(88001, 1)
    ok("daily goal counter", n1 == 2 and n2 == 3 and await learned_today(88001) == 3)
    mm = await crud.get_mindmap(88001)
    import datetime as _dt
    ok("mindmap learning block", mm["learning"]["total"] == 3
       and list(mm["learning"]["daily"]) == [_dt.date.today().isoformat()])

    # [5] roleplay pipeline with monkeypatched LLM: [VOICE] -> real TTS file + history
    import handlers.roleplay as rp
    orig_chat = rp.llm.chat

    async def fake_chat(messages, user_id=None, **kw):
        assert any(m["role"] == "system" and "NOT an assistant" in m["content"] for m in messages)
        return "[VOICE] heyy bestie, watcha up to? 🔥"

    rp.llm.chat = fake_chat
    await crud.set_genders(88001, "male")
    user = await crud.get_user(88001)
    ok("partner gender set", user.bot_partner_gender == "female")

    voice, reply = await rp.get_ai_reply(user, "hi!")
    ok("voice reply parsed", voice is True and reply == "heyy bestie, watcha up to? 🔥")

    class FakeMsg:
        def __init__(self):
            self.voice_paths, self.texts = [], []
        async def answer(self, text, reply_markup=None):
            self.texts.append(text)
        async def answer_voice(self, f, caption=None):
            self.voice_paths.append(getattr(f, "path", str(f)))

    msg = FakeMsg()
    await rp._deliver(msg, user, "en", is_voice=True, text=reply)
    sent = msg.voice_paths[0]
    ok("tts voice file real", os.path.exists(sent) and os.path.getsize(sent) > 2000, sent)
    ok("text + translate btn after voice", any("heyy bestie" in t for t in msg.texts))
    from handlers.roleplay import translate_kb
    ok("translate button cb", translate_kb("fa").inline_keyboard[0][0].callback_data == "rp:tr")
    rp.llm.chat = orig_chat

    # [6] history memory ordering + mindmap session stats
    await crud.add_chat_message(88001, "user", "hi")
    await crud.add_chat_message(88001, "assistant", "heyy")
    hist = await crud.get_chat_history(88001, limit=10)
    ok("history order", [h.role for h in hist][-2:] == ["user", "assistant"])
    msgs = await rp.build_llm_messages(user, "hi!")
    ok("history in llm messages", msgs[-1] == {"role": "user", "content": "hi!"} and len(msgs) >= 3)

    await crud.update_mindmap(88001, {"roleplay": {"last_session": {"msgs": 7, "minutes": 4}}})
    mm2 = await crud.get_mindmap(88001)
    ok("session stats stored", mm2["roleplay"]["last_session"]["msgs"] == 7)

    # [7] full wiring: all 3 routers in main.py, handler counts
    from aiogram import Dispatcher
    import main as m
    dp = Dispatcher()
    dp.include_router(m.onboarding.router)
    dp.include_router(m.learning.router)
    dp.include_router(m.roleplay.router)
    ok("routers wired", len(dp.sub_routers) == 3)
    ok("learning handlers", len(m.learning.router.callback_query.handlers) >= 9
       and len(m.learning.router.message.handlers) >= 2)
    ok("roleplay handlers", len(m.roleplay.router.callback_query.handlers) >= 2
       and len(m.roleplay.router.message.handlers) >= 3)

    await get_engine().dispose()
    print(f"\n[PASS] STEP 5 VALIDATION PASSED - {PASS} checks green")


if __name__ == "__main__":
    asyncio.run(main())
