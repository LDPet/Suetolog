from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from asgiref.sync import sync_to_async
from django.db.models import TextChoices

from errors import error_messages
from reminder.bot.formatting import (format_task_created_message,
                                     format_task_due_to, format_task_identity)
from reminder.models import Reminder, Task, TaskEvent
from reminder.repositories.task_event import TaskEventRepository


class TaskCardVariant(TextChoices):
    UNDATED = "undated", "Без даты"
    REMINDER = "reminder", "Напоминание"
    DIGEST = "digest", "На сегодня"
    EVENING = "evening", "Не сделано"


TASK_CARD_EVENT_TYPES = {
    TaskCardVariant.UNDATED: TaskEvent.EventType.UNDATED_CARD_SENT,
    TaskCardVariant.DIGEST: TaskEvent.EventType.DIGEST_CARD_SENT,
    TaskCardVariant.EVENING: TaskEvent.EventType.EVENING_QUESTION_SENT,
}


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

    async def send_task_created(self,
                                chat_id,
                                task,
                                reminders: list[Reminder] | None = None):
        text = format_task_created_message(task, reminders)
        message_id = await self.send_text(chat_id, text)
        return message_id

    async def send_error(self, chat_id, error_code):
        message_id = await self.send_text(chat_id, error_messages[error_code])
        return message_id

    async def send_undated_list(self, chat_id, tasks):
        message_id = None
        for task in tasks:
            message_id = await self._send_task_card_with_event(
                chat_id, task, TaskCardVariant.UNDATED)

        return message_id

    async def send_reminder(self, chat_id, task):
        return await self.send_task_card(chat_id, task,
                                         TaskCardVariant.REMINDER)

    async def send_evening_question(self, chat_id, task):
        return await self._send_task_card_with_event(chat_id, task,
                                                     TaskCardVariant.EVENING)

    async def send_digest(self, chat_id, task):
        return await self._send_task_card_with_event(chat_id, task,
                                                     TaskCardVariant.DIGEST)

    async def _send_task_card_with_event(self, chat_id, task, variant):
        message_id = await self.send_task_card(chat_id, task, variant)
        await self._create_task_card_event(
            task=task,
            message_id=message_id,
            event_type=TASK_CARD_EVENT_TYPES[variant],
        )
        return message_id

    async def _create_task_card_event(self, task, message_id, event_type):
        await sync_to_async(TaskEventRepository.create, thread_sensitive=True)(
            message_id=message_id,
            task=task,
            event_type=event_type,
        )

    async def send_date_confirmed(self,
                                  chat_id,
                                  task,
                                  *,
                                  rescheduled: bool = False):
        due_text = format_task_due_to(task)
        action = "Дата перенесена" if rescheduled else "Дата назначена"
        text = (f"{action}\n"
                f"{format_task_identity(task)}\n"
                f"📅 Срок: {due_text}")
        message_id = await self.send_text(chat_id, text)
        return message_id

    async def send_deleted(self, chat_id, task):
        text = f"Задача удалена\n{format_task_identity(task)}"
        message_id = await self.send_text(chat_id, text)
        return message_id

    async def send_task_completed(self, chat_id, task):
        text = f"Задача выполнена\n{format_task_identity(task)}"
        message_id = await self.send_text(chat_id, text)
        return message_id

    async def send_empty_digest(self, chat_id):
        text = "На сегодня задач нет"
        message_id = await self.send_text(chat_id, text)
        return message_id

    async def send_empty_undated(self, chat_id):
        text = "Нет задач без даты"
        message_id = await self.send_text(chat_id, text)
        return message_id

    async def send_task_card(self, chat_id: int, task: Task,
                             variant: TaskCardVariant):
        identity = format_task_identity(task)
        task_id = task.pk
        due_text = format_task_due_to(task)
        prompt = ("Ответь на это сообщение с датой и временем —\n"
                  "назначить или изменить срок.")
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Сделано",
                                 callback_data=f"done:{task_id}"),
            InlineKeyboardButton(text="🗑 Удалить",
                                 callback_data=f"delete:{task_id}")
        ]])

        cards = {
            TaskCardVariant.UNDATED:
            f"{identity}\nБез даты",
            TaskCardVariant.REMINDER:
            (f"⏰ Напоминание:\n{identity}\n📅 {due_text}"),
            TaskCardVariant.DIGEST:
            (f"🌅 На сегодня:\n{identity}\n📅 {due_text}"),
            TaskCardVariant.EVENING:
            (f"Задача не выполнена.\n{identity}\n📅 {due_text}"),
        }

        try:
            body = cards[variant]
        except KeyError as exc:
            raise ValueError(f"Unknown task card variant: {variant}") from exc

        message_id = await self.send_text_with_keyboard(
            chat_id,
            f"{body}\n\n{prompt}",
            keyboard,
        )

        return message_id
