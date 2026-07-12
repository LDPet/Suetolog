from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from reminder.bot.handlers.callbacks import (complete_task_callback,
                                             delete_task_callback)
from reminder.models import Task


@pytest.fixture
def callback():
    callback = Mock()
    callback.answer = AsyncMock()
    callback.data = "done:42"
    callback.from_user.id = 1001
    callback.message.message_id = 777
    callback.message.chat.id = 2002
    return callback


@pytest.fixture
def owner():
    return SimpleNamespace(id=1, telegram_user_id=1001)


@pytest.fixture
def task(owner):
    return SimpleNamespace(
        id=42,
        user=owner,
        user_id=owner.id,
        status=Task.Status.ACTIVE,
    )


@pytest.fixture
def sender():
    sender = Mock()
    sender.send_text = AsyncMock()
    sender.send_deleted = AsyncMock()
    sender.send_task_completed = AsyncMock()
    return sender


def mock_task_lookup(mocker, task):
    select_related = mocker.patch(
        "reminder.bot.handlers.callbacks.Task.objects.select_related")
    select_related.return_value.filter.return_value.first.return_value = task


@pytest.mark.asyncio
async def test_delete_uses_delete_task(callback, owner, task, sender, mocker):
    callback.data = "delete:42"
    task_service = Mock()
    mock_task_lookup(mocker, task)

    await delete_task_callback(callback, task_service, sender)

    callback.answer.assert_awaited_once_with()
    task_service.delete_task.assert_called_once_with(owner, 42)
    task_service.mark_cancelled.assert_not_called()
    sender.send_deleted.assert_awaited_once_with(callback.message.chat.id,
                                                 task)


@pytest.mark.asyncio
async def test_delete_rejects_another_user(callback, task, sender, mocker):
    callback.data = "delete:42"
    callback.from_user.id = 9999
    task_service = Mock()
    mock_task_lookup(mocker, task)

    await delete_task_callback(callback, task_service, sender)

    callback.answer.assert_awaited_once_with()
    task_service.delete_task.assert_not_called()
    sender.send_deleted.assert_not_awaited()
    sender.send_text.assert_awaited_once_with(
        callback.message.chat.id,
        "Задача принадлежит другому пользователю",
    )


@pytest.mark.asyncio
async def test_missing_task_returns_user_message(callback, sender, mocker):
    callback.data = "delete:404"
    task_service = Mock()
    mock_task_lookup(mocker, None)

    await delete_task_callback(callback, task_service, sender)

    callback.answer.assert_awaited_once_with()
    task_service.delete_task.assert_not_called()
    sender.send_text.assert_awaited_once_with(
        callback.message.chat.id,
        "Задача не найдена",
    )


@pytest.mark.asyncio
async def test_done_uses_matching_reminder(callback, owner, task, sender,
                                           mocker):
    task_service = Mock()
    reminder = SimpleNamespace(task_id=task.id)
    reminder_service = Mock()
    reminder_service.find_by_message.return_value = reminder
    mock_task_lookup(mocker, task)

    await complete_task_callback(callback, task_service, sender,
                                 reminder_service)

    callback.answer.assert_awaited_once_with()
    reminder_service.find_by_message.assert_called_once_with(
        callback.message.chat.id,
        callback.message.message_id,
    )
    task_service.mark_done.assert_called_once_with(owner, reminder=reminder)
    sender.send_task_completed.assert_awaited_once_with(
        callback.message.chat.id,
        task,
    )


@pytest.mark.asyncio
async def test_done_falls_back_to_task_id(callback, owner, task, sender,
                                          mocker):
    task_service = Mock()
    reminder_service = Mock()
    reminder_service.find_by_message.return_value = None
    mock_task_lookup(mocker, task)

    await complete_task_callback(callback, task_service, sender,
                                 reminder_service)

    callback.answer.assert_awaited_once_with()
    task_service.mark_done.assert_called_once_with(owner, task_id=task.id)
    sender.send_task_completed.assert_awaited_once_with(
        callback.message.chat.id,
        task,
    )


@pytest.mark.parametrize("callback_data", ["done:", "done:abc", "done", ""])
@pytest.mark.asyncio
async def test_done_rejects_malformed_callback_data(callback_data, sender,
                                                    mocker):
    callback = Mock()
    callback.answer = AsyncMock()
    callback.data = callback_data
    callback.message.chat.id = 2002
    task_service = Mock()
    reminder_service = Mock()

    await complete_task_callback(callback, task_service, sender,
                                 reminder_service)

    callback.answer.assert_awaited_once_with("Некорректные данные")
    sender.send_text.assert_awaited_once_with(
        2002,
        "Не удалось обработать действие",
    )
    task_service.mark_done.assert_not_called()
    sender.send_task_completed.assert_not_awaited()
