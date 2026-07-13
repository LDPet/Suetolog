from unittest.mock import AsyncMock, Mock

import pytest
from aiogram.enums import ContentType

from reminder.bot import dispatcher
from reminder.bot.dispatcher import (date_reply_message, delete_callback,
                                     done_callback, echo_message,
                                     get_date_parser, handle_voice,
                                     is_date_reply_message, set_dependencies,
                                     start_bot, start_command, undated_command)
from reminder.bot.handlers.date_reply import NO_REPLY_TEXT
from reminder.services.dto import VoiceTaskResult
from reminder.services.stt import STTConfigurationError


@pytest.fixture
def mock_message():
    message = Mock()
    message.from_user.id = 123
    message.chat.id = 456
    message.message_id = 789
    message.content_type = ContentType.TEXT
    message.reply_to_message = None
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
    sender.send_task_created = AsyncMock()
    sender.send_error = AsyncMock()
    sender.send_undated_list = AsyncMock()
    sender.send_empty_undated = AsyncMock(return_value=123)
    sender.send_date_confirmed = AsyncMock()
    return sender


@pytest.fixture
def mock_user_service():
    service = Mock()
    service.get_or_create_user = Mock(return_value=Mock())
    return service


@pytest.fixture
def mock_voice_task_service():
    service = Mock()
    service.create_from_voice = AsyncMock(
        return_value=VoiceTaskResult.ok(Mock()))
    return service


@pytest.fixture
def mock_task_service():
    service = Mock()
    service.list_undated.return_value = []
    return service


@pytest.fixture
def mock_reminder_service():
    return Mock()


@pytest.fixture
def mock_date_parser():
    return Mock()


def test_voice_handler_is_registered():
    assert any(handler.callback is handle_voice
               for handler in dispatcher.dp.message.handlers)


def test_date_reply_handler_is_registered_before_generic_text_handler():
    callbacks = [
        handler.callback for handler in dispatcher.dp.message.handlers
    ]

    assert date_reply_message in callbacks
    assert callbacks.index(date_reply_message) < callbacks.index(echo_message)


def test_date_reply_filter_accepts_only_non_command_text_replies(mock_message):
    mock_message.reply_to_message = Mock()

    assert is_date_reply_message(mock_message) is True

    mock_message.text = "/start"
    assert is_date_reply_message(mock_message) is False

    mock_message.text = "завтра"
    mock_message.content_type = ContentType.VOICE
    assert is_date_reply_message(mock_message) is False

    mock_message.content_type = ContentType.TEXT
    mock_message.reply_to_message = None
    assert is_date_reply_message(mock_message) is False


def test_voice_service_uses_dispatcher_dependencies(monkeypatch):
    stt = Mock()
    service = Mock()
    stt_factory = Mock(return_value=stt)
    service_factory = Mock(return_value=service)
    monkeypatch.setattr(dispatcher, "voice_task_service", None)
    monkeypatch.setattr(dispatcher, "YandexSpeechKitSTTService", stt_factory)
    monkeypatch.setattr(dispatcher, "VoiceTaskCreationService",
                        service_factory)

    result = dispatcher.get_voice_task_service()

    assert result is service
    stt_factory.assert_called_once_with()
    service_factory.assert_called_once_with(
        downloader=dispatcher.downloader,
        stt=stt,
    )


def test_date_parser_is_created_lazily(monkeypatch):
    parser = Mock()
    factory = Mock(return_value=parser)
    monkeypatch.setattr(dispatcher, "date_parser", None)
    monkeypatch.setattr(dispatcher, "YandexGPTDateParser", factory)

    result = get_date_parser()

    assert result is parser
    factory.assert_called_once_with()


@pytest.mark.asyncio
async def test_start_bot_validates_voice_service_before_polling(monkeypatch):
    configuration_error = STTConfigurationError("missing credentials")
    service_factory = Mock(side_effect=configuration_error)
    polling = AsyncMock()
    monkeypatch.setattr(dispatcher, "get_voice_task_service", service_factory)
    monkeypatch.setattr(dispatcher.dp, "start_polling", polling)

    with pytest.raises(STTConfigurationError) as exc_info:
        await start_bot()

    assert exc_info.value is configuration_error
    service_factory.assert_called_once_with()
    polling.assert_not_awaited()


