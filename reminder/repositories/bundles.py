from django.db import transaction

from reminder.models import Task, TaskEvent
from reminder.repositories.reminders import ReminderRepository
from reminder.repositories.task_event import TaskEventRepository
from reminder.repositories.tasks import TaskRepository


def create_task_with_reminder_and_event(
    *,
    user,
    title: str,
    description: str = "",
    due_to=None,
    repeat_type: str = "",
    repeat_interval: int = None,
) -> Task:
    with transaction.atomic():
        task = TaskRepository.create(
            user=user,
            title=title,
            description=description,
            due_to=due_to,
            repeat_type=repeat_type,
            repeat_interval=repeat_interval,
        )
        if due_to is not None:
            ReminderRepository.create(task=task, reminder_time=due_to)

        TaskEventRepository.create(
            task=task,
            event_type=TaskEvent.EventType.CREATED,
        )
    return task
