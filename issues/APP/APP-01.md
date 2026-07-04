# APP-01: Каркас Django-проекта и dev-окружение

Тег: APP-01

Эпик: APP

Результат: в репозитории есть минимальный Django-каркас с `manage.py`, заготовкой под настройки, `Makefile` для типовых dev-команд и pytest scaffold (`make test` работает). Зависимости установлены. Всё остальное команда добавляет в своих тикетах.

Зависимости: нет

## Описание

Создать стартовый каркас backend-приложения. Scope — только «проект существует, структура понятна, dev-команды работают». Модели, интеграции, сервисы, Telegram, Celery, внешние API и содержимое настроек **не входят**.

### Django-каркас

- `manage.py` в корне
- пакет `config/` с `urls.py`, `wsgi.py`, `asgi.py` — по стандарту `django-admin startproject`
- `config/settings.py` — **пустой файл-заглушка** (допустим комментарий вроде `# Настройки Django — здесь`). Ничего не добавлять: ни `SECRET_KEY`, ни параметров БД, ни заготовок под интеграции. Файл нужен, чтобы команда знала, **куда писать конфигурацию** в следующих тикетах
- приложение `reminder/`; подключение в `INSTALLED_APPS` — когда в `settings.py` появится минимальная конфигурация Django
- Python 3.10+, Django 4.2+

### Зависимости и окружение

- **pipenv**: `Pipfile` + `Pipfile.lock` (включая `pytest` в dev-зависимостях)
- `requirements.txt` — из Pipfile (`pipenv requirements > requirements.txt`)
- `.env.example` — пока пустой или с комментарием «переменные окружения — по мере необходимости»
- `.gitignore` — `.env`, venv, `__pycache__`, тестовые артефакты, IDE-файлы

### Pytest scaffold (бывш. QA-01)

- `pytest` в `Pipfile` / `requirements.txt`
- минимальный `pytest.ini` или `pyproject.toml` + пустой `conftest.py` (или один smoke-тест)
- `make test` реально запускается (даже с 0–1 тестом)
- в README — одна строка про `make test`

Полноценные моки Telegram/Yandex API **не входят** — они появятся в тикетах с первыми unit-тестами (DB-01, CORE-01, CORE-07).

### Makefile

Добавить `Makefile` с базовыми dev-командами:

| Target | Назначение |
|--------|------------|
| `make install` | `pipenv install --dev` |
| `make check` | `python manage.py check` |
| `make test` | `pytest` или `manage.py test` |
| `make format` | `yapf` + `isort` |

`make check` заработает, когда в `settings.py` появится минимальная конфигурация Django. `make test` должен проходить уже в этом тикете (smoke-тест или пустой прогон pytest).

README: быстрый старт — `make install`, `make test`; далее `make check` по мере появления настроек.

## Критерии приемки

- Есть `manage.py`, `config/`, `config/settings.py` (пустой или с комментарием-указателем)
- Есть приложение `reminder/`
- В `settings.py` нет настроек и заготовок под будущие интеграции
- Есть `Pipfile`, `Pipfile.lock`, `requirements.txt`, `.env.example`, `.gitignore`
- Есть `Makefile` с targets `install`, `check`, `test`, `format`
- `make install`, `make format` и `make test` работают в чистом окружении
- Есть pytest scaffold: `pytest.ini` или `pyproject.toml`, `conftest.py` (или smoke-тест)
- В репозитории нет секретов и токенов

## Что проверить вручную/автоматически

- `make install` в чистом окружении
- `make format`
- `make test` (pytest scaffold)
- `config/settings.py` существует и пустой (или только комментарий)
- `.env` не попадает в git
