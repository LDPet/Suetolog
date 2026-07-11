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
    due_to_has_time: bool = False,
    repeat_type: str | None = None,
    repeat_interval: int | None = None,
    reminder_time=_REMINDER_FROM_DUE_TO,
) -> Task:
    """Атомарно создать задачу, напоминание и событие создания."""
    if reminder_time is _REMINDER_FROM_DUE_TO:
        reminder_time = due_to if due_to_has_time else None

    with transaction.atomic():
        task = TaskRepository.create(
            user=user,
            title=title,
            description=description,
            due_to=due_to,
            due_to_has_time=due_to_has_time,
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
