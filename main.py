"""LearneAI entry point — Dummy Webhook server (FastAPI) for Koyeb Health Checks + Long Polling Bot.

Runs via Uvicorn. Reads PORT env var, defaults to 8000.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from handlers import learning, onboarding, roleplay, settings as settings_handler
from utils.config import get_settings
from database.connection import close_engine, init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)
logger = logging.getLogger("learneai")

settings = get_settings()
if not settings.bot_token:
    raise RuntimeError("BOT_TOKEN is missing — set it in your environment variables.")

bot = Bot(
    token=settings.bot_token,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()

dp.include_router(onboarding.router)
dp.include_router(learning.router)
dp.include_router(roleplay.router)
dp.include_router(settings_handler.router)


_polling_task = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Startup Database
    logger.info("Initializing database schemas (Supabase)...")
    await init_db()
    logger.info("Database schemas initialized.")

    # 2. Setup Bot Commands
    await bot.set_my_commands([
        BotCommand(command="start", description="start / restart setup 🚀"),
        BotCommand(command="menu", description="main menu 🏠"),
        BotCommand(command="learn", description="vocab gym (leitner) 📚"),
        BotCommand(command="roleplay", description="las o lus chat 💬"),
        BotCommand(command="settings", description="change AI engine ⚙️"),
        BotCommand(command="end", description="end current chat session 💬"),
    ])
    me = await bot.get_me()
    logger.info("Bot live as @%s (id=%s)", me.username, me.id)
    
    # 3. Drop any existing webhook to prevent conflicts with long polling
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Webhook deleted. Starting long polling...")

    # 4. Start long polling as a background task
    global _polling_task
    _polling_task = asyncio.create_task(dp.start_polling(bot))
    
    yield
    
    # 5. Shutdown
    if _polling_task:
        _polling_task.cancel()
        try:
            await _polling_task
        except asyncio.CancelledError:
            pass
    await close_engine()
    logger.info("Engine disposed — bye 👋")


# FastAPI acts as a dummy web server for Koyeb health checks
app = FastAPI(lifespan=lifespan)


@app.get("/")
@app.get("/health")
@app.get("/healthz")
async def health_check():
    """Koyeb / UptimeRobot health check endpoint."""
    return {"status": "healthy", "server": "koyeb"}


if __name__ == "__main__":
    import uvicorn
    # Koyeb requires listening on a specific port for health checks
    port = int(os.getenv("PORT", 8000))
    logger.info(f"Starting dummy web server on port {port} for health checks...")
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
