"""Learning module: Leitner review sessions, new-word flow, manual adds,
dashboard. Daily-goal counters live in the Mind-Map (learning.daily.<date>).
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import utils.i18n as i18n
from database import crud
from services import llm, translation
from services.prompts import GEN_WORDS_PROMPT, lang_name, level_cefr

logger = logging.getLogger(__name__)
router = Router(name="learning")

MAX_BATCH = 10


class Learn(StatesGroup):
    review = State()     # walking through due cards
    new_words = State()  # presenting generated words
    add_word = State()   # manual word entry


# ------------------------------------------------------------------ #
#  Pure helpers (unit-tested)                                        #
# ------------------------------------------------------------------ #


def parse_manual_words(text: str) -> list[tuple[str, str | None]]:
    """'strawberry = توت', 'chill', one per line or comma-separated."""
    out: list[tuple[str, str | None]] = []
    for line in re.split(r"[\n,;]+", text):
        line = line.strip()
        if not line:
            continue
        if "=" in line:
            w, _, t = line.partition("=")
            w, t = w.strip(), t.strip()
            if w:
                out.append((w, t or None))
        else:
            out.append((line, None))
    return out[:MAX_BATCH]


def parse_llm_words(raw: str) -> list[tuple[str, str]]:
    """Robust JSON parse of the word-generation reply -> [(word, translation)]."""
    raw = re.sub(r"^```(json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
    start, end = raw.find("["), raw.rfind("]")
    if start == -1 or end == -1:
        raise ValueError("no JSON array in reply")
    data = json.loads(raw[start : end + 1])
    words = []
    for item in data:
        if isinstance(item, dict) and item.get("w") and item.get("t"):
            words.append((str(item["w"]).strip(), str(item["t"]).strip()))
    return words


async def learned_today(user_id: int) -> int:
    mm = await crud.get_mindmap(user_id)
    daily = (mm.get("learning") or {}).get("daily") or {}
    return int(daily.get(date.today().isoformat(), 0))


async def bump_learned(user_id: int, n: int = 1) -> int:
    """Count new words toward today's goal (stored in mind-map)."""
    mm = await crud.get_mindmap(user_id)
    learning = dict(mm.get("learning") or {})
    daily = dict(learning.get("daily") or {})
    today = date.today().isoformat()
    daily[today] = int(daily.get(today, 0)) + n
    learning["daily"] = daily
    learning["total"] = int(learning.get("total", 0)) + n
    await crud.update_mindmap(user_id, {"learning": learning})
    return daily[today]


def glass(label: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=f"┃ {label} ┃", callback_data=data)


def _lang(user) -> str:
    return user.ui_language if i18n.supported(user.ui_language) else "en"


def _gate(target_msg_or_cb) -> None:
    """Send the not-onboarded nudge through whichever update we got."""
    if isinstance(target_msg_or_cb, CallbackQuery):
        return target_msg_or_cb.message.answer(i18n.t("en", "common.not_onboarded"))
    return target_msg_or_cb.answer(i18n.t("en", "common.not_onboarded"))


# ------------------------------------------------------------------ #
#  Review flow (due Leitner cards)                                   #
# ------------------------------------------------------------------ #


def _review_kb(lang: str, show: bool = False) -> InlineKeyboardMarkup:
    if not show:
        return InlineKeyboardMarkup(inline_keyboard=[
            [glass(i18n.t(lang, "learn.btn_show"), "learn:show")],
        ])
    return InlineKeyboardMarkup(inline_keyboard=[[
        glass(i18n.t(lang, "learn.btn_knew"), "learn:knew"),
        glass(i18n.t(lang, "learn.btn_nope"), "learn:nope"),
    ]])


async def _start_review(cb: CallbackQuery, state: FSMContext, user) -> None:
    lang = _lang(user)
    cards = await crud.get_due_cards(user.id, limit=20)
    if not cards:
        await cb.answer(i18n.t(lang, "learn.no_due"), show_alert=True)
        return
    payload = [{"wid": c.word_id, "w": c.vocab.word, "t": c.vocab.translation} for c in cards]
    await state.set_state(Learn.review)
    await state.update_data(cards=payload, idx=0, correct=0)
    await cb.message.edit_text(i18n.t(lang, "learn.review_intro", n=len(payload)))
    await _show_card(cb.message, state, user)


