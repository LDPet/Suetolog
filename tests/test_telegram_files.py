from unittest.mock import AsyncMock, Mock

import pytest
from aiogram.exceptions import TelegramNetworkError
from aiogram.methods import GetFile

from errors import ErrorCode


class TestTelegramFileDownloader:

    def test_validate_voice_ok(self, downloader, mock_voice):
        mock_voice.duration = 30
        mock_voice.file_size = 1024 * 1024

        result = downloader.validate_voice(mock_voice)

        assert result == ErrorCode.OK

    def test_validate_voice_too_long(self, downloader, mock_voice):
        mock_voice.duration = 100

        result = downloader.validate_voice(mock_voice)

        assert result == ErrorCode.VOICE_TOO_LONG

    def test_validate_voice_too_large(self, downloader, mock_voice):
        mock_voice.duration = 30
        mock_voice.file_size = 100 * 1024 * 1024

        result = downloader.validate_voice(mock_voice)

        assert result == ErrorCode.VOICE_TOO_LARGE

    @pytest.mark.asyncio
    async def test_download_voice_success(self, downloader, mock_bot):
        mock_file = Mock()
        mock_file.file_path = "voices/test.ogg"
        mock_bot.get_file = AsyncMock(return_value=mock_file)
        mock_bot.download_file = AsyncMock()

        temp_path, error_code = await downloader.download_voice("test_file_id")

        assert error_code == ErrorCode.OK
        assert temp_path is not None
        mock_bot.get_file.assert_called_once_with("test_file_id")
        mock_bot.download_file.assert_called_once()

    @pytest.mark.asyncio
    async def test_download_voice_network_error(self, downloader, mock_bot):
        mock_bot.get_file = AsyncMock(
            side_effect=TelegramNetworkError(GetFile(
                file_id="some_file_id"), "Network error"))

        temp_path, error_code = await downloader.download_voice("test_file_id")

        assert error_code == ErrorCode.GENERIC
        assert temp_path is None

    @pytest.mark.asyncio
    async def test_download_voice_no_space(self, downloader, mock_bot):
        mock_file = Mock()
        mock_file.file_path = "voices/test.ogg"
        mock_bot.get_file = AsyncMock(return_value=mock_file)
        mock_bot.download_file = AsyncMock(
            side_effect=OSError(28, "No space left"))

        temp_path, error_code = await downloader.download_voice("test_file_id")

        assert error_code == ErrorCode.GENERIC
        assert temp_path is not None