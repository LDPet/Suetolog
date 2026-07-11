from datetime import timedelta

import pytest
from django.utils import timezone

from reminder.models import Reminder, Task, TaskEvent
from reminder.services.reminders import ReminderService


@pytest.fixture
def service():
    return ReminderService()


@pytest.mark.django_db
def test_returns_due_reminder(service, task):
    now = timezone.now()

    due_reminder = Reminder.objects.create(
        task=task,
        reminder_time=now - timedelta(minutes=5),
    )

    result = service.get_due_reminders(now)

    assert due_reminder in result


@pytest.mark.django_db
def test_reminders_skips_sent_reminder(service, task):
    now = timezone.now()

    sent_reminder = Reminder.objects.create(
        task=task,
        reminder_time=now - timedelta(minutes=5),
        sent_time=now,
    )

    result = service.get_due_reminders(now)

    assert sent_reminder not in result


@pytest.mark.django_db
def test_skips_future_reminder(service, task):
    now = timezone.now()

    future_reminder = Reminder.objects.create(
        task=task,
        reminder_time=now + timedelta(minutes=5),
    )

    result = service.get_due_reminders(now)

    assert future_reminder not in result


@pytest.mark.django_db
@pytest.mark.parametrize(
    "status",
    [
        Task.Status.DONE,
        Task.Status.CANCELLED,
        Task.Status.DELETED,
    ],
)
def test_skips_inactive_tasks(service, task, status):
    now = timezone.now()

    task.status = status
    task.save(update_fields=["status"])

    reminder = Reminder.objects.create(
        task=task,
        reminder_time=now - timedelta(minutes=5),
    )

    result = service.get_due_reminders(now)

    assert reminder not in result


@pytest.mark.django_db
def test_saves_message_id_and_creates_event(service, task):
    reminder = Reminder.objects.create(
        task=task,
        reminder_time=timezone.now(),
    )

    result = service.mark_sent(
        reminder=reminder,
        message_id=777,
    )

    reminder.refresh_from_db()

    assert result is not None
    assert reminder.sent_time is not None
    assert reminder.message_id == 777

    event = TaskEvent.objects.get(
        task=task,
        event_type=TaskEvent.EventType.REMINDER_SENT,
    )

    assert event.message_id == 777


@pytest.mark.django_db
def test_is_idempotent(service, task):
    reminder = Reminder.objects.create(
        task=task,
        reminder_time=timezone.now(),
    )

    first_result = service.mark_sent(
        reminder=reminder,
        message_id=777,
    )

    second_result = service.mark_sent(
        reminder=reminder,
        message_id=888,
    )

    reminder.refresh_from_db()

    assert first_result is not None
    assert second_result is not None
    assert reminder.message_id == 777
    assert TaskEvent.objects.filter(
        task=task,
        event_type=TaskEvent.EventType.REMINDER_SENT,
    ).count() == 1


@pytest.mark.django_db
def test_returns_reminder(service, user, reminder):
    result = service.find_by_message(
        chat_id=user.chat_id,
        message_id=reminder.message_id,
    )

    assert result == reminder


@pytest.mark.django_db
def test_returns_none_for_wrong_chat(service, reminder):
    result = service.find_by_message(
        chat_id=999999,
        message_id=reminder.message_id,
    )

    assert result is None


@pytest.mark.django_db
def test_skips_reminder_without_message_id(service, user, task):
    reminder = Reminder.objects.create(
        task=task,
        reminder_time=timezone.now(),
    )

    result = service.find_by_message(
        chat_id=user.chat_id,
        message_id=123456,
    )

    assert result is None


@pytest.mark.django_db
def test_creates_reminder(service, task):
    reminder_time = timezone.now() + timedelta(hours=1)

    reminder = service.create_for_task(
        task=task,
        reminder_time=reminder_time,
    )

    assert reminder.task == task
    assert reminder.reminder_time == reminder_time
    assert Reminder.objects.filter(id=reminder.id).exists()


@pytest.mark.django_db
def test_limit(service, task):
    now = timezone.now()

    first = Reminder.objects.create(
        task=task,
        reminder_time=now - timedelta(minutes=3),
    )
    second = Reminder.objects.create(
        task=task,
        reminder_time=now - timedelta(minutes=2),
    )
    Reminder.objects.create(
        task=task,
        reminder_time=now - timedelta(minutes=1),
    )

    result = service.get_due_reminders(
        now=now,
        limit=2,
    )

    assert result == [first, second]
