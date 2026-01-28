import logging
from pathlib import Path
from typing import Optional

from aiogram import Bot
from aiogram.types import FSInputFile

from moderator_bot.database.operations import db_get_bot_by_token_hash, db_list_active_bots

from . import services
from .keyboards import build_complaint_status_keyboard
from .models import BotRecord, ComplaintDecisionResult

PROJECT_ROOT = Path(__file__).resolve().parents[1]
logger = logging.getLogger(__name__)


def resolve_media_source(path: str | None) -> tuple[object | None, str | None]:
    """Возвращает объект для отправки (FSInputFile или URL) и его путь для логов."""
    if not path:
        return None, None

    normalized = path.strip()
    if not normalized:
        return None, None

    if normalized.startswith(("http://", "https://", "attach://")):
        return normalized, normalized

    candidate = Path(normalized)
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate

    if candidate.exists():
        return FSInputFile(str(candidate)), str(candidate)

    return None, str(candidate)


async def get_bot_record_for_user(bot_hash: Optional[str] = None) -> Optional[BotRecord]:
    """Получает BotRecord по bot_hash или возвращает первый активный бот."""
    if bot_hash:
        bot_row = await db_get_bot_by_token_hash(bot_hash)
        if bot_row:
            return BotRecord.from_row(bot_row)

    active_bots = await db_list_active_bots()
    if active_bots:
        return BotRecord.from_row(active_bots[0])

    return None


async def process_complaint_decision(
    *,
    complaint_id: int,
    action_key: str,
) -> tuple[bool, ComplaintDecisionResult | None, Optional[object]]:
    result = await services.apply_complaint_decision(complaint_id, action_key)
    if not result:
        return False, None, None

    keyboard = build_complaint_status_keyboard(result.complaint_id, result.status)
    return True, result, keyboard

