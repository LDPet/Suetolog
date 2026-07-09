import pytest

from reminder.models import Task, User


@pytest.fixture
def user(db) -> User:
    return User.objects.create(chat_id=123456789, telegram_user_id=987654321)


@pytest.fixture
def task(db, user) -> Task:
    return Task.objects.create(
        user=user,
        title="Test Task",
        description="Some description",
        due_to=None,
        status=Task.Status.ACTIVE,
    )
