"""Async CRUD layer — the ONLY module handlers/services talk to for DB access.

Every function opens its own transaction via `get_session()` so handlers
stay clean. Functions that must run atomically together accept a session.
"""
from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_session
from database.models import ApiConfig, ChatHistory, LeitnerBox, MindMap, User, Vocabulary
from utils.leitner import demote, next_review_date, promote

# ------------------------------------------------------------------ #
#  Users                                                             #
# ------------------------------------------------------------------ #


async def get_user(user_id: int, session: AsyncSession | None = None) -> User | None:
    async with _session_or_new(session) as s:
        return await s.get(User, user_id)


async def get_or_create_user(
    user_id: int,
    *,
    native_language: str = "en",
    session: AsyncSession | None = None,
) -> User:
    async with _session_or_new(session) as s:
        user = await s.get(User, user_id)
        if user is None:
            user = User(id=user_id, native_language=native_language)
            s.add(user)
            await s.flush()
        return user


async def update_user(user_id: int, **fields: Any) -> User | None:
    """Set arbitrary columns, e.g. update_user(uid, daily_goal=50, level='A2')."""
    async with get_session() as s:
        user = await s.get(User, user_id)
        if user is None:
            return None
        for key, value in fields.items():
            if hasattr(user, key):
                setattr(user, key, value)
        await s.flush()
        return user


async def set_languages(user_id: int, native: str | None = None, target: str | None = None,
                        session: AsyncSession | None = None) -> User | None:
    fields: dict[str, Any] = {}
    if native is not None:
        fields["native_language"] = fields["ui_language"] = native  # instant UI switch (spec 3A)
    if target is not None:
        fields["target_language"] = target
    if session is not None:
        user = await session.get(User, user_id)
        if user:
            for k, v in fields.items():
                setattr(user, k, v)
            return user
        return None
    return await update_user(user_id, **fields)




# ------------------------------------------------------------------ #
#  Vocabulary                                                        #
# ------------------------------------------------------------------ #


async def get_or_create_vocab(
    word: str,
    translation: str,
    language: str,
    difficulty: int = 1,
    session: AsyncSession | None = None,
) -> Vocabulary:
    async with _session_or_new(session) as s:
        result = await s.execute(
            select(Vocabulary).where(
                func.lower(Vocabulary.word) == word.lower().strip(),
                Vocabulary.language == language,
            )
        )
        vocab = result.scalar_one_or_none()
        if vocab is None:
            vocab = Vocabulary(
                word=word.strip().lower(),
                translation=translation.strip(),
                language=language,
                difficulty=max(1, min(5, difficulty)),
            )
            s.add(vocab)
            await s.flush()
        return vocab


async def find_vocab(word: str, language: str, session: AsyncSession | None = None) -> Vocabulary | None:
    async with _session_or_new(session) as s:
        result = await s.execute(
            select(Vocabulary).where(
                func.lower(Vocabulary.word) == word.lower().strip(),
                Vocabulary.language == language,
            )
        )
        return result.scalar_one_or_none()


async def find_vocab_by_id(word_id: int, session: AsyncSession | None = None) -> Vocabulary | None:
    async with _session_or_new(session) as s:
        return await s.get(Vocabulary, word_id)


# ------------------------------------------------------------------ #
#  Leitner box                                                       #
# ------------------------------------------------------------------ #


async def add_to_leitner(
    user_id: int,
    word_id: int,
    *,
    box_level: int = 1,
    session: AsyncSession | None = None,
) -> LeitnerBox:
    """Add a word to the user's box (idempotent — existing cards untouched)."""
    async with _session_or_new(session) as s:
        card = await _get_card(s, user_id, word_id)
        if card is None:
            card = LeitnerBox(
                user_id=user_id,
                word_id=word_id,
                box_level=box_level,
                next_review=next_review_date(box_level),
            )
            s.add(card)
            await s.flush()
        return card


async def review_card(user_id: int, word_id: int, correct: bool,
                      session: AsyncSession | None = None) -> LeitnerBox | None:
    """Apply Leitner promotion/demotion and schedule the next review."""
    async with _session_or_new(session) as s:
        card = await _get_card(s, user_id, word_id)
        if card is None:
            return None
        now = datetime.utcnow()
        card.last_reviewed = now
        if correct:
            card.correct_count += 1
            card.box_level = promote(card.box_level)
        else:
            card.wrong_count += 1
            card.box_level = demote(card.box_level)
        card.next_review = next_review_date(card.box_level, now)
        await s.flush()
        return card


async def get_due_cards(
    user_id: int,
    limit: int = 10,
    *,
    session: AsyncSession | None = None,
) -> list[LeitnerBox]:
    """Cards whose next_review is due (used by learning session + vocab injection)."""
    async with _session_or_new(session) as s:
        result = await s.execute(
            select(LeitnerBox)
            .options(selectinload(LeitnerBox.vocab))  # eager: safe to read .vocab later
            .where(LeitnerBox.user_id == user_id, LeitnerBox.next_review <= datetime.utcnow())
            .order_by(LeitnerBox.next_review.asc())
            .limit(limit)
        )
        return list(result.scalars().all())



# ------------------------------------------------------------------ #
#  Chat history (Las o Lus memory)                                   #
# ------------------------------------------------------------------ #


