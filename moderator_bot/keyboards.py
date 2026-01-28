from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from moderator_bot.ui.keyboards import (
    build_complaint_moderation_keyboard,
    build_complaint_status_keyboard,
)

def build_main_keyboard() -> ReplyKeyboardMarkup:
    """Основная клавиатура с кнопками."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 Жалобы")],
            [KeyboardButton(text="👤 Пользователь")],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
    )


def build_user_actions_keyboard(target_user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📋 Жалобы",
                    callback_data=f"user_complaints:{target_user_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🎬 Генерации",
                    callback_data=f"user_generations:{target_user_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔄 Переотправка результата",
                    callback_data=f"user_resend:{target_user_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="💳 Проверка платежей",
                    callback_data=f"user_payments:{target_user_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🧹 Снять резерв",
                    callback_data=f"user_release_reserved:{target_user_id}",
                )
            ],
        ]
    )


def build_resend_keyboard(target_user_id: int, generation_id: int) -> InlineKeyboardMarkup:
    """Создает клавиатуру для переотправки генерации."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔁 Переотправить",
                    callback_data=f"resend_generation:{target_user_id}:{generation_id}",
                )
            ]
        ]
    )


def build_payment_recheck_keyboard(payment_id: int, status: str) -> InlineKeyboardMarkup:
    """Создает клавиатуру для перепроверки платежа."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔎 Перепроверить",
                    callback_data=f"payment_recheck:{payment_id}:{status}",
                )
            ]
        ]
    )


__all__ = [
    "build_main_keyboard",
    "build_user_actions_keyboard",
    "build_resend_keyboard",
    "build_payment_recheck_keyboard",
    "build_complaint_moderation_keyboard",
    "build_complaint_status_keyboard",
]

