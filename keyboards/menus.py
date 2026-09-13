"""Main menu keyboard + text (dashboard lives in handlers/dashboard later)."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import utils.i18n as i18n


def _glass(label: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=f"┃ {label} ┃", callback_data=data)


def main_menu_kb(lang: str = "en", streak: int = 0) -> InlineKeyboardMarkup:
    streak_label = i18n.t(lang, "menu.streak", n=streak)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_glass(i18n.t(lang, "menu.learn"), "menu:learn"), _glass(i18n.t(lang, "menu.roleplay"), "menu:roleplay")],
            [_glass(i18n.t(lang, "menu.dashboard"), "menu:dashboard"), _glass(streak_label, "menu:streak")],
        ]
    )


def main_menu_text(lang: str = "en", name: str = "") -> str:
    return f"{i18n.t(lang, 'menu.title')}\n\n👋 {name}"
