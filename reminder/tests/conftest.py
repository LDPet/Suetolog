import pytest
from reminder.models import User

@pytest.fixture
def user(db) -> User:
    return User.objects.create(
        chat_id=123456789,
        telegram_user_id=987654321
    )
