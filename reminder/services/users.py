from reminder.repositories.users import UserRepository


class UserService:

    def get_or_create_user(self, chat_id, telegram_user_id):
        user = UserRepository.get_by_chat_id(chat_id)

        if user is not None:
            return user

        return UserRepository.create(chat_id=chat_id,
                                     telegram_user_id=telegram_user_id)
