import logging
from datetime import datetime

from asgiref.sync import sync_to_async
from django.utils import timezone

from reminder.bot.sender import TelegramSender
from reminder.services.reminders import ReminderService

logger = logging.getLogger(__name__)


class ReminderMailingService:

    def __init__(self,
                 sender: TelegramSender,
                 reminder_service: ReminderService | None = None):
        self._sender = sender
        self._reminder_service = reminder_service or ReminderService()

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
