from datetime import datetime

from django.utils import timezone

from reminder.models import Reminder, Task

_MONTHS = (
    "",
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)

_REPEAT_LABELS = {
    Task.RepeatType.MINUTELY: "каждую минуту",
    Task.RepeatType.HOURLY: "каждый час",
    Task.RepeatType.DAILY: "ежедневно",
    Task.RepeatType.WEEKLY: "еженедельно",
}


def format_datetime(value: datetime, *, has_time: bool) -> str:
    local = timezone.localtime(value)
    date_part = f"{local.day} {_MONTHS[local.month]} {local.year}"
    if has_time:
        return f"{date_part}, {local:%H:%M}"
    return date_part


def format_task_due_to(task) -> str:
    if task.due_to is None:
        return "не указан"
    return format_datetime(task.due_to, has_time=task.due_to_has_time)


def format_task_identity(task) -> str:
    """Название и описание — всегда, в одном формате."""
    description = (getattr(task, "description", None) or "").strip()
    if not description:
        description = "не указано"
    return (f"📋 Название: {task.title}\n"
            f"📝 Описание: {description}")


def format_repeat(repeat_type: str, repeat_interval: int | None) -> str:
    if repeat_type == Task.RepeatType.MINUTELY:
        if repeat_interval is None or repeat_interval == 1:
            return "каждую минуту"
        unit = _russian_minute_word(repeat_interval)
        return f"каждые {repeat_interval} {unit}"

    label = _REPEAT_LABELS.get(repeat_type, repeat_type)
    if repeat_interval is None or repeat_interval == 1:
        return label
    return f"{label} (каждые {repeat_interval})"


def _russian_minute_word(count: int) -> str:
    mod100 = count % 100
    if 11 <= mod100 <= 14:
        return "минут"
    mod10 = count % 10
    if mod10 == 1:
        return "минуту"
    if 2 <= mod10 <= 4:
        return "минуты"
    return "минут"


def format_reminders_section(reminders: list[Reminder],
                             *,
                             due_to=None,
                             due_to_has_time: bool = False) -> str:
    if reminders:
        lines = ["⏰ Напоминания:"]
        for reminder in reminders:
            when = format_datetime(reminder.reminder_time, has_time=True)
            lines.append(f"  • {when} — ожидает отправки")
        return "\n".join(lines)

    if due_to is None:
        return "⏰ Напоминания: нет (срок не указан)"

    if not due_to_has_time:
        return ("⏰ Напоминания: не запланированы "
                "(нужно точное время в сроке)")
    return "⏰ Напоминания: нет"


def format_task_created_message(task: Task,
                                reminders: list[Reminder] | None = None
                                ) -> str:
    lines = [
        "✅ Задача создана",
        "",
        format_task_identity(task),
    ]

    if task.due_to is None:
        lines.extend([
            "📅 Срок: не указан",
            "Назначить дату: /undated",
        ])
    else:
        due_text = format_datetime(task.due_to, has_time=task.due_to_has_time)
        if task.due_to_has_time:
            lines.append(f"📅 Срок: {due_text} (точное время)")
        else:
            lines.append(f"📅 Срок: {due_text} (без точного времени)")

    if task.repeat_type:
        lines.append(
            f"🔁 Повтор: {format_repeat(task.repeat_type, task.repeat_interval)}"
        )

    lines.extend([
        "",
        format_reminders_section(
            reminders or [],
            due_to=task.due_to,
            due_to_has_time=task.due_to_has_time,
        ),
    ])
    return "\n".join(lines)
