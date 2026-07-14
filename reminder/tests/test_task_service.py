from datetime import datetime, time, timedelta
from unittest.mock import Mock

import pytest
from django.utils import timezone

from reminder.models import Reminder, Task, TaskEvent, User
from reminder.repositories.reminders import ReminderRepository
from reminder.repositories.task_event import TaskEventRepository
from reminder.services.dto import ParsedTaskInput
from reminder.services.tasks import (TaskDateInPastError, TaskNotFoundError,
                                     TaskService, TaskStateError)

pytestmark = pytest.mark.django_db


@pytest.fixture
def service():
    return TaskService()


@pytest.fixture
def other_user():
    return User.objects.create(chat_id=222222, telegram_user_id=333333)


def parsed_task(**overrides) -> ParsedTaskInput:
    values = {
        "title": "Позвонить врачу",
        "raw_text": "завтра в 15 позвонить врачу",
        "description": None,
        "due_to": None,
        "due_to_has_time": False,
        "repeat_type": None,
        "repeat_interval": None,
    }
    values.update(overrides)
    return ParsedTaskInput(**values)


def future_at(hour: int = 15, days: int = 1) -> datetime:
    return (timezone.now() + timedelta(days=days)).replace(
        hour=hour,
        minute=0,
        second=0,
        microsecond=0,
    )


def moscow_datetime(year: int,
                    month: int,
                    day: int,
                    hour: int = 0,
                    minute: int = 0) -> datetime:
    return timezone.make_aware(
        datetime(year, month, day, hour, minute),
        timezone.get_default_timezone(),
    )


def configure_repeat(task: Task,
                     due_to: datetime,
                     repeat_type: str,
                     repeat_interval: int = 1,
                     *,
                     due_to_has_time: bool = True) -> Task:
    task.due_to = due_to
    task.due_to_has_time = due_to_has_time
    task.repeat_type = repeat_type
    task.repeat_interval = repeat_interval
    task.save(update_fields=[
        "due_to",
        "due_to_has_time",
        "repeat_type",
        "repeat_interval",
    ])
    return task


def test_create_with_future_due_to_creates_task_reminder_and_event(
        service, user):
    due_to = future_at()

    task = service.create_from_parsed(
        user,
        parsed_task(
            due_to=due_to,
            due_to_has_time=True,
            description="Регистратура",
        ))

    assert task.user == user
    assert task.title == "Позвонить врачу"
    assert task.description == "Регистратура"
    assert task.due_to == due_to
    assert task.due_to_has_time is True
    assert task.status == Task.Status.ACTIVE
    assert task.reminders.get().reminder_time == due_to
    assert task.events.get().event_type == TaskEvent.EventType.CREATED


def test_create_without_date_has_no_reminder(service, user):
    task = service.create_from_parsed(user, parsed_task())

    assert task.due_to is None
    assert task.reminders.count() == 0
    assert task.events.filter(
        event_type=TaskEvent.EventType.CREATED).count() == 1


def test_create_with_date_without_time_has_no_reminder(service, user):
    tomorrow = timezone.localdate() + timedelta(days=1)
    due_to = timezone.make_aware(
        datetime.combine(tomorrow, time.min),
        timezone.get_current_timezone(),
    )

    task = service.create_from_parsed(user, parsed_task(due_to=due_to))

    assert task.due_to == due_to
    assert task.due_to_has_time is False
    assert task.reminders.count() == 0


def test_create_with_today_without_time_is_allowed(service, user):
    due_to = timezone.make_aware(
        datetime.combine(timezone.localdate(), time.min),
        timezone.get_current_timezone(),
    )

    task = service.create_from_parsed(user, parsed_task(due_to=due_to))

    assert task.due_to == due_to
    assert task.due_to_has_time is False
    assert task.reminders.count() == 0


def test_create_rejects_past_calendar_date_without_time(service, user):
    yesterday = timezone.localdate() - timedelta(days=1)
    due_to = timezone.make_aware(
        datetime.combine(yesterday, time.min),
        timezone.get_current_timezone(),
    )

    with pytest.raises(TaskDateInPastError):
        service.create_from_parsed(user, parsed_task(due_to=due_to))


