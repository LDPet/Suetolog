import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.enums import ContentType
from aiogram.filters import Command
from aiogram.types import Message

from config.settings import TELEGRAM_BOT_TOKEN
from errors import ErrorCode
from reminder.bot.handlers.start import handle_start
from reminder.bot.telegram_files import TelegramFileDownloader
from reminder.services.users import UserService

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


#Функция для тестов
def set_dependencies(mock_sender=None,
                     mock_downloader=None,
                     mock_user_service=None):
    global sender, downloader, user_service
    if mock_sender is not None:
        sender = mock_sender
    if mock_downloader is not None:
        downloader = mock_downloader
    if mock_user_service is not None:
        user_service = mock_user_service


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
    user_id = message.from_user.id
    chat_id = message.chat.id
    message_id = message.message_id
    temp_path = None

    await sender.send_processing(chat_id)

    logger.info(f"Голосовое сообщение | "
                f"user_id={user_id} | "
                f"chat_id={chat_id} | "
                f"msg_id={message_id}")

    voice = message.voice
    error_code = downloader.validate_voice(voice)

    if error_code != ErrorCode.OK:
        await sender.send_error(chat_id, error_code)
        logger.info(f"Ошибка скачивания | "
                    f"Код ошибки: {error_code} |"
                    f"user_id={user_id} | "
                    f"chat_id={chat_id} | "
                    f"msg_id={message_id}")
        return None

    file_id = voice.file_id
    try:
        logger.info(f"Начало скачивания | "
                    f"user_id={user_id} | "
                    f"chat_id={chat_id} | "
                    f"file_id={voice.file_id}")
        temp_path, error_code = await downloader.download_voice(file_id)
        if error_code != ErrorCode.OK:
            await sender.send_error(chat_id, error_code)
            logger.info(f"Ошибка скачивания |"
                        f"user_id={user_id} | "
                        f"chat_id={chat_id} | "
                        f"error_code={error_code}")
            return None

        logger.info(f"Голосовое скачано | "
                    f"user_id={user_id} | "
                    f"chat_id={chat_id} | "
                    f"path={temp_path} | "
                    f"size={voice.file_size} байт |"
                    f"duration={voice.duration} сек")
    except Exception as e:
        logger.error(
            f"Ошибка скачивания | "
            f"user_id={user_id} | "
            f"chat_id={chat_id} | "
            f"error={str(e)}",
            exc_info=True)
        await sender.send_error(chat_id, ErrorCode.GENERIC)
        return None

    finally:
        if temp_path:
            downloader.delete_voice(temp_path)
            logger.info(f"Голосовое удалено | "
                        f"user_id={user_id} | "
                        f"chat_id={chat_id} | "
                        f"path={temp_path} | "
                        f"file_id={file_id}")


async def start_bot():
    print("Бот запущен")

    try:
        await dp.start_polling(bot)
    except Exception as e:
        print(f"Ошибка при работе бота: {e}")


if __name__ == "__main__":
    asyncio.run(start_bot())
