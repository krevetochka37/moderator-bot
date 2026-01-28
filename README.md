# Moderator Bot

Отдельный сервис Telegram‑бота модератора для обработки жалоб пользователей, просмотра генераций и проверки платежей.

---

## Описание

Moderator Bot — вспомогательный бот для модераторов, который:
- принимает и показывает новые жалобы пользователей;
- позволяет модератору принять / отклонить жалобу и автоматически скорректировать баланс;
- показывает последние генерации пользователя и позволяет переотправить результат;
- показывает историю платежей и инициирует перепроверку спорных платежей;
- управляет зарезервированным балансом (разблокировка при отсутствии активных задач).

Бот работает только с авторизованными модераторами (список хранится в таблице `admins` в БД).

---

## Технологии

- Python 3.10+
- FastAPI — HTTP‑сервис (webhook endpoint)
- aiogram 3 — Telegram Bot API
- asyncpg — асинхронный PostgreSQL‑драйвер
- uv — управление зависимостями и виртуальным окружением

---

## Требования

- Python 3.10+
- PostgreSQL 12+ (или совместимая версия)
- Доступ к интернету для Telegram Bot API
- Токен бота от `@BotFather`
- Домен с HTTPS для webhook (для продакшена)

---

## Установка

Рекомендуемый способ — через `uv`:

```bash
git clone <URL_ВАШЕГО_РЕПОЗИТОРИЯ>
cd moderator-bot

# Установка зависимостей и создание .venv
uv sync
```

Альтернатива через `pip` (менее предпочтительно, но возможно):

```bash
pip install -e .
```

---

## Настройка окружения

1. Создайте файл `.env` на основе шаблона:

```bash
cp .env.example .env
```

2. Заполните переменные в `.env`:

**Обязательные:**

- `MODERATOR_BOT_TOKEN=your_moderator_bot_token_here`
- `MODERATOR_WEBHOOK_URL=https://your-public-domain.example.com`
- `DB_HOST=your_db_host_here`
- `DB_PORT=your_db_port_here`
- `DB_NAME=your_db_name_here`
- `DB_USER=your_db_user_here`
- `DB_PASSWORD=your_db_password_here`

**Опциональные (имеют значения по умолчанию):**

- `MODERATOR_WEBHOOK_PORT` — порт для локального uvicorn (по умолчанию `8002`).
- `ENVIRONMENT` — `DEV` или `PROD` (по умолчанию `DEV`).
- `OUTPUT_DIR` — директория для файлов с результатами генераций (по умолчанию `output`).
- `DB_TIMEOUT` — таймаут подключения к БД в секундах (по умолчанию `30`).
- `AIOHTTP_SESSION_LIMIT` — лимит соединений в aiohttp‑сессии бота (по умолчанию `100`).
- Настройки прокси: `DISABLE_PROXY`, `PROXY_USER`, `PROXY_PASS`, `PROXY_HOST`, `PROXY_PORT` или `PROXY_URL`/`PROXY_AUTH`.

---

## Запуск

### Локальный запуск (webhook‑сервер)

1. Убедитесь, что PostgreSQL запущен и в БД есть необходимые таблицы (`users`, `admins`, `complaints`, `payments`, `generation_queue` и т.д.).
2. Запустите приложение:

Через `uv`:

```bash
uv run uvicorn app:app --host 0.0.0.0 --port 8002 --reload
```

Или (при активированном виртуальном окружении):

```bash
uvicorn app:app --host 0.0.0.0 --port 8002 --reload
```

3. Настройте webhook в Telegram (через ngrok или другой HTTPS‑туннель):

- webhook URL: `https://<ваш-домен>/moderator`

При старте `app.py` сам устанавливает webhook по адресу `MODERATOR_WEBHOOK_URL + "/moderator"`.

---

## Основные эндпоинты

- `POST /moderator` — webhook‑endpoint для Telegram (вызывать вручную не нужно).
- `GET /` — простая информация о сервисе.
- `GET /health` — health‑check для мониторинга.

---

## Структура проекта

```text
moderator-bot/
├── app.py                     # FastAPI‑приложение и настройка webhook
├── pyproject.toml             # Зависимости и конфигурация сборки
├── uv.lock                    # lock‑файл зависимостей (uv)
├── .env.example               # Шаблон настроек окружения
├── .gitignore                 # Игнорируемые файлы
└── moderator_bot/
    ├── handlers.py            # Обработчики апдейтов Telegram (только здесь отправка сообщений)
    ├── keyboards.py           # Основные клавиатуры бота
    ├── models.py              # DTO‑модели и форматирование текстов
    ├── services.py            # Бизнес‑логика и работа с operations.py
    ├── database/
    │   └── operations.py      # Все операции с БД (asyncpg)
    ├── config/
    │   └── settings.py        # Загрузка настроек из .env
    ├── transport.py           # Работа с ботами и медиа
    ├── states.py              # FSM‑состояния модератора
    └── ui/
        └── keyboards.py       # Inline‑клавиатуры UI для модерации
```

---

## Логирование

- `app.py` настраивает базовый формат логов и уровень `INFO`.
- В `database/operations.py` ошибки и предупреждения логируются через `logger`, а не через `print()`.

Рекомендуется настроить сбор логов на уровне инфраструктуры (Docker, Kubernetes, systemd и т.п.).

---

## Разработка

Установка зависимостей:

```bash
uv sync
```

Запуск в режиме разработки:

```bash
uv run uvicorn app:app --host 0.0.0.0 --port 8002 --reload
```

Принципы:

- Доступ к БД — только через функции из `database/operations.py`.
- Сообщения пользователям и модераторам — только из `handlers.py`.
- Секреты и настройки — только через `.env` / переменные окружения.

---

Разработала Гасанова Марина