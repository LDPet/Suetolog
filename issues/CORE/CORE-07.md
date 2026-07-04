# CORE-07: `VoiceTaskCreationService`

Тег: CORE-07

Эпик: EPIC-02. Сервисный слой

Результат: download → STT → `get_parser()` → `TaskService.create_from_parsed()`; `VoiceTaskResult`; unit-тесты с моками; без Telegram-отправки

Зависимости: TG-01, AI-06, CORE-03

Для prod: AI-02 (STT), AI-03 (`PARSER_BACKEND=yandex`).

## Технологии и контекст

Голосовой MVP — **синхронный pipeline** (без Celery для AI):

```
Telegram voice → TG-01 download → AI-02 STT → AI-06/03 parser → CORE-03 create → ответ TG-09
```

- **CORE-07** — оркестратор: знает порядок шагов, ошибки, cleanup temp-файла. Не знает про тексты сообщений в Telegram.
- **STT** (SpeechKit) и **parser** (mock / YandexGPT) — injectable зависимости; в тестах всегда mock.
- **`VoiceTaskResult`** — success + Task или error_code для TG-09 → `send_error`.
- **Идempotency:** при любой ошибке после начала — **нет** частичной Task в БД.
- Документация: `tz/VOICE_PIPELINES.md` § Telegram voice input, `tz/ARCHITECTURE.md`.

**Demo без Yandex:** `PARSER_BACKEND=mock`, STT — stub до AI-02.

## Границы тикета

**Входит:** оркестрация voice pipeline.

**Не входит:** Telegram send (TG-09), реализация STT/parser (AI-*), бизнес-логика Task (CORE-03).

> Бывший AI-05. **Не импортировать** `TelegramSender` / handlers.

## Что сделать

1. Сервис: user + voice → `VoiceTaskResult` (структуру спроектируй).
2. Цепочка по VOICE_PIPELINES: лимиты → download → STT → parser → `TaskService.create_from_parsed()`.
3. Temp-файл — `finally`.
4. Ошибка на любом шаге — без partial Task.
5. Error codes как в TG-01: `voice_too_long`, `voice_too_large`, `stt_empty`, `parser_failed`, `date_in_past`, `generic`.
6. Unit-тесты: mock STT + mock-parser.

## Связанные use cases

| UC | Связь |
| --- | --- |
| [UC-02](tz/use_cases.md) | Полный voice flow |
| [UC-04](tz/use_cases.md) | Задача без даты |
| UC-02 § Исключения | Лимиты, пустой STT, parser, past date |

E2E в чате — **TG-09**.

## Примеры для проверки в чате

*(после TG-09)*

| # | Голосовое | Ожидание в чате | БД |
| --- | --- | --- | --- |
| 1 | «Напомни завтра в 15:00 позвонить врачу» | «Слушаю…» → подтверждение с датой | Task + Reminder + `TaskEvent(created)` |
| 2 | «Купить молоко без даты» | Подтверждение без даты | Task, нет Reminder |
| 3 | «Отправить отчёт с добавлением графиков» | Задача без даты (если дата не названа) | `due_to=null` |
| 4 | «Каждый понедельник в 9 проверить финансы» | Задача; repeat поля — если parser вернул | `repeat_type` в Task |
| 5 | «Э-э-э…» / неразборчиво | «Не расслышал…» или parser error | Нет Task |
| 6 | Длинная речь > лимита | «Голосовое слишком длинное…» | Нет Task |
| 7 | «Напомни вчера сделать X» | Ошибка про дату | Нет Task |
| 8 | Два voice подряд быстро | Две отдельные Task (если оба успешны) | 2× `TaskEvent(created)` |

## Кривые кейсы — учесть

| Ситуация | Ожидание |
| --- | --- |
| Download OK, STT упал | Task **не** создана, temp-файл удалён |
| STT OK, parser упал | Task **не** создана |
| Parser OK, CORE-03 упал (БД) | Task **не** создана, пользователю не «успех» |
| Пустой transcript | `stt_empty` |
| Файл слишком большой после download | `voice_too_large` — STT/parser не вызывать |
| `PARSER_BACKEND=mock`, STT stub | Demo без Yandex |
| Двойная отправка одного voice | Две задачи — нормально для MVP (идempotency — post-MVP) |

## Acceptance criteria

- Voice-логика в сервисе; TG-09 — wiring
- Happy path + минимум 3 error codes в тестах
- Нет Telegram API в сервисе

## Unit-тесты (обязательно в этом тикете)

- [ ] Happy path: mock STT + mock-parser → Task в БД
- [ ] Минимум 3 error codes: `stt_empty`, `parser_failed`, `date_in_past` (или `voice_too_long`)
- [ ] Ошибка на любом шаге — partial Task не создаётся
- [ ] Temp-файл удаляется в `finally`

## Ручная проверка разработчиком

- [ ] Unit-тесты с моками
- [ ] UC-02: строки 1–2, 7–8 из таблицы
- [ ] UC-04: строка 2
- [ ] Кривой кейс: строка 5 или 6
- [ ] Сервис не импортирует Telegram-слой
