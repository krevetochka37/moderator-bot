import logging
import os
from pathlib import Path
from typing import Optional

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardMarkup, InputMediaPhoto, InputMediaVideo, Message
from . import services, transport
from .keyboards import (
    build_complaint_moderation_keyboard,
    build_complaint_status_keyboard,
    build_main_keyboard,
    build_payment_recheck_keyboard,
    build_resend_keyboard,
    build_user_actions_keyboard,
)
from .models import ComplaintRender, parse_callback_id
from .states import ModeratorStates

PROJECT_ROOT = Path(__file__).resolve().parents[1]
logger = logging.getLogger(__name__)

# Создаем Dispatcher глобально
dp = Dispatcher(storage=MemoryStorage())


async def _send_complaint_media(
    *,
    bot_instance: Bot,
    chat_id: int,
    render: ComplaintRender,
    keyboard: InlineKeyboardMarkup,
) -> bool:
    """Отправляет жалобу (медиа + текст с кнопками)."""
    video_input, resolved_video = transport.resolve_media_source(render.video_path)
    if not video_input:
        if render.video_path:
            logger.warning("Video file not found for complaint media: %s", render.video_path)
        return False

    photo_input, resolved_photo = transport.resolve_media_source(render.source_path)

    if photo_input:
        try:
            media_group = [
                InputMediaPhoto(
                    media=photo_input,
                    caption="🖼 <b>Исходное фото</b>",
                    parse_mode="HTML",
                ),
                InputMediaVideo(
                    media=video_input,
                    caption=render.text,
                    parse_mode="HTML",
                ),
            ]
            await bot_instance.send_media_group(chat_id=chat_id, media=media_group)
            await bot_instance.send_message(
                chat_id,
                render.text,
                parse_mode="HTML",
                reply_markup=keyboard,
            )
            return True
        except Exception:
            logger.exception("Failed to send media group (photo+video)")

    try:
        await bot_instance.send_video(
            chat_id=chat_id,
            video=video_input,
            caption=render.text,
            parse_mode="HTML",
            reply_markup=keyboard,
        )
        if photo_input is None and render.source_path and resolved_photo:
            await bot_instance.send_message(
                chat_id,
                f"⚠️ <b>Исходное фото недоступно:</b> {resolved_photo}",
                parse_mode="HTML",
            )
        await bot_instance.send_message(
            chat_id,
            render.text,
            parse_mode="HTML",
            reply_markup=keyboard,
        )
        return True
    except Exception:
        logger.exception("Failed to send complaint video")
        return False


async def _send_complaints_list(
    *,
    bot_instance: Bot,
    chat_id: int,
    renders: list,
    mark_dispatched: bool = True,
) -> str:
    """Отправляет список жалоб модератору"""
    if not renders:
        return "📋 Жалоб пока нет"

    for render in renders:
        keyboard = build_complaint_moderation_keyboard(render.complaint_id)
        media_sent = await _send_complaint_media(
            bot_instance=bot_instance,
            chat_id=chat_id,
            render=render,
            keyboard=keyboard,
        )
        if not media_sent:
            await bot_instance.send_message(
                chat_id, render.text, parse_mode="HTML", reply_markup=keyboard
            )
            if render.video_path and not os.path.exists(render.video_path):
                await bot_instance.send_message(
                    chat_id,
                    f"⚠️ <b>Видео не найдено:</b> {render.video_path}",
                    parse_mode="HTML",
                )

    if mark_dispatched:
        await services.mark_complaints_dispatched([r.complaint_id for r in renders])

    return f"📋 Показано {len(renders)} жалоб"


async def _send_user_generations(
    *,
    bot_instance: Bot,
    chat_id: int,
    generations: list,
) -> str:
    """Отправляет список генераций пользователя модератору"""
    if not generations:
        return "🎬 У пользователя нет завершённых генераций."

    sent = 0
    for render in generations:
        if render.media_path and os.path.exists(render.media_path):
            try:
                await bot_instance.send_video(
                    chat_id=chat_id,
                    video=FSInputFile(render.media_path),
                    caption=render.caption,
                    parse_mode="HTML",
                )
            except Exception:
                await bot_instance.send_message(
                    chat_id,
                    f"{render.caption}\n⚠️ <b>Видео не найдено:</b> {render.media_path}",
                    parse_mode="HTML",
                )
        else:
            await bot_instance.send_message(
                chat_id,
                f"{render.caption}\n⚠️ <b>Видео не найдено или не сохранено.</b>",
                parse_mode="HTML",
            )
        sent += 1

    return f"🎬 Показано {sent} генераций"


