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
    message_id = models.BigIntegerField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["reminder_time"]),
            models.Index(fields=["sent_time"]),
            models.Index(fields=["message_id"]),
            models.Index(fields=["task"]),
        ]

    def __str__(self):
        return f"Reminder(task={self.task_id}, at={self.reminder_time}, reaction={self.reaction})"
