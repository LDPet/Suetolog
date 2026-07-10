import pytest

from reminder.models import User
from reminder.services.users import UserService


@pytest.mark.django_db
def test_creates_user():
    service = UserService()

    user = service.get_or_create_user(chat_id=123, telegram_user_id=456)

    assert user.chat_id == 123
    assert user.telegram_user_id == 456
    assert User.objects.count() == 1


@pytest.mark.django_db
def test_returns_user():
    service = UserService()

    first_user = service.get_or_create_user(chat_id=123, telegram_user_id=456)
    second_user = service.get_or_create_user(chat_id=123, telegram_user_id=456)

    assert second_user.id == first_user.id
    assert second_user.chat_id == first_user.chat_id
    assert second_user.telegram_user_id == first_user.telegram_user_id


@pytest.mark.django_db
def test_does_not_create_duplicate():
    service = UserService()

    service.get_or_create_user(chat_id=123, telegram_user_id=456)
    service.get_or_create_user(chat_id=123, telegram_user_id=456)

    assert User.objects.count() == 1
