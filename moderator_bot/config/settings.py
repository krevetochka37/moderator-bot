"""Settings for Moderator Bot"""
import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv


def _env(key: str, default: str | None = None) -> str | None:
    val = os.getenv(key)
    return val if val is not None else default


@dataclass
class Settings:
    """Settings for Moderator Bot"""
    proxy_user: str | None = None
    proxy_pass: str | None = None
    proxy_host: str | None = None
    proxy_port: str | None = None
    proxy_url: str | None = None  # Старый формат (для обратной совместимости)
    proxy_auth: str | None = None  # Старый формат (для обратной совместимости)
    environment: str = "DEV"  # "DEV" или "PROD"
    moderator_bot_token: str | None = None

    def get_proxy_url(self) -> str | None:
        """
        Возвращает полный URL прокси в формате: http://user:pass@host:port

        Приоритет:
        1. Проверка DISABLE_PROXY - если установлен в true/1/yes/on, прокси отключается
        2. Новый формат: PROXY_USER, PROXY_PASS, PROXY_HOST, PROXY_PORT
        3. Старый формат: PROXY_URL, PROXY_AUTH (для обратной совместимости)
        """
        # Проверяем, отключен ли прокси через переменную окружения
        disable_proxy = os.getenv("DISABLE_PROXY", "").lower()
        if disable_proxy in ("true", "1", "yes", "on"):
            return None

        # Новый формат: отдельные переменные
        if self.proxy_user and self.proxy_pass and self.proxy_host and self.proxy_port:
            return f"http://{self.proxy_user}:{self.proxy_pass}@{self.proxy_host}:{self.proxy_port}"

        # Старый формат: для обратной совместимости
        if self.proxy_url and self.proxy_auth:
            if "://" not in self.proxy_url:
                proxy_url = f"http://{self.proxy_url}"
            else:
                proxy_url = self.proxy_url
            if ":" in self.proxy_auth:
                username, password = self.proxy_auth.split(":", 1)
                proxy_url = proxy_url.replace("://", f"://{username}:{password}@")
            return proxy_url

        return None

    @staticmethod
    def load() -> "Settings":
        project_root = Path(__file__).resolve().parents[2]
        dotenv_path = project_root / ".env"
        if dotenv_path.exists():
            load_dotenv(dotenv_path=dotenv_path)
        else:
            load_dotenv()

        return Settings(
            # Новый формат прокси (приоритет)
            proxy_user=_env("PROXY_USER"),
            proxy_pass=_env("PROXY_PASS"),
            proxy_host=_env("PROXY_HOST"),
            proxy_port=_env("PROXY_PORT"),
            # Старый формат прокси (для обратной совместимости)
            proxy_url=_env("PROXY_URL", None),
            proxy_auth=_env("PROXY_AUTH", None),
            environment=_env("ENVIRONMENT", "DEV") or "DEV",
            moderator_bot_token=_env("MODERATOR_BOT_TOKEN", None),
        )

