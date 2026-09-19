"""Las o Lus — roleplay chat with the AI Gen-Z partner.

Voice notes -> STT -> LLM -> TTS. The LLM can send voice on its own via a
[VOICE] tag. "I didn't understand" button translates the last partner message
into the user's native language. Sessions auto-end after 15 minutes of
inactivity (lazy check on next interaction) or via /end.
"""
from __future__ import annotations

import logging
import time

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import utils.i18n as i18n
from database import crud
from services import llm, stt, tts, translation
from services.prompts import build_roleplay_system_prompt

logger = logging.getLogger(__name__)
router = Router(name="roleplay")

VOICE_TAG = "[VOICE]"
SESSION_TTL = 15 * 60  # seconds of inactivity


class Rp(StatesGroup):
    chat = State()


def glass(label: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=f"┃ {label} ┃", callback_data=data)


def _lang(user) -> str:
    return user.ui_language if i18n.supported(user.ui_language) else "en"


# ------------------------------------------------------------------ #
#  Pure helpers (unit-tested)                                        #
# ------------------------------------------------------------------ #


def parse_voice_tag(raw: str) -> tuple[bool, str]:
    """'[VOICE] heyy' -> (True, 'heyy'); otherwise (False, raw)."""
    s = (raw or "").strip()
    if s.startswith(VOICE_TAG):
        return True, s[len(VOICE_TAG):].strip()
    return False, s


def is_expired(session: dict) -> bool:
    """session = {'started': epoch, 'last': epoch, 'msgs': int}"""
    if not session:
        return False
    last = float(session.get("last") or session.get("started") or time.time())
    return (time.time() - last) > SESSION_TTL


def translate_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [glass(i18n.t(lang, "rp.btn_tr"), "rp:tr")],
    ])


# ------------------------------------------------------------------ #
#  LLM glue                                                          #
# ------------------------------------------------------------------ #


async def _due_vocab_pairs(user) -> list[tuple[str, str]]:
    """3-5 words from the due Leitner box for the prompt's vocab mission."""
    cards = await crud.get_due_cards(user.id, limit=5)
    return [(c.vocab.word, c.vocab.translation) for c in cards]


async def build_llm_messages(user, user_text: str) -> list[dict]:
    """System persona + last 10 turns of memory + the new user message."""
    return await llm.ContextBuilder.build_messages(user, user_text)


async def get_ai_reply(user, user_text: str) -> tuple[bool, str]:
    """(should_send_as_voice, reply_text) — LLM decides via the [VOICE] tag."""
    raw = await llm.chat(
        await build_llm_messages(user, user_text),
        temperature=0.95, max_tokens=300,
        user_id=user.id
    )
    return parse_voice_tag(raw)


# ------------------------------------------------------------------ #
#  Session lifecycle                                                 #
# ------------------------------------------------------------------ #


async def _start_session(state: FSMContext) -> None:
    await state.set_state(Rp.chat)
    now = time.time()
    await state.update_data(session={"started": now, "last": now, "msgs": 0})


async def _end_session(msg: Message, state: FSMContext, user, lang: str, *, expired: bool = False) -> None:
    data = await state.get_data()
    s = data.get("session") or {}
    await state.clear()
    started = float(s.get("started") or time.time())
    mins = max(1, round((time.time() - started) / 60))
    msgs = int(s.get("msgs") or 0)
    await crud.update_mindmap(user.id, {"roleplay": {
        "last_session": {
            "msgs": msgs, "minutes": mins, "expired": expired,
            "ended_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
        }
    }})
    await msg.answer(i18n.t(lang, "rp.expired" if expired else "rp.ended", msgs=msgs, mins=mins))


# ------------------------------------------------------------------ #
#  Entry points                                                      #
# ------------------------------------------------------------------ #


async def _open_session(message: Message, state: FSMContext, user) -> None:
    lang = _lang(user)
    await _start_session(state)
    await message.answer(i18n.t(lang, "rp.intro"))
    try:
        voice, text = await get_ai_reply(
            user, "(start the conversation — open with something short, fun, flirty)"
        )
    except Exception as exc:
        logger.warning("Opening line failed: %s", exc)
        return
    await crud.add_chat_message(user.id, "assistant", text, is_voice=voice)
    await _deliver(message, user, lang, voice, text)


