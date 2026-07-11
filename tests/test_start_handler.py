from unittest.mock import AsyncMock, Mock

import pytest
from asgiref.sync import sync_to_async

from reminder.bot.handlers.start import handle_start
from reminder.models import User
from reminder.services.users import UserService


@pytest.fixture
def start_message():
    message = Mock()
    message.chat.id = 456
    message.from_user.id = 123
    return message


@pytest.fixture
def welcome_sender():
    sender = Mock()
    sender.send_welcome = AsyncMock()
    return sender


@pytest.mark.asyncio
async def test_start_calls_user_service_and_sends_welcome(
        start_message, welcome_sender):
    user_service = Mock()
    user_service.get_or_create_user = Mock()

    await handle_start(start_message, user_service, welcome_sender)

    user_service.get_or_create_user.assert_called_once_with(
        chat_id=start_message.chat.id,
        telegram_user_id=start_message.from_user.id,
    )
    welcome_sender.send_welcome.assert_awaited_once_with(start_message.chat.id)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_repeated_start_creates_one_user(start_message, welcome_sender):
    user_service = UserService()

    await handle_start(start_message, user_service, welcome_sender)
    await handle_start(start_message, user_service, welcome_sender)

    users = await sync_to_async(list,
                                thread_sensitive=True)(User.objects.all())
    assert len(users) == 1
    assert users[0].chat_id == start_message.chat.id
    assert users[0].telegram_user_id == start_message.from_user.id
    assert welcome_sender.send_welcome.await_count == 2
