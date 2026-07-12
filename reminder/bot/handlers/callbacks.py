import logging

from aiogram.types import CallbackQuery
from asgiref.sync import sync_to_async

from reminder.bot.sender import TelegramSender
from reminder.models import Task
from reminder.services.reminders import ReminderService
from reminder.services.tasks import TaskService

logger = logging.getLogger(__name__)


def callback_startswith(prefix: str):

    def predicate(callback: CallbackQuery) -> bool:
        return callback.data.startswith(prefix)

    return predicate


async def validate(task: Task | None, telegram_user_id: int | None,
                   sender: TelegramSender, chat_id: int) -> bool:
    if not task:
        await sender.send_text(chat_id, "Задача не найдена")
        return False

    if task.status != Task.Status.ACTIVE:
        await sender.send_text(chat_id, "Задача не активна")
        return False

    if not telegram_user_id or task.user.telegram_user_id != telegram_user_id:
        await sender.send_text(chat_id,
                               "Задача принадлежит другому пользователю")
        return False

    return True


def _parse_task_id(callback_data: str | None) -> int | None:
    if not callback_data:
        return None

    prefix, _, raw_task_id = callback_data.partition(":")
    if not prefix or not raw_task_id:
        return None

    try:
        return int(raw_task_id)
    except ValueError:
        return None


async def _reject_bad_callback(callback: CallbackQuery, sender: TelegramSender,
                               chat_id: int) -> None:
    await callback.answer("Некорректные данные")
    await sender.send_text(chat_id, "Не удалось обработать действие")


async def delete_task_callback(callback: CallbackQuery,
                               task_service: TaskService,
                               sender: TelegramSender) -> None:
    chat_id = callback.message.chat.id
    task_id = _parse_task_id(callback.data)
    if task_id is None:
        await _reject_bad_callback(callback, sender, chat_id)
        return

    await callback.answer()
    telegram_user_id = callback.from_user.id

    task = await sync_to_async(
        lambda: Task.objects.select_related('user').filter(id=task_id).first(),
        thread_sensitive=True)()

    if not await validate(task, telegram_user_id, sender, chat_id):
        return

    user = task.user
    await sync_to_async(task_service.delete_task,
                        thread_sensitive=True)(user, task_id)
    await sender.send_deleted(chat_id, task)


async def complete_task_callback(callback: CallbackQuery,
                                 task_service: TaskService,
                                 sender: TelegramSender,
                                 reminder_service: ReminderService) -> None:
    chat_id = callback.message.chat.id
    task_id = _parse_task_id(callback.data)
    if task_id is None:
        await _reject_bad_callback(callback, sender, chat_id)
        return

    await callback.answer()
    message_id = callback.message.message_id
    telegram_user_id = callback.from_user.id

    task = await sync_to_async(
        lambda: Task.objects.select_related('user').filter(id=task_id).first(),
        thread_sensitive=True)()

    if not await validate(task, telegram_user_id, sender, chat_id):
        return

    user = task.user

    reminder = await sync_to_async(reminder_service.find_by_message,
                                   thread_sensitive=True)(chat_id, message_id)
    if reminder is not None and reminder.task_id == task_id:
        await sync_to_async(task_service.mark_done,
                            thread_sensitive=True)(user, reminder=reminder)
    else:
        await sync_to_async(task_service.mark_done,
                            thread_sensitive=True)(user, task_id=task_id)

    await sender.send_task_completed(chat_id, task)
