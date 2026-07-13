import logging

from aiogram import Bot
from asgiref.sync import async_to_sync
from celery import shared_task
from django.conf import settings

from reminder.bot.sender import TelegramSender
from reminder.services.mailing import ReminderMailingService

logger = logging.getLogger(__name__)


async def _send_due_reminders() -> dict[str, int]:
    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
    try:
        service = ReminderMailingService(sender=TelegramSender(bot))
        return await service.send_due_reminders()
    finally:
        await bot.session.close()


async def _send_morning_digest() -> dict[str, int]:
    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
    try:
        service = ReminderMailingService(sender=TelegramSender(bot))
        return await service.send_morning_digest()
    finally:
        await bot.session.close()


@shared_task(name="reminder.tasks.send_due_reminders", ignore_result=True)
def send_due_reminders() -> dict[str, int]:
    result = async_to_sync(_send_due_reminders)()
    logger.info(
        "Due reminders job finished | processed=%s sent=%s failed=%s skipped=%s",
        result["processed"],
        result["sent"],
        result["failed"],
        result["skipped"],
    )
    return result


@shared_task(name="reminder.tasks.send_morning_digest", ignore_result=True)
def send_morning_digest() -> dict[str, int]:
    result = async_to_sync(_send_morning_digest)()
    logger.info(
        "Morning digest job finished | processed=%s sent=%s failed=%s skipped=%s",
        result["processed"],
        result["sent"],
        result["failed"],
        result["skipped"],
    )
    return result