async def add_chat_message(
    user_id: int,
    role: str,
    content: str,
    *,
    is_voice: bool = False,
    translation: str | None = None,
    session: AsyncSession | None = None,
) -> ChatHistory:
    async with _session_or_new(session) as s:
        msg = ChatHistory(
            user_id=user_id, role=role, content=content,
            is_voice=is_voice, translation=translation,
        )
        s.add(msg)
        await s.flush()
        return msg


async def get_chat_history(user_id: int, limit: int = 20,
                           session: AsyncSession | None = None) -> list[ChatHistory]:
    """Last `limit` messages in chronological order — feed straight to the LLM."""
    async with _session_or_new(session) as s:
        result = await s.execute(
            select(ChatHistory)
            .where(ChatHistory.user_id == user_id)
            .order_by(ChatHistory.created_at.desc(), ChatHistory.id.desc())
            .limit(limit)
        )
        return list(reversed(result.scalars().all()))


# ------------------------------------------------------------------ #
#  Mind map                                                          #
# ------------------------------------------------------------------ #


async def get_mindmap(user_id: int, session: AsyncSession | None = None) -> dict:
    async with _session_or_new(session) as s:
        mm = await s.get(MindMap, user_id)
        return dict(mm.data) if mm else {}


async def update_mindmap(user_id: int, patch: dict[str, Any],
                         session: AsyncSession | None = None) -> dict:
    """Shallow-merge `patch` into the existing mind-map JSON."""
    async with _session_or_new(session) as s:
        mm = await s.get(MindMap, user_id)
        if mm is None:
            mm = MindMap(user_id=user_id, data={})
            s.add(mm)
        data = dict(mm.data or {})
        data.update(patch)
        data["updated_at"] = datetime.utcnow().isoformat()
        mm.data = data  # reassign so the JSON change is tracked
        await s.flush()
        return mm.data


# ------------------------------------------------------------------ #
#  Streak                                                            #
# ------------------------------------------------------------------ #


async def touch_streak(user_id: int, session: AsyncSession | None = None) -> int:
    """Call on any learning activity: +1 streak if new day, reset if a day was missed."""
    async with _session_or_new(session) as s:
        user = await s.get(User, user_id)
        if user is None:
            return 0
        today = date.today()
        if user.last_active == today:
            return user.streak
        if user.last_active == today - timedelta(days=1):
            user.streak += 1
        elif user.last_active is None or user.last_active < today:
            user.streak = 1
        user.last_active = today
        await s.flush()
        return user.streak


# ------------------------------------------------------------------ #
#  Dynamic API config (admin panel cache)                            #
# ------------------------------------------------------------------ #


async def get_api_config(key: str, default: str | None = None,
                         session: AsyncSession | None = None) -> str | None:
    async with _session_or_new(session) as s:
        row = await s.get(ApiConfig, key)
        return row.value if row else default


async def get_all_api_config(session: AsyncSession | None = None) -> dict[str, str]:
    async with _session_or_new(session) as s:
        result = await s.execute(select(ApiConfig.key, ApiConfig.value))
        return dict(result.all())


async def set_api_config(key: str, value: str, session: AsyncSession | None = None) -> None:
    async with _session_or_new(session) as s:
        row = await s.get(ApiConfig, key)
        if row is None:
            row = ApiConfig(key=key, value=value)
            s.add(row)
        else:
            row.value = value
        await s.flush()


# ------------------------------------------------------------------ #
#  Internal helpers                                                  #
# ------------------------------------------------------------------ #


@asynccontextmanager
async def _session_or_new(session: AsyncSession | None) -> AsyncIterator[AsyncSession]:
    """Reuse the caller's session when given, else open/commit our own."""
    if session is not None:
        yield session
    else:
        async with get_session() as s:
            yield s


async def _get_card(s: AsyncSession, user_id: int, word_id: int) -> LeitnerBox | None:
    result = await s.execute(
        select(LeitnerBox).where(LeitnerBox.user_id == user_id, LeitnerBox.word_id == word_id)
    )
    return result.scalar_one_or_none()


async def get_known_word_ids(user_id: int, *, session: AsyncSession | None = None) -> set[int]:
    """All word_ids the user already has — new words must skip these (spec 3C)."""
    async with _session_or_new(session) as s:
        result = await s.execute(select(LeitnerBox.word_id).where(LeitnerBox.user_id == user_id))
        return {row[0] for row in result.all()}


async def get_leitner_stats(user_id: int, *, session: AsyncSession | None = None) -> dict[int, int]:
    """Word counts per box level, e.g. {1: 12, 2: 5, 7: 40} (dashboard)."""
    async with _session_or_new(session) as s:
        result = await s.execute(
            select(LeitnerBox.box_level, func.count(LeitnerBox.id))
            .where(LeitnerBox.user_id == user_id)
            .group_by(LeitnerBox.box_level)
        )
        return {box: count for box, count in result.all()}

async def set_genders(user_id: int, gender: str, session: AsyncSession | None = None) -> User | None:
    """Las o Lus rule: bot partner = opposite gender of the user."""
    partner = "female" if gender == "male" else "male"
    return await update_user(user_id, gender=gender, bot_partner_gender=partner)
