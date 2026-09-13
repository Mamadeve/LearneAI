"""Onboarding: /start → native language (instant UI switch) → target language
→ level claim → dynamic placement quiz → roast/praise verdict → daily goal.

FSM is only used where typing is involved (custom language, custom goal,
quiz answer flow state lives in FSM data).
"""
from __future__ import annotations

import logging
from datetime import datetime

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

import utils.i18n as i18n
from database import crud
from keyboards.inline import (
    LANGUAGES,
    goals_kb,
    languages_kb,
    levels_kb,
    quiz_options_kb,
    target_languages_kb,
)
from keyboards.menus import main_menu_kb, main_menu_text
from services import llm_manager
from services.prompts import (
    LEVEL_TO_CEFR,
    SUPPORTED_LEVELS,
    build_quiz_verdict_prompt,
    lang_name,
)

logger = logging.getLogger(__name__)
router = Router(name="onboarding")

MAX_GOAL = 100


class Onb(StatesGroup):
    native_other = State()   # typing a custom native language name
    goal_custom = State()    # typing a custom daily goal
    quiz = State()           # answering quiz questions (data in FSM)


# ------------------------------------------------------------------ #
#  Helpers                                                           #
# ------------------------------------------------------------------ #


def score_to_cefr(score_pct: int) -> str:
    """Placement score -> honest CEFR level."""
    if score_pct >= 90:
        return "C1"
    if score_pct >= 75:
        return "B2"
    if score_pct >= 60:
        return "B1"
    if score_pct >= 40:
        return "A2"
    return "A1"


def canned_verdict(score_pct: int, claimed: str) -> str:
    if score_pct >= 80:
        return "Riiiight... you cooked 🔥"
    if score_pct >= 50:
        return "ok ok, respectable... but i see you 👀"
    if claimed in ("good", "advanced", "intermediate"):
        return "you got destroyed 😂 💀"
    return "humble king/queen 👑 respect."


def weak_skills(questions: list[dict], answers: dict[int, int]) -> list[str]:
    return sorted(
        {
            q.get("skill", "general")
            for i, q in enumerate(questions)
            if answers.get(i) != q.get("correct")
        }
    )


async def _send_question(msg_or_cb, state: FSMContext, lang: str) -> None:
    data = await state.get_data()
    questions: list[dict] = data["quiz_questions"]
    idx: int = data["quiz_idx"]
    q = questions[idx]
    text = i18n.t(lang, "start.question", i=idx + 1, n=len(questions), q=q["q"])
    kb = quiz_options_kb(idx, q["options"], lang)
    if isinstance(msg_or_cb, CallbackQuery):
        await msg_or_cb.message.edit_text(text, reply_markup=kb)
    else:
        await msg_or_cb.answer(text, reply_markup=kb)


# ------------------------------------------------------------------ #
#  /start + main menu                                                #
# ------------------------------------------------------------------ #


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    user = await crud.get_or_create_user(
        message.from_user.id, native_language="en"
    )
    if user.onboarding_done:
        await message.answer(
            main_menu_text(user.ui_language, message.from_user.first_name or ""),
            reply_markup=main_menu_kb(user.ui_language, user.streak),
        )
        return
    # Expandable intro: welcome + "more" section with the native-language picker
    await message.answer(i18n.t("en", "start.welcome"))
    await message.answer(
        f"{i18n.t('en', 'start.welcome_more')}\n\n{len(LANGUAGES)} languages loaded 👇",
        reply_markup=languages_kb(),
    )


@router.message(Command("menu"))
async def cmd_menu(message: Message) -> None:
    user = await crud.get_user(message.from_user.id)
    if user is None or not user.onboarding_done:
        await message.answer(i18n.t("en", "common.not_onboarded"))
        return
    await message.answer(
        main_menu_text(user.ui_language, message.from_user.first_name or ""),
        reply_markup=main_menu_kb(user.ui_language, user.streak),
    )


# ------------------------------------------------------------------ #
#  Step 1: native language  (instant UI switch happens here)         #
# ------------------------------------------------------------------ #


