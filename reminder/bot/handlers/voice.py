import logging

from aiogram.types import Message
from asgiref.sync import sync_to_async

from errors import ErrorCode
from reminder.bot.sender import TelegramSender
from reminder.services.users import UserService
from reminder.services.voice_tasks import VoiceTaskCreationService

logger = logging.getLogger(__name__)


async def handle_voice(message: Message, user_service: UserService,
                       sender: TelegramSender,
                       voice_task_service: VoiceTaskCreationService) -> None:
    chat_id = message.chat.id
    voice = message.voice
    logger.info(
        "Голосовое сообщение | user_id=%s | chat_id=%s | msg_id=%s | "
        "duration=%s | size=%s | file_id=%s",
        message.from_user.id,
        chat_id,
        message.message_id,
        voice.duration,
        voice.file_size,
        voice.file_id,
    )

    try:
        user = await sync_to_async(user_service.get_or_create_user,
                                   thread_sensitive=True)(
                                       chat_id=chat_id,
                                       telegram_user_id=message.from_user.id,
                                   )

        await sender.send_processing(chat_id)
        result = await voice_task_service.create_from_voice(user, voice)

        if result.success:
            logger.info(
                "Voice handler: задача создана | chat_id=%s | task_id=%s",
                chat_id,
                result.task.pk,
            )
            await sender.send_task_created(chat_id, result.task)
        else:
            logger.warning(
                "Voice handler: ошибка пайплайна | chat_id=%s | error=%s",
                chat_id,
                result.error_code.name,
            )
            await sender.send_error(chat_id, result.error_code)
    except Exception:
        logger.exception(
            "Неожиданная ошибка voice handler | chat_id=%s | msg_id=%s",
            chat_id,
            message.message_id,
        )
        await sender.send_error(chat_id, ErrorCode.GENERIC)
