import logging
from datetime import date as Date
from datetime import datetime

from asgiref.sync import sync_to_async
from django.utils import timezone

from reminder.bot.sender import TelegramSender
from reminder.repositories.task_event import TaskEventRepository
from reminder.services.reminders import ReminderService
from reminder.services.tasks import TaskService

logger = logging.getLogger(__name__)


class ReminderMailingService:

    def __init__(self,
                 sender: TelegramSender,
                 task_service: TaskService | None = None,
                 reminder_service: ReminderService | None = None):
        self._sender = sender
        self._reminder_service = reminder_service or ReminderService()
        self._task_service = task_service or TaskService()

    async def send_due_reminders(self,
                                 now: datetime | None = None,
                                 limit: int | None = None) -> dict[str, int]:
        current = now or timezone.now()
        reminders = await sync_to_async(
            self._reminder_service.get_due_reminders,
            thread_sensitive=True,
        )(now=current, limit=limit)
        result = {
            "processed": len(reminders),
            "sent": 0,
            "failed": 0,
            "skipped": 0,
        }

        for reminder in reminders:
            if reminder.sent_time is not None:
                result["skipped"] += 1
                continue

            try:
                message_id = await self._sender.send_reminder(
                    reminder.task.user.chat_id,
                    reminder.task,
                )
            except Exception:
                result["failed"] += 1
                logger.error(
                    "Failed to deliver reminder | reminder_id=%s task_id=%s",
                    reminder.id,
                    reminder.task_id,
                )
                continue

            if message_id is None:
                result["failed"] += 1
                logger.error(
                    "Telegram returned no message_id | reminder_id=%s "
                    "task_id=%s",
                    reminder.id,
                    reminder.task_id,
                )
                continue

            try:
                marked = await sync_to_async(
                    self._reminder_service.mark_sent,
                    thread_sensitive=True,
                )(reminder=reminder, message_id=message_id)
            except Exception:
                result["failed"] += 1
                logger.error(
                    "Failed to persist reminder delivery | reminder_id=%s "
                    "task_id=%s",
                    reminder.id,
                    reminder.task_id,
                )
                continue

            if marked is None:
                result["skipped"] += 1
            else:
                result["sent"] += 1

        return result

    async def send_morning_digest(
        self,
        now: datetime | Date | None = None,
    ) -> dict[str, int]:
        today = self._resolve_today(now)
        sent_task_ids = await sync_to_async(
            TaskEventRepository.get_task_ids_with_digest_sent_today,
            thread_sensitive=True,
        )(today)
        tasks = await sync_to_async(
            self._task_service.list_active_for_day,
            thread_sensitive=True,
        )(day=today)
        result = {
            "processed": len(tasks),
            "sent": 0,
            "failed": 0,
            "skipped": 0,
        }

        for task in tasks:
            if task.id in sent_task_ids:
                result["skipped"] += 1
                continue

            try:
                message_id = await self._sender.send_digest(
                    task.user.chat_id, task)
            except Exception:
                result["failed"] += 1
                logger.error(
                    "Failed to deliver digest card | task_id=%s",
                    task.id,
                )
                continue

            if message_id is None:
                result["failed"] += 1
                logger.error(
                    "Telegram returned no message_id | task_id=%s",
                    task.id,
                )
                continue

            result["sent"] += 1

        return result

    @staticmethod
    def _resolve_today(now: datetime | Date | None) -> Date:
        if isinstance(now, datetime):
            return timezone.localdate(now)
        if isinstance(now, Date):
            return now
        return timezone.localdate()
