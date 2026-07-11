from django.db import migrations, models


def mark_existing_tasks_as_timed(apps, schema_editor):
    """Сохранить прежнее правило: существующие сроки содержат точное время."""
    Task = apps.get_model("reminder", "Task")
    Task.objects.update(due_to_has_time=True)


class Migration(migrations.Migration):

    dependencies = [
        ("reminder", "0006_taskevent"),
    ]

    operations = [
        migrations.AddField(
            model_name="task",
            name="due_to_has_time",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(
            mark_existing_tasks_as_timed,
            migrations.RunPython.noop,
        ),
    ]
