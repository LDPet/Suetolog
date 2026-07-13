from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest
from asgiref.sync import sync_to_async

from errors import ErrorCode, error_messages
from reminder.bot.formatting import format_task_due_to, format_task_identity
from reminder.bot.sender import TaskCardVariant
from reminder.models import Task, TaskEvent, User

CARD_FOOTER = ("Ответь на это сообщение с датой и временем —\n"
               "назначить или изменить срок.")


@pytest.fixture
def task():
    return Task(
        pk=1,
        title="Купить молоко",
        description="",
        due_to=datetime(2026, 7, 15, 10, 0, tzinfo=ZoneInfo("Europe/Moscow")),
        due_to_has_time=True,
    )


def set_message_id(mock_bot, message_id):
    mock_bot.send_message.return_value = Mock(message_id=message_id)


def assert_keyboard(mock_bot, task_id):
    keyboard = mock_bot.send_message.call_args.kwargs["reply_markup"]
    buttons = keyboard.inline_keyboard[0]
    assert buttons[0].text == "✅ Сделано"
    assert buttons[0].callback_data == f"done:{task_id}"
    assert buttons[1].text == "🗑 Удалить"
    assert buttons[1].callback_data == f"delete:{task_id}"


class TestTelegramSender:

    @pytest.mark.asyncio
    async def test_send_text(self, sender, mock_bot):
        await sender.send_text(123456, "Hello, World!")

        mock_bot.send_message.assert_called_once_with(
            chat_id=123456,
            text="Hello, World!\n\n",
        )

    @pytest.mark.asyncio
    async def test_send_date_confirmed_for_new_date(self, sender, mock_bot,
                                                    task):
        await sender.send_date_confirmed(456, task)

        mock_bot.send_message.assert_called_once_with(
            chat_id=456,
            text=("Дата назначена\n"
                  "📋 Название: Купить молоко\n"
                  "📝 Описание: не указано\n"
                  "📅 Срок: 15 июля 2026, 10:00\n\n"),
        )

    @pytest.mark.asyncio
    async def test_send_date_confirmed_for_reschedule(self, sender, mock_bot,
                                                      task):
        await sender.send_date_confirmed(456, task, rescheduled=True)

        mock_bot.send_message.assert_called_once_with(
            chat_id=456,
            text=("Дата перенесена\n"
                  "📋 Название: Купить молоко\n"
                  "📝 Описание: не указано\n"
                  "📅 Срок: 15 июля 2026, 10:00\n\n"),
        )

    @pytest.mark.asyncio
    async def test_send_task_created_shows_parsed_fields(
            self, sender, mock_bot, task):
        due_to = task.due_to
        task.description = "2 литра"
        task.due_to_has_time = True
        task.repeat_type = None
        reminders = [SimpleNamespace(reminder_time=due_to)]

        await sender.send_task_created(456, task, reminders)

        mock_bot.send_message.assert_called_once()
        text = mock_bot.send_message.call_args.kwargs["text"]
        assert "✅ Задача создана" in text
        assert "📋 Название: Купить молоко" in text
        assert "📝 Описание: 2 литра" in text
        assert "15 июля 2026, 10:00 (точное время)" in text
        assert "⏰ Напоминания:" in text
        assert "ожидает отправки" in text

    @pytest.mark.parametrize("error_code", [
        ErrorCode.VOICE_TOO_LONG,
        ErrorCode.VOICE_TOO_LARGE,
        ErrorCode.STT_EMPTY,
        ErrorCode.PARSER_FAILED,
        ErrorCode.DATE_IN_PAST,
        ErrorCode.GENERIC,
    ])
    @pytest.mark.asyncio
    async def test_send_error(self, sender, mock_bot, error_code):
        await sender.send_error(123456, error_code)

        mock_bot.send_message.assert_called_once()
        call_args = mock_bot.send_message.call_args.kwargs
        assert call_args["chat_id"] == 123456
        assert call_args["text"] == f"{error_messages[error_code]}\n\n"

    @pytest.mark.asyncio
    async def test_send_welcome(self, sender, mock_bot):
        await sender.send_welcome(123456)

        mock_bot.send_message.assert_called_once()
        call_args = mock_bot.send_message.call_args.kwargs
        target_text = (
            "Привет! Я голосовой напоминальщик. "
            "Отправь голосовое сообщение с задачей — назови дело, дату и время."
            "Если дата неизвестна — скажи «без даты»."
            "Команды: /undated — задачи без даты.")
        assert call_args["text"] == f"{target_text}\n\n"


