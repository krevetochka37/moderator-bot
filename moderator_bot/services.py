import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Sequence

from moderator_bot.database.operations import (
    db_is_admin,
    db_add_credits,
    db_get_complaint_by_id,
    db_get_generation_cost_by_subcategory,
    db_get_payments_by_user,
    db_get_task_by_id,
    db_get_user,
    db_get_user_by_username,
    db_get_user_generations,
    db_get_user_pending_complaints,
    db_list_active_bots,
    db_list_pending_complaints,
    db_mark_complaints_dispatched,
    db_reset_reserved_balance,
    db_update_complaint_status,
    db_update_payment_status_by_id,
    db_user_has_active_generations,
)

from .models import (
    COMPLAINT_DECISIONS,
    ComplaintDTO,
    ComplaintDecisionResult,
    ComplaintRender,
    GenerationRender,
    PaymentRender,
    ReleaseReservedResult,
    ResendGenerationData,
    TaskDTO,
    UserInfoRender,
    format_datetime,
    username_display,
)

logger = logging.getLogger(__name__)


async def is_moderator(user_id: int) -> bool:
    return await db_is_admin(user_id)


def _format_complaint_text(
    complaint: ComplaintDTO,
    username_label: str,
    include_user_id: bool,
    header_template: str,
) -> str:
    created_str = format_datetime(complaint.created_at)
    filename_display = os.path.basename(complaint.file_path or "") or "Не указан"
    user_line = (
        f"👤 <b>Пользователь:</b> {username_label} (ID: {complaint.user_id})\n"
        if include_user_id
        else f"👤 <b>Пользователь:</b> {username_label}\n"
    )
    header = f"📋 <b>{header_template.format(complaint.id)}</b>\n\n"

    return (
        f"{header}"
        f"{user_line}"
        f"📁 <b>Категория:</b> {complaint.category or 'Не указана'}\n"
        f"🤖 <b>Бот:</b> {complaint.bot_id or 'Не указан'}\n"
        f"🕒 <b>Время:</b> {created_str}\n"
        f"🗂 <b>Файл:</b> {filename_display}\n"
    )


async def _build_complaint_render(
    row: Sequence[Any],
    include_user_id: bool,
    header_template: str,
    target_user_id: int | None = None,
) -> ComplaintRender:
    complaint = ComplaintDTO.from_row(row)
    user_id = target_user_id or complaint.user_id
    user_info = await db_get_user(user_id)
    username_label = username_display(user_info, user_id)
    text = _format_complaint_text(complaint, username_label, include_user_id, header_template)
    return ComplaintRender(
        complaint_id=complaint.id,
        text=text,
        video_path=complaint.file_path,
        source_path=complaint.source_path,
    )


async def get_pending_complaints(
    *,
    limit: int = 5,
    include_user_id: bool = True,
    header_template: str = "Поступила жалоба #{}",
) -> list[ComplaintRender]:
    complaints = await db_list_pending_complaints(False)
    complaints = complaints[:limit]
    renders = []
    for row in complaints:
        renders.append(
            await _build_complaint_render(
                row,
                include_user_id=include_user_id,
                header_template=header_template,
            )
        )
    return renders


async def get_user_complaints(user_id: int, limit: int = 5) -> list[ComplaintRender]:
    complaints = await db_get_user_pending_complaints(user_id, limit)
    renders = []
    for row in complaints:
        renders.append(
            await _build_complaint_render(
                row,
                include_user_id=True,
                header_template="Жалоба #{}",
                target_user_id=user_id,
            )
        )
    return renders


async def mark_complaints_dispatched(complaint_ids: list[int]) -> None:
    if complaint_ids:
        await db_mark_complaints_dispatched(complaint_ids)


