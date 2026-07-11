from aiogram.types import Message
from asgiref.sync import sync_to_async

from reminder.bot.sender import TelegramSender
from reminder.services.users import UserService


async def handle_start(message: Message, user_service: UserService,
                       sender: TelegramSender) -> None:
    chat_id = message.chat.id
    telegram_user_id = message.from_user.id

    await sync_to_async(user_service.get_or_create_user,
                        thread_sensitive=True)(
                            chat_id=chat_id,
                            telegram_user_id=telegram_user_id,
                        )
    await sender.send_welcome(chat_id)
