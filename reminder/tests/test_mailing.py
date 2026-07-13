import logging
from datetime import datetime, time, timedelta
from unittest.mock import AsyncMock, Mock

import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone

from reminder.bot.formatting import format_task_due_to
from reminder.bot.sender import TelegramSender
from reminder.models import Reminder, Task, TaskEvent
from reminder.services.mailing import ReminderMailingService

pytestmark = pytest.mark.django_db(transaction=True)


async def db_call(function):
    return await sync_to_async(function, thread_sensitive=True)()


def due_on(day, hour=10):
    return timezone.make_aware(
        datetime.combine(day, time(hour=hour)),
        timezone.get_current_timezone(),
    )


@pytest.fixture
def sender():
    sender = Mock()
    sender.send_reminder = AsyncMock(return_value=777)
    sender.send_digest = AsyncMock(return_value=888)
    return sender


@pytest.fixture
def mailing_service(sender):
    return ReminderMailingService(sender=sender)


@pytest.mark.asyncio
async def test_sends_due_reminder_and_records_delivery(mailing_service, sender,
                                                       task, user):
    now = timezone.now()
    reminder = await db_call(lambda: Reminder.objects.create(
        task=task,
        reminder_time=now - timedelta(minutes=1),
    ))

    result = await mailing_service.send_due_reminders(now=now)

    await db_call(reminder.refresh_from_db)
    events = await db_call(lambda: list(
        TaskEvent.objects.filter(task=task).values_list(
            "event_type", "message_id")))
    assert result == {
        "processed": 1,
        "sent": 1,
        "failed": 0,
        "skipped": 0,
    }
    sender.send_reminder.assert_awaited_once_with(user.chat_id, task)
    assert reminder.sent_time is not None
    assert reminder.message_id == 777
    assert events == [(TaskEvent.EventType.REMINDER_SENT, 777)]


@pytest.mark.asyncio
async def test_due_reminder_uses_task_card_and_creates_one_event(task, user):
    now = timezone.now()
    due_to = now - timedelta(minutes=1)
    task.due_to = due_to
    task.due_to_has_time = True
    await db_call(
        lambda: task.save(update_fields=["due_to", "due_to_has_time"]))
    reminder = await db_call(lambda: Reminder.objects.create(
        task=task,
        reminder_time=due_to,
    ))
    bot = Mock()
    bot.send_message = AsyncMock(return_value=Mock(message_id=777))
    service = ReminderMailingService(sender=TelegramSender(bot))

    result = await service.send_due_reminders(now=now)

    await db_call(reminder.refresh_from_db)
    events = await db_call(lambda: list(
        TaskEvent.objects.filter(
            task=task,
            event_type=TaskEvent.EventType.REMINDER_SENT,
        ).values_list("message_id", flat=True)))
    send_call = bot.send_message.await_args.kwargs
    buttons = send_call["reply_markup"].inline_keyboard[0]

    assert result["sent"] == 1
    assert send_call["chat_id"] == user.chat_id
    assert task.title in send_call["text"]
    assert format_task_due_to(task) in send_call["text"]
    assert "Ответь на это сообщение с датой и временем" in send_call["text"]
    assert buttons[0].callback_data == f"done:{task.id}"
    assert buttons[1].callback_data == f"delete:{task.id}"
    assert reminder.sent_time is not None
    assert reminder.message_id == 777
    assert events == [777]


@pytest.mark.asyncio
async def test_repeated_run_does_not_send_duplicate(mailing_service, sender,
                                                    task):
    now = timezone.now()
    await db_call(lambda: Reminder.objects.create(
        task=task,
        reminder_time=now - timedelta(minutes=1),
    ))

    first = await mailing_service.send_due_reminders(now=now)
    second = await mailing_service.send_due_reminders(now=now)

    assert first["sent"] == 1
    assert second == {
        "processed": 0,
        "sent": 0,
        "failed": 0,
        "skipped": 0,
    }
    sender.send_reminder.assert_awaited_once()
    assert await db_call(TaskEvent.objects.count) == 1


@pytest.mark.asyncio
async def test_empty_batch_does_nothing(mailing_service, sender):
    result = await mailing_service.send_due_reminders(now=timezone.now())

    assert result == {
        "processed": 0,
        "sent": 0,
        "failed": 0,
        "skipped": 0,
    }
    sender.send_reminder.assert_not_awaited()


