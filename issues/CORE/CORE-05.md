# CORE-05: Реализовать `ReminderService`

Тег: CORE-05

Эпик: EPIC-02. Сервисный слой

Результат: due reminders, sent_time/message_id, lookup по реакции; unit-тесты в этом же тикете

Зависимости: DB-03, CORE-03

## Зачем этот тикет

**Мост между Task и фоновыми рассылками.** BG-01 вызывает ReminderService для due reminders; TG-08 — для поиска reminder по `message_id` реакции.

## Технологии и контекст

```
Celery send_due_reminders → ReminderService.get_due / mark_sent → TaskEvent(reminder_sent)
Reaction handler → ReminderService.find_by_message → TaskService.mark_done/cancelled
```

- **ReminderService** — выборка и фиксация отправки; **не** вызывает Telegram (это BG + TelegramSender).
- `TaskEvent(reminder_sent)` — пишет сервис (или mailing-обёртка, вызываемая из BG через CORE-05).
- Документация: `tz/MAILING_PIPELINES.md`, `tz/use_cases.md` UC-07, UC-08.

## Границы тикета

**Входит:** create_for_task, get_due_reminders(now), mark_sent(reminder, message_id), find_by_message(chat_id, message_id), отмена future reminders при done/cancelled.

**Не входит:** Celery config (BG-01), Telegram send, утренний дайджест (BG-05).

## Что реализуется

1. `reminder/services/reminders.py` — `ReminderService`.
2. `get_due_reminders(now)` — active task, `sent_time IS NULL`, `reminder_time <= now`, batch limit.
3. `mark_sent` — `sent_time`, `message_id`, `TaskEvent(reminder_sent)`.
4. `find_by_message` — для TG-08.
5. Unit-тесты: due selection; skip sent; find_by_message; exclude done/cancelled/deleted tasks.

## Связанные use cases

| UC | Связь |
| --- | --- |
| [UC-07](tz/use_cases.md) | due reminder |
| [UC-08](tz/use_cases.md) | find_by_message + reaction |

## Кривые кейсы

| Ситуация | Ожидание |
| --- | --- |
| mark_sent повторно | идемпотентность / skip |
| task deleted после выборки due | не отправлять |
| reminder без message_id | find_by_message → None |

## Acceptance criteria

- BG-01 может вызывать get_due + mark_sent без ORM в Celery task
- TG-08 находит reminder по chat_id + message_id
- Unit-тесты проходят

## Unit-тесты (обязательно в этом тикете)

- [ ] Due reminder попадает в выборку
- [ ] С `sent_time` — не попадает
- [ ] mark_sent сохраняет message_id + event
- [ ] find_by_message happy path