def test_explicit_future_midnight_creates_reminder(service, user):
    tomorrow = timezone.localdate() + timedelta(days=1)
    due_to = timezone.make_aware(
        datetime.combine(tomorrow, time.min),
        timezone.get_current_timezone(),
    )

    task = service.create_from_parsed(
        user,
        parsed_task(due_to=due_to, due_to_has_time=True),
    )

    assert task.due_to_has_time is True
    assert task.reminders.get().reminder_time == due_to


def test_create_rejects_past_date_without_partial_task(service, user):
    with pytest.raises(TaskDateInPastError):
        service.create_from_parsed(
            user,
            parsed_task(
                due_to=timezone.now() - timedelta(minutes=1),
                due_to_has_time=True,
            ),
        )

    assert Task.objects.count() == 0
    assert Reminder.objects.count() == 0
    assert TaskEvent.objects.count() == 0


def test_create_rolls_back_when_reminder_creation_fails(
        service, user, monkeypatch):
    monkeypatch.setattr(
        ReminderRepository,
        "create",
        Mock(side_effect=RuntimeError("Reminder storage failed")),
    )

    with pytest.raises(RuntimeError, match="Reminder storage failed"):
        service.create_from_parsed(
            user,
            parsed_task(due_to=future_at(), due_to_has_time=True),
        )

    assert Task.objects.count() == 0
    assert Reminder.objects.count() == 0
    assert TaskEvent.objects.count() == 0


def test_list_undated_returns_only_users_active_undated_tasks(
        service, user, other_user):
    expected = Task.objects.create(user=user, title="Без даты", due_to=None)
    Task.objects.create(user=user, title="С датой", due_to=future_at())
    Task.objects.create(user=user,
                        title="Завершена",
                        due_to=None,
                        status=Task.Status.DONE)
    Task.objects.create(user=other_user, title="Чужая", due_to=None)

    assert service.list_undated(user) == [expected]


def test_list_for_day_returns_only_users_active_tasks(service, user,
                                                      other_user):
    target_day = timezone.localdate() + timedelta(days=2)
    target_due = timezone.make_aware(
        datetime.combine(target_day, time(hour=10)),
        timezone.get_current_timezone(),
    )
    expected = Task.objects.create(user=user,
                                   title="На день",
                                   due_to=target_due)
    Task.objects.create(user=user,
                        title="Другой день",
                        due_to=target_due + timedelta(days=1))
    Task.objects.create(user=user,
                        title="Завершена",
                        due_to=target_due,
                        status=Task.Status.DONE)
    Task.objects.create(user=other_user, title="Чужая", due_to=target_due)

    assert service.list_for_day(user, date=target_day) == [expected]


def test_set_due_date_creates_reminder_and_date_set_event(service, user, task):
    due_to = future_at()

    updated = service.set_due_date(user, task.id, due_to)

    assert updated.due_to == due_to
    assert updated.due_to_has_time is True
    assert updated.reminders.get().reminder_time == due_to
    assert updated.events.get().event_type == TaskEvent.EventType.DATE_SET


def test_set_due_date_on_final_task_is_rejected(service, user, task):
    task.status = Task.Status.DONE
    task.save(update_fields=["status"])

    with pytest.raises(TaskStateError):
        service.set_due_date(user, task.id, future_at())

    task.refresh_from_db()
    assert task.due_to is None
    assert task.events.count() == 0


def test_set_due_date_rejects_task_that_already_has_date(service, user, task):
    task.due_to = future_at()
    task.save(update_fields=["due_to"])

    with pytest.raises(TaskStateError, match="reschedule"):
        service.set_due_date(user, task.id, future_at(days=2))


def test_reschedule_replaces_pending_reminder_and_creates_event(
        service, user, task):
    old_due_to = future_at()
    new_due_to = future_at(hour=18, days=2)
    task.due_to = old_due_to
    task.save(update_fields=["due_to"])
    old_reminder = Reminder.objects.create(task=task, reminder_time=old_due_to)

    updated = service.reschedule(user, task.id, new_due_to)

    assert updated.due_to == new_due_to
    assert updated.due_to_has_time is True
    assert not Reminder.objects.filter(id=old_reminder.id).exists()
    assert updated.reminders.get().reminder_time == new_due_to
    assert updated.events.get().event_type == TaskEvent.EventType.RESCHEDULED


