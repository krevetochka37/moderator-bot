"""Keyboards for Moderator Bot"""
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def build_complaint_moderation_keyboard(complaint_id: int) -> InlineKeyboardMarkup:
    """Создает клавиатуру для модерации жалобы админом"""
    builder = InlineKeyboardBuilder()
    
    builder.button(
        text="✅ Принять",
        callback_data=f"complaint_accept:{complaint_id}"
    )
    builder.button(
        text="❌ Отклонить", 
        callback_data=f"complaint_reject:{complaint_id}"
    )
    
    builder.adjust(2)
    return builder.as_markup()


def build_complaint_status_keyboard(complaint_id: int, status: str) -> InlineKeyboardMarkup:
    """Создает клавиатуру с статусом жалобы после обработки"""
    builder = InlineKeyboardBuilder()
    
    if status == "accepted":
        builder.button(
            text="✅ Жалоба одобрена",
            callback_data=f"complaint_status_accepted:{complaint_id}"
        )
    elif status == "rejected":
        builder.button(
            text="❌ Жалоба отклонена",
            callback_data=f"complaint_status_rejected:{complaint_id}"
        )
    
    builder.adjust(1)
    return builder.as_markup()