async def _send_resend_generations(
    *,
    bot_instance: Bot,
    chat_id: int,
    generations: list,
    target_user_id: int,
) -> str:
    """Отправляет список результатов для переотправки модератору"""
    if not generations:
        return "🔄 У пользователя нет доступных результатов для переотправки."

    for render in generations:
        resend_keyboard = build_resend_keyboard(target_user_id, render.generation_id)
        await bot_instance.send_message(
            chat_id, render.caption, parse_mode="HTML", reply_markup=resend_keyboard
        )

    return f"🔄 Показано {len(generations)} результатов"


async def _send_user_payments(
    *,
    bot_instance: Bot,
    chat_id: int,
    payments: list,
) -> str:
    """Отправляет список платежей пользователя модератору"""
    if not payments:
        return "💳 У пользователя пока нет платежей."

    await bot_instance.send_message(chat_id, "💳 <b>Платежи пользователя</b>", parse_mode="HTML")
    for payment in payments:
        keyboard = build_payment_recheck_keyboard(payment.payment_id, payment.status)
        await bot_instance.send_message(
            chat_id, payment.text, parse_mode="HTML", reply_markup=keyboard
        )

    return f"💳 Показано {len(payments)} платежей"


async def _notify_user(user_id: int, bot_hash: str | None, message: str) -> bool:
    """Отправляет уведомление пользователю от имени соответствующего бота."""
    
    try:
        bot_record = await transport.get_bot_record_for_user(bot_hash)
        if bot_record:
            user_bot = Bot(token=bot_record.token)
            await user_bot.send_message(user_id, message, parse_mode="HTML")
            await user_bot.session.close()
            return True
        else:
            logger.error("No bot found for user notification")
    except Exception:
        logger.exception("Failed to notify user %s", user_id)
    
    return False


async def _send_generation_video_to_user(
    user_id: int,
    bot_hash: str | None,
    media_path: str,
    caption: str,
) -> bool:
    """Отправляет видео генерации пользователю."""
    
    if not os.path.exists(media_path):
        logger.error("Media file not found for resend: %s", media_path)
        return False

    try:
        bot_record = await transport.get_bot_record_for_user(bot_hash)
        if not bot_record:
            logger.error("Cannot resend result: no active bot available")
            return False

        user_bot = Bot(token=bot_record.token)
        try:
            await user_bot.send_video(
                user_id,
                video=FSInputFile(media_path),
                caption=caption,
                parse_mode="HTML",
            )
            return True
        except Exception:
            logger.exception("Failed to resend generation to user %s", user_id)
            return False
        finally:
            await user_bot.session.close()
    except Exception:
        logger.exception("Failed to get bot for resend to user %s", user_id)
        return False


@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    if not await services.is_moderator(message.from_user.id):
        await message.answer("❌ У вас нет доступа к этому боту")
        return

    await state.clear()
    await message.answer(
        "🛡 <b>Бот модерации жалоб</b>\n\n"
        "Нажмите кнопку «📋 Жалобы», чтобы получить список новых обращений.",
        reply_markup=build_main_keyboard(),
        parse_mode="HTML",
    )


@dp.message(F.text == "📋 Жалобы")
async def on_main_complaints(message: Message, state: FSMContext):
    """Обработка нажатия на кнопку '📋 Жалобы' через reply-клавиатуру."""
    if not await services.is_moderator(message.from_user.id):
        return

    await state.clear()
    renders = await services.get_pending_complaints()
    result_text = await _send_complaints_list(
        bot_instance=message.bot,
        chat_id=message.chat.id,
        renders=renders,
    )
    await message.answer(result_text)


@dp.message(F.text == "👤 Пользователь")
async def on_main_user(message: Message, state: FSMContext):
    """Обработка нажатия на кнопку '👤 Пользователь' через reply-клавиатуру."""
    user_id = message.from_user.id
    if not await services.is_moderator(user_id):
        return

    await state.set_state(ModeratorStates.waiting_user_lookup)
    await message.answer(
        "Введите user_id или @username, чтобы посмотреть баланс пользователя.",
        reply_markup=build_main_keyboard(),
    )