def test_reschedule_to_date_without_time_removes_pending_reminder(
        service, user, task):
    old_due_to = future_at()
    new_day = timezone.localdate() + timedelta(days=2)
    new_due_to = timezone.make_aware(
        datetime.combine(new_day, time.min),
        timezone.get_current_timezone(),
    )
    task.due_to = old_due_to
    task.due_to_has_time = True
    task.save(update_fields=["due_to", "due_to_has_time"])
    Reminder.objects.create(task=task, reminder_time=old_due_to)

    updated = service.reschedule(
        user,
        task.id,
        new_due_to,
        due_to_has_time=False,
    )

    assert updated.due_to == new_due_to
    assert updated.due_to_has_time is False
    assert updated.reminders.count() == 0


def test_reschedule_rejects_past_date_without_changes(service, user, task):
    old_due_to = future_at()
    task.due_to = old_due_to
    task.save(update_fields=["due_to"])

    with pytest.raises(TaskDateInPastError):
        service.reschedule(user, task.id,
                           timezone.now() - timedelta(minutes=1))

    task.refresh_from_db()
    assert task.due_to == old_due_to
    assert task.events.count() == 0


def test_delete_marks_task_deletes_pending_reminder_and_creates_event(
        service, user, task):
    Reminder.objects.create(task=task, reminder_time=future_at())

    deleted = service.delete_task(user, task.id)

    assert deleted.status == Task.Status.DELETED
    assert deleted.reminders.count() == 0
    assert deleted.events.get().event_type == TaskEvent.EventType.DELETED


def test_repeated_delete_is_noop(service, user, task):
    service.delete_task(user, task.id)
    service.delete_task(user, task.id)

    assert task.events.filter(
        event_type=TaskEvent.EventType.DELETED).count() == 1


def test_mark_done_is_idempotent(service, user, task):
    Reminder.objects.create(task=task, reminder_time=future_at())

    service.mark_done(user, task_id=task.id)
    completed = service.mark_done(user, task_id=task.id)

    assert completed.status == Task.Status.DONE
    assert completed.reminders.count() == 0
    assert completed.events.filter(
        event_type=TaskEvent.EventType.COMPLETED).count() == 1


def test_mark_done_rolls_daily_task_to_next_occurrence(service, user, task,
                                                       monkeypatch):
    now = moscow_datetime(2026, 7, 14, 9)
    due_to = moscow_datetime(2026, 7, 14, 10)
    expected_due_to = moscow_datetime(2026, 7, 15, 10)
    monkeypatch.setattr(timezone, "now", lambda: now)
    configure_repeat(task, due_to, Task.RepeatType.DAILY)
    old_reminder = Reminder.objects.create(task=task, reminder_time=due_to)

    rolled = service.mark_done(user, task_id=task.id)

    rolled.refresh_from_db()
    assert rolled.status == Task.Status.ACTIVE
    assert rolled.due_to == expected_due_to
    assert not Reminder.objects.filter(id=old_reminder.id).exists()
    assert rolled.reminders.get().reminder_time == expected_due_to
    assert rolled.events.filter(
        event_type=TaskEvent.EventType.COMPLETED).count() == 1
    assert rolled.events.filter(
        event_type=TaskEvent.EventType.RESCHEDULED).count() == 0


def test_mark_done_fast_forwards_deeply_overdue_repeat(service, user, task,
                                                       monkeypatch):
    now = moscow_datetime(2026, 7, 13, 18)
    due_to = moscow_datetime(2026, 7, 10, 10)
    expected_due_to = moscow_datetime(2026, 7, 14, 10)
    monkeypatch.setattr(timezone, "now", lambda: now)
    configure_repeat(task, due_to, Task.RepeatType.DAILY)
    Reminder.objects.create(task=task, reminder_time=due_to)

    rolled = service.mark_done(user, task_id=task.id)

    rolled.refresh_from_db()
    pending = rolled.reminders.filter(sent_time__isnull=True)
    assert rolled.due_to == expected_due_to
    assert pending.count() == 1
    assert pending.get().reminder_time == expected_due_to
    assert rolled.events.filter(
        event_type=TaskEvent.EventType.COMPLETED).count() == 1


