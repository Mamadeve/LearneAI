"""Glass-style inline keyboards for the onboarding flow (and shared pieces)."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import utils.i18n as i18n

# Displayed in native script so users instantly recognize their language.
LANGUAGES: list[tuple[str, str]] = [
    ("🇮🇷 فارسی", "fa"), ("🇬🇧 English", "en"),
    ("🇪🇸 Español", "es"), ("🇫🇷 Français", "fr"),
    ("🇩🇪 Deutsch", "de"), ("🇸🇦 العربية", "ar"),
    ("🇹🇷 Türkçe", "tr"), ("🇷🇺 Русский", "ru"),
    ("🇨🇳 中文", "zh"), ("🇯🇵 日本語", "ja"),
    ("🇰🇷 한국어", "ko"), ("🇮🇳 हिन्दी", "hi"),
    ("🌐 Other…", "other"),
]

TARGET_LANGUAGES: list[tuple[str, str]] = [
    ("🇬🇧 English", "en"), ("🇪🇸 Spanish", "es"), ("🇫🇷 French", "fr"),
    ("🇩🇪 German", "de"), ("🇹🇷 Turkish", "tr"), ("🇷🇺 Russian", "ru"),
    ("🇮🇷 Persian", "fa"), ("🇸🇦 Arabic", "ar"), ("🇨🇳 Chinese", "zh"),
    ("🇯🇵 Japanese", "ja"), ("🇰🇷 Korean", "ko"), ("🇮🇳 Hindi", "hi"),
]

LEVEL_KEYS = ("barely", "beginner", "intermediate", "good", "advanced")

GOAL_OPTIONS = (10, 20, 30, 50, 100)


def _glass(label: str, data: str) -> InlineKeyboardButton:
    """Single glass button: subtle frame + emoji, generous tap target."""
    return InlineKeyboardButton(text=f"┃ {label} ┃", callback_data=data)


def languages_kb(prefix: str = "onb:lang") -> InlineKeyboardMarkup:
    rows = [
        [_glass(label, f"{prefix}:{code}") for label, code in LANGUAGES[i : i + 2]]
        for i in range(0, len(LANGUAGES), 2)
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def target_languages_kb(prefix: str = "onb:target") -> InlineKeyboardMarkup:
    rows = [
        [_glass(label, f"{prefix}:{code}") for label, code in TARGET_LANGUAGES[i : i + 2]]
        for i in range(0, len(TARGET_LANGUAGES), 2)
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def levels_kb(lang: str = "en", prefix: str = "onb:lvl") -> InlineKeyboardMarkup:
    rows = [
        [_glass(i18n.t(lang, f"levels.{key}"), f"{prefix}:{key}")]
        for key in LEVEL_KEYS
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def quiz_options_kb(q_idx: int, options: list[str], lang: str = "en") -> InlineKeyboardMarkup:
    """Options for question #q_idx — answer letters A/B/C/D for the vibe."""
    letters = ("🅰️", "🅱️", "🅲", "🅳")
    rows = [
        [_glass(f"{letters[i]} {opt[:48]}", f"onb:quiz:{q_idx}:{i}")]
        for i, opt in enumerate(options[:4])
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def goals_kb(lang: str = "en", prefix: str = "onb:goal") -> InlineKeyboardMarkup:
    rows = [
        [_glass(f"{n} 🔥", f"{prefix}:{n}") for n in GOAL_OPTIONS[i : i + 3]]
        for i in range(0, len(GOAL_OPTIONS), 3)
    ]
    rows.append([_glass(i18n.t(lang, "goals.custom"), f"{prefix}:custom")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
