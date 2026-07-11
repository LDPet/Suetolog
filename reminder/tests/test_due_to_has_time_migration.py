from datetime import timedelta

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone


@pytest.mark.django_db(transaction=True)
def test_existing_tasks_are_migrated_as_having_exact_time():
    executor = MigrationExecutor(connection)
    executor.migrate([("reminder", "0006_taskevent")])
    old_apps = executor.loader.project_state([("reminder", "0006_taskevent")
                                              ]).apps

    User = old_apps.get_model("reminder", "User")
    Task = old_apps.get_model("reminder", "Task")
    user = User.objects.create(chat_id=700001, telegram_user_id=700002)
    task = Task.objects.create(
        user=user,
        title="Existing task",
        due_to=timezone.now() + timedelta(days=1),
    )

    executor = MigrationExecutor(connection)
    executor.migrate([("reminder", "0007_task_due_to_has_time")])
    new_apps = executor.loader.project_state([
        ("reminder", "0007_task_due_to_has_time")
    ]).apps
    MigratedTask = new_apps.get_model("reminder", "Task")

    assert MigratedTask.objects.get(id=task.id).due_to_has_time is True
