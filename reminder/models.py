from django.db import models

class User(models.Model):
    # django автоматически добавляет id = BigAutoFeild
    chat_id = models.BigIntegerField(unique=True)
    telegram_user_id = models.BigIntegerField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"User(chat={self.chat_id}, tg={self.telegram_user_id})"
