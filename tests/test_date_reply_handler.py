from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from zoneinfo import ZoneInfo

import pytest

from errors import ErrorCode
from reminder.bot.handlers.date_reply import (CARD_EVENT_TYPES,
                                              FOREIGN_TASK_TEXT,
                                              INACTIVE_TASK_TEXT,
                                              NO_REPLY_TEXT, UNKNOWN_CARD_TEXT,
                                              handle_date_reply)
from reminder.models import TaskEvent
from reminder.services.dto import ParsedDateResult
from reminder.services.parsing import ParserError, ParserErrorCode
from reminder.services.tasks import (TaskDateInPastError, TaskNotFoundError,
                                     TaskStateError)

MSK = ZoneInfo("Europe/Moscow")
NEW_DUE_TO = datetime(2026, 7, 15, 18, 0, tzinfo=MSK)


@pytest.fixture
def message():
    return SimpleNamespace(
        chat=SimpleNamespace(id=456),
        from_user=SimpleNamespace(id=123),
        text="послезавтра в 18",
        reply_to_message=SimpleNamespace(message_id=777),
    )


@pytest.fixture
def user():
    return SimpleNamespace(id=10)


@pytest.fixture
def user_service(user):
    service = Mock()
    service.get_or_create_user.return_value = user
    return service


@pytest.fixture
def task_service():
    service = Mock()
    service.set_due_date.return_value = SimpleNamespace(id=42)
    service.reschedule.return_value = SimpleNamespace(id=42)
    return service


@pytest.fixture
def date_parser():
    parser = Mock()
    parser.parse_date.return_value = ParsedDateResult(
        due_to=NEW_DUE_TO,
        due_to_has_time=True,
    )
    return parser


@pytest.fixture
def sender():
    sender = Mock()
    sender.send_text = AsyncMock()
    sender.send_error = AsyncMock()
    sender.send_date_confirmed = AsyncMock()
    return sender


def event(event_type, due_to=None):
    return SimpleNamespace(
        event_type=event_type,
        task_id=42,
        task=SimpleNamespace(due_to=due_to),
    )


@pytest.mark.asyncio
async def test_without_reply_sends_hint_without_lookup_or_parser(
        message, user_service, task_service, date_parser, sender, mocker):
    message.reply_to_message = None
    lookup = mocker.patch(
        "reminder.bot.handlers.date_reply.TaskEventRepository."
        "find_by_message_id")

    await handle_date_reply(message, user_service, task_service, date_parser,
                            sender)

    sender.send_text.assert_awaited_once_with(message.chat.id, NO_REPLY_TEXT)
    lookup.assert_not_called()
    date_parser.parse_date.assert_not_called()


@pytest.mark.parametrize(
    "lookup_result",
    [None, event(TaskEvent.EventType.CREATED)],
)
@pytest.mark.asyncio
async def test_unknown_or_non_card_message_is_rejected(lookup_result, message,
                                                       user_service,
                                                       task_service,
                                                       date_parser, sender,
                                                       mocker):
    lookup = mocker.patch(
        "reminder.bot.handlers.date_reply.TaskEventRepository."
        "find_by_message_id",
        return_value=lookup_result,
    )

    await handle_date_reply(message, user_service, task_service, date_parser,
                            sender)

    lookup.assert_called_once_with(message.reply_to_message.message_id)
    sender.send_text.assert_awaited_once_with(message.chat.id,
                                              UNKNOWN_CARD_TEXT)
    user_service.get_or_create_user.assert_not_called()
    date_parser.parse_date.assert_not_called()


@pytest.mark.asyncio
async def test_lookup_failure_sends_generic_error(message, user_service,
                                                  task_service, date_parser,
                                                  sender, mocker):
    mocker.patch(
        "reminder.bot.handlers.date_reply.TaskEventRepository."
        "find_by_message_id",
        side_effect=RuntimeError("database unavailable"),
    )

    await handle_date_reply(message, user_service, task_service, date_parser,
                            sender)

    sender.send_error.assert_awaited_once_with(message.chat.id,
                                               ErrorCode.GENERIC)
    user_service.get_or_create_user.assert_not_called()
    date_parser.parse_date.assert_not_called()


@pytest.mark.asyncio
async def test_undated_card_sets_first_due_date(message, user, user_service,
                                                task_service, date_parser,
                                                sender, mocker):
    card_event = event(TaskEvent.EventType.UNDATED_CARD_SENT)
    mocker.patch(
        "reminder.bot.handlers.date_reply.TaskEventRepository."
        "find_by_message_id",
        return_value=card_event,
    )
    updated_task = task_service.set_due_date.return_value

    await handle_date_reply(message, user_service, task_service, date_parser,
                            sender)

    user_service.get_or_create_user.assert_called_once_with(
        chat_id=message.chat.id,
        telegram_user_id=message.from_user.id,
    )
    date_parser.parse_date.assert_called_once_with(message.text)
    task_service.set_due_date.assert_called_once_with(
        user=user,
        task_id=card_event.task_id,
        due_to=NEW_DUE_TO,
        due_to_has_time=True,
    )
    task_service.reschedule.assert_not_called()
    sender.send_date_confirmed.assert_awaited_once_with(message.chat.id,
                                                        updated_task,
                                                        rescheduled=False)


