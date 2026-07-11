from django.db import transaction

from reminder.models import Task, TaskEvent
from reminder.repositories.reminders import ReminderRepository
from reminder.repositories.task_event import TaskEventRepository
from reminder.repositories.tasks import TaskRepository

_REMINDER_FROM_DUE_TO = object()


def create_task_with_reminder_and_event(
    *,
    user,
    title: str,
    description: str = "",
    due_to=None,
    repeat_type: str | None = None,
    repeat_interval: int | None = None,
    reminder_time=_REMINDER_FROM_DUE_TO,
) -> Task:
    if reminder_time is _REMINDER_FROM_DUE_TO:
        reminder_time = due_to

    with transaction.atomic():
        task = TaskRepository.create(
            user=user,
            title=title,
            description=description,
            due_to=due_to,
            repeat_type=repeat_type,
            repeat_interval=repeat_interval,
        )
        if reminder_time is not None:
            ReminderRepository.create(task=task, reminder_time=reminder_time)

        TaskEventRepository.create(
            task=task,
            event_type=TaskEvent.EventType.CREATED,
        )
    return task
