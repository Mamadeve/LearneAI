"""LearneAI entry point — Webhook server (FastAPI) and bot wiring.

Runs via Uvicorn. Reads PORT env var, defaults to 8000. Includes optional keep-alive task.
"""
from __future__ import annotations

import asyncio
import logging
import os
import random
import sys
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, Update

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


# Anti-Sleep Keep-Alive Task
async def anti_sleep_task(app_url: str):
    """Pings the /healthz endpoint at randomized intervals (10-14m) to prevent HF pause."""
    health_url = f"{app_url.rstrip('/')}/healthz"
    logger.info("Anti-sleep task started, targeting: %s", health_url)
    async with httpx.AsyncClient(timeout=30) as client:
        while True:
            # Sleep between 10 to 14 minutes
            sleep_time = random.uniform(10 * 60, 14 * 60)
            await asyncio.sleep(sleep_time)
            try:
                resp = await client.get(health_url)
                logger.info("Anti-sleep ping successful: HTTP %s", resp.status_code)
            except Exception as e:
                logger.warning("Anti-sleep ping failed: %s", e)


_anti_sleep_task_ref = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Initializing database schemas (Supabase)...")
    await init_db()
    logger.info("Database schemas initialized.")

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
    
    app_url = settings.app_url or os.getenv("APP_URL")
    if app_url:
        webhook_target = f"{app_url.rstrip('/')}/webhook"
        await bot.set_webhook(webhook_target)
        logger.info("Webhook set to %s", webhook_target)
        
        # Start anti-sleep if enabled
        if settings.enable_anti_sleep:
            global _anti_sleep_task_ref
            _anti_sleep_task_ref = asyncio.create_task(anti_sleep_task(app_url))
    else:
        logger.warning("APP_URL not set! Webhook will not be configured.")
    
    yield
    
    # Shutdown
    if _anti_sleep_task_ref:
        _anti_sleep_task_ref.cancel()
    await bot.delete_webhook()
    await close_engine()
    logger.info("Engine disposed — bye 👋")


app = FastAPI(lifespan=lifespan)

@app.post("/webhook")
async def telegram_webhook(request: Request):
    """Handle incoming Telegram updates."""
    data = await request.json()
    update = Update(**data)
    await dp.feed_update(bot, update)
    return {"status": "ok"}

@app.get("/")
@app.get("/healthz")
async def health_check():
    """Hugging Face / UptimeRobot health check endpoint."""
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
