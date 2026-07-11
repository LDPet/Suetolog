import logging

from aiogram.types import CallbackQuery
from asgiref.sync import sync_to_async

from reminder.bot.sender import TelegramSender
from reminder.models import Task, User
from reminder.services.tasks import TaskService

logger = logging.getLogger(__name__)


async def validate(task: Task | None, telegram_user_id: int,
                   sender: TelegramSender, chat_id: int) -> bool:
    if not task:
        await sender.send_text(chat_id, "Задача не найдена")
        return False

    if task.status != Task.Status.ACTIVE:
        await sender.send_text(chat_id, "Задача не активна")
        return False

    if task.user.telegram_user_id != telegram_user_id:
        await sender.send_text(chat_id,
                               "Задача принадлежит другому пользователю")
        return False

    return True


async def delete_task_callback(callback: CallbackQuery,
                               task_service: TaskService,
                               sender: TelegramSender) -> None:
    task_id = int(callback.data.split(":")[1])
    telegram_user_id = callback.from_user.id
    await callback.answer()
    task = await sync_to_async(
        lambda: Task.objects.select_related('user').filter(id=task_id).first(),
        thread_sensitive=True)()

    user = task.user
    chat_id = user.chat_id

    if not await validate(task, telegram_user_id, sender, chat_id):
        return

    await sync_to_async(task_service.delete_task,
                        thread_sensitive=True)(user, task_id)

    await sender.send_text(chat_id, f"Задача {task.title} удалена")
    logger.info(f"Задача без даты удалена |"
                f"task_id={task_id} |"
                f"user_id={telegram_user_id} |"
                f"task_title={task.title}")


async def assign_date_callback(callback: CallbackQuery,
                               sender: TelegramSender) -> None:
    task_id = int(callback.data.split(":")[1])
    telegram_user_id = callback.from_user.id
    await callback.answer()
    task = await sync_to_async(
        lambda: Task.objects.select_related('user').filter(id=task_id).first(),
        thread_sensitive=True)()

    user = task.user
    chat_id = user.chat_id

    if not await validate(task, telegram_user_id, sender, chat_id):
        return

    logger.info(f"Задаче без даты назначена дата |"
                f"task_id={task_id} |"
                f"user_id={telegram_user_id} |"
                f"task_title={task.title} |"
                f"task_due_t={task.due_to}")

    text = "Ответь на это сообщение с датой"
    await sender.send_text(chat_id, text)
