#!/usr/bin/env python3
"""
FastAPI приложение для обработки webhook'ов модератор-бота
"""
import logging
import os
import sys
from pathlib import Path

from contextlib import asynccontextmanager
from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.default import DefaultBotProperties
from aiogram.types import Update
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent
dotenv_path = PROJECT_ROOT / ".env"
if dotenv_path.exists():
    load_dotenv(dotenv_path=dotenv_path)
else:
    load_dotenv()

sys.path.insert(0, str(PROJECT_ROOT))

from moderator_bot.config.settings import Settings
import moderator_bot.database.operations as db_ops
from moderator_bot.handlers import dp

logger = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

WEBHOOK_URL = os.getenv("MODERATOR_WEBHOOK_URL")
MODERATOR_BOT_TOKEN = os.getenv("MODERATOR_BOT_TOKEN")

if not MODERATOR_BOT_TOKEN:
    logger.error("MODERATOR_BOT_TOKEN не настроен в .env файле")
    sys.exit(1)

if not WEBHOOK_URL:
    logger.error("MODERATOR_WEBHOOK_URL не настроен в .env файле")
    sys.exit(1)

# Проверяем, что URL использует HTTPS (Telegram требует HTTPS для webhook)
if not WEBHOOK_URL.startswith("https://"):
    logger.error(
        f"❌ MODERATOR_WEBHOOK_URL должен начинаться с 'https://'\n"
        f"Текущее значение: {WEBHOOK_URL}\n"
        f"Для локальной разработки используйте ngrok или другой HTTPS туннель."
    )
    sys.exit(1)

settings = Settings.load()
proxy_url = settings.get_proxy_url()

session = AiohttpSession(limit=int(os.getenv("AIOHTTP_SESSION_LIMIT", "100")))
bot = Bot(
    token=MODERATOR_BOT_TOKEN,
    session=session,
    default=DefaultBotProperties(parse_mode="HTML"),
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db_ops.db_init()
    logger.info("Database initialized")
    
    # Удаляем старый webhook (если был) для гарантии чистого состояния
    try:
        await bot.delete_webhook()
        logger.info("Старый webhook удалён (если был)")
    except Exception as e:
        logger.warning(f"Предупреждение при удалении старого webhook: {e}")
    
    # Устанавливаем новый webhook
    webhook_path = f"{WEBHOOK_URL}/moderator"
    try:
        await bot.set_webhook(
            url=webhook_path,
            drop_pending_updates=True
        )
        logger.info(f"✅ Webhook установлен: {webhook_path}")
        
        # Проверяем, что webhook действительно установлен
        webhook_info = await bot.get_webhook_info()
        if webhook_info.url == webhook_path:
            logger.info(f"✅ Webhook подтверждён: {webhook_info.url}")
        else:
            logger.warning(f"⚠️ Webhook URL не совпадает! Ожидалось: {webhook_path}, получено: {webhook_info.url}")
    except Exception as e:
        logger.error(f"❌ Ошибка установки webhook: {e}", exc_info=True)
        raise
    
    yield
    
    try:
        await bot.delete_webhook()
        logger.info("Webhook удалён")
    except Exception as e:
        logger.error(f"Ошибка удаления webhook: {e}")
    
    await bot.session.close()


app = FastAPI(lifespan=lifespan)


@app.post("/moderator")
async def handle_webhook(update: Update):
    try:
        # Определяем тип обновления
        if update.message:
            update_type = "message"
            user_id = update.message.from_user.id if update.message.from_user else None
        elif update.callback_query:
            update_type = "callback_query"
            user_id = update.callback_query.from_user.id if update.callback_query.from_user else None
        else:
            update_type = "other"
            user_id = None
        
        logger.info(f"📨 Получено обновление: {update_type}, update_id={update.update_id}, user_id={user_id}")
        
        await dp.feed_update(bot=bot, update=update)
        return JSONResponse({"ok": True})
    except Exception as e:
        logger.error(f"Ошибка обработки update: {e}", exc_info=True)
        return JSONResponse({"ok": False})


@app.get("/")
async def root():
    return {
        "status": "ok",
        "bot": "moderator",
        "webhook_endpoint": "/moderator",
        "health_endpoint": "/health"
    }


@app.get("/health")
async def health_check():
    return {"status": "ok", "bot": "moderator"}



