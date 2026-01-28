from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any, Mapping, Sequence


def format_datetime(dt: datetime | None) -> str:
    if not isinstance(dt, datetime):
        return str(dt) if dt else "—"
    
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    
    moscow_tz = timezone(timedelta(hours=3))
    moscow_dt = dt.astimezone(moscow_tz)
    return moscow_dt.strftime("%Y-%m-%d %H:%M")


def parse_callback_id(cb_data: str, prefix: str) -> int | None:
    """Парсит ID из callback_data. Возвращает None при ошибке."""
    try:
        return int(cb_data.split(":", 1)[1])
    except (ValueError, IndexError):
        return None


def row_to_dict(row: Mapping[str, Any] | Sequence[Any], columns: tuple[str, ...]) -> dict[str, Any]:
    """Преобразует строку БД в словарь."""
    if isinstance(row, Mapping):
        return dict(row)
    return {
        column: row[idx] if idx < len(row) else None
        for idx, column in enumerate(columns)
    }


COMPLAINT_COLUMNS = (
    "id",
    "user_id",
    "message_id",
    "file_path",
    "category",
    "bot_id",
    "subcategory_id",
    "status",
    "dispatched",
    "created_at",
    "source_path",
    "generation_id",
)

TASK_COLUMNS = (
    "id",
    "user_id",
    "priority",
    "category",
    "image_path",
    "comfy_url",
    "is_finished",
    "created_at",
    "updated_at",
    "bot_id",
    "subcategory_id",
    "cost",
)

BOT_COLUMNS = (
    "id",
    "name",
    "token",
    "is_active",
    "created_at",
    "updated_at",
)


@dataclass
class ComplaintDTO:
    id: int
    user_id: int
    message_id: int | None
    file_path: str | None
    category: str | None
    bot_id: str | None
    subcategory_id: int | None
    status: str
    dispatched: bool
    created_at: Any
    source_path: str | None
    generation_id: int | None

    @classmethod
    def from_row(cls, row: Mapping[str, Any] | Sequence[Any]) -> "ComplaintDTO":
        data = row_to_dict(row, COMPLAINT_COLUMNS)
        return cls(
            id=data["id"],
            user_id=data["user_id"],
            message_id=data.get("message_id"),
            file_path=data.get("file_path"),
            category=data.get("category"),
            bot_id=data.get("bot_id"),
            subcategory_id=data.get("subcategory_id"),
            status=data.get("status"),
            dispatched=data.get("dispatched"),
            created_at=data.get("created_at"),
            source_path=data.get("source_path"),
            generation_id=data.get("generation_id"),
        )


@dataclass
class TaskDTO:
    id: int
    user_id: int
    priority: int | None
    category: str | None
    image_path: str | None
    comfy_url: str | None
    is_finished: bool | None
    created_at: datetime | None
    updated_at: datetime | None
    bot_id: str | None
    subcategory_id: int | None
    cost: int | None

    @classmethod
    def from_row(cls, row: Mapping[str, Any] | Sequence[Any]) -> "TaskDTO":
        data = row_to_dict(row, TASK_COLUMNS)
        return cls(
            id=data["id"],
            user_id=data["user_id"],
            priority=data.get("priority"),
            category=data.get("category"),
            image_path=data.get("image_path"),
            comfy_url=data.get("comfy_url"),
            is_finished=data.get("is_finished"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
            bot_id=data.get("bot_id"),
            subcategory_id=data.get("subcategory_id"),
            cost=data.get("cost"),
        )


@dataclass
class BotRecord:
    id: int
    name: str | None
    token: str
    is_active: bool
    created_at: datetime | None
    updated_at: datetime | None

    @classmethod
    def from_row(cls, row: Mapping[str, Any] | Sequence[Any]) -> "BotRecord":
        data = row_to_dict(row, BOT_COLUMNS)
        return cls(
            id=data["id"],
            name=data.get("name"),
            token=data.get("token"),
            is_active=bool(data.get("is_active")),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )


COMPLAINT_DECISIONS = {
    "accept": {
        "status": "accepted",
        "delta_sign": 1,
        "user_message": (
            "✅ <b>Ваша жалоба была рассмотрена и принята</b>\n\n"
            "Вернули {amount} кредитов за генерацию на ваш баланс.\n"
            "ID жалобы: #{complaint_id}"
        ),
        "moderator_success": "✅ Жалоба принята, пользователь уведомлен",
        "moderator_warning": "✅ Жалоба принята, но ошибка уведомления пользователя",
    },
    "reject": {
        "status": "rejected",
        "delta_sign": -1,
        "user_message": (
            "❌ <b>Ваша жалоба была отклонена</b>\n\n"
            "С баланса списали {amount} кредитов (двойная плата за генерацию).\n"
            "ID жалобы: #{complaint_id}"
        ),
        "moderator_success": "❌ Жалоба отклонена, пользователь уведомлен",
        "moderator_warning": "❌ Жалоба отклонена, но ошибка уведомления пользователя",
    },
}


def username_display(user_info: dict | None, fallback_id: int) -> str:
    """Возвращает строку для отображения пользователя."""
    username = user_info.get("username") if user_info else None
    if username:
        return f"@{username}"
    return f"user_{fallback_id}"


@dataclass
class ComplaintRender:
    complaint_id: int
    text: str
    video_path: str | None
    source_path: str | None


@dataclass
class GenerationRender:
    generation_id: int
    caption: str
    media_path: str | None


@dataclass
class PaymentRender:
    payment_id: int
    text: str
    status: str


@dataclass
class ComplaintDecisionResult:
    complaint_id: int
    user_id: int
    bot_hash: str | None
    user_message: str
    status: str
    moderator_success: str
    moderator_warning: str


@dataclass
class ReleaseReservedResult:
    success: bool
    released: int
    message: str
    alert_text: str | None = None


@dataclass
class ResendGenerationData:
    generation_id: int
    user_id: int
    media_path: str
    bot_hash: str | None
    caption: str


@dataclass
class UserInfoRender:
    text: str
    user_id: int

