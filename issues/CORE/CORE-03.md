# CORE-03: Реализовать `TaskService` (merged CORE-03/04)

Тег: CORE-03

Эпик: EPIC-02. Сервисный слой

Поглощает: CORE-04

Результат: Полный `TaskService`: создание из parser + все операции над задачей; `TaskEvent` на каждое действие; unit-тесты в этом же тикете

Зависимости: DB-02..DB-04, CORE-02

## Зачем этот тикет

**Единая точка бизнес-логики задач** (`tz/ARCHITECTURE.md`). Создание и все операции — в одном сервисе и одном PR, без разрыва между «создал» и «удалил/перенёс».

> Бывший CORE-04 (операции списков/статусов) — **не отдельный тикет**.

## Технологии и контекст

```
ParsedTaskInput → TaskService.create_from_parsed() → Task + Reminder? + TaskEvent(created)
Handler/Celery  → TaskService.* → TaskEvent + статус Task
```

- **TaskService** — единственный класс для правил вокруг Task (не дробить на TaskCreationService + микросервисы).
- **TaskEvent** пишет **сервис**, не handler.
- Транзакции: create / delete / set_date / done / cancelled — atomic с событием.
- Документация: `tz/ARCHITECTURE.md`, `tz/use_cases.md`, `tz/tables.md`.

## Границы тикета

**Входит:**

- `create_from_parsed(user, parsed)` — Task + optional Reminder + `TaskEvent(created)`; дата в прошлом → ошибка; без даты → без Reminder.
- `list_undated(user)`, `list_for_day(user, date)` — только `active`.
- `set_due_date(user, task_id, due_to)`, `reschedule(...)`.
- `delete_task(user, task_id)` → `deleted` + `TaskEvent(deleted)`.
- `mark_done(...)`, `mark_cancelled(...)` — по task_id или reminder (для TG-08).
- Проверка владельца и `active`-статус на всех мутациях.
- Unit-тесты всех методов.

**Не входит:** выбор due reminders для Celery (CORE-05), Telegram send, parser/STT, `undated_card_sent` / `evening_question_sent` (это handlers + CORE-05/BG с `message_id`).

## Правило: `TaskEvent`

| Метод / действие | `event_type` |
| --- | --- |
| `create_from_parsed` | `created` |
| `set_due_date` (первая дата) | `date_set` |
| `reschedule` | `rescheduled` |
| `delete_task` | `deleted` |
| `mark_done` | `completed` |
| `mark_cancelled` | `cancelled` |

События с `message_id` (`undated_card_sent`, `evening_question_sent`, `reminder_sent`, `digest_sent`) — в TG/BG тикетах, но статус Task меняет только TaskService.

## Что реализуется

1. `reminder/services/tasks.py` — `TaskService`.
2. Repositories из DB-02..04 — без ORM в handlers.
3. При create: одна `@transaction.atomic`.
4. При set_date/reschedule: отклонять `due_to` в прошлом.
5. При done/cancelled: не трогать уже финальные задачи; идемпотентность повторных вызовов.
6. Unit-тесты (минимум):

| Сценарий | Ожидание |
| --- | --- |
| create с future due_to | Task + Reminder + `created` |
| create без даты | Task, нет Reminder |
| create, дата в прошлом | ошибка, нет Task |
| list_undated | только active, due_to IS NULL |
| delete | `deleted` + event |
| set_due_date | `date_set`, Reminder создан/обновлён |
| mark_done / mark_cancelled | статус + event; повтор игнорируется |
| чужой task_id | PermissionError / NotFound |

## Связанные use cases

| UC | Методы |
| --- | --- |
| [UC-02](tz/use_cases.md) | `create_from_parsed` |
| [UC-04](tz/use_cases.md) | create без Reminder |
| [UC-05](tz/use_cases.md) | `list_undated`, `delete_task` |
| [UC-06](tz/use_cases.md) | `set_due_date` / `reschedule` |
| [UC-08](tz/use_cases.md) | `mark_done`, `mark_cancelled` |

## Кривые кейсы

| Ситуация | Ожидание |
| --- | --- |
| delete уже deleted | ошибка или no-op — зафиксировать в тесте |
| set_date на done task | отклонить |
| reschedule с датой в прошлом | отклонить |
| create упал на Reminder | rollback всей транзакции |

## Acceptance criteria

- Один `TaskService` с create + operations (ARCHITECTURE.md)
- Каждая мутация → `TaskEvent` в той же транзакции
- Проверка owner + active
- Unit-тесты проходят без Telegram/Yandex
- Нет импортов bot/celery

## Unit-тесты (обязательно в этом тикете)

- [ ] `pytest` по TaskService — все строки таблицы сценариев выше
- [ ] Transaction rollback при ошибке create
