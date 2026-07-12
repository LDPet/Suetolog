from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from asgiref.sync import sync_to_async
from django.db.models import TextChoices

from errors import error_messages
from reminder.models import Task, TaskEvent
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
            message_id = await self._send_task_card_with_event(
                chat_id, task, TaskCardVariant.UNDATED)

        return message_id

    async def send_reminder(self, chat_id, task):
        return await self.send_task_card(chat_id, task,
                                         TaskCardVariant.REMINDER)

    async def send_evening_question(self, chat_id, task):
        return await self._send_task_card_with_event(chat_id, task,
                                                     TaskCardVariant.EVENING)

    async def send_digest(self, chat_id, tasks):
        message_id = None
        for task in tasks:
            message_id = await self._send_task_card_with_event(
                chat_id, task, TaskCardVariant.DIGEST)

        return message_id

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

    async def send_date_confirmed(self, chat_id, task):
        text = f"Дата назначена: {task.title} - {task.due_to}"
        message_id = await self.send_text(chat_id, text)
        return message_id

    async def send_deleted(self, chat_id, task):
        text = f"Задача {task.title} удалена"
        message_id = await self.send_text(chat_id, text)
        return message_id

    async def send_task_completed(self, chat_id, task):
        text = f"Задача «{task.title}» выполнена"
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
        title = task.title
        task_id = task.pk
        due_to = task.due_to
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
            f"📋 {title}\nБез даты",
            TaskCardVariant.REMINDER:
            (f"⏰ Напоминание:\n📋 {title}\n📅 {due_to}"),
            TaskCardVariant.DIGEST: (f"🌅 На сегодня:\n📋 {title}\n📅 {due_to}"),
            TaskCardVariant.EVENING:
            (f"Задача «{title}» не выполнена.\n📅 {due_to}"),
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
