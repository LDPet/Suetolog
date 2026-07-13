from datetime import datetime

from django.utils import timezone

from reminder.models import Reminder


class ReminderRepository:

    @staticmethod
    def create(task, reminder_time: datetime) -> Reminder:
        return Reminder.objects.create(
            task=task,
            reminder_time=reminder_time,
        )

    @staticmethod
    def get_by_id(reminder_id: int) -> Reminder | None:
        try:
            return Reminder.objects.get(id=reminder_id)
        except Reminder.DoesNotExist:
            return None

    @staticmethod
    def get_due_reminders(now: datetime = None) -> list[Reminder]:
        if now is None:
            now = timezone.now()
        return list(
            Reminder.objects.filter(
                sent_time__isnull=True,
                reminder_time__lte=now,
            ).select_related("task").order_by("reminder_time"))

    @staticmethod
    def set_reaction_by_message_id(message_id: int,
                                   reaction: str) -> Reminder | None:
        try:
            reminder = Reminder.objects.get(message_id=message_id)
        except Reminder.DoesNotExist:
            return None
        reminder.reaction = reaction
        reminder.save(update_fields=['reaction'])
        return reminder

    @staticmethod
    def list_pending_for_task(task) -> list[Reminder]:
        return list(
            Reminder.objects.filter(
                task=task,
                sent_time__isnull=True,
            ).order_by("reminder_time"))

    @staticmethod
    def replace_pending_for_task(
            task, reminder_time: datetime | None) -> Reminder | None:
        Reminder.objects.filter(task=task, sent_time__isnull=True).delete()
        if reminder_time is None:
            return None
        return ReminderRepository.create(task=task,
                                         reminder_time=reminder_time)

    @staticmethod
    def delete_pending_for_task(task) -> int:
        deleted_count, _ = Reminder.objects.filter(
            task=task, sent_time__isnull=True).delete()
        return deleted_count
