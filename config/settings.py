import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-secret-key-change-me")
ALLOWED_HOSTS = []

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "reminder",
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

TIME_ZONE = "Europe/Moscow"
USE_TZ = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