async def apply_complaint_decision(complaint_id: int, action_key: str) -> ComplaintDecisionResult | None:
    complaint = await db_get_complaint_by_id(complaint_id)
    if not complaint:
        return None

    config = COMPLAINT_DECISIONS[action_key]

    await db_update_complaint_status(complaint_id, config["status"])

    user_id = complaint["user_id"]
    generation_cost = 200
    if complaint.get("subcategory_id"):
        generation_cost = await db_get_generation_cost_by_subcategory(complaint["subcategory_id"])

    await db_add_credits(user_id, generation_cost * config["delta_sign"])

    user_message = config["user_message"].format(amount=generation_cost, complaint_id=complaint_id)
    return ComplaintDecisionResult(
        complaint_id=complaint_id,
        user_id=user_id,
        bot_hash=complaint.get("bot_id"),
        user_message=user_message,
        status=config["status"],
        moderator_success=config["moderator_success"],
        moderator_warning=config["moderator_warning"],
    )


def _format_generation_caption(generation: dict[str, Any]) -> str:
    created_str = format_datetime(generation.get("created_at"))
    completed_str = format_datetime(generation.get("completed_at"))
    category = generation.get("category") or "—"
    return (
        f"🎬 <b>Генерация #{generation['id']}</b>\n\n"
        f"📁 <b>Категория:</b> {category}\n"
        f"🕒 <b>Создано:</b> {created_str}\n"
        f"✅ <b>Завершено:</b> {completed_str}\n"
    )


def _format_resend_caption(generation: dict[str, Any]) -> str:
    created_str = format_datetime(generation.get("created_at"))
    completed_str = format_datetime(generation.get("completed_at"))
    category = generation.get("category") or "—"
    subcategory_id = generation.get("subcategory_id") or "—"
    bot_id = generation.get("bot_id") or "—"
    return (
        f"🔄 <b>Переотправка результата #{generation['id']}</b>\n\n"
        f"📁 <b>Категория:</b> {category}\n"
        f"🧩 <b>Subcategory ID:</b> {subcategory_id}\n"
        f"🤖 <b>Бот:</b> {bot_id}\n"
        f"🕒 <b>Создано:</b> {created_str}\n"
        f"✅ <b>Завершено:</b> {completed_str}\n"
    )


async def get_user_generations_overview(user_id: int, limit: int = 5) -> list[GenerationRender]:
    generations = await db_get_user_generations(user_id, limit)
    renders: list[GenerationRender] = []
    for generation in generations:
        media_path = await _find_result_video_for_task(generation["id"])
        if not media_path:
            media_path = generation.get("media_path") or generation.get("image_path")
        renders.append(
            GenerationRender(
                generation_id=generation["id"],
                caption=_format_generation_caption(generation),
                media_path=media_path,
            )
        )
    return renders

async def get_user_generations_for_resend(user_id: int, limit: int = 5) -> list[GenerationRender]:
    generations = await db_get_user_generations(user_id, limit)
    renders: list[GenerationRender] = []
    for generation in generations:
        renders.append(
            GenerationRender(
                generation_id=generation["id"],
                caption=_format_resend_caption(generation),
                media_path=None,
            )
        )
    return renders


async def get_resend_generation_data(generation_id: int) -> ResendGenerationData | None:
    task_row = await db_get_task_by_id(generation_id)
    if not task_row:
        return None
    task = TaskDTO.from_row(task_row)
    media_path = await _find_result_video_for_task(task.id)
    if not media_path:
        media_path = task.image_path
    if not media_path:
        return None
    caption = f"🎬 <b>Переотправка результата #{task.id}</b>\n\n📁 <b>Категория:</b> {task.category or '—'}"
    return ResendGenerationData(
        generation_id=task.id,
        user_id=task.user_id,
        media_path=media_path,
        bot_hash=task.bot_id,
        caption=caption,
    )


