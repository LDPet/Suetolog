import asyncio

from django.core.management.base import BaseCommand

from reminder.bot.dispatcher import start_bot


class Command(BaseCommand):

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Запуск бота...'))
        asyncio.run(start_bot())