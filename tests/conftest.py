import os
import sys
from pathlib import Path

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

os.environ[
    'TELEGRAM_BOT_TOKEN'] = '1234567890:ABCdefGHIjklMNOpqrsTUVwxyzAAAAAAAAA'

sys.path.insert(0, str(Path(__file__).parent.parent))

import django

import errors

django.setup()

from unittest.mock import AsyncMock, Mock, patch

import pytest
from aiogram.types import Chat, Message, User, Voice

from reminder.bot.sender import TelegramSender
from reminder.bot.telegram_files import TelegramFileDownloader


@pytest.fixture(autouse=True)
def mock_telegram_bot():
    with patch('reminder.bot.dispatcher.Bot') as MockBot:
        yield MockBot


@pytest.fixture(autouse=True)
def setup_test_token():
    original_token = os.environ.get('TELEGRAM_BOT_TOKEN')
    os.environ[
        'TELEGRAM_BOT_TOKEN'] = '1234567890:ABCdefGHIjklMNOpqrsTUVwxyzAAAAAAAAA'
    yield
    if original_token:
        os.environ['TELEGRAM_BOT_TOKEN'] = original_token
    else:
        os.environ.pop('TELEGRAM_BOT_TOKEN', None)


@pytest.fixture
def mock_bot():
    bot = Mock()
    bot.send_message = AsyncMock()
    bot.send_voice = AsyncMock()
    bot.get_file = AsyncMock()
    bot.download_file = AsyncMock()
    return bot


@pytest.fixture
def sender(mock_bot):
    return TelegramSender(mock_bot)


@pytest.fixture
def downloader(mock_bot):
    return TelegramFileDownloader(mock_bot)


@pytest.fixture
def mock_voice():
    voice = Mock(spec=Voice)
    voice.file_id = "test_file_id_12345"
    voice.file_unique_id = "unique_12345"
    voice.duration = 30
    voice.file_size = 1024 * 1024
    voice.mime_type = "audio/ogg"
    voice.file_name = "voice.ogg"
    return voice


@pytest.fixture
def mock_message(mock_voice):
    message = Mock(spec=Message)
    message.message_id = 42
    message.chat = Mock(spec=Chat)
    message.chat.id = 123456789
    message.from_user = Mock(spec=User)
    message.from_user.id = 987654321
    message.from_user.username = "test_user"
    message.voice = mock_voice
    message.text = "Test message"
    return message


@pytest.fixture
def mock_message_for_dispatcher():
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
def mock_downloader_for_dispatcher():
    downloader = Mock()
    downloader.validate_voice = Mock(return_value=errors.ErrorCode.OK)
    downloader.download_voice = AsyncMock(return_value=("/tmp/test.ogg",
                                                        errors.ErrorCode.OK))
    downloader.delete_voice = Mock()
    return downloader


@pytest.fixture
def test_settings():
    return {
        'TELEGRAM_BOT_TOKEN': 'dummy_token_for_testing:ABC123',
        'VOICE_MAX_DURATION_SEC': 60,
        'VOICE_MAX_SIZE_BYTES': 20 * 1024 * 1024,
    }