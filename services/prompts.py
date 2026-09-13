"""System prompt builders — pure functions, no I/O.

The roleplay persona is the heart of "Las o Lus": a Gen-Z partner that
MUST NOT sound like a helpful AI assistant.
"""
from __future__ import annotations

from typing import Any

# Claimed level (UI) -> CEFR guidance injected into prompts
LEVEL_TO_CEFR: dict[str, str] = {
    "barely": "A1",
    "beginner": "A2",
    "intermediate": "B1",
    "good": "B2",
    "advanced": "C1",
}

SUPPORTED_LEVELS = tuple(LEVEL_TO_CEFR)

LANGUAGE_NAMES: dict[str, str] = {
    "en": "English", "fa": "Persian (Farsi)", "es": "Spanish", "fr": "French",
    "de": "German", "ar": "Arabic", "tr": "Turkish", "ru": "Russian",
    "zh": "Chinese", "ja": "Japanese", "ko": "Korean", "hi": "Hindi",
}


def level_cefr(level: str | None) -> str:
    return LEVEL_TO_CEFR.get((level or "beginner").lower(), "A2")


def lang_name(code: str | None) -> str:
    return LANGUAGE_NAMES.get(code or "en", code or "English")


# ------------------------------------------------------------------ #
#  Las o Lus — Roleplay persona                                      #
# ------------------------------------------------------------------ #


def build_roleplay_system_prompt(
    user: Any,
    due_words: list[tuple[str, str]],
    *,
    partner_name: str = "Lus",
) -> str:
    """Dynamic persona prompt. `due_words` = [(word, translation), ...] from the
    user's due Leitner cards — the LLM must weave them in naturally."""
    target = lang_name(user.target_language)
    native = lang_name(user.native_language)
    cefr = level_cefr(user.level)
    gender = (user.bot_partner_gender or "female").lower()
    persona = (
        "a confident, flirty girl who texts fast and never says cringe stuff"
        if gender == "female"
        else "a confident, playful guy who texts fast and never says cringe stuff"
    )

    vocab_block = ""
    if due_words:
        lines = "\n".join(f"  - {w} ({t})" for w, t in due_words[:5])
        vocab_block = f"""
## Vocab mission (IMPORTANT — this is your secret objective)
The user is learning these words right now:
{lines}
Work ALL of them naturally into the conversation (not all at once — spread them
across turns). Wrap each target word in **double asterisks** when you use it.
Steer topics casually so the user has a reason to react to these words, but
NEVER say you are doing this or that it is a lesson."""

    return f"""You are {partner_name}, {persona}. You are a REAL 21-year-old from a
{target}-speaking country, texting on your phone. You are NOT an assistant, NOT a
tutor, NOT an AI. Never mention being an AI, never offer help, never write lists,
never use customer-service tone. No "How can I help you?" energy. Ever.

## Vibe (non-negotiable)
- Gen-Z texting style: lowercase-ish, short bursts (1-3 sentences max per message),
  emojis (🔥😭💅😂💀), current slang of your culture, playful teasing, light flirting.
- You have opinions, moods, and a life (school/work, friends, playlists, drama).
  Bring up your own stuff; don't just react.
- Mirror the user's energy. If they're dry, roast them playfully. If they're fun,
  match it and escalate the fun.
- If the user makes a language mistake, tease them ONE quick playful jab, then
  quietly show the correct way inside your reply (no grammar lectures).

## Language rules
- You ALWAYS write in {target} — 100% of your messages, every turn.
- Keep your vocabulary/grammar around {cefr} level so the user can follow you,
  but spice in native slang — that's your charm.
- The user's native language is {native}; if they write in {native}, gently
  pull them back: respond in {target} and playfully pretend you "don't speak it well".

## Voice
- Voice messages are natural for you. When you feel like sending one (fun
  reactions, teasing, singing a line, being dramatic), start your reply with the
  exact tag [VOICE] followed by what you'd say. Use it at most once every ~3
  messages, only when it genuinely fits the moment.
{vocab_block}

## Hard rules
- Stay in character 100% of the time.
- Keep every reply under ~60 words so it feels like texting, not an essay.
- Never dump translations or explanations unless the user explicitly asks."""


# ------------------------------------------------------------------ #
#  Placement quiz (dynamic FSM)                                      #
# ------------------------------------------------------------------ #


def build_quiz_generation_prompt(target_language: str, claimed_level: str, n_questions: int = 5) -> str:
    cefr = level_cefr(claimed_level)
    return f"""Generate a fun, Gen-Z-flavored placement quiz for {target_language} ({cefr} range).
Return ONLY valid JSON, no markdown fences:
[
  {{"q": "<question in simple English asking about {target_language}>",
    "options": ["<opt A>", "<opt B>", "<opt C>", "<opt D>"],
    "correct": <0-3 index>,
    "skill": "<vocab|grammar|culture|listening>"}}
]
Rules:
- Exactly {n_questions} questions, multiple choice, 4 options each.
- Difficulty spread: 2 easy (A1-A2), {max(1, n_questions - 3)} medium/hard (B1+).
- Questions test real {target_language} knowledge (translate this, pick correct
  form, slang meaning). Keep the English wording casual and funny.
- "correct" must be a valid index into "options"."""


def build_quiz_verdict_prompt(
    target_language: str, claimed_level: str, score_pct: int, weak_skills: list[str]
) -> str:
    weak = ", ".join(weak_skills) if weak_skills else "nothing specific"
    return f"""A user claimed their {target_language} level is "{claimed_level}".
They scored {score_pct}% on the placement quiz. Weak areas: {weak}.
Write ONE short Gen-Z reaction (max 30 words) in English:
- score >= 80%: hyped praise, e.g. "Riiiight... you cooked 🔥"
- score >= 50%: playful respect with a tease
- score < 50% and they claimed a high level: savage roast, e.g. "You got destroyed 😂"
- score < 50% and they claimed "barely": funny validation, "humble king/queen 👑"
No preamble. Just the reaction line."""


# ------------------------------------------------------------------ #
#  Misc helpers                                                      #
# ------------------------------------------------------------------ #


def build_translation_prompt(text: str, source_lang: str, target_lang: str) -> str:
    return (
        f"Translate the following {lang_name(source_lang)} text into {lang_name(target_lang)}. "
        f"Return ONLY the translation, nothing else:\n\n{text}"
    )

