import os
import sys
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-secret-key-change-me")
if not SECRET_KEY:
    raise ValueError("DJANGO_SECRET_KEY не найден!\n"
                     "Добавьте DJANGO_SECRET_KEY в .env файл.\n"
                     "Для генерации ключа выполните:\n"
                     "python -c 'from django.core.management.utils import "
                     "get_random_secret_key; print(get_random_secret_key())'")


def is_testing():
    return ("test" in sys.argv or "pytest" in sys.modules
            or os.getenv("TESTING", "false").lower() == "true"
            or os.getenv("CI", "false").lower() == "true")


DEBUG = os.getenv("DEBUG", "False").lower() == "true"
ALLOWED_HOSTS = (os.getenv("ALLOWED_HOSTS", "").split(",")
                 if os.getenv("ALLOWED_HOSTS") else [])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "reminder",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("POSTGRES_DB", "suetolog_db"),
        "USER": os.getenv("POSTGRES_USER", "suetolog_user"),
        "PASSWORD": os.getenv("POSTGRES_PASSWORD", "suetolog_pass"),
        "HOST": os.getenv("POSTGRES_HOST", "localhost"),
        "PORT": os.getenv("POSTGRES_PORT", "5432"),
    }
}

if is_testing():
    DATABASES["default"] = {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME":
        "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME":
        "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME":
        "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME":
        "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

LANGUAGE_CODE = "ru-ru"
TIME_ZONE = "Europe/Moscow"
DEFAULT_TIMEZONE = os.getenv("DEFAULT_TIMEZONE", TIME_ZONE)
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

PARSER_BACKEND = os.getenv("PARSER_BACKEND", "mock")
YANDEX_API_KEY = os.getenv("YANDEX_API_KEY", "")
YANDEX_FOLDER_ID = os.getenv("YANDEX_FOLDER_ID", "")
YANDEX_GPT_MODEL = os.getenv("YANDEX_GPT_MODEL", "yandexgpt-lite")
YANDEX_GPT_TEMPERATURE = float(os.getenv("YANDEX_GPT_TEMPERATURE", "0.1"))
YANDEX_GPT_MAX_TOKENS = int(os.getenv("YANDEX_GPT_MAX_TOKENS", "1000"))
YANDEX_GPT_TIMEOUT_SEC = int(os.getenv("YANDEX_GPT_TIMEOUT_SEC", "30"))

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

IS_TESTING = is_testing()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not TELEGRAM_BOT_TOKEN and IS_TESTING:
    TELEGRAM_BOT_TOKEN = "1234567890:ABCdefGHIjklMNOpqrsTUVwxyzAAAAAAAAA"

if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN не найден!\n"
                     "Создайте файл .env в корне проекта и добавьте:\n"
                     "TELEGRAM_BOT_TOKEN=ваш_токен_сюда")

VOICE_MAX_DURATION_SEC = 60
VOICE_MAX_SIZE_BYTES = 20 * 1024 * 1024