class TestTaskCards:

    @pytest.mark.asyncio
    async def test_undated_card(self, sender, mock_bot, mocker, task):
        set_message_id(mock_bot, 123)
        mock_create = mocker.patch(
            "reminder.bot.sender.TaskEventRepository.create")

        message_id = await sender.send_undated_list(456, [task])

        mock_bot.send_message.assert_awaited_once_with(
            chat_id=456,
            text=(f"{format_task_identity(task)}\n"
                  f"Без даты\n\n{CARD_FOOTER}\n\n"),
            reply_markup=mock_bot.send_message.call_args.
            kwargs["reply_markup"],
        )
        assert_keyboard(mock_bot, task.pk)
        mock_create.assert_called_once_with(
            message_id=123,
            task=task,
            event_type=TaskEvent.EventType.UNDATED_CARD_SENT,
        )
        assert message_id == 123

    @pytest.mark.asyncio
    async def test_reminder_card(self, sender, mock_bot, mocker, task):
        set_message_id(mock_bot, 124)
        mock_create = mocker.patch(
            "reminder.bot.sender.TaskEventRepository.create")

        message_id = await sender.send_reminder(456, task)

        due_text = format_task_due_to(task)
        text = mock_bot.send_message.call_args.kwargs["text"]
        assert text == (f"⏰ Напоминание:\n"
                        f"{format_task_identity(task)}\n"
                        f"📅 {due_text}\n\n{CARD_FOOTER}\n\n")
        assert_keyboard(mock_bot, task.pk)
        mock_create.assert_not_called()
        assert message_id == 124

    @pytest.mark.asyncio
    async def test_reminder_card_with_description(self, sender, mock_bot,
                                                  mocker, task):
        task.description = "с моющим средством"
        set_message_id(mock_bot, 128)
        mocker.patch("reminder.bot.sender.TaskEventRepository.create")

        await sender.send_reminder(456, task)

        text = mock_bot.send_message.call_args.kwargs["text"]
        assert "📋 Название: Купить молоко" in text
        assert "📝 Описание: с моющим средством" in text
        assert "📅" in text

    @pytest.mark.asyncio
    async def test_digest_card(self, sender, mock_bot, mocker, task):
        set_message_id(mock_bot, 125)
        mock_create = mocker.patch(
            "reminder.bot.sender.TaskEventRepository.create")

        message_id = await sender.send_digest(456, task)

        due_text = format_task_due_to(task)
        text = mock_bot.send_message.call_args.kwargs["text"]
        assert text == (f"🌅 На сегодня:\n"
                        f"{format_task_identity(task)}\n"
                        f"📅 {due_text}\n\n{CARD_FOOTER}\n\n")
        assert_keyboard(mock_bot, task.pk)
        mock_create.assert_called_once_with(
            message_id=125,
            task=task,
            event_type=TaskEvent.EventType.DIGEST_CARD_SENT,
        )
        assert message_id == 125

    @pytest.mark.asyncio
    async def test_evening_card(self, sender, mock_bot, mocker, task):
        set_message_id(mock_bot, 126)
        mock_create = mocker.patch(
            "reminder.bot.sender.TaskEventRepository.create")

        message_id = await sender.send_evening_question(456, task)

        due_text = format_task_due_to(task)
        text = mock_bot.send_message.call_args.kwargs["text"]
        assert text == (f"Задача не выполнена.\n"
                        f"{format_task_identity(task)}\n"
                        f"📅 {due_text}\n\n{CARD_FOOTER}\n\n")
        assert_keyboard(mock_bot, task.pk)
        mock_create.assert_called_once_with(
            message_id=126,
            task=task,
            event_type=TaskEvent.EventType.EVENING_QUESTION_SENT,
        )
        assert message_id == 126

    @pytest.mark.asyncio
    async def test_send_task_card_does_not_create_event(
            self, sender, mock_bot, mocker, task):
        set_message_id(mock_bot, 127)
        mock_create = mocker.patch(
            "reminder.bot.sender.TaskEventRepository.create")

        message_id = await sender.send_task_card(456, task,
                                                 TaskCardVariant.REMINDER)

        assert message_id == 127
        mock_create.assert_not_called()

    @pytest.mark.asyncio
    async def test_unknown_variant_is_rejected(self, sender, mock_bot, task):
        with pytest.raises(ValueError, match="Unknown task card variant"):
            await sender.send_task_card(456, task, "unknown")

        mock_bot.send_message.assert_not_awaited()

    def test_digest_event_type_is_available(self):
        assert TaskEvent.EventType.DIGEST_CARD_SENT == "digest_card_sent"

    def test_all_variants_are_declared(self):
        assert set(TaskCardVariant.values) == {
            "undated",
            "reminder",
            "digest",
            "evening",
        }

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_message_id_is_persisted_in_task_event(
            self, sender, mock_bot):
        user = await sync_to_async(User.objects.create)(
            chat_id=456,
            telegram_user_id=654,
        )
        task = await sync_to_async(Task.objects.create)(
            user=user,
            title="Купить молоко",
        )
        set_message_id(mock_bot, 321)

        await sender.send_undated_list(user.chat_id, [task])

        event = await sync_to_async(TaskEvent.objects.get)(
            task=task,
            event_type=TaskEvent.EventType.UNDATED_CARD_SENT,
        )
        assert event.message_id == 321
