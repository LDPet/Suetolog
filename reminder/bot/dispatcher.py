import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.enums import ContentType
from aiogram.filters import Command
from aiogram.types import Message

from config.settings import TELEGRAM_BOT_TOKEN
from errors import ErrorCode
from reminder.bot.handlers.start import handle_start
from reminder.bot.handlers.voice import handle_voice as handle_voice_message
from reminder.bot.telegram_files import TelegramFileDownloader
from reminder.services.stt import YandexSpeechKitSTTService
from reminder.services.users import UserService
from reminder.services.voice_tasks import VoiceTaskCreationService

from .sender import TelegramSender

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S')

logger = logging.getLogger(__name__)

dp = Dispatcher()
bot = Bot(token=TELEGRAM_BOT_TOKEN)
sender = TelegramSender(bot)
downloader = TelegramFileDownloader(bot)
user_service = UserService()
voice_task_service = None


def set_dependencies(mock_sender=None,
                     mock_downloader=None,
                     mock_user_service=None,
                     mock_voice_task_service=None):
    global sender, downloader, user_service, voice_task_service
    if mock_sender is not None:
        sender = mock_sender
    if mock_downloader is not None:
        downloader = mock_downloader
    if mock_user_service is not None:
        user_service = mock_user_service
    if mock_voice_task_service is not None:
        voice_task_service = mock_voice_task_service


def get_voice_task_service():
    global voice_task_service
    if voice_task_service is None:
        logger.info("Инициализация VoiceTaskCreationService")
        voice_task_service = VoiceTaskCreationService(
            downloader=downloader,
            stt=YandexSpeechKitSTTService(),
        )
    return voice_task_service


@dp.message(Command("start"))
async def start_command(message: Message):
    await handle_start(message, user_service, sender)


@dp.message(lambda message: message.content_type == ContentType.TEXT)
async def echo_message(message: Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    message_id = message.message_id
    text = message.text[:50]

    logger.info(f"Текстовое сообщение | "
                f"user_id={user_id} | "
                f"chat_id={chat_id} | "
                f"msg_id={message_id} | "
                f"text={text}...")

    await sender.send_text(chat_id, f"{message.text}\n\n")


@dp.message(lambda message: message.content_type == ContentType.VOICE)
async def handle_voice(message: Message):
    try:
        await handle_voice_message(message, user_service, sender,
                                   get_voice_task_service())
    except Exception:
        logger.exception(
            "Необработанная ошибка voice dispatcher | chat_id=%s",
            message.chat.id,
        )
        await sender.send_error(message.chat.id, ErrorCode.GENERIC)


async def start_bot():
    try:
        get_voice_task_service()
    except Exception:
        logger.exception("Не удалось инициализировать voice pipeline")
        raise

    logger.info("Бот запущен")

    try:
        await dp.start_polling(bot)
    except Exception:
        logger.exception("Ошибка при работе бота")
        raise


if __name__ == "__main__":
    asyncio.run(start_bot())