@pytest.mark.asyncio
async def test_batch_continues_after_telegram_error(mailing_service, sender,
                                                    task):
    now = timezone.now()
    first = await db_call(lambda: Reminder.objects.create(
        task=task,
        reminder_time=now - timedelta(minutes=2),
    ))
    second = await db_call(lambda: Reminder.objects.create(
        task=task,
        reminder_time=now - timedelta(minutes=1),
    ))
    sender.send_reminder.side_effect = [
        RuntimeError("telegram unavailable"), 888
    ]

    result = await mailing_service.send_due_reminders(now=now)

    await db_call(first.refresh_from_db)
    await db_call(second.refresh_from_db)
    assert result == {
        "processed": 2,
        "sent": 1,
        "failed": 1,
        "skipped": 0,
    }
    assert sender.send_reminder.await_count == 2
    assert first.sent_time is None
    assert first.message_id is None
    assert second.sent_time is not None
    assert second.message_id == 888
    assert await db_call(TaskEvent.objects.count) == 1


@pytest.mark.asyncio
async def test_batch_continues_after_delivery_persistence_error(
        sender, task, caplog):
    now = timezone.now()
    first = await db_call(lambda: Reminder.objects.create(
        task=task,
        reminder_time=now - timedelta(minutes=2),
    ))
    second = await db_call(lambda: Reminder.objects.create(
        task=task,
        reminder_time=now - timedelta(minutes=1),
    ))
    reminder_service = Mock()
    reminder_service.get_due_reminders.return_value = [first, second]
    reminder_service.mark_sent.side_effect = [
        RuntimeError("database unavailable"), second
    ]
    sender.send_reminder.side_effect = [777, 888]
    mailing_service = ReminderMailingService(
        sender=sender,
        reminder_service=reminder_service,
    )

    with caplog.at_level(logging.ERROR, logger="reminder.services.mailing"):
        result = await mailing_service.send_due_reminders(now=now)

    assert result == {
        "processed": 2,
        "sent": 1,
        "failed": 1,
        "skipped": 0,
    }
    assert sender.send_reminder.await_count == 2
    assert reminder_service.mark_sent.call_count == 2
    assert "Failed to persist reminder delivery" in caplog.text
    assert "Failed to deliver reminder" not in caplog.text


@pytest.mark.asyncio
async def test_missing_message_id_is_failed_delivery(mailing_service, sender,
                                                     task, caplog):
    now = timezone.now()
    reminder = await db_call(lambda: Reminder.objects.create(
        task=task,
        reminder_time=now - timedelta(minutes=1),
    ))
    sender.send_reminder.return_value = None

    with caplog.at_level(logging.ERROR, logger="reminder.services.mailing"):
        result = await mailing_service.send_due_reminders(now=now)

    await db_call(reminder.refresh_from_db)
    assert result["failed"] == 1
    assert result["sent"] == 0
    assert reminder.sent_time is None
    assert reminder.message_id is None
    assert await db_call(TaskEvent.objects.count) == 0
    assert "Telegram returned no message_id" in caplog.text
    assert "Failed to deliver reminder" not in caplog.text


@pytest.mark.asyncio
async def test_telegram_error_details_are_not_logged(mailing_service, sender,
                                                     task, caplog):
    now = timezone.now()
    await db_call(lambda: Reminder.objects.create(
        task=task,
        reminder_time=now - timedelta(minutes=1),
    ))
    secret = "telegram-secret-token"
    sender.send_reminder.side_effect = RuntimeError(secret)

    with caplog.at_level(logging.ERROR, logger="reminder.services.mailing"):
        await mailing_service.send_due_reminders(now=now)

    assert secret not in caplog.text
    assert "Failed to deliver reminder" in caplog.text


@pytest.mark.asyncio
async def test_morning_digest_sends_one_card_per_active_task_today(
        mailing_service, sender, user):
    today = timezone.localdate()
    first = await db_call(lambda: Task.objects.create(
        user=user,
        title="Утро",
        due_to=due_on(today, hour=9),
    ))
    second = await db_call(lambda: Task.objects.create(
        user=user,
        title="День",
        due_to=due_on(today, hour=15),
    ))
    await db_call(lambda: Task.objects.create(
        user=user,
        title="Завтра",
        due_to=due_on(today + timedelta(days=1)),
    ))
    await db_call(lambda: Task.objects.create(
        user=user,
        title="Без даты",
        due_to=None,
    ))
    await db_call(lambda: Task.objects.create(
        user=user,
        title="Готово",
        due_to=due_on(today),
        status=Task.Status.DONE,
    ))

    result = await mailing_service.send_morning_digest()

    assert result == {
        "processed": 2,
        "sent": 2,
        "failed": 0,
        "skipped": 0,
    }
    assert sender.send_digest.await_count == 2
    sender.send_digest.assert_any_await(user.chat_id, first)
    sender.send_digest.assert_any_await(user.chat_id, second)


@pytest.mark.asyncio
async def test_morning_digest_empty_day_is_silent(mailing_service, sender):
    result = await mailing_service.send_morning_digest()

    assert result == {
        "processed": 0,
        "sent": 0,
        "failed": 0,
        "skipped": 0,
    }
    sender.send_digest.assert_not_awaited()


