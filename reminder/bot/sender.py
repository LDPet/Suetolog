from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from asgiref.sync import sync_to_async

from errors import error_messages
from reminder.models import TaskEvent
from reminder.repositories.task_event import TaskEventRepository


class TelegramSender:

    def __init__(self, bot: Bot):
        self.bot = bot

    async def send_text(self, chat_id, text):
        message = await self.bot.send_message(chat_id=chat_id,
                                              text=f"{text}\n\n")
        return message.message_id

    async def send_text_with_keyboard(self, chat_id, text, keyboard):
        message = await self.bot.send_message(chat_id=chat_id,
                                              text=f"{text}\n\n",
                                              reply_markup=keyboard)
        return message.message_id

    async def send_welcome(self, chat_id):
        text = (
            "Привет! Я голосовой напоминальщик. "
            "Отправь голосовое сообщение с задачей — назови дело, дату и время."
            "Если дата неизвестна — скажи «без даты»."
            "Команды: /undated — задачи без даты.")
        message_id = await self.send_text(chat_id, text)
        return message_id

    async def send_processing(self, chat_id):
        text = "Слушаю..."
        message_id = await self.send_text(chat_id, text)
        return message_id

    async def send_task_created(self, chat_id, task):
        text = f"Задача создана: {task.title}"
        message_id = await self.send_text(chat_id, text)
        return message_id

    async def send_error(self, chat_id, error_code):
        message_id = await self.send_text(chat_id, error_messages[error_code])
        return message_id

    async def send_undated_list(self, chat_id, tasks):
        message_id = None
        for task in tasks:
            task_id = task.pk
            text = f"{task.title}"
            keyboard = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="📅 Назначить дату",
                                     callback_data=f"assign_date:{task_id}"),
                InlineKeyboardButton(text="🗑️ Удалить",
                                     callback_data=f"delete:{task_id}")
            ]])
            message_id = await self.send_text_with_keyboard(
                chat_id, text, keyboard)
            await sync_to_async(
                TaskEventRepository.create, thread_sensitive=True)(
                    task=task,
                    event_type=TaskEvent.EventType.UNDATED_CARD_SENT)

        return message_id

    async def send_reminder(self, chat_id, task):
        text = f"Напоминание: {task.title}"
        message_id = await self.send_text(chat_id, text)
        return message_id

    async def send_evening_question(self, chat_id, task):
        text = (f"Задача {task.title} не выполнена.\n"
                f"Ответь на это сообщение: на какую дату и время перенести?")
        message_id = await self.send_text(chat_id, text)
        return message_id

    async def send_date_confirmed(self, chat_id, task):
        text = f"Дата назначена: {task.title} - {task.due_to}"
        message_id = await self.send_text(chat_id, text)
        return message_id

    async def send_deleted(self, chat_id, task):
        text = f"Задача {task.title} удалена"
        message_id = await self.send_text(chat_id, text)
        return message_id

    async def send_empty_undated(self, chat_id):
        text = "Нет задач без даты"
        message_id = await self.send_text(chat_id, text)
        return message_id