async def _show_card(msg: Message, state: FSMContext, user) -> None:
    lang = _lang(user)
    data = await state.get_data()
    cards: list[dict] = data["cards"]
    idx: int = data["idx"]
    if idx >= len(cards):
        return await _finish_review(msg, state, user)
    card = cards[idx]
    await msg.answer(i18n.t(lang, "learn.front", word=card["w"]), reply_markup=_review_kb(lang))


@router.callback_query(F.data == "learn:review")
async def cb_review(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    user = await crud.get_user(cb.from_user.id)
    if user is None or not user.onboarding_done:
        await _gate(cb)
        return
    await _start_review(cb, state, user)


@router.callback_query(F.data == "learn:show")
async def cb_show(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    user = await crud.get_user(cb.from_user.id)
    lang = _lang(user)
    data = await state.get_data()
    card = data["cards"][data["idx"]]
    await cb.message.edit_text(
        i18n.t(lang, "learn.back", word=card["w"], translation=card["t"]),
        reply_markup=_review_kb(lang, show=True),
    )


@router.callback_query(F.data.in_({"learn:knew", "learn:nope"}))
async def cb_answer(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    user = await crud.get_user(cb.from_user.id)
    lang = _lang(user)
    correct = cb.data == "learn:knew"
    data = await state.get_data()
    card = data["cards"][data["idx"]]
    await crud.review_card(user.id, card["wid"], correct=correct)
    idx = data["idx"] + 1
    correct_n = data.get("correct", 0) + (1 if correct else 0)
    await state.update_data(idx=idx, correct=correct_n)
    if idx >= len(data["cards"]):
        await state.clear()
        await crud.touch_streak(user.id)
        await cb.message.edit_text(i18n.t(lang, "learn.review_done",
                                          correct=correct_n, total=len(data["cards"])))
        await show_learn_menu(cb.message, user)
    else:
        nxt = data["cards"][idx]
        await cb.message.edit_text(i18n.t(lang, "learn.front", word=nxt["w"]),
                                   reply_markup=_review_kb(lang))


# ------------------------------------------------------------------ #
#  New-word flow (LLM-generated, known words skipped)                #
# ------------------------------------------------------------------ #


async def generate_words(user, n: int, known_texts: list[str]) -> list[tuple[str, str]]:
    prompt = GEN_WORDS_PROMPT.format(
        n=n, lang=lang_name(user.target_language), cefr=level_cefr(user.level),
        exclude=", ".join(known_texts[:60]) or "(none)",
        native=lang_name(user.native_language),
    )
    raw = await llm.chat([{"role": "user", "content": prompt}],
                                 user_id=user.id, temperature=0.8, max_tokens=900)
    return parse_llm_words(raw)


@router.callback_query(F.data == "learn:new")
async def cb_new_words(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    user = await crud.get_user(cb.from_user.id)
    if user is None or not user.onboarding_done:
        await _gate(cb)
        return
    lang = _lang(user)
    done = await learned_today(user.id)
    n = min(MAX_BATCH, user.daily_goal - done)
    if n <= 0:
        await cb.answer(i18n.t(lang, "learn.all_done"), show_alert=True)
        return
    known_ids = await crud.get_known_word_ids(user.id)
    known_texts: list[str] = []
    for wid in list(known_ids)[:80]:
        v = await crud.find_vocab_by_id(wid)
        if v:
            known_texts.append(v.word)
    try:
        words = await generate_words(user, n, known_texts)
        # double-check the known-set locally (LLMs sometimes ignore exclusions)
        filtered = []
        for w, t in words:
            v = await crud.find_vocab(w, user.target_language)
            if v and v.id in known_ids:
                continue
            filtered.append((w, t))
        words = filtered or words  # if everything got filtered, keep raw (rare)
    except Exception as exc:
        logger.warning("Word generation failed: %s", exc)
        await cb.message.answer(i18n.t(lang, "learn.no_new"))
        return
    if not words:
        await cb.message.answer(i18n.t(lang, "learn.no_new"))
        return
    await state.set_state(Learn.new_words)
    await state.update_data(words=words[:n], idx=0, added=0)
    await cb.message.answer(i18n.t(lang, "learn.new_intro", n=min(len(words), n)))
    await _show_new_word(cb.message, state, user)


async def _show_new_word(msg: Message, state: FSMContext, user) -> None:
    lang = _lang(user)
    data = await state.get_data()
    words: list[tuple[str, str]] = data["words"]
    idx: int = data["idx"]
    if idx >= len(words):
        return await _finish_new_words(msg, state, user, lang)
    w, t = words[idx]
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        glass(i18n.t(lang, "learn.btn_got"), "learn:got"),
        glass(i18n.t(lang, "learn.btn_known"), "learn:known"),
    ]])
    await msg.answer(i18n.t(lang, "learn.new_card", word=w, translation=t), reply_markup=kb)


async def _finish_new_words(msg: Message, state: FSMContext, user, lang: str) -> None:
    data = await state.get_data()
    await state.clear()
    done = await learned_today(user.id)
    await crud.touch_streak(user.id)
    await msg.answer(i18n.t(lang, "learn.new_done", n=data.get("added", 0), done=done, goal=user.daily_goal))
    await show_learn_menu(msg, user)


@router.callback_query(F.data.in_({"learn:got", "learn:known"}))
async def cb_new_answer(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    user = await crud.get_user(cb.from_user.id)
    data = await state.get_data()
    w, t = data["words"][data["idx"]]
    vocab = await crud.get_or_create_vocab(w, t, user.target_language)
    if cb.data == "learn:got":
        await crud.add_to_leitner(user.id, vocab.id, box_level=1)
        await bump_learned(user.id, 1)
        added = data.get("added", 0) + 1
    else:
        # "already knew it" -> straight into the mastered box (Box 7, 90-day gap)
        await crud.add_to_leitner(user.id, vocab.id, box_level=7)
        added = data.get("added", 0)
    idx = data["idx"] + 1
    await state.update_data(idx=idx, added=added)
    await _show_new_word(cb.message, state, user)


# ------------------------------------------------------------------ #
#  Manual word adding                                                #
# ------------------------------------------------------------------ #


async def resolve_word(user, word: str) -> tuple[str, str]:
    """Translate a bare word target->native; flip direction if unchanged."""
    src, dst = user.target_language, user.native_language
    tr = await translation.translate(word, target=dst, source=src)
    if tr and tr.strip().lower() != word.strip().lower():
        return word, tr
    tr2 = await translation.translate(word, target=src, source=dst)
    return (tr2 or word), word


@router.callback_query(F.data == "learn:add")
async def cb_add_word(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    user = await crud.get_user(cb.from_user.id)
    if user is None or not user.onboarding_done:
        await _gate(cb)
        return
    await state.set_state(Learn.add_word)
    await cb.message.answer(i18n.t(_lang(user), "learn.add_prompt"))


@router.message(Learn.add_word, F.text)
async def add_words_typed(message: Message, state: FSMContext) -> None:
    user = await crud.get_user(message.from_user.id)
    lang = _lang(user)
    pairs = parse_manual_words(message.text or "")
    if not pairs:
        await message.answer(i18n.t(lang, "learn.add_invalid"))
        return
    added = 0
    for w, t in pairs:
        try:
            if t is None:
                w, t = await resolve_word(user, w)
            vocab = await crud.get_or_create_vocab(w, t, user.target_language)
            await crud.add_to_leitner(user.id, vocab.id, box_level=1)
            added += 1
        except Exception as exc:
            logger.warning("Manual add failed for %r: %s", w, exc)
    await state.clear()
    if added:
        await bump_learned(user.id, added)
        await crud.touch_streak(user.id)
    await message.answer(i18n.t(lang, "learn.add_done", n=added))
    await show_learn_menu(message, user)


# ------------------------------------------------------------------ #
#  Menu + dashboard                                                  #
# ------------------------------------------------------------------ #


async def show_learn_menu(target: Message | CallbackQuery, user) -> None:
    lang = _lang(user)
    due = await crud.get_due_cards(user.id, limit=999)
    done = await learned_today(user.id)
    stats = await crud.get_leitner_stats(user.id)
    stat_str = ", ".join(f"B{k}:{v}" for k, v in sorted(stats.items())) or "—"
    text = (
        f"{i18n.t(lang, 'learn.menu')}\n\n"
        f"{i18n.t(lang, 'learn.due', n=len(due)) if due else i18n.t(lang, 'learn.no_due')}\n"
        f"{i18n.t(lang, 'learn.today', done=done, goal=user.daily_goal)}\n"
        f"{i18n.t(lang, 'learn.boxes', stats=stat_str)}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [glass(i18n.t(lang, "learn.btn_review", n=len(due)), "learn:review")] if due else [],
        [glass(i18n.t(lang, "learn.btn_new"), "learn:new"),
         glass(i18n.t(lang, "learn.btn_add"), "learn:add")],
        [glass(i18n.t(lang, "learn.btn_back"), "learn:back")],
    ])
    kb.inline_keyboard = [row for row in kb.inline_keyboard if row]
    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, reply_markup=kb)
    else:
        await target.answer(text, reply_markup=kb)


async def show_dashboard(target: Message | CallbackQuery, user) -> None:
    lang = _lang(user)
    stats = await crud.get_leitner_stats(user.id)
    done = await learned_today(user.id)
    mm = await crud.get_mindmap(user.id)
    total = int((mm.get("learning") or {}).get("total", 0))
    quiz = mm.get("quiz") or {}
    text = (
        "📊 <b>dashboard</b>\n\n"
        f"🔥 streak: <b>{user.streak}</b>\n"
        f"🎚 level: <b>{user.level or '??'}</b>\n"
        f"📈 today: <b>{done}/{user.daily_goal}</b> • all-time: <b>{total}</b>\n"
        f"🧠 boxes: {', '.join(f'B{k}:{v}' for k, v in sorted(stats.items())) or '—'}\n"
        f"🎯 quiz: {quiz.get('score_pct', '—')}% • weak: "
        f"{', '.join(quiz.get('weak_skills') or []) or '—'}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[glass(i18n.t(lang, "learn.btn_back"), "learn:back")]])
    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, reply_markup=kb)
    else:
        await target.answer(text, reply_markup=kb)


@router.message(Command("learn"))
async def cmd_learn(message: Message) -> None:
    user = await crud.get_user(message.from_user.id)
    if user is None or not user.onboarding_done:
        await _gate(message)
        return
    await show_learn_menu(message, user)


@router.callback_query(F.data == "menu:learn")
async def cb_menu_learn(cb: CallbackQuery) -> None:
    await cb.answer()
    user = await crud.get_user(cb.from_user.id)
    if user is None or not user.onboarding_done:
        await _gate(cb)
        return
    await show_learn_menu(cb, user)


@router.callback_query(F.data == "menu:dashboard")
async def cb_menu_dashboard(cb: CallbackQuery) -> None:
    await cb.answer()
    user = await crud.get_user(cb.from_user.id)
    if user is None or not user.onboarding_done:
        await _gate(cb)
        return
    await show_dashboard(cb, user)


@router.callback_query(F.data == "menu:streak")
async def cb_menu_streak(cb: CallbackQuery) -> None:
    await cb.answer()
    user = await crud.get_user(cb.from_user.id)
    streak = user.streak if user else 0
    if streak == 0:
        flex = "day 0. let's change that today 🔥"
    elif streak < 7:
        flex = f"{streak} days?! okay spark emoji 🔥 keep it alive"
    elif streak < 30:
        flex = f"{streak} days UNHINGED 🥵 the box fears you"
    else:
        flex = f"{streak} days?! touch grass (in your target language) 🌱🔥"
    await cb.message.answer(f"🔥 {flex}")


@router.callback_query(F.data == "learn:back")
async def cb_learn_back(cb: CallbackQuery) -> None:
    await cb.answer()
    from keyboards.menus import main_menu_kb, main_menu_text

    user = await crud.get_user(cb.from_user.id)
    lang = _lang(user) if user else "en"
    await cb.message.edit_text(
        main_menu_text(lang, cb.from_user.first_name or ""),
        reply_markup=main_menu_kb(lang, user.streak if user else 0),
    )
