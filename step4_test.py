"""Live validation of Step 4: i18n, keyboards, onboarding logic, router wiring.

No Telegram connection needed — we exercise importable pieces directly.
Run: python step4_test.py
"""
import asyncio
import json
import os
import sys

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./step4_test.db"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PASS = 0


def ok(label: str, cond: bool = True, extra: str = "") -> None:
    global PASS
    assert cond, f"FAILED: {label} {extra}"
    PASS += 1
    print(f"[{PASS:02d}] {label} OK")


async def main() -> None:
    # [1] Locale files are valid JSON with matching key structure
    en = json.load(open("locales/en.json", encoding="utf-8"))
    fa = json.load(open("locales/fa.json", encoding="utf-8"))
    ok("locale files parse", set(en) == {"start", "levels", "goals", "menu", "learn", "rp", "common"})
    ok("fa mirrors en keys", set(fa) == set(en) and set(fa["start"]) == set(en["start"]))

    # [2] i18n: lookup, kwargs, fallback, missing-key behavior
    import utils.i18n as i18n
    ok("en lookup", i18n.t("en", "start.choose_native").startswith("first things first"))
    ok("fa lookup", "زبان مادری" in i18n.t("fa", "start.choose_native"))
    ok("kwargs format", "English" in i18n.t("fa", "start.level_q", target="English"))
    ok("unknown lang -> en fallback", i18n.t("xx", "start.goal_q").startswith("last thing"))
    ok("missing key -> key itself", i18n.t("en", "start.nope.entirely") == "start.nope.entirely")
    ok("levels list", len(i18n.t("en", "levels.barely")) > 3)

    # [3] Keyboards build + callback data matches handler filters
    from keyboards.inline import goals_kb, languages_kb, levels_kb, quiz_options_kb, target_languages_kb
    from keyboards.menus import main_menu_kb
    nat = languages_kb()
    ok("native kb: 13 langs / 7 rows", len(nat.inline_keyboard) == 7 and sum(len(r) for r in nat.inline_keyboard) == 13)
    ok("native cb format", nat.inline_keyboard[0][0].callback_data == "onb:lang:fa")

    # [4] Handlers import + aiogram router wiring + main.py composition root
    from aiogram import Dispatcher
    from handlers import onboarding
    dp = Dispatcher()
    dp.include_router(onboarding.router)
    n_handlers = len(onboarding.router.message.handlers) + len(onboarding.router.callback_query.handlers)
    ok("onboarding router registered", n_handlers >= 8, f"({n_handlers} handlers)")
    import importlib
    m = importlib.import_module("main")
    ok("main.py imports clean", asyncio.iscoroutinefunction(m.main))

    # [5] Onboarding pure logic: scoring, CEFR mapping, verdicts
    from handlers.onboarding import canned_verdict, score_to_cefr, weak_skills
    ok("cefr mapping", (score_to_cefr(95), score_to_cefr(80), score_to_cefr(65), score_to_cefr(45), score_to_cefr(10)) == ("C1", "B2", "B1", "A2", "A1"))
    ok("roast path", "destroyed" in canned_verdict(20, "advanced"))
    ok("praise path", "cooked" in canned_verdict(90, "barely"))
    ok("humble path", "humble" in canned_verdict(20, "barely"))
    qs = [{"skill": "vocab", "correct": 0}, {"skill": "grammar", "correct": 1}, {"skill": "vocab", "correct": 2}]
    ok("weak skills dedup", weak_skills(qs, {0: 1, 1: 1, 2: 0}) == ["vocab"])

    # [6] Quiz finish path: verdict fallback + mindmap + level, DB-backed
    from database.engine import get_engine, init_db
    await init_db()
    import database.crud as crud
    await crud.get_or_create_user(555001, native_language="en")
    await crud.set_languages(555001, native="en")
    await crud.update_user(555001, target_language="en")
    ok("db user for flow", (await crud.get_user(555001)).ui_language == "en")

    from handlers.onboarding import _finish_quiz

    class FakeMsg:
        def __init__(self): self.sent = []
        async def answer(self, text, reply_markup=None): self.sent.append(text)

    class FakeState:
        def __init__(self): self.cleared = False
        async def clear(self): self.cleared = True

    msg = FakeMsg(); st = FakeState()
    user = await crud.get_user(555001)
    fake_q = [{"q": "q1", "options": ["a", "b"], "correct": 0, "skill": "vocab"},
              {"q": "q2", "options": ["a", "b"], "correct": 1, "skill": "grammar"}]
    await _finish_quiz(msg, st, user, "en", fake_q, {0: 0, 1: 0}, "advanced")
    mm_data = await crud.get_mindmap(555001)
    ok("quiz finish: mindmap updated", mm_data["quiz"]["score_pct"] == 50 and mm_data["quiz"]["cefr_assigned"] == "A2")
    ok("quiz finish: mid-score verdict fired", any("respectable" in s for s in msg.sent), str(msg.sent))
    ok("quiz finish: state cleared", st.cleared)
    lvl = (await crud.get_user(555001)).level
    ok("quiz finish: level saved", lvl == "A2")

    # [7] streak touched at finalize
    await crud.touch_streak(555001)
    ok("streak live", (await crud.get_user(555001)).streak == 1)

    await get_engine().dispose()
    print(f"\n[PASS] STEP 4 VALIDATION PASSED - {PASS} checks green")


if __name__ == "__main__":
    asyncio.run(main())

