from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from asgiref.sync import async_to_sync
from django.utils import timezone

from reminder.bot.handlers.date_reply import handle_date_reply
from reminder.models import Reminder, TaskEvent
from reminder.services.dto import ParsedDateResult
from reminder.services.tasks import TaskService
from reminder.services.users import UserService

pytestmark = pytest.mark.django_db(transaction=True)


def message_for(user, message_id, text="завтра в 15:00"):
    return SimpleNamespace(
        chat=SimpleNamespace(id=user.chat_id),
        from_user=SimpleNamespace(id=user.telegram_user_id),
        text=text,
        reply_to_message=SimpleNamespace(message_id=message_id),
    )


def sender_mock():
    sender = Mock()
    sender.send_text = AsyncMock()
    sender.send_error = AsyncMock()
    sender.send_date_confirmed = AsyncMock()
    return sender


def parser_for(due_to, due_to_has_time):
    parser = Mock()
    parser.parse_date.return_value = ParsedDateResult(
        due_to=due_to,
        due_to_has_time=due_to_has_time,
    )
    return parser


def test_reply_to_old_undated_card_sets_date_and_creates_reminder(user, task):
    card_event = TaskEvent.objects.create(
        task=task,
        event_type=TaskEvent.EventType.UNDATED_CARD_SENT,
        message_id=7001,
    )
    due_to = timezone.now() + timedelta(days=1)
    parser = parser_for(due_to, due_to_has_time=True)
    sender = sender_mock()

    async_to_sync(handle_date_reply)(
        message_for(user, card_event.message_id),
        UserService(),
        TaskService(),
        parser,
        sender,
    )

    task.refresh_from_db()
    assert task.due_to == due_to
    assert task.due_to_has_time is True
    assert Reminder.objects.filter(task=task, reminder_time=due_to).exists()
    assert TaskEvent.objects.filter(
        task=task,
        event_type=TaskEvent.EventType.DATE_SET,
    ).count() == 1
    sender.send_date_confirmed.assert_awaited_once_with(user.chat_id,
                                                        task,
                                                        rescheduled=False)


def test_reply_with_date_without_time_does_not_create_reminder(user, task):
    card_event = TaskEvent.objects.create(
        task=task,
        event_type=TaskEvent.EventType.UNDATED_CARD_SENT,
        message_id=7002,
    )
    due_to = (timezone.localtime(timezone.now()) + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0)
    parser = parser_for(due_to, due_to_has_time=False)

    async_to_sync(handle_date_reply)(
        message_for(user, card_event.message_id, text="завтра"),
        UserService(),
        TaskService(),
        parser,
        sender_mock(),
    )

    task.refresh_from_db()
    assert task.due_to == due_to
    assert task.due_to_has_time is False
    assert not Reminder.objects.filter(task=task).exists()


def test_reply_to_reminder_reschedules_and_creates_new_pending_reminder(
        user, task):
    old_due_to = timezone.now() + timedelta(days=1)
    task.due_to = old_due_to
    task.due_to_has_time = True
    task.save(update_fields=["due_to", "due_to_has_time"])
    sent_at = timezone.now()
    Reminder.objects.create(
        task=task,
        reminder_time=old_due_to,
        sent_time=sent_at,
        message_id=7003,
    )
    card_event = TaskEvent.objects.create(
        task=task,
        event_type=TaskEvent.EventType.REMINDER_SENT,
        message_id=7003,
    )
    new_due_to = timezone.now() + timedelta(days=2)
    parser = parser_for(new_due_to, due_to_has_time=True)
    sender = sender_mock()

    async_to_sync(handle_date_reply)(
        message_for(user, card_event.message_id, text="послезавтра в 18"),
        UserService(),
        TaskService(),
        parser,
        sender,
    )

    task.refresh_from_db()
    pending = Reminder.objects.get(task=task, sent_time__isnull=True)
    assert task.due_to == new_due_to
    assert task.due_to_has_time is True
    assert pending.reminder_time == new_due_to
    assert TaskEvent.objects.filter(
        task=task,
        event_type=TaskEvent.EventType.RESCHEDULED,
    ).count() == 1
    sender.send_date_confirmed.assert_awaited_once_with(user.chat_id,
                                                        task,
                                                        rescheduled=True)