def test_weekly_rollover_preserves_weekday_and_time(service, user, task,
                                                    monkeypatch):
    now = moscow_datetime(2026, 7, 15, 12)
    due_to = moscow_datetime(2026, 7, 6, 9, 30)
    expected_due_to = moscow_datetime(2026, 7, 20, 9, 30)
    monkeypatch.setattr(timezone, "now", lambda: now)
    configure_repeat(task, due_to, Task.RepeatType.WEEKLY)

    rolled = service.mark_done(user, task_id=task.id)

    rolled.refresh_from_db()
    local_due_to = timezone.localtime(rolled.due_to)
    assert rolled.due_to == expected_due_to
    assert local_due_to.weekday() == timezone.localtime(due_to).weekday()
    assert (local_due_to.hour, local_due_to.minute) == (9, 30)


@pytest.mark.parametrize(
    ("repeat_type", "repeat_interval", "due_to", "now", "expected"),
    [
        (
            Task.RepeatType.MINUTELY,
            2,
            moscow_datetime(2026, 7, 14, 10),
            moscow_datetime(2026, 7, 14, 10, 5),
            moscow_datetime(2026, 7, 14, 10, 6),
        ),
        (
            Task.RepeatType.HOURLY,
            3,
            moscow_datetime(2026, 7, 14, 10),
            moscow_datetime(2026, 7, 14, 15),
            moscow_datetime(2026, 7, 14, 16),
        ),
        (
            Task.RepeatType.DAILY,
            2,
            moscow_datetime(2026, 7, 10, 10),
            moscow_datetime(2026, 7, 13, 10),
            moscow_datetime(2026, 7, 14, 10),
        ),
        (
            Task.RepeatType.WEEKLY,
            2,
            moscow_datetime(2026, 7, 6, 9),
            moscow_datetime(2026, 7, 20, 9),
            moscow_datetime(2026, 8, 3, 9),
        ),
        (
            Task.RepeatType.MONTHLY,
            1,
            moscow_datetime(2026, 1, 31, 10),
            moscow_datetime(2026, 2, 28, 10),
            moscow_datetime(2026, 3, 31, 10),
        ),
    ],
)
def test_next_repeat_due_supports_every_repeat_type(service, repeat_type,
                                                    repeat_interval, due_to,
                                                    now, expected):
    assert service._next_repeat_due(
        due_to,
        repeat_type,
        repeat_interval,
        now=now,
    ) == expected


def test_repeated_done_for_same_reminder_is_noop(service, user, task,
                                                 monkeypatch):
    now = moscow_datetime(2026, 7, 13, 18)
    due_to = moscow_datetime(2026, 7, 10, 10)
    expected_due_to = moscow_datetime(2026, 7, 14, 10)
    monkeypatch.setattr(timezone, "now", lambda: now)
    configure_repeat(task, due_to, Task.RepeatType.DAILY)
    sent_reminder = Reminder.objects.create(
        task=task,
        reminder_time=due_to,
        sent_time=due_to,
        message_id=98765,
    )

    first = service.mark_done(user, reminder=sent_reminder)
    second = service.mark_done(user, reminder=sent_reminder)

    first.refresh_from_db()
    second.refresh_from_db()
    sent_reminder.refresh_from_db()
    assert first.due_to == expected_due_to
    assert second.due_to == expected_due_to
    assert sent_reminder.reaction == Task.Status.DONE
    assert task.reminders.filter(sent_time__isnull=True).count() == 1
    assert task.events.filter(
        event_type=TaskEvent.EventType.COMPLETED).count() == 1


