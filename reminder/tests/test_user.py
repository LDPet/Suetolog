import pytest
from django.db import IntegrityError, transaction

from reminder.models import User
from reminder.repositories.users import UserRepository

pytestmark = pytest.mark.django_db


class TestUserModel:

    def test_create_user(self):
        u = User.objects.create(chat_id=1, telegram_user_id=100)
        assert u.chat_id == 1
        assert u.telegram_user_id == 100
        assert u.created_at is not None

    def test_duplicate_chat_id_raises(self, user):
        with pytest.raises(IntegrityError):
            User.objects.create(chat_id=user.chat_id, telegram_user_id=999)

    def test_transaction_rollback(self):
        try:
            with transaction.atomic():
                User.objects.create(chat_id=2, telegram_user_id=200)
                raise ValueError("Trigger rollback")
        except ValueError:
            pass
        assert not User.objects.filter(chat_id=2).exists()


class TestUserRepository:

    def test_create(self):
        u = UserRepository.create(chat_id=10, telegram_user_id=1000)
        assert u.chat_id == 10
        assert User.objects.filter(chat_id=10).exists()

    def test_get_by_chat_id_found(self, user):
        u = UserRepository.get_by_chat_id(user.chat_id)
        assert u == user

    def test_get_by_chat_id_not_found(self):
        assert UserRepository.get_by_chat_id(999999) is None

    def test_get_by_telegram_user_id_found(self, user):
        u = UserRepository.get_by_telegram_user_id(user.telegram_user_id)
        assert u == user

    def test_get_by_telegram_user_id_not_found(self):
        assert UserRepository.get_by_telegram_user_id(999999) is None
