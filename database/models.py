"""SQLAlchemy 2.0 models — LearneAI schema.

Designed for PostgreSQL scalability: BigInteger IDs, JSON columns,
no SQLite-specific types.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    """Telegram user + learning preferences + streak tracking."""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)  # Telegram ID
    native_language: Mapped[str] = mapped_column(String(8), default="en")   # BCP-47-ish code
    target_language: Mapped[str | None] = mapped_column(String(8))
    ui_language: Mapped[str] = mapped_column(String(8), default="en")       # bot UI language (switched at onboarding)
    level: Mapped[str | None] = mapped_column(String(16))                   # e.g. "A1".."C2" / "beginner".. after quiz
    daily_goal: Mapped[int] = mapped_column(Integer, default=20)            # words per day (max 100)
    user_gender: Mapped[str | None] = mapped_column(String(16))                  # "male" | "female" | "other"
    partner_gender: Mapped[str | None] = mapped_column(String(16))      # opposite of `user_gender` (Las o Lus)
    partner_archetype: Mapped[str | None] = mapped_column(String(32))   # e.g., "femboy", "straight", "gay"
    
    # Active LLM provider/model (user-level model switcher)
    selected_model_id: Mapped[str | None] = mapped_column(String(64), default=None)
    
    api_overrides: Mapped[dict] = mapped_column(JSON, default=dict)         # per-user API overrides (rare, admin-style)
    onboarding_done: Mapped[bool] = mapped_column(Boolean, default=False)

    # Streak system
    streak: Mapped[int] = mapped_column(Integer, default=0)
    last_active: Mapped[date | None] = mapped_column(Date)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    leitner_cards: Mapped[list["LeitnerBox"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    chat_messages: Mapped[list["ChatHistory"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    mindmap: Mapped["MindMap | None"] = relationship(back_populates="user", uselist=False, cascade="all, delete-orphan")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<User id={self.id} native={self.native_language} target={self.target_language} level={self.level}>"


class Vocabulary(Base):
    """Global word bank, shared across users, per target language."""
    __tablename__ = "vocabulary"
    __table_args__ = (UniqueConstraint("word", "language", name="uq_word_language"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    word: Mapped[str] = mapped_column(String(128), index=True)
    translation: Mapped[str] = mapped_column(String(256))
    language: Mapped[str] = mapped_column(String(8), index=True)  # target language code
    difficulty: Mapped[int] = mapped_column(Integer, default=1)   # 1 (easy) .. 5 (hard)

    cards: Mapped[list["LeitnerBox"]] = relationship(back_populates="vocab", cascade="all, delete-orphan")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Vocab {self.word!r}:{self.translation!r} ({self.language})>"


class LeitnerBox(Base):
    """Per-user spaced-repetition card state."""
    __tablename__ = "leitner_boxes"
    __table_args__ = (UniqueConstraint("user_id", "word_id", name="uq_user_word"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    word_id: Mapped[int] = mapped_column(Integer, ForeignKey("vocabulary.id", ondelete="CASCADE"), index=True)
    box_level: Mapped[int] = mapped_column(Integer, default=1)               # 1..7
    next_review: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, default=lambda: datetime.now(timezone.utc))
    last_reviewed: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    correct_count: Mapped[int] = mapped_column(Integer, default=0)
    wrong_count: Mapped[int] = mapped_column(Integer, default=0)

    user: Mapped["User"] = relationship(back_populates="leitner_cards")
    vocab: Mapped["Vocabulary"] = relationship(back_populates="cards")


class ChatHistory(Base):
    """Conversational memory for the 'Las o Lus' roleplay mode."""
    __tablename__ = "chat_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16))          # "user" | "assistant" | "system"
    content: Mapped[str] = mapped_column(Text)
    is_voice: Mapped[bool] = mapped_column(Boolean, default=False)   # message came from/went out as voice
    translation: Mapped[str | None] = mapped_column(Text)  # cached "I didn't understand" translation
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    user: Mapped["User"] = relationship(back_populates="chat_messages")


class MindMap(Base):
    """JSON behavioral analysis + learning gaps, fed by quiz/chat performance."""
    __tablename__ = "mind_maps"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    # Expected shape (grows over time):
    # {
    #   "quiz": {"placement": {...}, "score_pct": 40, "claimed_level": "beginner"},
    #   "weak_topics": ["past tense", "food vocab"],
    #   "strong_topics": ["greetings"],
    #   "behavior": {"avg_session_min": 12, "prefers_voice": true},
    #   "updated_at": "..."
    # }
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user: Mapped["User"] = relationship(back_populates="mindmap")


class ApiConfig(Base):
    """DB cache of live API configuration, editable by admins without restart."""
    __tablename__ = "api_configs"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)  # e.g. "llm_provider", "groq_api_key"
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