@pytest.mark.asyncio
async def test_morning_digest_skips_only_tasks_already_sent_today(
        mailing_service, sender, user, task):
    today = timezone.localdate()
    task.due_to = due_on(today)
    await db_call(lambda: task.save(update_fields=["due_to"]))
    await db_call(lambda: TaskEvent.objects.create(
        task=task,
        event_type=TaskEvent.EventType.DIGEST_CARD_SENT,
        message_id=1001,
    ))
    remaining = await db_call(lambda: Task.objects.create(
        user=user,
        title="Ещё на сегодня",
        due_to=due_on(today, hour=12),
    ))

    result = await mailing_service.send_morning_digest()

    assert result == {
        "processed": 2,
        "sent": 1,
        "failed": 0,
        "skipped": 1,
    }
    sender.send_digest.assert_awaited_once_with(user.chat_id, remaining)


@pytest.mark.asyncio
async def test_morning_digest_resumes_after_partial_run(user):
    today = timezone.localdate()
    first = await db_call(lambda: Task.objects.create(
        user=user,
        title="Уже ушла",
        due_to=due_on(today, hour=9),
    ))
    second = await db_call(lambda: Task.objects.create(
        user=user,
        title="Ещё нет",
        due_to=due_on(today, hour=10),
    ))
    await db_call(lambda: TaskEvent.objects.create(
        task=first,
        event_type=TaskEvent.EventType.DIGEST_CARD_SENT,
        message_id=1001,
    ))
    bot = Mock()
    bot.send_message = AsyncMock(return_value=Mock(message_id=1002))
    service = ReminderMailingService(sender=TelegramSender(bot))

    result = await service.send_morning_digest()

    assert result == {
        "processed": 2,
        "sent": 1,
        "failed": 0,
        "skipped": 1,
    }
    bot.send_message.assert_awaited_once()
    assert bot.send_message.await_args.kwargs["chat_id"] == user.chat_id
    assert second.title in bot.send_message.await_args.kwargs["text"]


@pytest.mark.asyncio
async def test_morning_digest_repeated_run_is_idempotent(user):
    today = timezone.localdate()
    task = await db_call(lambda: Task.objects.create(
        user=user,
        title="Дайджест",
        due_to=due_on(today),
    ))
    bot = Mock()
    bot.send_message = AsyncMock(side_effect=[
        Mock(message_id=501),
        Mock(message_id=502),
    ])
    service = ReminderMailingService(sender=TelegramSender(bot))

    first = await service.send_morning_digest()
    second = await service.send_morning_digest()

    assert first == {
        "processed": 1,
        "sent": 1,
        "failed": 0,
        "skipped": 0,
    }
    assert second == {
        "processed": 1,
        "sent": 0,
        "failed": 0,
        "skipped": 1,
    }
    assert bot.send_message.await_count == 1
    events = await db_call(lambda: list(
        TaskEvent.objects.filter(
            task=task,
            event_type=TaskEvent.EventType.DIGEST_CARD_SENT,
        ).values_list("message_id", flat=True)))
    assert events == [501]


@pytest.mark.asyncio
async def test_morning_digest_continues_after_telegram_error(
        mailing_service, sender, user, caplog):
    today = timezone.localdate()
    first = await db_call(lambda: Task.objects.create(
        user=user,
        title="Падает",
        due_to=due_on(today, hour=9),
    ))
    second = await db_call(lambda: Task.objects.create(
        user=user,
        title="Ок",
        due_to=due_on(today, hour=10),
    ))
    sender.send_digest.side_effect = [
        RuntimeError("telegram unavailable"),
        902,
    ]

    with caplog.at_level(logging.ERROR, logger="reminder.services.mailing"):
        result = await mailing_service.send_morning_digest()

    assert result == {
        "processed": 2,
        "sent": 1,
        "failed": 1,
        "skipped": 0,
    }
    assert sender.send_digest.await_count == 2
    sender.send_digest.assert_any_await(user.chat_id, first)
    sender.send_digest.assert_any_await(user.chat_id, second)
    assert "Failed to deliver digest card" in caplog.text
    assert "telegram unavailable" not in caplog.text


@pytest.mark.asyncio
async def test_morning_digest_accepts_datetime_and_uses_local_date(
        mailing_service, sender, user):
    today = timezone.localdate()
    task = await db_call(lambda: Task.objects.create(
        user=user,
        title="Сегодня",
        due_to=due_on(today),
    ))

    result = await mailing_service.send_morning_digest(now=timezone.now())

    assert result["sent"] == 1
    sender.send_digest.assert_awaited_once_with(user.chat_id, task)
