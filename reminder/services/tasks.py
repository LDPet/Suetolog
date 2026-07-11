"""Business rules for creating and mutating tasks."""

from datetime import date as Date
from datetime import datetime

from django.db import transaction
from django.utils import timezone

from reminder.models import Reminder, Task, TaskEvent, User
from reminder.repositories.bundles import create_task_with_reminder_and_event
from reminder.repositories.reminders import ReminderRepository
from reminder.repositories.task_event import TaskEventRepository
from reminder.repositories.tasks import TaskRepository
from reminder.services.dto import ParsedTaskInput


class TaskNotFoundError(LookupError):
    pass


class TaskStateError(ValueError):
    pass


class TaskDateInPastError(ValueError):
    pass


class TaskService:

    def create_from_parsed(self, user: User, parsed: ParsedTaskInput) -> Task:
        """Создать задачу и напоминание из проверенного результата парсера."""
        if parsed.due_to is not None:
            self._validate_due_to(parsed.due_to, parsed.due_to_has_time)

        return create_task_with_reminder_and_event(
            user=user,
            title=parsed.title,
            description=parsed.description or "",
            due_to=parsed.due_to,
            due_to_has_time=parsed.due_to_has_time,
            repeat_type=parsed.repeat_type,
            repeat_interval=parsed.repeat_interval,
            reminder_time=self._get_reminder_time(
                parsed.due_to,
                parsed.due_to_has_time,
            ),
        )

    @staticmethod
    def list_undated(user: User) -> list[Task]:
        return TaskRepository.list_undated(user)

    @staticmethod
    def list_for_day(user: User, date: Date) -> list[Task]:
        return TaskRepository.list_for_day(user, date)

    @transaction.atomic
    def set_due_date(self,
                     user: User,
                     task_id: int,
                     due_to: datetime,
                     due_to_has_time: bool = True) -> Task:
        """Назначить первый срок и сохранить признак точного времени."""
        self._validate_due_to(due_to, due_to_has_time)
        task = self._get_owned_task_for_update(user, task_id)
        self._require_active(task)
        if task.due_to is not None:
            raise TaskStateError(
                "Task already has a date; use reschedule instead.")
        return self._change_due_to(task, due_to, due_to_has_time,
                                   TaskEvent.EventType.DATE_SET)

    @transaction.atomic
    def reschedule(self,
                   user: User,
                   task_id: int,
                   due_to: datetime,
                   due_to_has_time: bool = True) -> Task:
        """Изменить срок задачи и пересоздать ожидающее напоминание."""
        self._validate_due_to(due_to, due_to_has_time)
        task = self._get_owned_task_for_update(user, task_id)
        self._require_active(task)
        if task.due_to is None:
            raise TaskStateError("Task has no date; use set_due_date instead.")
        return self._change_due_to(task, due_to, due_to_has_time,
                                   TaskEvent.EventType.RESCHEDULED)

    @transaction.atomic
    def delete_task(self, user: User, task_id: int) -> Task:
        task = self._get_owned_task_for_update(user, task_id)
        if task.status == Task.Status.DELETED:
            return task
        self._require_active(task)
        return self._set_final_status(task, Task.Status.DELETED,
                                      TaskEvent.EventType.DELETED)

    def mark_done(self,
                  user: User,
                  task_id: int | None = None,
                  reminder: Reminder | None = None) -> Task:
        return self._mark_final(
            user,
            task_id,
            reminder,
            Task.Status.DONE,
            TaskEvent.EventType.COMPLETED,
        )

    def mark_cancelled(self,
                       user: User,
                       task_id: int | None = None,
                       reminder: Reminder | None = None) -> Task:
        return self._mark_final(
            user,
            task_id,
            reminder,
            Task.Status.CANCELLED,
            TaskEvent.EventType.CANCELLED,
        )

    @transaction.atomic
    def _mark_final(self, user: User, task_id: int | None,
                    reminder: Reminder | None, status: str,
                    event_type: str) -> Task:
        resolved_task_id = self._resolve_task_id(task_id, reminder)
        task = self._get_owned_task_for_update(user, resolved_task_id)
        if task.status != Task.Status.ACTIVE:
            return task
        return self._set_final_status(task, status, event_type)

    @staticmethod
    def _resolve_task_id(task_id: int | None,
                         reminder: Reminder | None) -> int:
        if (task_id is None) == (reminder is None):
            raise ValueError("Provide exactly one of task_id or reminder.")
        if reminder is not None:
            return reminder.task_id
        return task_id

    @staticmethod
    def _get_owned_task_for_update(user: User, task_id: int) -> Task:
        task = TaskRepository.get_by_id_for_update(task_id)
        if task is None:
            raise TaskNotFoundError("Task was not found.")
        if task.user_id != user.id:
            raise PermissionError("Task belongs to another user.")
        return task

    @staticmethod
    def _require_active(task: Task) -> None:
        if task.status != Task.Status.ACTIVE:
            raise TaskStateError("Only active tasks can be changed.")

    @staticmethod
    def _change_due_to(task: Task, due_to: datetime, due_to_has_time: bool,
                       event_type: str) -> Task:
        """Сохранить новый срок, заменить напоминание и создать событие."""
        TaskRepository.update_due_to(task, due_to, due_to_has_time)
        ReminderRepository.replace_pending_for_task(
            task,
            TaskService._get_reminder_time(due_to, due_to_has_time),
        )
        TaskEventRepository.create(task=task, event_type=event_type)
        return task

    @staticmethod
    def _set_final_status(task: Task, status: str, event_type: str) -> Task:
        TaskRepository.update_status(task, status)
        ReminderRepository.delete_pending_for_task(task)
        TaskEventRepository.create(task=task, event_type=event_type)
        return task

    @staticmethod
    def _validate_due_to(due_to: datetime, due_to_has_time: bool) -> None:
        """Проверить календарную дату и точное время по разным правилам."""
        if not isinstance(due_to, datetime):
            raise TypeError("due_to must be a datetime.")
        if not isinstance(due_to_has_time, bool):
            raise TypeError("due_to_has_time must be a bool.")
        if timezone.is_naive(due_to):
            raise ValueError("due_to must be timezone-aware.")

        now = timezone.now()
        if due_to_has_time:
            is_past = due_to <= now
        else:
            is_past = timezone.localdate(due_to) < timezone.localdate(now)

        if is_past:
            raise TaskDateInPastError("Task date is in the past.")

    @staticmethod
    def _get_reminder_time(due_to: datetime | None,
                           due_to_has_time: bool) -> datetime | None:
        """Вернуть время напоминания только для точного будущего срока."""
        if due_to is None or not due_to_has_time:
            return None
        if due_to <= timezone.now():
            return None
        return due_to
