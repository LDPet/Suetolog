# Голосовой напоминальщик

Telegram-бот для проекта стажировки Иви-2026: пользователь быстро создаёт задачи голосом или текстом, получает напоминания, отмечает результат реакциями и переносит невыполненные дела.

## О проекте

**Название:** Голосовой напоминальщик  
**Команда:** TODO: ФИО студентов / название команды  
**Ментор:** TODO  
**Demo video:** TODO: ссылка на видео до 7 минут

Проблема: иногда нужно быстро записать дело, чтобы не забыть, но вручную заводить задачу неудобно. Целевая аудитория — занятые люди, которым проще сказать боту «напомни завтра в 15:00 позвонить врачу», чем открывать отдельное приложение.

Основная ценность MVP — Telegram-бот, который принимает голос или текст, превращает свободную русскую фразу в задачу, хранит её в PostgreSQL и сам напоминает в нужное время.

## Быстрый старт

Кодовая часть проекта ещё не добавлена в репозиторий, поэтому команды ниже — целевой шаблон. После появления `manage.py`, файла зависимостей, `.env.example` и `docker-compose.yml` нужно заменить `TODO` на точные команды.

```bash
git clone <repo-url>
cd Suetolog

# TODO: выбрать файл зависимостей: requirements.txt или pyproject.toml
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# TODO: создать .env.example и скопировать его
cp .env.example .env
```

Все настраиваемые параметры проекта — интервалы Celery Beat, timezone, лимиты voice, провайдеры STT/parser, подключения к БД и Redis — задаются в **`config/settings.py`** (Django settings module). Это единственный источник правды для конфигурации: код и Celery читают значения оттуда, а не из разрозненных env-переменных в разных модулях.

**`.env`** — только секреты, которые нельзя коммитить в git (токены, API-ключи, пароль БД). При старте Django они читаются в **`config/settings.py`** через `os.environ` или `django-environ`.

**`config/settings.py`** — все остальные параметры: `DEBUG`, подключение к PostgreSQL/Redis, timezone, интервалы Celery Beat, лимиты voice, провайдеры STT/parser и т.д. У tunable-констант есть значения по умолчанию прямо в файле.

Минимальный `.env` для локального запуска:

```env
SECRET_KEY=change-me
TELEGRAM_BOT_TOKEN=change-me
DB_PASSWORD=suetolog
YANDEX_FOLDER_ID=
YANDEX_API_KEY=
```

Пример того, что задаётся в `config/settings.py`, а не в `.env`:

```python
DEBUG = True
DB_NAME = 'suetolog'
DB_HOST = 'localhost'
REDIS_URL = 'redis://localhost:6379/0'
DEFAULT_TIMEZONE = 'Europe/Moscow'
REMINDER_CHECK_INTERVAL_MINUTES = 1
```

Полный список констант — в [`config/settings.py`](config/settings.py) (появится вместе с кодом) и в [`tz/ARCHITECTURE.md`](tz/ARCHITECTURE.md#6-конфигурация-configsettingspy).

```bash
# TODO: команды станут актуальными после создания Django-проекта и compose-файла
python manage.py migrate
python manage.py runbot
docker compose up --build

# TODO: имена Celery app/tasks уточнить в коде
celery -A config worker -l info
celery -A config beat -l info

pytest
pytest --cov
yapf -r -i .
isort .
```

Компонентная диаграмма: [`ARCHITECTURE.drawio`](ARCHITECTURE.drawio).

## Документация

Подробные требования, архитектура и сценарии — в каталоге [`tz/`](tz/).

| Файл | Описание |
|------|----------|
| [`tz/tz.md`](tz/tz.md) | Исходное ТЗ проекта: проблема, целевая аудитория, ключевая бизнес-логика и усложнения MVP. |
| [`tz/use_cases.md`](tz/use_cases.md) | Полный каталог пользовательских сценариев бота: команды, реакции, дайджесты, переносы и граничные случаи. |
| [`tz/ARCHITECTURE.md`](tz/ARCHITECTURE.md) | Архитектура системы: модули, слои, принципы разделения ответственности и точки расширения. |
| [`tz/tables.md`](tz/tables.md) | Черновик модели данных: сущности `User`, `Task`, `Reminder`, `TaskEvent` и их поля. |
| [`tz/VOICE_PIPELINES.md`](tz/VOICE_PIPELINES.md) | Голосовой и текстовый пайплайн: STT, YandexGPT-парсер, контракты данных и обработка ошибок. |
| [`tz/MAILING_PIPELINES.md`](tz/MAILING_PIPELINES.md) | Фоновые рассылки через Celery: утренний дайджест, точечные напоминания, вечерний перенос. |

Исходные документы стажировки:

- [`tz/Стажировка_2026_CodeStyle.pdf`](tz/Стажировка_2026_CodeStyle.pdf)
- [`tz/Стажировка_2026_Требования_к_проекту.pdf`](tz/Стажировка_2026_Требования_к_проекту.pdf)
- [`tz/Стажировка_2026_Техническое_задание.pdf`](tz/Стажировка_2026_Техническое_задание.pdf)
