from aiogram.types import Message
from asgiref.sync import sync_to_async

from reminder.bot.sender import TelegramSender
from reminder.services.tasks import TaskService
from reminder.services.users import UserService


async def handle_undated(message: Message, user_service: UserService,
                         task_service: TaskService,
                         sender: TelegramSender) -> int:
    chat_id = message.chat.id
    telegram_user_id = message.from_user.id
    user = await sync_to_async(user_service.get_or_create_user,
                               thread_sensitive=True)(
                                   chat_id=chat_id,
                                   telegram_user_id=telegram_user_id)

    undated_list = await sync_to_async(task_service.list_undated,
                                       thread_sensitive=True)(user)

    if undated_list:
        message_id = await sender.send_undated_list(chat_id, undated_list)
    else:
        message_id = await sender.send_empty_undated(chat_id)

    return message_id