class TestHandlers:

    @pytest.fixture(autouse=True)
    def setup(self, mock_sender, mock_user_service, mock_voice_task_service,
              mock_task_service, mock_reminder_service, mock_date_parser):
        set_dependencies(
            mock_sender=mock_sender,
            mock_user_service=mock_user_service,
            mock_voice_task_service=mock_voice_task_service,
            mock_task_service=mock_task_service,
            mock_reminder_service=mock_reminder_service,
            mock_date_parser=mock_date_parser,
        )
        self.sender = mock_sender
        self.user_service = mock_user_service
        self.voice_task_service = mock_voice_task_service
        self.task_service = mock_task_service
        self.reminder_service = mock_reminder_service
        self.date_parser = mock_date_parser

    @pytest.mark.asyncio
    async def test_start_command(self, mock_message):
        await start_command(mock_message)

        self.user_service.get_or_create_user.assert_called_once_with(
            chat_id=mock_message.chat.id,
            telegram_user_id=mock_message.from_user.id,
        )
        self.sender.send_welcome.assert_called_once_with(mock_message.chat.id)

    @pytest.mark.asyncio
    async def test_echo_message(self, mock_message):
        mock_message.text = "Hello!"
        await echo_message(mock_message)
        self.sender.send_text.assert_awaited_once_with(mock_message.chat.id,
                                                       NO_REPLY_TEXT)
        self.date_parser.parse_date.assert_not_called()

    @pytest.mark.asyncio
    async def test_date_reply_uses_injected_services(self, mock_message,
                                                     monkeypatch):
        mock_message.reply_to_message = Mock(message_id=321)
        handler = AsyncMock()
        monkeypatch.setattr(dispatcher, "handle_date_reply", handler)

        await date_reply_message(mock_message)

        handler.assert_awaited_once_with(
            mock_message,
            self.user_service,
            self.task_service,
            self.date_parser,
            self.sender,
        )

    @pytest.mark.asyncio
    async def test_undated_command(self, mock_message):
        await undated_command(mock_message)

        self.task_service.list_undated.assert_called_once_with(
            self.user_service.get_or_create_user.return_value)
        self.sender.send_empty_undated.assert_awaited_once_with(
            mock_message.chat.id)

    @pytest.mark.asyncio
    async def test_delete_callback_uses_injected_services(self, monkeypatch):
        callback = Mock()
        handler = AsyncMock()
        monkeypatch.setattr(dispatcher, "delete_task_callback", handler)

        await delete_callback(callback)

        handler.assert_awaited_once_with(callback, self.task_service,
                                         self.sender)

    @pytest.mark.asyncio
    async def test_done_callback_uses_injected_services(self, monkeypatch):
        callback = Mock()
        handler = AsyncMock()
        monkeypatch.setattr(dispatcher, "complete_task_callback", handler)

        await done_callback(callback)

        handler.assert_awaited_once_with(callback, self.task_service,
                                         self.sender, self.reminder_service)

    @pytest.mark.asyncio
    async def test_handle_voice_success(self, mock_message, monkeypatch):
        reminders = []
        monkeypatch.setattr(
            "reminder.bot.handlers.voice.ReminderRepository."
            "list_pending_for_task",
            lambda task: reminders,
        )

        await handle_voice(mock_message)

        user = self.user_service.get_or_create_user.return_value
        task = self.voice_task_service.create_from_voice.return_value.task
        self.user_service.get_or_create_user.assert_called_once_with(
            chat_id=mock_message.chat.id,
            telegram_user_id=mock_message.from_user.id,
        )
        self.sender.send_processing.assert_called_once_with(
            mock_message.chat.id)
        self.voice_task_service.create_from_voice.assert_awaited_once_with(
            user, mock_message.voice)
        self.sender.send_task_created.assert_awaited_once_with(
            mock_message.chat.id, task, reminders)
