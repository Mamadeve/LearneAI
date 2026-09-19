from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from database import crud
from aiogram.fsm.context import FSMContext
import utils.i18n as i18n

router = Router(name="settings")

# ------------------------------------------------------------------ #
#  Active Groq models — keep in sync with groq_provider.ACTIVE_MODELS
# ------------------------------------------------------------------ #

ENGINE_BUTTONS = [
    ("⚡ GPT-OSS 20B (سریع و سبک)", "openai/gpt-oss-20b"),
    ("🧠 Qwen 3.8 27B (آموزش زبان و گرامر)", "qwen/qwen3.8-27b"),
    ("🚀 GPT-OSS 120B (قدرتمند)", "openai/gpt-oss-120b"),
]

DEFAULT_ENGINE = "openai/gpt-oss-20b"

# Human-readable labels for display
ENGINE_LABELS: dict[str, str] = {model: label for label, model in ENGINE_BUTTONS}


def model_switcher_kb(current: str | None = None) -> InlineKeyboardMarkup:
    """Build inline keyboard with a ✅ marker on the active engine."""
    rows: list[list[InlineKeyboardButton]] = []
    for label, model_id in ENGINE_BUTTONS:
        display = f"✅ {label}" if model_id == current else label
        rows.append([InlineKeyboardButton(text=display, callback_data=f"engine:{model_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("settings"))
async def cmd_settings(message: Message) -> None:
    user = await crud.get_user(message.from_user.id)
    if not user:
        return
    current = user.selected_model_id or DEFAULT_ENGINE
    label = ENGINE_LABELS.get(current, current)
    await message.answer(
        f"🤖 موتور هوش مصنوعی فعلی: {label}\n\nیک موتور جدید انتخاب کن:",
        reply_markup=model_switcher_kb(current),
    )


@router.callback_query(F.data.startswith("engine:"))
async def cb_set_engine(cb: CallbackQuery) -> None:
    model_id = cb.data.split(":", 1)[1]
    user = await crud.get_user(cb.from_user.id)
    if not user:
        await cb.answer("⚠️ User not found", show_alert=True)
        return

    # Persist to database
    await crud.update_user(cb.from_user.id, selected_model_id=model_id)

    label = ENGINE_LABELS.get(model_id, model_id)
    await cb.message.edit_text(
        f"✅ موتور هوش مصنوعی تغییر کرد به: {label}",
        reply_markup=model_switcher_kb(model_id),
    )
    await cb.answer("Done ✅")


# ------------------------------------------------------------------ #
#  Account Reset
# ------------------------------------------------------------------ #

@router.message(Command("reset"))
async def cmd_reset(message: Message) -> None:
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="بله، اکانتم رو پاک کن", callback_data="reset_account:confirm")],
        [InlineKeyboardButton(text="نه، پشیمون شدم", callback_data="reset_account:cancel")]
    ])
    await message.answer("⚠️ آیا مطمئن هستید؟ تمام پیشرفتها و کلمات شما پاک خواهد شد.", reply_markup=kb)

@router.callback_query(F.data.startswith("reset_account:"))
async def cb_reset_account(cb: CallbackQuery, state: FSMContext) -> None:
    action = cb.data.split(":")[1]
    if action == "cancel":
        await cb.message.edit_text("✅ عملیات ریست لغو شد. پیشرفت شما امن است.")
        return

    # Confirm action
    # We delete the user from DB which cascades to everything else.
    from database.connection import get_session
    from database.models import User
    
    async with get_session() as s:
        user = await s.get(User, cb.from_user.id)
        if user:
            await s.delete(user)
            await s.commit()

    await state.clear()
    await cb.message.edit_text("🔄 اکانت شما پاک شد. در حال راه‌اندازی مجدد...")
    
    # Trigger /start implicitly
    from handlers.onboarding import cmd_start
    await cmd_start(cb.message, state)
