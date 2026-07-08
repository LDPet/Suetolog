from unittest.mock import AsyncMock, Mock

import pytest

from errors import ErrorCode
from reminder.bot.dispatcher import (echo_message, handle_voice,
                                     set_dependencies, start_command)


@pytest.fixture
def mock_message():
    message = Mock()
    message.from_user.id = 123
    message.chat.id = 456
    message.message_id = 789
    message.voice = Mock()
    message.voice.file_id = "test_file_id"
    message.voice.file_size = 1000
    message.voice.duration = 10
    message.text = "Test message"
    return message


@pytest.fixture
def mock_sender():
    sender = Mock()
    sender.send_welcome = AsyncMock()
    sender.send_text = AsyncMock()
    sender.send_processing = AsyncMock()
    sender.send_error = AsyncMock()
    return sender


@pytest.fixture
def mock_downloader():
    downloader = Mock()
    downloader.validate_voice = Mock(return_value=ErrorCode.OK)
    downloader.download_voice = AsyncMock(return_value=("/tmp/test.ogg",
                                                        ErrorCode.OK))
    downloader.delete_voice = Mock()
    return downloader


class TestHandlers:

    @pytest.fixture(autouse=True)
    def setup(self, mock_sender, mock_downloader):
        set_dependencies(mock_sender, mock_downloader)
        self.sender = mock_sender
        self.downloader = mock_downloader

    @pytest.mark.asyncio
    async def test_start_command(self, mock_message):
        await start_command(mock_message)
        self.sender.send_welcome.assert_called_once_with(mock_message.chat.id)

    @pytest.mark.asyncio
    async def test_echo_message(self, mock_message):
        mock_message.text = "Hello!"
        await echo_message(mock_message)
        self.sender.send_text.assert_called_once_with(mock_message.chat.id,
                                                      "Hello!\n\n")

    @pytest.mark.asyncio
    async def test_handle_voice_success(self, mock_message):
        await handle_voice(mock_message)

        self.downloader.validate_voice.assert_called_once_with(
            mock_message.voice)
        self.downloader.download_voice.assert_called_once_with(
            mock_message.voice.file_id)
        self.downloader.delete_voice.assert_called_once()
        self.sender.send_processing.assert_called_once_with(
            mock_message.chat.id)
        self.sender.send_processing.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_voice_too_long(self, mock_message):
        self.downloader.validate_voice = Mock(
            return_value=ErrorCode.VOICE_TOO_LONG)
        set_dependencies(self.sender, self.downloader)

        await handle_voice(mock_message)

        self.downloader.validate_voice.assert_called_once()
        self.downloader.download_voice.assert_not_called()
        self.sender.send_error.assert_called_once_with(
            mock_message.chat.id, ErrorCode.VOICE_TOO_LONG)

    @pytest.mark.asyncio
    async def test_handle_voice_download_error(self, mock_message):
        self.downloader.download_voice = AsyncMock(
            side_effect=Exception("Download failed"))
        set_dependencies(self.sender, self.downloader)

        await handle_voice(mock_message)

        self.downloader.download_voice.assert_called_once()
        self.sender.send_error.assert_called_once_with(mock_message.chat.id,
                                                       ErrorCode.GENERIC)
