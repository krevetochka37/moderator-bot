"""Database operations for Moderator Bot"""
import hashlib
import logging
import os
from pathlib import Path
from typing import Optional

import asyncpg
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Загружаем переменные окружения из .env файла
PROJECT_ROOT = Path(__file__).resolve().parents[2]
dotenv_path = PROJECT_ROOT / ".env"
if dotenv_path.exists():
    load_dotenv(dotenv_path=dotenv_path)
else:
    load_dotenv()


async def _get_db_conn():
    """Создает соединение с PostgreSQL БД с повторами при временных сбоях."""
    for attempt in range(5):
        try:
            return await asyncpg.connect(
                host=os.getenv("DB_HOST", "localhost"),
                port=int(os.getenv("DB_PORT", "6432")),
                database=os.getenv("DB_NAME", "refbot"),
                user=os.getenv("DB_USER", "postgres"),
                password=os.getenv("DB_PASSWORD", ""),
                timeout=int(os.getenv("DB_TIMEOUT", "30")),
            )
        except (asyncpg.PostgresConnectionError, OSError):
            if attempt < 4:
                continue
            raise


async def db_init():
    """Инициализация БД - проверка существования таблиц (не создает их, только проверяет)"""
    conn = await _get_db_conn()
    try:
        await conn.execute("SELECT 1")
    finally:
        await conn.close()


async def db_is_admin(user_id: str) -> bool:
    """Проверяет, является ли пользователь админом"""
    user_id = str(user_id) if user_id is not None else None
    conn = await _get_db_conn()
    try:
        result = await conn.fetchval(
            "SELECT COUNT(*) FROM admins WHERE user_id = $1 AND is_active = TRUE",
            user_id,
        )
        return result > 0
    except Exception as e:
        logger.error(f"Ошибка проверки админа: {e}", exc_info=True)
        return False
    finally:
        await conn.close()


async def db_get_user(user_id: int):
    """Получает данные пользователя"""
    conn = await _get_db_conn()
    try:
        row = await conn.fetchrow(
            """
            SELECT user_id, referrer_id, lang, balance, joined_at, access_code_used,
                   terms_accepted_at, username, COALESCE(reserved_balance, 0), channel_subscribed_at
            FROM users
            WHERE user_id=$1
            """,
            user_id,
        )
        if row:
            return {
                "user_id": row["user_id"],
                "referrer_id": row["referrer_id"],
                "lang": row["lang"],
                "balance": row["balance"],
                "joined_at": row["joined_at"],
                "access_code_used": row["access_code_used"],
                "terms_accepted_at": row.get("terms_accepted_at"),
                "username": row.get("username"),
                "reserved_balance": row.get("reserved_balance", 0),
                "channel_subscribed_at": row.get("channel_subscribed_at"),
            }
        return None
    finally:
        await conn.close()


async def db_get_user_by_username(username: str):
    """Получает данные пользователя по username (без @), регистронезависимо"""
    if not username:
        return None

    normalized = username.strip()
    if not normalized:
        return None

    normalized = normalized.lstrip("@").lower()

    conn = await _get_db_conn()
    try:
        row = await conn.fetchrow(
            """
            SELECT user_id, referrer_id, lang, balance, joined_at, access_code_used,
                   terms_accepted_at, username, COALESCE(reserved_balance, 0), channel_subscribed_at
            FROM users
            WHERE LOWER(username) = $1
            """,
            normalized,
        )
        if row:
            return {
                "user_id": row["user_id"],
                "referrer_id": row["referrer_id"],
                "lang": row["lang"],
                "balance": row["balance"],
                "joined_at": row["joined_at"],
                "access_code_used": row["access_code_used"],
                "terms_accepted_at": row.get("terms_accepted_at"),
                "username": row.get("username"),
                "reserved_balance": row.get("reserved_balance", 0),
                "channel_subscribed_at": row.get("channel_subscribed_at"),
            }
        return None
    finally:
        await conn.close()