@router.message(Command("roleplay"))
async def cmd_roleplay(message: Message, state: FSMContext) -> None:
    user = await crud.get_user(message.from_user.id)
    if user is None or not user.onboarding_done:
        await message.answer(i18n.t("en", "common.not_onboarded"))
        return
    await _open_session(message, state, user)


@router.callback_query(F.data == "menu:roleplay")
async def cb_menu_roleplay(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    user = await crud.get_user(cb.from_user.id)
    if user is None or not user.onboarding_done:
        await cb.message.answer(i18n.t("en", "common.not_onboarded"))
        return
    await _open_session(cb.message, state, user)


@router.message(Command("end"), Rp.chat)
async def rp_end(message: Message, state: FSMContext) -> None:
    user = await crud.get_user(message.from_user.id)
    await _end_session(message, state, user, _lang(user) if user else "en")


# ------------------------------------------------------------------ #
#  Conversation handlers                                             #
# ------------------------------------------------------------------ #


@router.message(Rp.chat, F.voice)
async def rp_voice(message: Message, state: FSMContext) -> None:
    user = await crud.get_user(message.from_user.id)
    if user is None or not user.onboarding_done:
        await message.answer(i18n.t("en", "common.not_onboarded"))
        return
    lang = _lang(user)
    data = await state.get_data()
    s = data.get("session") or {}
    if is_expired(s):
        await _end_session(message, state, user, lang, expired=True)
        await _start_session(state)
    try:
        buf = await message.bot.download(message.voice)
        text = await stt.transcribe(buf.read(), "voice_note.ogg", user.id)
    except Exception as exc:
        logger.warning("STT failed: %s", exc)
        await message.answer(i18n.t(lang, "rp.stt_fail"))
        return
    await _process(message, state, user, lang, text, is_voice=True)


@router.message(Rp.chat, F.text)
async def rp_text(message: Message, state: FSMContext) -> None:
    user = await crud.get_user(message.from_user.id)
    if user is None or not user.onboarding_done:
        await message.answer(i18n.t("en", "common.not_onboarded"))
        return
    lang = _lang(user)
    data = await state.get_data()
    s = data.get("session") or {}
    if is_expired(s):
        await _end_session(message, state, user, lang, expired=True)
        await _start_session(state)
    await _process(message, state, user, lang, message.text or "")


async def _process(message: Message, state: FSMContext, user, lang: str, text: str, *, is_voice: bool = False) -> None:
    data = await state.get_data()
    s = data.get("session") or {"started": time.time(), "last": time.time(), "msgs": 0}
    await crud.add_chat_message(user.id, "user", text, is_voice=is_voice)
    await crud.touch_streak(user.id)
    try:
        voice, reply = await get_ai_reply(user, text)
    except Exception as exc:
        logger.warning("LLM failed in roleplay: %s", exc)
        await message.answer(i18n.t(lang, "rp.llm_fail"))
        return
    await crud.add_chat_message(user.id, "assistant", reply, is_voice=voice)
    await state.update_data(session={
        "started": s.get("started", time.time()),
        "last": time.time(),
        "msgs": int(s.get("msgs", 0)) + 1,
    }, last_ai=reply)
    await _deliver(message, user, lang, voice, reply)


async def _deliver(message: Message, user, lang: str, is_voice: bool, text: str) -> None:
    """Voice replies go out as audio + the text (with translate button) after."""
    if is_voice and text:
        try:
            audio_bytes = await tts.synthesize_to_bytes(
                text, user.target_language, user.partner_gender or "female"
            )
            from aiogram.types import BufferedInputFile

            await message.answer_voice(BufferedInputFile(audio_bytes, filename="voice.ogg"))
        except Exception as exc:
            logger.warning("TTS failed, falling back to text: %s", exc)
    await message.answer(text, reply_markup=translate_kb(lang))


# ------------------------------------------------------------------ #
#  "I didn't understand" -> translate last partner message           #
# ------------------------------------------------------------------ #


@router.callback_query(F.data == "rp:tr")
async def rp_translate(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    user = await crud.get_user(cb.from_user.id)
    lang = _lang(user) if user else "en"
    data = await state.get_data()
    text = (data.get("last_ai") or "").strip()
    if not text:
        return
    try:
        tr = await translation.translate(
            text, target=user.native_language, source=user.target_language
        )
    except Exception as exc:
        logger.warning("Translate button failed: %s", exc)
        await cb.message.answer(i18n.t(lang, "common.error"))
        return
    await cb.message.answer(i18n.t(lang, "rp.translation", word=text[:48], tr=tr))
