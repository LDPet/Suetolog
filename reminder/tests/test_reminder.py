from datetime import timedelta

import pytest
from django.utils import timezone

from reminder.models import Reminder
from reminder.repositories.reminders import ReminderRepository

pytestmark = pytest.mark.django_db


class TestReminderModel:

    def test_create_reminder(self, task):
        now = timezone.now()
        reminder = Reminder.objects.create(
            task=task,
            reminder_time=now,
        )
        assert reminder.task == task
        assert reminder.sent_time is None
        assert reminder.reaction is None
        assert reminder.message_id is None

    def test_relation_with_task(self, task, reminder):
        assert reminder in task.reminders.all()


class TestReminderRepository:

    def test_create(self, task):
        due = timezone.now() + timedelta(hours=2)
        rem = ReminderRepository.create(task, due)
        assert rem.task_id == task.id
        assert rem.reminder_time == due

    def test_get_by_id_found(self, reminder):
        found = ReminderRepository.get_by_id(reminder.id)
        assert found == reminder

    def test_get_by_id_not_found(self):
        assert ReminderRepository.get_by_id(99999) is None

    def test_get_due_reminders(self, task):
        now = timezone.now()
        past_rem = Reminder.objects.create(
            task=task,
            reminder_time=now - timedelta(minutes=10),
            sent_time=None,
        )
        future_rem = Reminder.objects.create(
            task=task,
            reminder_time=now + timedelta(minutes=10),
            sent_time=None,
        )
        sent_rem = Reminder.objects.create(
            task=task,
            reminder_time=now - timedelta(minutes=5),
            sent_time=now,
        )

        due = ReminderRepository.get_due_reminders(now)
        assert past_rem in due
        assert future_rem not in due
        assert sent_rem not in due

    def test_set_reaction_by_message_id_success(self, reminder):
        updated = ReminderRepository.set_reaction_by_message_id(
            reminder.message_id, "✅")
        assert updated is not None
        assert updated.reaction == "✅"
        reminder.refresh_from_db()
        assert reminder.reaction == "✅"

    def test_set_reaction_by_message_id_not_found(self):
        result = ReminderRepository.set_reaction_by_message_id(99999, "❌")
        assert result is None