async def db_add_credits(user_id: int, delta: int) -> None:
    """Добавляет кредиты пользователю"""
    conn = await _get_db_conn()
    try:
        async with conn.transaction():
            await conn.execute(
                "INSERT INTO users(user_id, balance) VALUES($1,0) ON CONFLICT(user_id) DO NOTHING",
                user_id,
            )
            await conn.execute(
                "UPDATE users SET balance = COALESCE(balance, 0) + $1 WHERE user_id=$2",
                delta,
                user_id,
            )
    finally:
        await conn.close()


async def db_user_has_active_generations(user_id: int) -> bool:
    """Проверяет, есть ли у пользователя генерации не в финальном статусе"""
    conn = await _get_db_conn()
    try:
        result = await conn.fetchval(
            """
            SELECT EXISTS(
                SELECT 1
                FROM generation_queue
                WHERE user_id = $1
                  AND COALESCE(status, 'processing') NOT IN ('failed', 'success', 'completed')
            )
            """,
            user_id,
        )
        return bool(result)
    except Exception as e:
        logger.error(f"Ошибка проверки активных генераций пользователя {user_id}: {e}", exc_info=True)
        return True
    finally:
        await conn.close()


async def db_reset_reserved_balance(user_id: int) -> int:
    """Обнуляет reserved_balance пользователя и возвращает сумму резервов"""
    conn = await _get_db_conn()
    try:
        amount = await conn.fetchval(
            "SELECT COALESCE(reserved_balance, 0) FROM users WHERE user_id = $1",
            user_id,
        )
        if not amount or amount <= 0:
            return 0

        async with conn.transaction():
            await conn.execute(
                "UPDATE users SET reserved_balance = 0, updated_at = NOW() WHERE user_id = $1",
                user_id,
            )
        return int(amount)
    except Exception as e:
        logger.error(f"Ошибка сброса резерва для пользователя {user_id}: {e}", exc_info=True)
        return 0
    finally:
        await conn.close()


async def db_get_bot_by_token_hash(token_hash: str):
    """Получает бота по хэшу токена (используется в жалобах)"""
    conn = await _get_db_conn()
    try:
        # Получаем всех ботов и ищем по хэшу токена
        bots = await conn.fetch("SELECT * FROM bot WHERE is_active = TRUE")

        for bot in bots:
            bot_token = bot["token"]
            bot_token_hash = hashlib.md5(bot_token.encode()).hexdigest()[:12]
            if bot_token_hash == token_hash:
                return tuple(bot)

        return None
    finally:
        await conn.close()


async def db_list_active_bots():
    """Возвращает только активные боты"""
    conn = await _get_db_conn()
    try:
        rows = await conn.fetch(
            "SELECT * FROM bot WHERE is_active = TRUE ORDER BY created_at DESC"
        )
        return [tuple(row) for row in rows]
    finally:
        await conn.close()


async def db_update_payment_status_by_id(payment_id: int, status: str) -> bool:
    """Обновляет статус платежа по внутреннему payment_id"""
    conn = await _get_db_conn()
    try:
        async with conn.transaction():
            result = await conn.execute(
                """
                UPDATE payments
                SET status = $1, updated_at = NOW()
                WHERE id = $2
                """,
                status,
                payment_id,
            )
            # asyncpg.execute возвращает строку вида "UPDATE N"
            if result == "UPDATE 0":
                logger.warning(f"Платеж {payment_id} не найден для обновления статуса")
                return False
            logger.info(f"Статус платежа {payment_id} обновлен на '{status}'")
            return True
    except Exception as e:
        logger.error(f"Ошибка обновления статуса платежа по id: {e}", exc_info=True)
        return False
    finally:
        await conn.close()