async def _find_result_video_for_task(task_id: int) -> str | None:
    """Ищет итоговый видеофайл генерации по ID задачи в output-директории."""
    try:
        project_root = Path(__file__).resolve().parents[1]
        output_base = os.getenv("OUTPUT_DIR") or "output"
        output_dir = project_root / output_base

        # Выполняем проверку существования и поиск файлов в отдельном потоке
        def _search_files():
            if not output_dir.exists() or not output_dir.is_dir():
                return None

            patterns = [
                f"{task_id}_result_*.mp4",
                f"*_{task_id}_result*.mp4",
                f"*{task_id}*result*.mp4",
            ]

            for pattern in patterns:
                matches = sorted(output_dir.glob(pattern))
                if matches:
                    return str(matches[0])
            return None

        return await asyncio.to_thread(_search_files)
    except Exception as e:
        logger.warning(f"Failed to find result video for task {task_id}: {e}")
        return None


async def release_reserved_balance(user_id: int) -> ReleaseReservedResult:
    user_data = await db_get_user(user_id)
    if not user_data:
        return ReleaseReservedResult(False, 0, "❌ Пользователь не найден", "❌ Пользователь не найден")

    reserved = int(user_data.get("reserved_balance") or 0)
    if reserved <= 0:
        return ReleaseReservedResult(False, 0, "ℹ️ Резервов нет", "ℹ️ Резервов нет")

    has_active = await db_user_has_active_generations(user_id)
    if has_active:
        return ReleaseReservedResult(
            False,
            reserved,
            "⚠️ Есть активные генерации, резерв снять нельзя",
            "⚠️ Есть активные генерации, резерв снять нельзя",
        )

    released = await db_reset_reserved_balance(user_id)
    if released <= 0:
        return ReleaseReservedResult(False, 0, "❌ Не удалось снять резерв", "❌ Не удалось снять резерв")

    return ReleaseReservedResult(True, released, f"🧹 Снято {released} зарезервированных кредитов.")

async def get_user_payments(user_id: int, limit: int = 10) -> list[PaymentRender]:
    payments = await db_get_payments_by_user(user_id, limit)
    renders: list[PaymentRender] = []
    for payment in payments:
        created_str = format_datetime(payment.get("created_at"))
        updated_str = format_datetime(payment.get("updated_at"))
        status = payment["status"] or "—"

        text = (
            f"• <b>#{payment['id']}</b> — {payment['amount']} кредитов\n"
            f"  Провайдер: {payment['payment_provider'] or '—'}\n"
            f"  Статус: {status}\n"
            f"  Создан: {created_str}\n"
            f"  Обновлён: {updated_str}\n"
            f"  External ID: {payment.get('external_payment_id') or '—'}"
        )
        renders.append(PaymentRender(payment_id=payment["id"], text=text, status=status))
    return renders


async def set_payment_status_pending(payment_id: int) -> bool:
    return await db_update_payment_status_by_id(payment_id, "pending")

async def lookup_user(query: str) -> UserInfoRender | None:
    normalized = query.strip()
    user_data = None
    if normalized.startswith("@"):
        user_data = await db_get_user_by_username(normalized)
    elif normalized.isdigit():
        user_data = await db_get_user(int(normalized))
    else:
        user_data = await db_get_user_by_username(normalized)
        if not user_data and normalized.lstrip("-").isdigit():
            user_data = await db_get_user(int(normalized))

    if not user_data:
        return None

    balance = user_data.get("balance", 0)
    reserved = user_data.get("reserved_balance", 0)
    username = user_data.get("username") or "—"
    username_display = f"@{username}" if username not in ("—", None) else "—"
    lang = user_data.get("lang") or "—"
    joined_str = format_datetime(user_data.get("joined_at"))

    text = (
        "👤 <b>Информация о пользователе</b>\n\n"
        f"🆔 <b>ID:</b> {user_data['user_id']}\n"
        f"🔗 <b>Username:</b> {username_display}\n"
        f"🌐 <b>Язык:</b> {lang}\n"
        f"📅 <b>Зарегистрирован:</b> {joined_str}\n\n"
        f"💰 <b>Баланс:</b> {balance} кредитов\n"
        f"⛔ <b>Зарезервировано:</b> {reserved} кредитов\n"
    )
    return UserInfoRender(text=text, user_id=user_data["user_id"])
