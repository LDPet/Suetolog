# CORE-01: Реализовать `UserService`

Тег: CORE-01

Эпик: EPIC-02. Сервисный слой

Результат: `get_or_create_user(chat_id)` идемпотентен; unit-тесты в этом же тикете

Зависимости: DB-01

## Зачем этот тикет

**Первый сервисный класс.** Все handlers и фоновые jobs идентифицируют пользователя по `chat_id`. Без идемпотентного `UserService` повторный `/start` или voice создаст дубли в БД.

## Технологии и контекст

```
Telegram update (chat_id) → handler → UserService → UserRepository → PostgreSQL
```

- **UserService** — только бизнес-правила вокруг пользователя; без Telegram API.
- **UserRepository** — из DB-01; сервис не пишет raw SQL.
- Документация: `tz/ARCHITECTURE.md` § Сервисный слой, [UC-01](tz/use_cases.md).

## Границы тикета

**Входит:** `UserService.get_or_create_user(chat_id)`, unit-тесты.

**Не входит:** Task/Reminder (CORE-03/05), Telegram handlers (TG-03), admin.

## Что реализуется

1. `reminder/services/users.py` — класс `UserService`.
2. `get_or_create_user(chat_id)`:
   - если User есть — вернуть существующего;
   - если нет — создать с `chat_id` / `telegram_user_id` по контракту DB-01;
   - повторный вызов с тем же `chat_id` **не** создаёт вторую запись.
3. Unit-тесты (`pytest`, Django test DB или fixtures):
   - первый вызов → User создан;
   - второй вызов → тот же id, count=1;
   - параллельные вызовы (опционально) — без дублей.

## Связанные use cases

| UC | Связь |
| --- | --- |
| [UC-01](tz/use_cases.md) | `/start` → get_or_create |
| UC-02 | Voice handler запрашивает user перед созданием задачи |

## Кривые кейсы

| Ситуация | Ожидание |
| --- | --- |
| Два быстрых `/start` подряд | Один User |
| `chat_id` отсутствует в update | Ошибка до сервиса (handler) |

## Acceptance criteria

- `get_or_create_user` идемпотентен
- Сервис не импортирует `reminder.bot.*` и Celery
- Unit-тесты проходят: `pytest reminder/tests/test_user_service.py` (путь на усмотрение)
- Секреты не в коде/логах

## Unit-тесты (обязательно в этом тикете)

- [ ] Happy path: create + get_or_create returns same user
- [ ] Нет дублей при повторном вызове
