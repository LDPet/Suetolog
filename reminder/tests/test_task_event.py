import datetime

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from reminder.models import Task, TaskEvent
from reminder.repositories.bundles import create_task_with_reminder_and_event
from reminder.repositories.task_event import TaskEventRepository

pytestmark = pytest.mark.django_db


class TestTaskEventModel:

    def test_create_event(self, task):
        event = TaskEvent.objects.create(
            task=task,
            event_type=TaskEvent.EventType.CREATED,
            message_id=111,
        )
        assert event.task == task
        assert event.event_type == TaskEvent.EventType.CREATED
        assert event.message_id == 111

    def test_message_id_unique(self, task_event):
        with pytest.raises(IntegrityError):
            TaskEvent.objects.create(
                task=task_event.task,
                event_type=TaskEvent.EventType.REMINDER_SENT,
                message_id=task_event.message_id,
            )


class TestTaskEventRepository:

    def test_create(self, task):
        event = TaskEventRepository.create(
            task=task,
            event_type=TaskEvent.EventType.COMPLETED,
            message_id=222,
        )
        assert event.message_id == 222

    def test_find_by_message_id_found(self, task_event):
        found = TaskEventRepository.find_by_message_id(task_event.message_id)
        assert found == task_event

    def test_find_by_message_id_not_found(self):
        assert TaskEventRepository.find_by_message_id(99999) is None


class TestAtomicBundle:

    def test_create_with_due_to_creates_reminder_and_event(self, user):
        due_to = timezone.make_aware(datetime.datetime(2026, 12, 1, 12, 0, 0))
        task = create_task_with_reminder_and_event(
            user=user,
            title="Test bundle",
            description="Desc",
            due_to=due_to,
        )
        assert task.pk is not None
        reminders = task.reminders.all()
        assert len(reminders) == 1
        assert reminders[0].reminder_time == task.due_to
        events = task.events.filter(event_type=TaskEvent.EventType.CREATED)
        assert events.count() == 1

    def test_create_without_due_to_no_reminder(self, user):
        task = create_task_with_reminder_and_event(
            user=user,
            title="No due",
        )
        assert task.reminders.count() == 0
        assert task.events.filter(
            event_type=TaskEvent.EventType.CREATED).exists()

    def test_atomic_rollback_on_error(self, user):
        with pytest.raises(ValueError):
            with transaction.atomic():
                create_task_with_reminder_and_event(
                    user=user,
                    title="Should rollback",
                )
                raise ValueError("Simulated error")

        assert not Task.objects.filter(title="Should rollback").exists()

    def test_find_by_event_type(self, task):
        TaskEventRepository.create(task=task,
                                   event_type=TaskEvent.EventType.CREATED)
        TaskEventRepository.create(
            task=task, event_type=TaskEvent.EventType.REMINDER_SENT)
        TaskEventRepository.create(task=task,
                                   event_type=TaskEvent.EventType.CREATED)

        created_events = TaskEventRepository.find_by_event_type(
            TaskEvent.EventType.CREATED)
        assert len(created_events) == 2
        assert created_events[0].event_type == TaskEvent.EventType.CREATED
        assert created_events[0].created_at >= created_events[1].created_at

        assert TaskEventRepository.find_by_event_type("nonexistent") == []
