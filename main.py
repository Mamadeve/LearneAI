"""LearneAI entry point — Webhook server (FastAPI) and bot wiring.

Runs via Uvicorn. Exposes /healthz for Render and /webhook for Telegram.
"""
from __future__ import annotations

import logging
import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, Update

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from handlers import learning, onboarding, roleplay, settings as settings_handler
from utils.config import get_settings
from database.connection import close_engine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)
logger = logging.getLogger("learneai")

settings = get_settings()
if not settings.bot_token:
    raise RuntimeError("BOT_TOKEN is missing — copy .env.example to .env and fill it in.")

bot = Bot(
    token=settings.bot_token,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()

# Include routers
dp.include_router(onboarding.router)
dp.include_router(learning.router)
dp.include_router(roleplay.router)
dp.include_router(settings_handler.router)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
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
    
    # Render requires WEBHOOK_URL environment variable to be set
    webhook_url = os.getenv("WEBHOOK_URL")
    if webhook_url:
        await bot.set_webhook(f"{webhook_url}/webhook")
        logger.info(f"Webhook set to {webhook_url}/webhook")
    
    yield
    
    # Shutdown
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

@app.get("/healthz")
async def health_check():
    """Render health check endpoint."""
    return {"status": "healthy"}