async def db_get_payments_by_user(user_id: int, limit: int = 50) -> list[dict]:
    """Возвращает последние платежи пользователя"""
    conn = await _get_db_conn()
    try:
        rows = await conn.fetch(
            """
            SELECT id, amount, payment_provider, status, created_at, updated_at,
                   external_payment_id, bot_owner_id, bot_id, payment_url
            FROM payments
            WHERE user_id = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            user_id,
            limit,
        )
        payments = []
        for row in rows:
            payments.append(
                {
                    "id": row["id"],
                    "amount": row["amount"],
                    "payment_provider": row["payment_provider"],
                    "status": row["status"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "external_payment_id": row["external_payment_id"],
                    "bot_owner_id": row["bot_owner_id"],
                    "bot_id": row["bot_id"],
                    "payment_url": row["payment_url"],
                }
            )
        return payments
    except Exception as e:
        logger.error(f"Ошибка получения платежей пользователя {user_id}: {e}", exc_info=True)
        return []
    finally:
        await conn.close()


async def db_get_task_by_id(task_id: int):
    """Получает задачу по ID"""
    conn = await _get_db_conn()
    try:
        task = await conn.fetchrow(
            """
            SELECT id, user_id, priority, category, image_path, comfy_url, is_finished, created_at, updated_at, bot_id, subcategory_id, cost
            FROM generation_queue
            WHERE id = $1
            """,
            task_id,
        )
        if task:
            return tuple(task)
        return None
    except Exception as e:
        logger.error(f"Ошибка получения задачи по ID: {e}", exc_info=True)
        return None
    finally:
        await conn.close()


async def db_list_pending_complaints(not_dispatched_only: bool = True) -> list:
    """Возвращает список жалоб в статусе pending. Если not_dispatched_only=True — только неотправленные."""
    conn = await _get_db_conn()
    try:
        base_query = """
            SELECT c.id,
                   c.user_id,
                   c.message_id,
                   c.file_path,
                   c.category,
                   c.bot_id,
                   c.subcategory_id,
                   c.status,
                   c.dispatched,
                   c.created_at,
                   gq.image_path AS source_file_path,
                   c.generation_id
            FROM complaints c
            LEFT JOIN generation_queue gq ON c.generation_id = gq.id
            WHERE c.status='pending'
        """
        if not_dispatched_only:
            base_query += " AND c.dispatched = FALSE"
        base_query += " ORDER BY c.created_at ASC"

        rows = await conn.fetch(base_query)
        return [tuple(row) for row in rows]
    except Exception as e:
        logger.error(f"Ошибка получения pending жалоб: {e}", exc_info=True)
        return []
    finally:
        await conn.close()


async def db_get_user_pending_complaints(user_id: int, limit: int = 5) -> list:
    """Возвращает pending-жалобы конкретного пользователя"""
    conn = await _get_db_conn()
    try:
        rows = await conn.fetch(
            """
            SELECT c.id,
                   c.user_id,
                   c.message_id,
                   c.file_path,
                   c.category,
                   c.bot_id,
                   c.subcategory_id,
                   c.status,
                   c.dispatched,
                   c.created_at,
                   gq.image_path AS source_file_path,
                   c.generation_id
            FROM complaints c
            LEFT JOIN generation_queue gq ON c.generation_id = gq.id
            WHERE c.user_id = $1 AND c.status = 'pending'
            ORDER BY c.created_at DESC
            LIMIT $2
            """,
            user_id,
            limit,
        )
        return [tuple(row) for row in rows]
    except Exception as e:
        logger.error(f"Ошибка получения жалоб пользователя {user_id}: {e}", exc_info=True)
        return []
    finally:
        await conn.close()


async def db_mark_complaints_dispatched(ids: list[int]) -> bool:
    """Помечает список жалоб как отправленные админам (dispatched = TRUE)"""
    if not ids:
        return True
    conn = await _get_db_conn()
    try:
        async with conn.transaction():
            await conn.execute(
                "UPDATE complaints SET dispatched = TRUE, updated_at=NOW() WHERE id = ANY($1::int[])",
                ids,
            )
        return True
    except Exception as e:
        logger.error(f"Ошибка пометки жалоб как отправленных: {e}", exc_info=True)
        return False
    finally:
        await conn.close()


async def db_update_complaint_status(complaint_id: int, status: str) -> bool:
    """Обновляет статус жалобы (accepted/rejected)"""
    conn = await _get_db_conn()
    try:
        async with conn.transaction():
            await conn.execute(
                """
                UPDATE complaints
                SET status=$1, updated_at=NOW()
                WHERE id=$2
                """,
                status,
                complaint_id,
            )
        return True
    except Exception as e:
        logger.error(f"Ошибка обновления статуса жалобы: {e}", exc_info=True)
        return False
    finally:
        await conn.close()


async def db_get_complaint_by_id(complaint_id: int) -> dict | None:
    """Получает жалобу по ID"""
    conn = await _get_db_conn()
    try:
        row = await conn.fetchrow(
            """
            SELECT c.id,
                   c.user_id,
                   c.message_id,
                   c.file_path,
                   gq.image_path AS source_file_path,
                   c.category,
                   c.bot_id,
                   c.subcategory_id,
                   c.status,
                   c.dispatched,
                   c.created_at,
                   c.generation_id
            FROM complaints c
            LEFT JOIN generation_queue gq ON c.generation_id = gq.id
            WHERE c.id=$1
            """,
            complaint_id,
        )
        if row:
            return {
                "id": row["id"],
                "user_id": row["user_id"],
                "message_id": row["message_id"],
                "file_path": row["file_path"],
                "source_file_path": row["source_file_path"],
                "category": row["category"],
                "bot_id": row["bot_id"],
                "subcategory_id": row["subcategory_id"],
                "status": row["status"],
                "dispatched": row["dispatched"],
                "created_at": row["created_at"],
                "generation_id": row["generation_id"],
            }
        return None
    except Exception as e:
        logger.error(f"Ошибка получения жалобы: {e}", exc_info=True)
        return None
    finally:
        await conn.close()


async def db_get_user_generations(user_id: int, limit: int = 5) -> list:
    """Возвращает последние завершенные генерации пользователя"""
    conn = await _get_db_conn()
    try:
        rows = await conn.fetch(
            """
            SELECT gq.id, gq.category, gq.status, gq.created_at, gq.updated_at,
                   gq.image_path, gq.bot_id, gq.subcategory_id
            FROM generation_queue gq
            WHERE gq.user_id = $1 AND gq.status = 'success'
            ORDER BY gq.updated_at DESC
            LIMIT $2
            """,
            user_id,
            limit,
        )
        generations = []
        for row in rows:
            generations.append(
                {
                    "id": row["id"],
                    "category": row["category"],
                    "status": row["status"],
                    "created_at": row["created_at"],
                    "completed_at": row["updated_at"],
                    "media_path": row["image_path"],
                    "bot_id": row["bot_id"],
                    "subcategory_id": row["subcategory_id"],
                }
            )
        return generations
    except Exception as e:
        logger.error(f"Ошибка получения генераций пользователя {user_id}: {e}", exc_info=True)
        return []
    finally:
        await conn.close()


async def db_get_generation_cost_by_subcategory(subcategory_id: int) -> int:
    """
    Получает стоимость генерации по подкатегории.
    Если у сценария указана сложность, использует новый расчет на основе сложности и времени.
    Иначе использует старую логику (price из subcategories).
    """
    conn = await _get_db_conn()
    try:
        row = await conn.fetchrow(
            """
            SELECT s.duration, s.price, sc.difficulty
            FROM subcategories s
            JOIN scenario sc ON s.scenario_id = sc.id
            WHERE s.id = $1 AND s.is_active = TRUE
            """,
            subcategory_id,
        )

        if not row:
            return 200  # Дефолтная стоимость

        duration = row["duration"] if row["duration"] else 10
        old_price = row["price"] if row["price"] else None
        difficulty = row.get("difficulty")

        # Если у сценария есть difficulty, используем новый расчет
        if difficulty:
            # Матрица стоимости [duration: [low, medium, high]]
            cost_matrix = {
                5: {"low": 70, "medium": 90, "high": 110},
                10: {"low": 90, "medium": 110, "high": 130},
                15: {"low": 110, "medium": 130, "high": 150},
            }

            # Определяем ближайшую длительность (5, 10 или 15)
            if duration <= 5:
                duration_key = 5
            elif duration <= 10:
                duration_key = 10
            else:
                duration_key = 15

            difficulty = difficulty.lower()
            cost = cost_matrix.get(duration_key, {}).get(difficulty, 110)  # Дефолт 110
            return cost

        # Иначе используем старую логику (price из subcategories)
        if old_price is not None:
            return old_price

        return 200  # Дефолтная стоимость
    except Exception as e:
        logger.error(f"Ошибка получения стоимости генерации: {e}", exc_info=True)
        return 200
    finally:
        await conn.close()
