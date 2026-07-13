from unittest.mock import AsyncMock, Mock, patch

import pytest

from errors import ErrorCode
from reminder.bot.handlers.voice import handle_voice
from reminder.services.dto import VoiceTaskResult


@pytest.fixture
def message():
    message = Mock()
    message.chat.id = 456
    message.from_user.id = 123
    message.voice = Mock()
    return message


@pytest.fixture
def user_service():
    service = Mock()
    service.get_or_create_user = Mock(return_value=Mock())
    return service


@pytest.fixture
def sender():
    sender = Mock()
    sender.send_processing = AsyncMock()
    sender.send_task_created = AsyncMock()
    sender.send_error = AsyncMock()
    return sender


@pytest.fixture
def voice_task_service():
    service = Mock()
    service.create_from_voice = AsyncMock()
    return service


@pytest.mark.asyncio
@patch("reminder.bot.handlers.voice.ReminderRepository.list_pending_for_task")
async def test_voice_handler_sends_created_task(list_pending_mock, message,
                                                user_service, sender,
                                                voice_task_service):
    task = Mock()
    reminders = [Mock()]
    list_pending_mock.return_value = reminders
    voice_task_service.create_from_voice.return_value = VoiceTaskResult.ok(
        task)

    await handle_voice(message, user_service, sender, voice_task_service)

    user = user_service.get_or_create_user.return_value
    user_service.get_or_create_user.assert_called_once_with(
        chat_id=message.chat.id,
        telegram_user_id=message.from_user.id,
    )
    sender.send_processing.assert_awaited_once_with(message.chat.id)
    voice_task_service.create_from_voice.assert_awaited_once_with(
        user, message.voice)
    list_pending_mock.assert_called_once_with(task)
    sender.send_task_created.assert_awaited_once_with(message.chat.id, task,
                                                      reminders)
    sender.send_error.assert_not_awaited()


@pytest.mark.asyncio
@patch("reminder.bot.handlers.voice.ReminderRepository.list_pending_for_task")
async def test_voice_handler_calls_dependencies_in_order(
        list_pending_mock, message, user_service, sender, voice_task_service):
    calls = []
    user = Mock()
    task = Mock()
    list_pending_mock.return_value = []

    def get_user(**_kwargs):
        calls.append("user")
        return user

    user_service.get_or_create_user.side_effect = get_user
    sender.send_processing.side_effect = lambda _chat_id: calls.append(
        "processing")
    voice_task_service.create_from_voice.side_effect = (
        lambda _user, _voice: calls.append("create") or VoiceTaskResult.ok(task
                                                                           ))
    sender.send_task_created.side_effect = (
        lambda _chat_id, _task, _reminders: calls.append("created"))

    await handle_voice(message, user_service, sender, voice_task_service)

    assert calls == ["user", "processing", "create", "created"]


@pytest.mark.parametrize("error_code", [
    ErrorCode.VOICE_TOO_LONG,
    ErrorCode.VOICE_TOO_LARGE,
    ErrorCode.STT_EMPTY,
    ErrorCode.PARSER_FAILED,
    ErrorCode.DATE_IN_PAST,
    ErrorCode.GENERIC,
])
@pytest.mark.asyncio
async def test_voice_handler_sends_pipeline_error(message, user_service,
                                                  sender, voice_task_service,
                                                  error_code):
    voice_task_service.create_from_voice.return_value = (
        VoiceTaskResult.failure(error_code))

    await handle_voice(message, user_service, sender, voice_task_service)

    sender.send_processing.assert_awaited_once_with(message.chat.id)
    sender.send_error.assert_awaited_once_with(message.chat.id, error_code)
    sender.send_task_created.assert_not_awaited()
