from datetime import timedelta
from unittest.mock import AsyncMock, Mock

import pytest
from celery.schedules import crontab
from django.conf import settings

from config.celery import app
from reminder import tasks


def test_due_reminders_registered_in_beat_schedule():
    schedule = settings.CELERY_BEAT_SCHEDULE["send-due-reminders"]

    assert schedule["task"] == "reminder.tasks.send_due_reminders"
    assert schedule["schedule"] == timedelta(
        minutes=settings.REMINDER_CHECK_INTERVAL_MINUTES)


def test_morning_digest_registered_in_beat_schedule():
    schedule = settings.CELERY_BEAT_SCHEDULE["send-morning-digest"]

    assert schedule["task"] == "reminder.tasks.send_morning_digest"
    assert schedule["schedule"] == crontab(minute=0,
                                           hour=settings.MORNING_DIGEST_HOUR)


def test_celery_app_uses_django_settings():
    assert app.conf.broker_url == settings.CELERY_BROKER_URL
    assert app.conf.timezone == settings.DEFAULT_TIMEZONE
    assert ("reminder.tasks.send_due_reminders" in app.tasks)
    assert ("reminder.tasks.send_morning_digest" in app.tasks)


@pytest.mark.asyncio
async def test_job_builds_mailing_service_and_closes_bot(monkeypatch):
    expected = {"processed": 1, "sent": 1, "failed": 0, "skipped": 0}
    bot = Mock()
    bot.session.close = AsyncMock()
    sender = Mock()
    service = Mock()
    service.send_due_reminders = AsyncMock(return_value=expected)
    bot_factory = Mock(return_value=bot)
    sender_factory = Mock(return_value=sender)
    service_factory = Mock(return_value=service)
    monkeypatch.setattr(tasks, "Bot", bot_factory)
    monkeypatch.setattr(tasks, "TelegramSender", sender_factory)
    monkeypatch.setattr(tasks, "ReminderMailingService", service_factory)

    result = await tasks._send_due_reminders()

    assert result == expected
    bot_factory.assert_called_once_with(token=settings.TELEGRAM_BOT_TOKEN)
    sender_factory.assert_called_once_with(bot)
    service_factory.assert_called_once_with(sender=sender)
    service.send_due_reminders.assert_awaited_once_with()
    bot.session.close.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_morning_digest_job_builds_mailing_service_and_closes_bot(
        monkeypatch):
    expected = {"processed": 2, "sent": 2, "failed": 0, "skipped": 0}
    bot = Mock()
    bot.session.close = AsyncMock()
    sender = Mock()
    service = Mock()
    service.send_morning_digest = AsyncMock(return_value=expected)
    bot_factory = Mock(return_value=bot)
    sender_factory = Mock(return_value=sender)
    service_factory = Mock(return_value=service)
    monkeypatch.setattr(tasks, "Bot", bot_factory)
    monkeypatch.setattr(tasks, "TelegramSender", sender_factory)
    monkeypatch.setattr(tasks, "ReminderMailingService", service_factory)

    result = await tasks._send_morning_digest()

    assert result == expected
    bot_factory.assert_called_once_with(token=settings.TELEGRAM_BOT_TOKEN)
    sender_factory.assert_called_once_with(bot)
    service_factory.assert_called_once_with(sender=sender)
    service.send_morning_digest.assert_awaited_once_with()
    bot.session.close.assert_awaited_once_with()


def test_celery_task_only_delegates_to_async_job(monkeypatch):
    expected = {"processed": 0, "sent": 0, "failed": 0, "skipped": 0}
    run_job = Mock(return_value=expected)
    async_to_sync = Mock(return_value=run_job)
    monkeypatch.setattr(tasks, "async_to_sync", async_to_sync)

    result = tasks.send_due_reminders.run()

    assert result == expected
    async_to_sync.assert_called_once_with(tasks._send_due_reminders)
    run_job.assert_called_once_with()


def test_morning_digest_celery_task_only_delegates_to_async_job(monkeypatch):
    expected = {"processed": 0, "sent": 0, "failed": 0, "skipped": 0}
    run_job = Mock(return_value=expected)
    async_to_sync = Mock(return_value=run_job)
    monkeypatch.setattr(tasks, "async_to_sync", async_to_sync)

    result = tasks.send_morning_digest.run()

    assert result == expected
    async_to_sync.assert_called_once_with(tasks._send_morning_digest)
    run_job.assert_called_once_with()
