import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.enums import ContentType
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from config.settings import TELEGRAM_BOT_TOKEN
from errors import ErrorCode
from reminder.bot.handlers.callbacks import (callback_startswith,
                                             complete_task_callback,
                                             delete_task_callback)
from reminder.bot.handlers.date_reply import NO_REPLY_TEXT, handle_date_reply
from reminder.bot.handlers.start import handle_start
from reminder.bot.handlers.undated import handle_undated
from reminder.bot.handlers.voice import handle_voice as handle_voice_message
from reminder.bot.telegram_files import TelegramFileDownloader
from reminder.services.parsing import YandexGPTDateParser
from reminder.services.reminders import ReminderService
from reminder.services.stt import YandexSpeechKitSTTService
from reminder.services.tasks import TaskService
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
reminder_service = ReminderService()
voice_task_service = None
date_parser = None
task_service = TaskService()


def set_dependencies(mock_sender=None,
                     mock_downloader=None,
                     mock_user_service=None,
                     mock_voice_task_service=None,
                     mock_task_service=None,
                     mock_reminder_service=None,
                     mock_date_parser=None):
    global sender, downloader, user_service, voice_task_service
    global task_service, reminder_service, date_parser
    if mock_sender is not None:
        sender = mock_sender
    if mock_downloader is not None:
        downloader = mock_downloader
    if mock_user_service is not None:
        user_service = mock_user_service
    if mock_voice_task_service is not None:
        voice_task_service = mock_voice_task_service
    if mock_task_service is not None:
        task_service = mock_task_service
    if mock_reminder_service is not None:
        reminder_service = mock_reminder_service
    if mock_date_parser is not None:
        date_parser = mock_date_parser


def get_voice_task_service():
    global voice_task_service
    if voice_task_service is None:
        logger.info("Инициализация VoiceTaskCreationService")
        voice_task_service = VoiceTaskCreationService(
            downloader=downloader,
            stt=YandexSpeechKitSTTService(),
        )
    return voice_task_service


def get_date_parser():
    global date_parser
    if date_parser is None:
        date_parser = YandexGPTDateParser()
    return date_parser


def is_date_reply_message(message: Message) -> bool:
    return (message.content_type == ContentType.TEXT
            and message.reply_to_message is not None
            and isinstance(message.text, str)
            and not message.text.lstrip().startswith("/"))


@dp.message(Command("start"))
async def start_command(message: Message):
    await handle_start(message, user_service, sender)


@dp.message(Command("undated"))
async def undated_command(message: Message):
    await handle_undated(message, user_service, task_service, sender)


@dp.message(is_date_reply_message)
async def date_reply_message(message: Message):
    try:
        parser = get_date_parser()
    except Exception:
        logger.exception(
            "Failed to initialize date parser | chat_id=%s",
            message.chat.id,
        )
        await sender.send_error(message.chat.id, ErrorCode.GENERIC)
        return

    await handle_date_reply(message, user_service, task_service, parser,
                            sender)


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

    if text == "Без даты" or text == "без даты":
        await handle_undated(message, user_service, task_service, sender)
        return

    if text.lstrip().startswith("/"):
        await sender.send_text(chat_id, f"{message.text}\n\n")
        return

    await sender.send_text(chat_id, NO_REPLY_TEXT)


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


@dp.callback_query(callback_startswith('delete:'))
async def delete_callback(callback: CallbackQuery):
    await delete_task_callback(callback, task_service, sender)


@dp.callback_query(callback_startswith('done:'))
async def done_callback(callback: CallbackQuery):
    await complete_task_callback(callback, task_service, sender,
                                 reminder_service)


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