@pytest.mark.parametrize(
    ("method_name", "expected_status", "event_type"),
    [
        (
            "mark_cancelled",
            Task.Status.CANCELLED,
            TaskEvent.EventType.CANCELLED,
        ),
        (
            "delete_task",
            Task.Status.DELETED,
            TaskEvent.EventType.DELETED,
        ),
    ],
)
def test_cancel_or_delete_stops_repeating_series(service, user, task,
                                                 method_name, expected_status,
                                                 event_type):
    due_to = future_at()
    configure_repeat(task, due_to, Task.RepeatType.DAILY)
    Reminder.objects.create(task=task, reminder_time=due_to)

    final_task = getattr(service, method_name)(user, task_id=task.id)

    final_task.refresh_from_db()
    assert final_task.status == expected_status
    assert final_task.reminders.filter(sent_time__isnull=True).count() == 0
    assert final_task.events.filter(event_type=event_type).count() == 1


def test_date_only_repeat_rolls_without_creating_reminder(
        service, user, task, monkeypatch):
    now = moscow_datetime(2026, 7, 14, 12)
    due_to = moscow_datetime(2026, 7, 14)
    expected_due_to = moscow_datetime(2026, 7, 15)
    monkeypatch.setattr(timezone, "now", lambda: now)
    configure_repeat(
        task,
        due_to,
        Task.RepeatType.DAILY,
        due_to_has_time=False,
    )

    rolled = service.mark_done(user, task_id=task.id)

    rolled.refresh_from_db()
    assert rolled.status == Task.Status.ACTIVE
    assert rolled.due_to == expected_due_to
    assert rolled.reminders.count() == 0


def test_repeat_rollover_rolls_back_when_event_creation_fails(
        service, user, task, monkeypatch):
    now = moscow_datetime(2026, 7, 13, 18)
    due_to = moscow_datetime(2026, 7, 10, 10)
    monkeypatch.setattr(timezone, "now", lambda: now)
    configure_repeat(task, due_to, Task.RepeatType.DAILY)
    sent_reminder = Reminder.objects.create(
        task=task,
        reminder_time=due_to,
        sent_time=due_to,
        message_id=87654,
    )
    monkeypatch.setattr(
        TaskEventRepository,
        "create",
        Mock(side_effect=RuntimeError("Event storage failed")),
    )

    with pytest.raises(RuntimeError, match="Event storage failed"):
        service.mark_done(user, reminder=sent_reminder)

    task.refresh_from_db()
    sent_reminder.refresh_from_db()
    assert task.status == Task.Status.ACTIVE
    assert task.due_to == due_to
    assert sent_reminder.reaction is None
    assert task.reminders.filter(sent_time__isnull=True).count() == 0
    assert task.events.count() == 0


def test_mark_cancelled_accepts_reminder(service, user, task):
    reminder = Reminder.objects.create(task=task, reminder_time=future_at())

    cancelled = service.mark_cancelled(user, reminder=reminder)

    assert cancelled.status == Task.Status.CANCELLED
    assert cancelled.reminders.count() == 0
    assert cancelled.events.get().event_type == TaskEvent.EventType.CANCELLED


def test_changed_reaction_does_not_change_final_status(service, user, task):
    service.mark_done(user, task_id=task.id)

    unchanged = service.mark_cancelled(user, task_id=task.id)

    assert unchanged.status == Task.Status.DONE
    assert unchanged.events.filter(
        event_type=TaskEvent.EventType.COMPLETED).count() == 1
    assert unchanged.events.filter(
        event_type=TaskEvent.EventType.CANCELLED).count() == 0


def test_mutation_rejects_another_users_task(service, other_user, task):
    with pytest.raises(PermissionError):
        service.mark_done(other_user, task_id=task.id)

    task.refresh_from_db()
    assert task.status == Task.Status.ACTIVE
    assert task.events.count() == 0


def test_mutation_rejects_unknown_task(service, user):
    with pytest.raises(TaskNotFoundError):
        service.delete_task(user, 999999)


def test_final_status_rolls_back_when_event_creation_fails(
        service, user, task, monkeypatch):
    reminder = Reminder.objects.create(task=task, reminder_time=future_at())
    monkeypatch.setattr(
        TaskEventRepository,
        "create",
        Mock(side_effect=RuntimeError("Event storage failed")),
    )

    with pytest.raises(RuntimeError, match="Event storage failed"):
        service.mark_done(user, task_id=task.id)

    task.refresh_from_db()
    assert task.status == Task.Status.ACTIVE
    assert Reminder.objects.filter(id=reminder.id).exists()
    assert TaskEvent.objects.count() == 0
