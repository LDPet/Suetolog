from django.conf import settings
from django.db import transaction
from django.utils import timezone

from reminder.models import Reminder, Task, TaskEvent
from reminder.repositories.reminders import ReminderRepository
from reminder.repositories.task_event import TaskEventRepository


class ReminderService:

    def create_for_task(self, task, reminder_time):
        return ReminderRepository.create(
            task=task,
            reminder_time=reminder_time,
        )

    def get_due_reminders(self, now, limit=None):
        if limit is None:
            limit = settings.DEFAULT_BATCH_LIMIT

        return list(
            Reminder.objects.filter(
                task__status=Task.Status.ACTIVE,
                sent_time__isnull=True,
                reminder_time__lte=now,
            ).select_related("task",
                             "task__user").order_by("reminder_time")[:limit])

    @transaction.atomic
    def mark_sent(self, reminder, message_id):
        reminder = (
            Reminder.objects.select_for_update().select_related("task").get(
                id=reminder.id))

        if reminder.sent_time is not None:
            return reminder

        if reminder.task.status != Task.Status.ACTIVE:
            return None

        reminder.sent_time = timezone.now()
        reminder.message_id = message_id
        reminder.save(update_fields=["sent_time", "message_id"])

        TaskEventRepository.create(
            task=reminder.task,
            event_type=TaskEvent.EventType.REMINDER_SENT,
            message_id=message_id,
        )

        return reminder

    def find_by_message(self, chat_id, message_id):
        return (Reminder.objects.select_related("task", "task__user").filter(
            task__user__chat_id=chat_id,
            message_id=message_id,
        ).first())
