from reminder.models import User

class UserRepository:
    @staticmethod
    def create(chat_id: int, telegram_user_id: int) -> User:
        return User.objects.create(
            chat_id=chat_id,
            telegram_user_id=telegram_user_id
        )

    @staticmethod
    def get_by_chat_id(chat_id: int) -> User | None:
        try:
            return User.objects.get(chat_id=chat_id)
        except User.DoesNotExist:
            return None

    @staticmethod
    def get_by_telegram_user_id(telegram_user_id: int) -> User | None:
        try:
            return User.objects.get(telegram_user_id=telegram_user_id)
        except User.DoesNotExist:
            return None
