import logging

from aiogram.types import Message
from asgiref.sync import sync_to_async

from errors import ErrorCode
from reminder.bot.sender import TelegramSender
from reminder.models import TaskEvent
from reminder.repositories.task_event import TaskEventRepository
from reminder.services.contracts import DateParser
from reminder.services.parsing import ParserError, ParserErrorCode
from reminder.services.tasks import (TaskDateInPastError, TaskNotFoundError,
                                     TaskService, TaskStateError)
from reminder.services.users import UserService

logger = logging.getLogger(__name__)

NO_REPLY_TEXT = (
    "Чтобы назначить или изменить дату, ответь (Reply) на сообщение с задачей."
)
UNKNOWN_CARD_TEXT = "Не нашёл задачу по этому сообщению."
FOREIGN_TASK_TEXT = "Эта задача принадлежит другому пользователю."
INACTIVE_TASK_TEXT = "Эту задачу уже нельзя изменить."

CARD_EVENT_TYPES = {
    TaskEvent.EventType.UNDATED_CARD_SENT,
    TaskEvent.EventType.REMINDER_SENT,
    TaskEvent.EventType.DIGEST_CARD_SENT,
    TaskEvent.EventType.EVENING_QUESTION_SENT,
}


async def handle_date_reply(message: Message, user_service: UserService,
                            task_service: TaskService,
                            date_parser: DateParser | None,
                            sender: TelegramSender) -> None:
    chat_id = message.chat.id
    reply = message.reply_to_message
    if reply is None:
        await sender.send_text(chat_id, NO_REPLY_TEXT)
        return

    reply_message_id = reply.message_id
    try:
        event = await sync_to_async(
            TaskEventRepository.find_by_message_id,
            thread_sensitive=True,
        )(reply_message_id)
    except Exception:
        logger.exception(
            "Failed to look up task card | chat_id=%s reply_message_id=%s",
            chat_id,
            reply_message_id,
        )
        await sender.send_error(chat_id, ErrorCode.GENERIC)
        return

    if event is None or event.event_type not in CARD_EVENT_TYPES:
        await sender.send_text(chat_id, UNKNOWN_CARD_TEXT)
        return

    if date_parser is None:
        logger.error("Date parser is not configured | chat_id=%s", chat_id)
        await sender.send_error(chat_id, ErrorCode.GENERIC)
        return

    try:
        user = await sync_to_async(
            user_service.get_or_create_user,
            thread_sensitive=True,
        )(
            chat_id=chat_id,
            telegram_user_id=message.from_user.id,
        )
        parsed = await sync_to_async(
            date_parser.parse_date,
            thread_sensitive=False,
        )(message.text or "")

        rescheduled = event.task.due_to is not None
        service_method = (task_service.reschedule
                          if rescheduled else task_service.set_due_date)
        task = await sync_to_async(
            service_method,
            thread_sensitive=True,
        )(
            user=user,
            task_id=event.task_id,
            due_to=parsed.due_to,
            due_to_has_time=parsed.due_to_has_time,
        )
    except ParserError as error:
        error_code = (ErrorCode.DATE_IN_PAST
                      if error.code == ParserErrorCode.DATE_IN_PAST else
                      ErrorCode.PARSER_FAILED)
        await sender.send_error(chat_id, error_code)
        return
    except TaskDateInPastError:
        await sender.send_error(chat_id, ErrorCode.DATE_IN_PAST)
        return
    except TaskNotFoundError:
        await sender.send_text(chat_id, UNKNOWN_CARD_TEXT)
        return
    except PermissionError:
        await sender.send_text(chat_id, FOREIGN_TASK_TEXT)
        return
    except TaskStateError:
        await sender.send_text(chat_id, INACTIVE_TASK_TEXT)
        return
    except Exception:
        logger.exception(
            "Failed to update task date | chat_id=%s task_id=%s",
            chat_id,
            event.task_id,
        )
        await sender.send_error(chat_id, ErrorCode.GENERIC)
        return

    await sender.send_date_confirmed(chat_id, task, rescheduled=rescheduled)
