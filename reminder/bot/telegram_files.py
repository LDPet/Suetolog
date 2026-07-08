import os
import tempfile as tmp
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramNetworkError, TelegramServerError

from config.settings import VOICE_MAX_DURATION_SEC, VOICE_MAX_SIZE_BYTES
from errors import ErrorCode


class TelegramFileDownloader:

    def __init__(self, bot: Bot):
        self.bot = bot

    def validate_voice(self, voice_message):
        if voice_message.duration > VOICE_MAX_DURATION_SEC:
            return ErrorCode.VOICE_TOO_LONG

        if voice_message.file_size > VOICE_MAX_SIZE_BYTES:
            return ErrorCode.VOICE_TOO_LARGE

        return ErrorCode.OK

    async def download_voice(self, file_id):
        try:
            file_object = await self.bot.get_file(file_id)
            if not file_object.file_path:
                return None, ErrorCode.GENERIC

            temp_file = tmp.NamedTemporaryFile(suffix='.ogg',
                                               delete=False,
                                               mode='wb')
        except (TelegramNetworkError, TelegramServerError, OSError):
            return None, ErrorCode.GENERIC

        temp_path = Path(temp_file.name)

        try:
            await self.bot.download_file(file_object.file_path, temp_path)
            temp_file.close()
            return temp_path, ErrorCode.OK
        except Exception:
            return temp_path, ErrorCode.GENERIC

    def delete_voice(self, filepath):
        if filepath and filepath.exists():
            os.unlink(filepath)
