from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('reminder', '0007_task_due_to_has_time'),
    ]

    operations = [
        migrations.AlterField(
            model_name='taskevent',
            name='event_type',
            field=models.CharField(
                choices=[
                    ('created', 'Создана'),
                    ('reminder_sent', 'Напоминание отправлено'),
                    ('undated_card_sent', 'Карточка без даты'),
                    ('evening_question_sent', 'Вечерний вопрос'),
                    ('completed', 'Выполнена'),
                    ('cancelled', 'Отменена'),
                    ('rescheduled', 'Перенесена'),
                    ('date_set', 'Дата установлена'),
                    ('deleted', 'Удалена'),
                    ('digest_sent', 'Дайджест отправлен'),
                    ('digest_card_sent', 'Карточка из дайджеста отправлена'),
                ],
                max_length=30,
            ),
        ),
    ]
