import datetime

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from reminder.models import Task
from reminder.repositories.tasks import TaskRepository

pytestmark = pytest.mark.django_db


class TestTaskModel:

    def test_create_task_with_user(self, user):
        task = Task.objects.create(user=user, title="Buy milk")
        assert task.user == user
        assert task.status == Task.Status.ACTIVE
        assert str(task)

    def test_invalid_status_raises(self, user):
        with pytest.raises(ValidationError):
            task = Task(user=user, title="Bad", status="invalid")
            task.full_clean()

    def test_user_tasks_related_name(self, user):
        Task.objects.create(user=user, title="One")
        Task.objects.create(user=user, title="Two")
        assert user.tasks.count() == 2


class TestTaskRepository:

    def test_create(self, user):
        due_to = timezone.make_aware(datetime.datetime(2026, 12, 1, 10, 0))
        task = TaskRepository.create(user,
                                     "Repo Task",
                                     due_to=due_to,
                                     due_to_has_time=True)
        assert task.title == "Repo Task"
        assert task.user_id == user.id
        assert task.due_to_has_time is True

    def test_get_by_id_found(self, task):
        found = TaskRepository.get_by_id(task.id)
        assert found == task

    def test_update_due_to_saves_time_precision(self, task):
        due_to = timezone.now() + datetime.timedelta(days=2)

        updated = TaskRepository.update_due_to(
            task,
            due_to,
            due_to_has_time=False,
        )

        task.refresh_from_db()
        assert updated.due_to == due_to
        assert task.due_to == due_to
        assert task.due_to_has_time is False

    def test_get_by_id_not_found(self):
        assert TaskRepository.get_by_id(99999) is None

    def test_get_active_by_user_excludes_deleted(self, user):
        t1 = TaskRepository.create(user, "Active")
        t2 = TaskRepository.create(user, "Deleted")
        t2.status = Task.Status.DELETED
        t2.save()
        active = TaskRepository.get_active_by_user(user)
        assert len(active) == 1
        assert active[0] == t1
