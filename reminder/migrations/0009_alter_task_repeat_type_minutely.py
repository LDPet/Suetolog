from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("reminder", "0008_alter_taskevent_event_type_digest_card_sent"),
    ]

    operations = [
        migrations.AlterField(
            model_name="task",
            name="repeat_type",
            field=models.CharField(
                blank=True,
                choices=[
                    ("minutely", "Каждую минуту"),
                    ("hourly", "Каждый час"),
                    ("daily", "Ежедневно"),
                    ("weekly", "Еженедельно"),
                ],
                default="daily",
                max_length=20,
                null=True,
            ),
        ),
    ]