@router.callback_query(F.data.startswith("onb:lang:"))
async def cb_native(cb: CallbackQuery, state: FSMContext) -> None:
    code = cb.data.split(":")[-1]
    await cb.answer()
    if code == "other":
        await state.set_state(Onb.native_other)
        await cb.message.edit_text(i18n.t("en", "start.choose_native_other"))
        return
    user = await crud.set_languages(cb.from_user.id, native=code)
    lang = code if i18n.supported(code) else "en"
    native_label = next(label for label, c in LANGUAGES if c == code)
    await cb.message.edit_text(
        f"{i18n.t(lang, 'start.native_saved', native=native_label)}\n\n"
        f"{i18n.t(lang, 'start.choose_target')}",
        reply_markup=target_languages_kb(),
    )


@router.message(Onb.native_other, F.text)
async def native_other_typed(message: Message, state: FSMContext) -> None:
    name = message.text.strip()[:32]
    # Unsupported languages keep the UI in English but are remembered natively.
    await crud.set_languages(message.from_user.id, native="en")
    await crud.update_user(message.from_user.id, native_language=name[:8].lower())
    await state.set_state(None)
    await message.answer(
        f"{i18n.t('en', 'start.native_saved', native=name)}\n\n"
        f"{i18n.t('en', 'start.choose_target')}",
        reply_markup=target_languages_kb(),
    )


# ------------------------------------------------------------------ #
#  Step 2: target language -> level claim                            #
# ------------------------------------------------------------------ #


@router.callback_query(F.data.startswith("onb:target:"))
async def cb_target(cb: CallbackQuery, state: FSMContext) -> None:
    code = cb.data.split(":")[-1]
    await cb.answer()
    user = await crud.update_user(cb.from_user.id, target_language=code)
    lang = user.ui_language if i18n.supported(user.ui_language) else "en"
    await cb.message.edit_text(
        i18n.t(lang, "start.level_q", target=lang_name(code)),
        reply_markup=levels_kb(lang),
    )


@router.callback_query(F.data.startswith("onb:lvl:"))
async def cb_level(cb: CallbackQuery, state: FSMContext) -> None:
    claimed = cb.data.split(":")[-1]
    if claimed not in SUPPORTED_LEVELS:
        await cb.answer()
        return
    await cb.answer()
    user = await crud.get_user(cb.from_user.id)
    lang = user.ui_language if i18n.supported(user.ui_language) else "en"
    await state.update_data(claimed_level=claimed)
    if claimed == "barely":
        await cb.message.edit_text(i18n.t(lang, "start.tease"))
    await _launch_quiz(cb.message, state, user, lang, claimed)


async def _launch_quiz(message: Message, state: FSMContext, user, lang: str, claimed: str) -> None:
    """Dynamic FSM placement quiz; degrades gracefully if the LLM is down."""
    target = user.target_language or "en"
    try:
        questions = await llm_manager.generate_quiz(lang_name(target), claimed, n_questions=5)
        # sanity-check LLM output shape
        for q in questions:
            assert isinstance(q.get("options"), list) and len(q["options"]) >= 2
            assert isinstance(q.get("correct"), int)
        questions = questions[:5]
    except Exception as exc:
        logger.warning("Quiz generation failed, skipping: %s", exc)
        await _finish_without_quiz(message, state, user, lang, claimed)
        return
    await state.set_state(Onb.quiz)
    await state.update_data(
        quiz_questions=questions, quiz_idx=0, quiz_answers={}, claimed_level=claimed,
        lang=lang,
    )
    await message.answer(i18n.t(lang, "start.quiz_intro", n=len(questions)))
    await _send_question(message, state, lang)


# ------------------------------------------------------------------ #
#  Quiz answering                                                    #
# ------------------------------------------------------------------ #


@router.callback_query(Onb.quiz, F.data.startswith("onb:quiz:"))
async def cb_quiz_answer(cb: CallbackQuery, state: FSMContext) -> None:
    _, _, idx_s, choice_s = cb.data.split(":")
    idx, choice = int(idx_s), int(choice_s)
    await cb.answer()
    data = await state.get_data()
    questions: list[dict] = data["quiz_questions"]
    answers: dict = dict(data["quiz_answers"])
    answers[idx] = choice

    if idx + 1 < len(questions):
        await state.update_data(quiz_idx=idx + 1, quiz_answers=answers)
        await _send_question(cb, state, data.get("lang", "en"))
        return
    await state.update_data(quiz_answers=answers)
    user = await crud.get_user(cb.from_user.id)
    lang = user.ui_language if i18n.supported(user.ui_language) else "en"
    await _finish_quiz(cb.message, state, user, lang, questions, answers, data["claimed_level"])


