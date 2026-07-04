# CORE-02: DTO `ParsedTaskInput` и контракты сервисов

Тег: CORE-02

Эпик: EPIC-02. Сервисный слой

Результат: Единый контракт voice/text → сервисы; unit-тесты валидации DTO

Зависимости: APP-01

## Зачем этот тикет

**Волна 0.** Контракт между AI-parser (AI-06/03), `TaskService` (CORE-03) и voice pipeline (CORE-07). Без общего DTO каждый слой изобретает свои поля.

## Технологии и контекст

```
STT transcript / text → ParserService → ParsedTaskInput → TaskService.create_from_parsed()
```

- **ParsedTaskInput** — dataclass / pydantic / typed dict (на выбор команды).
- Поля по `tz/VOICE_PIPELINES.md` и `tz/tables.md`: `title`, `description`, `due_to`, `repeat_type`, `repeat_interval`, `raw_text`.
- **AI-06** и **CORE-07** зависят от этого тикета.

## Границы тикета

**Входит:** DTO, базовая валидация (обязательный `title`, типы полей), unit-тесты DTO.

**Не входит:** HTTP к Yandex, создание Task, mock-parser (AI-06).

## Что реализуется

1. `reminder/services/dto.py` (или `schemas.py`) — `ParsedTaskInput`.
2. Валидация: пустой `title` → ошибка; `due_to` optional; `repeat_*` optional.
3. Документировать контракт в docstring — что ожидает `TaskService.create_from_parsed()`.
4. Unit-тесты: валидный объект; пустой title; `due_to=None` (задача без даты).

## Связанные use cases

| UC | Поля DTO |
| --- | --- |
| [UC-02](tz/use_cases.md) | title + due_to из voice |
| [UC-04](tz/use_cases.md) | `due_to=null` |

## Acceptance criteria

- Один контракт для voice и (future) text
- AI-06 может импортировать DTO без циклических зависимостей
- Unit-тесты DTO проходят

## Unit-тесты (обязательно в этом тикете)

- [ ] Валидный ParsedTaskInput
- [ ] Без title → ValidationError
- [ ] `due_to=None` допустим
