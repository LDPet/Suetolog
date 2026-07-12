from unittest.mock import AsyncMock, Mock

import pytest

from reminder.bot.handlers.undated import handle_undated


@pytest.fixture
def message():
    message = Mock()
    message.chat.id = 2002
    message.from_user.id = 1001
    return message


@pytest.fixture
def user_service():
    service = Mock()
    service.get_or_create_user.return_value = Mock()
    return service


@pytest.fixture
def task_service():
    return Mock()


@pytest.fixture
def sender():
    sender = Mock()
    sender.send_undated_list = AsyncMock(return_value=777)
    sender.send_empty_undated = AsyncMock(return_value=778)
    return sender


@pytest.mark.asyncio
async def test_sends_undated_tasks(message, user_service, task_service,
                                   sender):
    tasks = [Mock(), Mock()]
    task_service.list_undated.return_value = tasks

    result = await handle_undated(message, user_service, task_service, sender)

    user_service.get_or_create_user.assert_called_once_with(
        chat_id=message.chat.id,
        telegram_user_id=message.from_user.id,
    )
    task_service.list_undated.assert_called_once_with(
        user_service.get_or_create_user.return_value)
    sender.send_undated_list.assert_awaited_once_with(message.chat.id, tasks)
    sender.send_empty_undated.assert_not_awaited()
    assert result == 777


@pytest.mark.asyncio
async def test_sends_empty_state(message, user_service, task_service, sender):
    task_service.list_undated.return_value = []

    result = await handle_undated(message, user_service, task_service, sender)

    sender.send_undated_list.assert_not_awaited()
    sender.send_empty_undated.assert_awaited_once_with(message.chat.id)
    assert result == 778