async def _finish_without_quiz(message: Message, state: FSMContext, user, lang: str, claimed: str) -> None:
    """LLM unavailable -> trust the claim, calibrate later during chats."""
    level = LEVEL_TO_CEFR.get(claimed, "A2")
    await crud.update_user(user.id, level=level)
    await crud.update_mindmap(user.id, {"quiz": {
        "claimed": claimed, "completed": False, "skipped_reason": "llm_unavailable",
    }})
    await state.clear()
    await message.answer(i18n.t(lang, "start.quiz_unavailable"))
    await message.answer(
        i18n.t(lang, "start.verdict", verdict=canned_verdict(50, claimed), level=level)
    )
    await message.answer(i18n.t(lang, "start.goal_q"), reply_markup=goals_kb(lang))


async def _finish_quiz(
    message: Message,
    state: FSMContext,
    user,
    lang: str,
    questions: list[dict],
    answers: dict[int, int],
    claimed: str,
) -> None:
    score = round(100 * sum(answers.get(i) == q.get("correct") for i, q in enumerate(questions)) / len(questions))
    weak = weak_skills(questions, answers)
    level = score_to_cefr(score)
    await crud.update_user(user.id, level=level)
    await crud.update_mindmap(user.id, {"quiz": {
        "claimed": claimed,
        "score_pct": score,
        "weak_skills": weak,
        "cefr_assigned": level,
        "completed": True,
        "ts": datetime.utcnow().isoformat(),
    }})
    # LLM-crafted roast/praise with canned fallback
    try:
        verdict = await llm_manager.chat(
            [{"role": "user", "content": build_quiz_verdict_prompt(lang_name(user.target_language), claimed, score, weak)}],
            temperature=1.0, max_tokens=80,
        )
        verdict = verdict.strip().strip('"')
    except Exception as exc:
        logger.warning("Verdict LLM failed, canned fallback: %s", exc)
        verdict = canned_verdict(score, claimed)
    await state.clear()
    await message.answer(i18n.t(lang, "start.verdict", verdict=verdict, level=level))
    await message.answer(i18n.t(lang, "start.goal_q"), reply_markup=goals_kb(lang))


# ------------------------------------------------------------------ #
#  Step 3: daily goal -> done                                        #
# ------------------------------------------------------------------ #


@router.callback_query(F.data.startswith("onb:goal:"))
async def cb_goal(cb: CallbackQuery, state: FSMContext) -> None:
    choice = cb.data.split(":")[-1]
    await cb.answer()
    if choice == "custom":
        await state.set_state(Onb.goal_custom)
        user = await crud.get_user(cb.from_user.id)
        lang = user.ui_language if i18n.supported(user.ui_language) else "en"
        await cb.message.edit_text(i18n.t(lang, "start.goal_custom"))
        return
    await _finalize(cb.message, cb.from_user, int(choice))


@router.message(Onb.goal_custom, F.text)
async def goal_custom_typed(message: Message, state: FSMContext) -> None:
    text = message.text.strip()
    if not text.isdigit() or not (1 <= int(text) <= MAX_GOAL):
        await message.answer(i18n.t("en", "start.goal_invalid"))
        return
    await state.set_state(None)
    await _finalize(message, message.from_user, int(text))


async def _finalize(message: Message, tg_user, goal: int) -> None:
    user = await crud.update_user(tg_user.id, daily_goal=goal, onboarding_done=True)
    lang = user.ui_language if i18n.supported(user.ui_language) else "en"
    await crud.touch_streak(tg_user.id)
    await message.answer(
        i18n.t(lang, "start.done", name=tg_user.first_name or "chief"),
        reply_markup=main_menu_kb(lang, user.streak),
    )

