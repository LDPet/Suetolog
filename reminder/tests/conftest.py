from datetime import timedelta

import pytest
from django.utils import timezone

from reminder.models import Reminder, Task, User


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


@pytest.fixture
def reminder(db, task) -> Reminder:
    future_time = timezone.now() + timedelta(hours=1)
    return Reminder.objects.create(
        task=task,
        reminder_time=future_time,
        message_id=12345,
    )
