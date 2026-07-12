from django.db import models


class User(models.Model):
    # django автоматически добавляет id = BigAutoFeild
    chat_id = models.BigIntegerField(unique=True)
    telegram_user_id = models.BigIntegerField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"User(chat={self.chat_id}, tg={self.telegram_user_id})"


class Task(models.Model):

    class Status(models.TextChoices):
        ACTIVE = "active", "Активна"
        DONE = "done", "Выполнена"
        CANCELLED = "cancelled", "Отменена"
        DELETED = "deleted", "Удалена"

    class RepeatType(models.TextChoices):
        HOURLY = "hourly", "Каждый час"
        DAILY = "daily", "Ежедневно"
        WEEKLY = "weekly", "Еженедельно"

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    due_to = models.DateTimeField(null=True, blank=True)
    due_to_has_time = models.BooleanField(default=False)
    repeat_type = models.CharField(
        max_length=20,
        choices=RepeatType.choices,
        null=True,
        blank=True,
        default=RepeatType.DAILY,
    )
    repeat_interval = models.PositiveIntegerField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    user = models.ForeignKey(
        "User",
        on_delete=models.CASCADE,
        related_name="tasks",
    )

    class Meta:
        indexes = [
            models.Index(fields=["user", "status"]),
            models.Index(fields=["user", "due_to"]),
        ]

    def __str__(self):
        return f"Task({self.title}, {self.status}, user={self.user_id}, repeat_type={self.repeat_type}, repeat_interval={self.repeat_interval})"


class Reminder(models.Model):
    task = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        related_name="reminders",
    )
    reminder_time = models.DateTimeField()
    sent_time = models.DateTimeField(null=True, blank=True)
    reaction = models.CharField(max_length=10, null=True, blank=True)
    message_id = models.BigIntegerField(null=True, blank=True, unique=True)

    class Meta:
        indexes = [
            models.Index(fields=["reminder_time"]),
            models.Index(fields=["sent_time"]),
            models.Index(fields=["task"]),
        ]

    def __str__(self):
        return f"Reminder(task={self.task_id}, at={self.reminder_time}, reaction={self.reaction})"


class TaskEvent(models.Model):

    class EventType(models.TextChoices):
        CREATED = "created", "Создана"
        REMINDER_SENT = "reminder_sent", "Напоминание отправлено"
        UNDATED_CARD_SENT = "undated_card_sent", "Карточка без даты"
        EVENING_QUESTION_SENT = "evening_question_sent", "Вечерний вопрос"
        COMPLETED = "completed", "Выполнена"
        CANCELLED = "cancelled", "Отменена"
        RESCHEDULED = "rescheduled", "Перенесена"
        DATE_SET = "date_set", "Дата установлена"
        DELETED = "deleted", "Удалена"
        DIGEST_SENT = "digest_sent", "Дайджест отправлен"
        DIGEST_CARD_SENT = "digest_card_sent", "Карточка из дайджеста отправлена"

    task = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        related_name="events",
    )
    event_type = models.CharField(
        max_length=30,
        choices=EventType.choices,
    )
    message_id = models.BigIntegerField(
        null=True,
        blank=True,
        unique=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["task", "created_at"]),
        ]

    def __str__(self):
        return f"TaskEvent(task={self.task_id}, event_type={self.event_type}, message_id={self.message_id})"
