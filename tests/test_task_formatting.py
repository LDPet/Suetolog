from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from reminder.bot.formatting import (format_reminders_section,
                                     format_task_created_message,
                                     format_task_due_to, format_task_identity)
from reminder.models import Task

MSK = ZoneInfo("Europe/Moscow")


def task(**overrides):
    defaults = {
        "title": "Купить молоко",
        "description": "",
        "due_to": None,
        "due_to_has_time": False,
        "repeat_type": None,
        "repeat_interval": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def reminder(reminder_time):
    return SimpleNamespace(reminder_time=reminder_time)


def test_format_task_created_without_date():
    text = format_task_created_message(task())

    assert "✅ Задача создана" in text
    assert "📋 Название: Купить молоко" in text
    assert "📝 Описание: не указано" in text
    assert "📅 Срок: не указан" in text
    assert "Назначить дату: /undated" in text
    assert "⏰ Напоминания: нет (срок не указан)" in text


def test_format_task_identity_always_includes_description():
    assert format_task_identity(task()) == ("📋 Название: Купить молоко\n"
                                            "📝 Описание: не указано")
    assert format_task_identity(
        task(description="  2 литра  ")) == ("📋 Название: Купить молоко\n"
                                             "📝 Описание: 2 литра")


def test_format_task_created_with_description_and_exact_due_to():
    due_to = datetime(2026, 7, 15, 15, 0, tzinfo=MSK)
    text = format_task_created_message(
        task(
            description="2 литра",
            due_to=due_to,
            due_to_has_time=True,
        ),
        [reminder(due_to)],
    )

    assert "📝 Описание: 2 литра" in text
    assert "📅 Срок: 15 июля 2026, 15:00 (точное время)" in text
    assert "⏰ Напоминания:" in text
    assert "• 15 июля 2026, 15:00 — ожидает отправки" in text


def test_format_task_created_with_date_without_time():
    due_to = datetime(2026, 7, 15, 0, 0, tzinfo=MSK)
    text = format_task_created_message(
        task(due_to=due_to, due_to_has_time=False))

    assert "📅 Срок: 15 июля 2026 (без точного времени)" in text
    assert "нужно точное время в сроке" in text


def test_format_task_created_with_minutely_repeat():
    due_to = datetime(2026, 7, 15, 9, 0, tzinfo=MSK)
    text = format_task_created_message(
        task(
            due_to=due_to,
            due_to_has_time=True,
            repeat_type=Task.RepeatType.MINUTELY,
            repeat_interval=2,
        ))

    assert "🔁 Повтор: каждые 2 минуты" in text


def test_format_task_created_with_repeat():
    due_to = datetime(2026, 7, 15, 9, 0, tzinfo=MSK)
    text = format_task_created_message(
        task(
            due_to=due_to,
            due_to_has_time=True,
            repeat_type=Task.RepeatType.WEEKLY,
            repeat_interval=2,
        ))

    assert "🔁 Повтор: еженедельно (каждые 2)" in text


def test_format_task_due_to_without_date():
    assert format_task_due_to(task()) == "не указан"


def test_format_task_due_to_with_exact_time():
    due_to = datetime(2026, 7, 13, 21, 33, tzinfo=MSK)
    assert format_task_due_to(task(
        due_to=due_to, due_to_has_time=True)) == "13 июля 2026, 21:33"


def test_format_reminders_section_without_exact_time():
    due_to = datetime(2026, 7, 15, 0, 0, tzinfo=MSK)
    text = format_reminders_section([], due_to=due_to, due_to_has_time=False)

    assert "не запланированы" in text