@dp.message(ModeratorStates.waiting_user_lookup)
async def handle_user_lookup_state(message: Message, state: FSMContext):
    """Обработка ввода user_id или @username в состоянии ожидания поиска пользователя."""
    if not await services.is_moderator(message.from_user.id):
        return

    text = (message.text or "").strip()
    info = await services.lookup_user(text)
    if not info:
        await message.answer(
            "❌ Пользователь не найден. Проверьте введённый ID или username.",
            reply_markup=build_main_keyboard(),
        )
        return

    await state.clear()
    await message.answer(
        info.text,
        parse_mode="HTML",
        reply_markup=build_user_actions_keyboard(info.user_id),
    )


@dp.message()
async def handle_message(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if not await services.is_moderator(user_id):
        return

    await message.answer(
        "Используйте кнопки меню: «📋 Жалобы» или «👤 Пользователь».",
        reply_markup=build_main_keyboard(),
    )


@dp.callback_query(F.data == "complaints_list")
async def handle_complaints_list(cb: CallbackQuery):
    if not await services.is_moderator(cb.from_user.id):
        await cb.answer("❌ У вас нет доступа к этому боту")
        return

    renders = await services.get_pending_complaints()
    result_text = await _send_complaints_list(
        bot_instance=cb.message.bot,
        chat_id=cb.message.chat.id,
        renders=renders,
    )
    await cb.answer(result_text, show_alert=False)


@dp.callback_query(F.data.startswith("complaint_accept:"))
async def handle_complaint_accept(cb: CallbackQuery):
    complaint_id = parse_callback_id(cb.data, "complaint_accept:")
    if complaint_id is None:
        await cb.answer("❌ Ошибка обработки жалобы")
        return

    success, result, keyboard = await transport.process_complaint_decision(
        complaint_id=complaint_id,
        action_key="accept",
    )
    if not success or not result:
        await cb.answer("❌ Жалоба не найдена")
        return

    # Отправляем уведомление пользователю
    notified = await _notify_user(result.user_id, result.bot_hash, result.user_message)

    if keyboard:
        try:
            await cb.message.edit_reply_markup(reply_markup=keyboard)
        except Exception:
            pass

    answer_text = result.moderator_success if notified else result.moderator_warning
    await cb.answer(answer_text)


@dp.callback_query(F.data.startswith("complaint_reject:"))
async def handle_complaint_reject(cb: CallbackQuery):
    complaint_id = parse_callback_id(cb.data, "complaint_reject:")
    if complaint_id is None:
        await cb.answer("❌ Ошибка обработки жалобы")
        return

    success, result, keyboard = await transport.process_complaint_decision(
        complaint_id=complaint_id,
        action_key="reject",
    )
    if not success or not result:
        await cb.answer("❌ Жалоба не найдена")
        return

    notified = await _notify_user(result.user_id, result.bot_hash, result.user_message)

    if keyboard:
        try:
            await cb.message.edit_reply_markup(reply_markup=keyboard)
        except Exception:
            pass

    answer_text = result.moderator_success if notified else result.moderator_warning
    await cb.answer(answer_text)


@dp.callback_query(F.data.startswith("complaint_status_"))
async def handle_complaint_status(cb: CallbackQuery):
    await cb.answer("ℹ️ Статус жалобы уже установлен")


@dp.callback_query(F.data.startswith("user_complaints:"))
async def handle_user_complaints(cb: CallbackQuery):
    if not await services.is_moderator(cb.from_user.id):
        await cb.answer("❌ Нет доступа")
        return

    target_user_id = parse_callback_id(cb.data, "user_complaints:")
    if target_user_id is None:
        await cb.answer("❌ Некорректный ID")
        return

    renders = await services.get_user_complaints(target_user_id)
    result_text = await _send_complaints_list(
        bot_instance=cb.message.bot,
        chat_id=cb.message.chat.id,
        renders=renders,
        mark_dispatched=False,
    )
    await cb.answer(result_text)


@dp.callback_query(F.data.startswith("user_generations:"))
async def handle_user_generations(cb: CallbackQuery):
    if not await services.is_moderator(cb.from_user.id):
        await cb.answer("❌ Нет доступа")
        return

    target_user_id = parse_callback_id(cb.data, "user_generations:")
    if target_user_id is None:
        await cb.answer("❌ Некорректный ID")
        return

    generations = await services.get_user_generations_overview(target_user_id)
    result_text = await _send_user_generations(
        bot_instance=cb.message.bot,
        chat_id=cb.message.chat.id,
        generations=generations,
    )
    await cb.answer(result_text)


@dp.callback_query(F.data.startswith("user_release_reserved:"))
async def handle_user_release_reserved(cb: CallbackQuery):
    if not await services.is_moderator(cb.from_user.id):
        await cb.answer("❌ Нет доступа")
        return

    target_user_id = parse_callback_id(cb.data, "user_release_reserved:")
    if target_user_id is None:
        await cb.answer("❌ Некорректный ID", show_alert=True)
        return

    result = await services.release_reserved_balance(target_user_id)
    if not result.success:
        await cb.answer(result.alert_text or result.message, show_alert=True)
        return

    await cb.message.answer(result.message)
    await cb.answer("✅ Резерв очищен", show_alert=False)


@dp.callback_query(F.data.startswith("user_resend:"))
async def handle_user_resend(cb: CallbackQuery):
    if not await services.is_moderator(cb.from_user.id):
        await cb.answer("❌ Нет доступа")
        return

    target_user_id = parse_callback_id(cb.data, "user_resend:")
    if target_user_id is None:
        await cb.answer("❌ Некорректный ID")
        return

    generations = await services.get_user_generations_for_resend(target_user_id)
    result_text = await _send_resend_generations(
        bot_instance=cb.message.bot,
        chat_id=cb.message.chat.id,
        generations=generations,
        target_user_id=target_user_id,
    )
    await cb.answer(result_text)


@dp.callback_query(F.data.startswith("resend_generation:"))
async def handle_resend_generation(cb: CallbackQuery):
    if not await services.is_moderator(cb.from_user.id):
        await cb.answer("❌ Нет доступа")
        return

    try:
        _, user_part, generation_part = cb.data.split(":", 2)
        target_user_id = int(user_part)
        generation_id = int(generation_part)
    except (ValueError, IndexError):
        await cb.answer("❌ Некорректные данные", show_alert=True)
        return

    data = await services.get_resend_generation_data(generation_id)
    if not data:
        await cb.answer("❌ Генерация не найдена", show_alert=True)
        return

    if data.user_id != target_user_id:
        await cb.answer("⚠️ Пользователь не совпадает", show_alert=True)
        return

    if not data.media_path or not os.path.exists(data.media_path):
        await cb.answer("⚠️ Файл не найден", show_alert=True)
        await cb.message.answer(
            f"⚠️ <b>Файл генерации не найден:</b> {data.media_path or '—'}",
            parse_mode="HTML",
        )
        return

    # Отправляем видео пользователю
    sent = await _send_generation_video_to_user(
        data.user_id, data.bot_hash, data.media_path, data.caption
    )

    if sent:
        await cb.answer("✅ Результат отправлен", show_alert=False)
    else:
        await cb.answer("❌ Не удалось отправить результат", show_alert=True)


@dp.callback_query(F.data.startswith("user_payments:"))
async def handle_user_payments(cb: CallbackQuery):
    if not await services.is_moderator(cb.from_user.id):
        await cb.answer("❌ Нет доступа")
        return

    target_user_id = parse_callback_id(cb.data, "user_payments:")
    if target_user_id is None:
        await cb.answer("❌ Некорректный ID")
        return

    payments = await services.get_user_payments(target_user_id)
    result_text = await _send_user_payments(
        bot_instance=cb.message.bot,
        chat_id=cb.message.chat.id,
        payments=payments,
    )
    await cb.answer(result_text)


@dp.callback_query(F.data.startswith("payment_recheck:"))
async def handle_payment_recheck(cb: CallbackQuery):
    if not await services.is_moderator(cb.from_user.id):
        await cb.answer("❌ Нет доступа")
        return

    try:
        _, payment_id_str, status = cb.data.split(":", 2)
        payment_id = int(payment_id_str)
    except (ValueError, IndexError):
        await cb.answer("❌ Некорректные данные", show_alert=True)
        return

    if status == "completed":
        await cb.answer("✅ Платеж уже completed")
        return

    updated = await services.set_payment_status_pending(payment_id)
    if updated:
        await cb.answer("🔄 Статус изменён на pending", show_alert=False)
        new_keyboard = build_payment_recheck_keyboard(payment_id, "pending")
        try:
            await cb.message.edit_reply_markup(reply_markup=new_keyboard)
        except Exception:
            pass
    else:
        await cb.answer("❌ Не удалось обновить статус", show_alert=True)