@pytest.mark.parametrize(
    "event_type",
    [
        TaskEvent.EventType.REMINDER_SENT,
        TaskEvent.EventType.DIGEST_CARD_SENT,
        TaskEvent.EventType.EVENING_QUESTION_SENT,
    ],
)
@pytest.mark.asyncio
async def test_dated_cards_reschedule_task(event_type, message, user,
                                           user_service, task_service,
                                           date_parser, sender, mocker):
    old_due_to = datetime(2026, 7, 14, 12, 0, tzinfo=MSK)
    card_event = event(event_type, due_to=old_due_to)
    mocker.patch(
        "reminder.bot.handlers.date_reply.TaskEventRepository."
        "find_by_message_id",
        return_value=card_event,
    )
    date_parser.parse_date.return_value = ParsedDateResult(
        due_to=NEW_DUE_TO,
        due_to_has_time=False,
    )
    updated_task = task_service.reschedule.return_value

    await handle_date_reply(message, user_service, task_service, date_parser,
                            sender)

    task_service.reschedule.assert_called_once_with(
        user=user,
        task_id=card_event.task_id,
        due_to=NEW_DUE_TO,
        due_to_has_time=False,
    )
    task_service.set_due_date.assert_not_called()
    sender.send_date_confirmed.assert_awaited_once_with(message.chat.id,
                                                        updated_task,
                                                        rescheduled=True)


@pytest.mark.parametrize(
    ("parser_code", "error_code"),
    [
        (ParserErrorCode.PARSER_FAILED, ErrorCode.PARSER_FAILED),
        (ParserErrorCode.DATE_IN_PAST, ErrorCode.DATE_IN_PAST),
    ],
)
@pytest.mark.asyncio
async def test_parser_errors_are_mapped(parser_code, error_code, message,
                                        user_service, task_service,
                                        date_parser, sender, mocker):
    mocker.patch(
        "reminder.bot.handlers.date_reply.TaskEventRepository."
        "find_by_message_id",
        return_value=event(TaskEvent.EventType.UNDATED_CARD_SENT),
    )
    date_parser.parse_date.side_effect = ParserError(parser_code,
                                                     "date parsing failed")

    await handle_date_reply(message, user_service, task_service, date_parser,
                            sender)

    sender.send_error.assert_awaited_once_with(message.chat.id, error_code)
    task_service.set_due_date.assert_not_called()


@pytest.mark.asyncio
async def test_service_rejects_past_date(message, user_service, task_service,
                                         date_parser, sender, mocker):
    mocker.patch(
        "reminder.bot.handlers.date_reply.TaskEventRepository."
        "find_by_message_id",
        return_value=event(TaskEvent.EventType.UNDATED_CARD_SENT),
    )
    task_service.set_due_date.side_effect = TaskDateInPastError()

    await handle_date_reply(message, user_service, task_service, date_parser,
                            sender)

    sender.send_error.assert_awaited_once_with(message.chat.id,
                                               ErrorCode.DATE_IN_PAST)
    sender.send_date_confirmed.assert_not_awaited()


@pytest.mark.parametrize(
    ("service_error", "expected_text"),
    [
        (TaskNotFoundError(), UNKNOWN_CARD_TEXT),
        (PermissionError(), FOREIGN_TASK_TEXT),
        (TaskStateError(), INACTIVE_TASK_TEXT),
    ],
)
@pytest.mark.asyncio
async def test_task_errors_are_shown_to_user(service_error, expected_text,
                                             message, user_service,
                                             task_service, date_parser, sender,
                                             mocker):
    mocker.patch(
        "reminder.bot.handlers.date_reply.TaskEventRepository."
        "find_by_message_id",
        return_value=event(TaskEvent.EventType.UNDATED_CARD_SENT),
    )
    task_service.set_due_date.side_effect = service_error

    await handle_date_reply(message, user_service, task_service, date_parser,
                            sender)

    sender.send_text.assert_awaited_once_with(message.chat.id, expected_text)
    sender.send_date_confirmed.assert_not_awaited()


def test_all_task_card_event_types_are_supported():
    assert CARD_EVENT_TYPES == {
        TaskEvent.EventType.UNDATED_CARD_SENT,
        TaskEvent.EventType.REMINDER_SENT,
        TaskEvent.EventType.DIGEST_CARD_SENT,
        TaskEvent.EventType.EVENING_QUESTION_SENT,
    }
