from types import SimpleNamespace

import pytest

from errors import ErrorCode, error_messages


class TestTelegramSender:

    @pytest.mark.asyncio
    async def test_send_text(self, sender, mock_bot):
        await sender.send_text(123456, "Hello, World!")

        mock_bot.send_message.assert_called_once_with(chat_id=123456,
                                                      text="Hello, World!\n\n")

    @pytest.mark.asyncio
    async def test_send_error(self, sender, mock_bot):
        await sender.send_error(123456, ErrorCode.VOICE_TOO_LARGE)

        mock_bot.send_message.assert_called_once()
        call_args = mock_bot.send_message.call_args[1]
        assert call_args["chat_id"] == 123456
        assert call_args[
            "text"] == f"{error_messages[ErrorCode.VOICE_TOO_LARGE]}\n\n"

    @pytest.mark.asyncio
    async def test_send_welcome(self, sender, mock_bot):
        await sender.send_welcome(123456)

        mock_bot.send_message.assert_called_once()
        call_args = mock_bot.send_message.call_args[1]
        target_text = (
            "Привет! Я голосовой напоминальщик. "
            "Отправь голосовое сообщение с задачей — назови дело, дату и время."
            "Если дата неизвестна — скажи «без даты»."
            "Команды: /undated — задачи без даты.")
        assert call_args["text"] == f"{target_text}\n\n"

    @pytest.mark.asyncio
    async def test_send_undated_list_uses_task_primary_key(
            self, sender, mock_bot):
        task = SimpleNamespace(pk=42, title="Купить молоко")

        await sender.send_undated_list(123456, [task])

        call_args = mock_bot.send_message.call_args.kwargs
        keyboard = call_args["reply_markup"]
        buttons = keyboard.inline_keyboard[0]
        assert buttons[0].callback_data == "assign_date:42"
        assert buttons[1].callback_data == "delete:42"
