from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from database import crud
import utils.i18n as i18n

router = Router(name="settings")

def model_switcher_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Groq (Llama-3)", callback_data="set_model:groq"),
            InlineKeyboardButton(text="Gemini (Flash)", callback_data="set_model:gemini"),
        ],
        [
            InlineKeyboardButton(text="OpenRouter (GPT-4o)", callback_data="set_model:openrouter"),
        ]
    ])

@router.message(Command("settings"))
async def cmd_settings(message: Message) -> None:
    user = await crud.get_user(message.from_user.id)
    if not user:
        return
    current_model = user.selected_model_id or "Default"
    await message.answer(f"Active AI Engine: {current_model}\nChoose a new AI Engine:", reply_markup=model_switcher_kb())

@router.callback_query(F.data.startswith("set_model:"))
async def cb_set_model(cb: CallbackQuery) -> None:
    model_id = cb.data.split(":")[1]
    user = await crud.get_user(cb.from_user.id)
    if user:
        user.selected_model_id = model_id
        await cb.message.answer(f"AI Engine changed to: {model_id} ✅")
        await cb.answer()
