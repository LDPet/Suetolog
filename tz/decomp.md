# Декомпозиция проекта «Голосовой напоминальщик»

Документ предназначен для нарезки задач студентам в Jira-like трекере. Основа: `README.md`, `tz/tz.md`, `tz/ARCHITECTURE.md`, `tz/use_cases.md`, `tz/tables.md`, `tz/VOICE_PIPELINES.md`, `tz/MAILING_PIPELINES.md` и PDF с требованиями стажировки.

## 1. Цель и границы MVP

Нужно реализовать Telegram-бота на `aiogram` с Django backend. Пользователь отправляет **голосовое** сообщение, система разбирает русскую фразу в задачу, сохраняет её в PostgreSQL, отправляет напоминания через Celery и учитывает реакции пользователя.

В MVP входят:

- создание задачи **голосом** (основной сценарий ТЗ);
- распознавание короткого Telegram voice через Yandex SpeechKit;
- разбор через YandexGPT / Foundation Models (`PARSER_BACKEND=yandex`; для dev — mock, см. AI-06);
- хранение пользователей, задач, напоминаний и событий в PostgreSQL;
- команда `/start`;
- команда `/undated` или текст «без даты»;
- назначение даты (Reply на сообщение бота), удаление задачи и перенос;
- утренний дайджест в 09:00;
- точечные напоминания по расписанию;
- реакции ✅ и ❌ на напоминание;
- вечерняя проверка задач без реакции;
- сквозная ручная проверка use-cases (TG-10);
- базовые тесты, README, `.env.example`, Docker Compose.

Post-MVP и follow-up (раздел 9):

- текстовый ввод задачи как альтернатива голосу (усложнение ТЗ, TG-F03);
- полный цикл повторяющихся задач;
- недельная статистика `/stats`;
- расширенная пагинация списков;
- автотесты handlers (TG-F02), AI pipeline (AI-F01);
- промышленная delivery-модель, метрики и мониторинг.

**Правила EPIC-03:**

- Каждое действие с задачей в Telegram → `TaskEvent` (пишет сервисный слой, не handler).
- В каждом TG-тикете — **ручная проверка разработчиком** перед закрытием (часть тикета, не отдельная QA-задача).
- **TG-10** — обязательный сквозной E2E в конце, после сборки всей системы.

**Правила EPIC-02:**

- Unit-тесты пишутся **в том же тикете**, где реализуется сервис — отдельный CORE-06 не создаётся.
- Перед закрытием тикета: `pytest` по модулю сервиса проходит локально.
- Сервисы не импортируют Telegram handlers и Celery tasks.

**Правила EPIC-05:**

- После реализации **каждого** фонового скрипта (BG-01, BG-05, BG-06) разработчик **обязан прогнать job вручную** (celery call / beat / тестовые данные в БД) и зафиксировать результат перед закрытием тикета.
- Отдельные BG-QA-* не создаются — самопроверка внутри BG-тикетов, как в EPIC-03.

## 2. Предлагаемые потоки работ

| Поток | Зона ответственности | Возможный ответственный |
| --- | --- | --- |
| App / Core | Django-проект, настройки, сервисный слой, CORE-07 | Женя |
| DB / Models | PostgreSQL, модели, миграции, admin, TaskEvent | Даниил |
| Telegram | aiogram, handlers, sender, callbacks, реакции, E2E | Миша |
| AI pipeline | SpeechKit, YandexGPT parser, mock-parser (AI-06) | Руслан |
| Background | Redis, Celery, Beat, рассылки | Макс |

Имена можно заменить на фактических студентов. Telegram handlers, Celery tasks и внешние API-клиенты остаются тонкими; бизнес-логика — в сервисах.

**Слияния тикетов (не создавать отдельно):** TG-02+AI-01 → TG-01; TG-05+TG-06 → TG-05; AI-05 → CORE-07+TG-09; TG-QA-* → самопроверка в тикетах + TG-10; BG-01+BG-02+BG-03 → BG-01; BG-QA-* → самопроверка в BG-01/05/06; CORE-03+CORE-04 → CORE-03; CORE-06 → unit-тесты inline в CORE-01..05, CORE-07; QA-01 → APP-01; QA-03 → TG-10 + DOC-01.

## 3. Эпики и задачи

### EPIC-00. Проектная основа и окружение

| ID | Задача | Волна | Оценка | Зависимости | Результат / Acceptance criteria |
| --- | --- | ---: | ---: | --- | --- |
| APP-01 | Каркас Django-проекта и dev-окружение | 0 | 5–7ч | нет | `manage.py`, `config/`, `reminder/`; pipenv + `requirements.txt`; `Makefile`; `.env.example`, `.gitignore`; pytest scaffold; рабочий `make test` |
| APP-04 | Поднять `docker-compose.yml` для PostgreSQL и Redis | 1 | 3ч | APP-01 | `docker compose up` поднимает БД и Redis; данные не теряются при рестарте |

### EPIC-01. Модель данных и PostgreSQL

| ID | Задача | Волна | Оценка | Зависимости | Результат / Acceptance criteria |
| --- | --- | ---: | ---: | --- | --- |
| DB-01 | Окружение PostgreSQL + модель User | 2 | 5–6ч | APP-01, APP-04 | User: `chat_id`, `telegram_user_id`, UserRepository, фикстура, тесты |
| DB-02 | Модель `Task` | 3 | 4ч | DB-01 | Поля и статусы по ТЗ; индексы; TaskRepository |
| DB-03 | Модель `Reminder` | 4 | 4ч | DB-02 | Поля по ТЗ; ReminderRepository |
| DB-04 | Модель `TaskEvent` + atomic bundle | 5 | 4–5ч | DB-03 | `TaskEvent` с `message_id` (nullable); `find_by_message_id()`; event types: `created`, `reminder_sent`, `undated_card_sent`, `evening_question_sent`, `date_set`, `rescheduled`, `completed`, `cancelled`, `deleted`, `digest_sent`; transaction-тесты |

### EPIC-02. Сервисный слой

| ID | Задача | Волна | Оценка | Зависимости | Результат / Acceptance criteria |
| --- | --- | ---: | ---: | --- | --- |
| CORE-01 | Реализовать `UserService` | 3 | 2ч | DB-01 | `get_or_create_user(chat_id)` идемпотентен; unit-тесты в тикете |
| CORE-02 | DTO `ParsedTaskInput` и контракты сервисов | 1 | 2ч | APP-01 | Единый контракт для voice: `title`, `due_to`, `repeat_type`, `raw_text`; unit-тесты DTO |
| CORE-03 | `TaskService` (merged CORE-03/04) | 6 | 10–11ч | DB-02..04, CORE-02 | create_from_parsed + все операции; `TaskEvent` на каждое действие; проверка владельца; unit-тесты в тикете |
| CORE-05 | `ReminderService` | 7 | 5ч | DB-03, CORE-03 | due reminders, `sent_time`, `message_id`, `find_by_message` для реакций; unit-тесты в тикете |
| CORE-07 | `VoiceTaskCreationService` (бывш. AI-05) | 7 | 5–6ч | TG-01, AI-06, CORE-03 | download → STT → `get_parser()` → create; `VoiceTaskResult`; unit-тесты с моками; без Telegram-отправки; **AI-02/AI-03 не блокируют** (mock-first, prod — по готовности) |
| ~~CORE-04~~ | — | — | — | **Merged в CORE-03** (операции TaskService) |
| ~~CORE-06~~ | — | — | — | **→ inline unit-тесты** в CORE-01..05, CORE-07 |

### EPIC-03. Telegram-бот и пользовательские сценарии

Задача: тонкий Telegram-интерфейс. Handlers вызывают сервисы; `TaskEvent` пишет сервисный слой.

| ID | Задача | Волна | Оценка | Зависимости | Результат / Acceptance criteria |
| --- | --- | ---: | ---: | --- | --- |
| TG-01 | aiogram + `TelegramSender` + скачивание voice | 1 | 8–10ч | APP-01 | Бот в BotFather; `runbot`; `TelegramSender` (все типы сообщений, возврат `message_id`); `TelegramFileDownloader`; лимиты voice; temp-файл cleanup. **Ручная проверка:** runbot; voice скачивается; длинный voice отклоняется |
| TG-03 | `/start` | 4 | 2ч | TG-01, CORE-01 | User get_or_create; приветствие. **Ручная проверка:** первый/повторный `/start`, один User в БД |
| TG-05 | `/undated` + inline-кнопки (merged TG-05/06) | 7 | 7–8ч | TG-01, CORE-03 | Список всех задач без даты; кнопки «Назначить дату»/«Удалить»; `TaskEvent(undated_card_sent, message_id)`; удаление → `deleted` + `TaskEvent(deleted)`. **Ручная проверка:** пустой список; карточки; удаление; кнопка назначения даты |
| TG-07 | Ввод даты через Reply + `TaskEvent` lookup | 8 | 6ч | TG-05, AI-04, CORE-03, DB-04 | Reply на карточку или вечерний вопрос → `find_by_message_id` → `date_set`/`rescheduled`; без Reply — подсказка. **Ручная проверка:** reply с датой; дата в прошлом; рестарт бота |
| TG-08 | Реакции ✅ и ❌ | 8 | 5ч | TG-01, CORE-03, CORE-05 | По `Reminder.message_id`; `completed`/`cancelled` + `TaskEvent`; повторные игнорируются. **Ручная проверка:** ✅/❌ на reminder, сверка с БД |
| TG-09 | Тонкий voice handler | 8 | 2ч | TG-01, CORE-07 | Только wiring: user → processing → CORE-07 → confirm/error. **Ручная проверка:** voice → задача в БД; mock-parser без Yandex |
| TG-10 | Сквозная проверка use-cases MVP (**обязательный**) | 10 | 3–4ч | TG-03..09, CORE-07, BG-01, BG-06 | Полный стек; чеклист UC-01..UC-12 (MVP); отчёт в трекере = финальный E2E-артефакт; блокирует DOC-03 |

### EPIC-04. AI и голосовой пайплайн

| ID | Задача | Волна | Оценка | Зависимости | Результат / Acceptance criteria |
| --- | --- | ---: | ---: | --- | --- |
| AI-06 | mock-parser | 2 | 3ч | APP-01, CORE-02 | `PARSER_BACKEND=mock\|yandex`; `get_parser()`; default mock в `.env.example`; до AI-03 |
| AI-02 | Клиент Yandex SpeechKit | 2 | 5ч | TG-01 | STT `oggopus`, `ru-RU`; пустой transcript = ошибка; ключи не в логах |
| AI-03 | YandexGPT parser задачи | 3 | 7ч | APP-01, CORE-02, AI-06 | `ParserService.parse_task()` → `ParsedTaskInput`; JSON Schema; дата в прошлом отклоняется |
| AI-04 | Parser даты для назначения/переноса | 4 | 4ч | AI-03 | Свободный русский ввод → datetime; для TG-07 |
| ~~AI-01~~ | — | — | — | **Merged в TG-01** (скачивание voice) |
| ~~AI-05~~ | — | — | — | **→ CORE-07 + TG-09** |

### EPIC-05. Celery, Redis и фоновые рассылки

Задача: тонкий Celery-слой. Tasks вызывают сервисы рассылок; `TaskEvent` пишет сервисный слой.

| ID | Задача | Волна | Оценка | Зависимости | Результат / Acceptance criteria |
| --- | --- | ---: | ---: | --- | --- |
| BG-01 | Celery + Beat + `send_due_reminders` (merged BG-01/02/03) | 8 | 12–14ч | APP-01, APP-04, CORE-05, TG-01 | `config/celery.py`; worker и beat; Beat schedule; due reminders пачкой; `sent_time`, `message_id`; `TaskEvent(reminder_sent)`; skip если `sent_time` уже есть. **Ручная проверка:** reminder в Telegram, повтор job без дубля |
| BG-05 | Утренний дайджест | 9 | 5ч | CORE-03, TG-01, BG-01 | 09:00; пустые не отправляются; без дубля за день. **Ручная проверка:** trigger job, сверка списка и БД |
| BG-06 | Вечерняя проверка и вопрос о переносе | 9 | 6ч | CORE-03, CORE-05, TG-07, BG-01 | 20:00; `TaskEvent(evening_question_sent, message_id)`; Reply → перенос (TG-07). **Ручная проверка:** вопрос без реакции; reply с новой датой |
| ~~BG-02~~ | — | — | — | **Merged в BG-01** (расписания Beat) |
| ~~BG-03~~ | — | — | — | **Merged в BG-01** (`send_due_reminders`) |
| ~~BG-04~~ | — | — | — | **→ follow-up BG-F01** |
| ~~BG-07~~ | — | — | — | **→ follow-up BG-F02** |
| ~~BG-08~~ | — | — | — | **→ follow-up BG-F03** |

### EPIC-06. Документация

| ID | Задача | Волна | Оценка | Зависимости | Результат / Acceptance criteria |
| --- | --- | ---: | ---: | --- | --- |
| DOC-01 | Обновить README | 1 | 4ч | APP-01 | Запуск, env, тесты, архитектура; секция «Как прогнать E2E» (на основе TG-10 и `use_cases.md`) |
| DOC-02 | Архитектурные артефакты | 9 | 3ч | DB-04, BG-01, CORE-07 | ER-диаграмма, схема сервисов |
| DOC-03 | Демо-сценарий и видео | 11 | 4ч | TG-10 | Ролик до 7 мин; голосовой demo-путь |
| ~~QA-01~~ | — | — | — | **→ APP-01** (pytest scaffold + `make test`) |
| ~~QA-03~~ | — | — | — | **→ TG-10 + DOC-01** (E2E-чеклист и отчёт) |

## 4. Рекомендуемый порядок выполнения

Порядок — **топологическая сортировка** по полю `Зависимости` в markdown-тикетах (28 активных MVP-тикетов). **Волна N** — тикеты, у которых все зависимости закрыты к концу волны **N−1**; внутри волны задачи **параллельны** разным исполнителям. Ручная проверка — внутри каждого тикета, не отдельными QA-задачами.

Пересчёт после слияний тикетов и актуализации зависимостей в `issues/`.

### Сводка: что раздать студентам по волнам

| Волна | Когда | Тикеты (параллельно) | Кому (поток) |
| ---: | --- | --- | --- |
| **0** | День 1, утро | `APP-01` | App |
| **1** | День 1 | `APP-04`, `CORE-02`, `TG-01`, `DOC-01` *(черновик README)* | App, Core, Telegram, Docs |
| **2** | День 1–2 | `DB-01`, `AI-06`, `AI-02` | DB, AI |
| **3** | День 2–3 | `DB-02`, `CORE-01`, `AI-03` | DB, Core, AI |
| **4** | День 3 | `DB-03`, `TG-03`, `AI-04` | DB, Telegram, AI |
| **5** | День 3–4 | `DB-04` | DB |
| **6** | День 4 | `CORE-03` | Core |
| **7** | День 4–5 | `CORE-05`, `CORE-07`, `TG-05` | Core, Telegram |
| **8** | День 5–6 | `BG-01`, `TG-07`, `TG-08`, `TG-09` | Background, Telegram |
| **9** | День 6–7 | `BG-05`, `BG-06`, `DOC-02` | Background, Docs |
| **10** | День 7–8 | `TG-10` | Вся команда / тимлид |
| **11** | День 8 | `DOC-03` | Docs / тимлид |

**Итого:** 12 волн, до **4 параллельных** тикетов в пике (волны 1 и 8).

### Топологический порядок (все 28 тикетов)

```text
APP-01
→ APP-04, CORE-02, DOC-01, TG-01
→ DB-01, AI-06, AI-02
→ DB-02, CORE-01, AI-03
→ DB-03, TG-03, AI-04
→ DB-04
→ CORE-03
→ CORE-05, CORE-07, TG-05
→ BG-01, TG-07, TG-08, TG-09
→ BG-05, BG-06, DOC-02
→ TG-10
→ DOC-03
```

### Волна 0. Точка входа

1. `APP-01` — блокирует все потоки; закрыть в первую очередь.

### Волна 1. Каркас и entrypoints

1. `APP-04` — compose-инфра (после APP-01)
2. `CORE-02` — DTO и контракты
3. `TG-01` — aiogram, sender, download voice
4. `DOC-01` — черновик README (обновлять по ходу; формальная зависимость только от APP-01)

**Параллельно:** 4 исполнителя, 0 взаимных блокировок.

### Волна 2. Mock-parser + старт БД + STT-клиент

1. `AI-06` — mock-parser (после CORE-02)
2. `DB-01` — User (после APP-04)
3. `AI-02` — SpeechKit-клиент (после TG-01; **не блокирует** CORE-07/TG-09 при mock)

### Волна 3. Модели и parser prod

1. `DB-02` → цепочка DB продолжается
2. `CORE-01` — UserService (после DB-01)
3. `AI-03` — YandexGPT parser (после AI-06)

### Волна 4. Reminder-модель + /start + date parser

1. `DB-03`
2. `TG-03` — `/start` (после CORE-01; **раньше**, чем TG-05/TG-08)
3. `AI-04` — parser даты для Reply (после AI-03)

### Волна 5. TaskEvent

1. `DB-04` — последний тикет DB-цепочки; разблокирует `CORE-03`.

### Волна 6. TaskService (крупный тикет)

1. `CORE-03` — полный TaskService + unit-тесты (~10–11ч). **Разблокирует** большую часть TG и BG.

### Волна 7. Сервисы напоминаний + undated + voice orchestration

1. `CORE-05` — ReminderService
2. `CORE-07` — VoiceTaskCreationService (**mock-first**, без ожидания AI-02/AI-03)
3. `TG-05` — `/undated` + inline-кнопки

**Ранний demo голосом (mock):** `TG-01 → AI-06 → CORE-03 → CORE-07 → TG-09` (волна 8).

### Волна 8. Интеграция: Celery, даты, реакции, voice handler

1. `BG-01` — Celery + Beat + `send_due_reminders` (после CORE-05)
2. `TG-07` — Reply + назначение даты (после TG-05 + AI-04)
3. `TG-08` — реакции ✅/❌ (после CORE-05; **после BG-01** для полной ручной проверки с реальным reminder)
4. `TG-09` — тонкий voice handler (после CORE-07)

**Critical path reminder flow:** `CORE-05 → BG-01 → TG-08`.

### Волна 9. Дайджест, вечерняя проверка, архитектурные артефакты

1. `BG-05` — утренний дайджест 09:00
2. `BG-06` — вечерняя проверка 20:00 (после TG-07)
3. `DOC-02` — ER-диаграмма, схема сервисов

### Волна 10. Сквозной E2E

1. **`TG-10`** — обязательный чеклист UC-01..UC-12; блокирует DOC-03.

### Волна 11. Демо

1. `DOC-03` — видео до 7 мин.

### Критический путь MVP (production, 12 шагов)

```text
APP-01 → APP-04 → DB-01 → DB-02 → DB-03 → DB-04
→ CORE-03 → CORE-05 → BG-01 → BG-06 → TG-10 → DOC-03
```

Параллельная ветка дат (тоже влияет на BG-06):

```text
APP-01 → CORE-02 → AI-06 → AI-03 → AI-04 → TG-05 → TG-07 → BG-06
```

### Критический путь раннего demo (mock, без Yandex)

```text
APP-01 → CORE-02 → AI-06
APP-01 → TG-01 → CORE-07 → TG-09
APP-01 → APP-04 → DB-01..04 → CORE-03
```

Можно показать **голос → задача в БД** уже на волне 8, не дожидаясь AI-02/AI-03/BG.

### Параллельные дорожки (по потокам)

| Поток | Цепочка волн |
| --- | --- |
| **App/Infra** | W0:`APP-01` → W1:`APP-04` |
| **DB** | W2:`DB-01` → W3:`DB-02` → W4:`DB-03` → W5:`DB-04` |
| **Core** | W1:`CORE-02` → W3:`CORE-01` → W6:`CORE-03` → W7:`CORE-05`, `CORE-07` |
| **Telegram** | W1:`TG-01` → W4:`TG-03` → W7:`TG-05` → W8:`TG-07`, `TG-08`, `TG-09` → W10:`TG-10` |
| **AI** | W2:`AI-06`, `AI-02` → W3:`AI-03` → W4:`AI-04` |
| **Background** | W8:`BG-01` → W9:`BG-05`, `BG-06` |
| **Docs** | W1:`DOC-01` → W9:`DOC-02` → W11:`DOC-03` |

### Что изменилось по сравнению с прежними 7 волнами

- `TG-03` поднят на **волну 4** (раньше был вместе с TG-05/TG-08) — меньше простоя Telegram-разработчика после TG-01.
- `TG-05` и `TG-08` опущены на **волны 7–8** — жёсткая зависимость от `CORE-03`/`CORE-05` больше не нарушается.
- `AI-02` вынесен в **волну 2** параллельно с `AI-06` — не блокирует mock-demo.
- `BG-01` сдвинут на **волну 8** (после `CORE-05`) — убрана ложная готовность на волне 5.
- `DOC-01` стартует на **волне 1** — README пишется с первого дня, финализация после TG-10.

## 5. Зависимости между потоками

- `send_due_reminders` — после `ReminderService` и `TelegramSender` (TG-01).
- Реакции — после сохранения `message_id` на Reminder (BG-01).
- Вечерний перенос — Reply на сообщение с `TaskEvent(evening_question_sent)`; lookup через TG-07.
- Voice — `TG-09` → `CORE-07`; download в TG-01, не в AI.
- Назначение даты из `/undated` — Reply на карточку с `TaskEvent(undated_card_sent)`.
- Базовая идемпотентность рассылок — проверка `sent_time` / event в MVP; полная claim/lock — follow-up BG-F01.

## 6. Сквозные acceptance criteria MVP

- пользователь создаётся по `chat_id`, повторные обращения не создают дубль;
- **голосовое** сообщение скачивается (TG-01), распознаётся (AI-02), разбирается (AI-03/mock), создаёт задачу (CORE-07);
- `Task`, `Reminder` и `TaskEvent(created)` в одной транзакции;
- задача без даты — без `Reminder`, видна в `/undated`;
- дата в прошлом не сохраняется;
- due reminder один раз, с `sent_time` и `message_id`;
- ✅ → `done`, ❌ → `cancelled`; каждое действие → `TaskEvent`;
- удаление → `deleted`;
- вечерняя проверка — Reply на вопрос → перенос;
- **TG-10** пройден или баги заведены;
- секреты не в логах; внешние API мокируемы в тестах;
- README с запуском и demo video.

## 7. Минимальный набор тикетов для первой нарезки

Стартовая пачка (волны 0–2):

1. W0: `APP-01`
2. W1: `APP-04`, `CORE-02`, `TG-01`, `DOC-01`
3. W2: `DB-01`, `AI-06`, `AI-02`

Цепочка данных и сервисов (волны 3–7):

4. W3–5: `DB-02..04`, `CORE-01`, `AI-03`
5. W4: `TG-03`, `AI-04`
6. W6–7: `CORE-03`, `CORE-05`, `CORE-07`, `TG-05`

Вертикальный срез mock (волна 8):

7. `TG-09`, `BG-01`, `TG-07`, `TG-08`

Финал (волны 9–11):

8. `BG-05`, `BG-06`, `DOC-02`
9. `TG-10`, `DOC-03`

## 8. Риски и открытые решения

- PDF про регистрацию/CBV/Bootstrap — не MVP; UI = Telegram-бот.
- Перенос даты — через **Reply** + `TaskEvent.message_id`, не отдельная таблица ожидания.
- `message_id` в `TaskEvent` — только для событий отправки сообщений бота.
- Базовая идемпотентность — `sent_time` в BG-01; полная — BG-F01.
- Recurrence-cycle — post-MVP; поля `repeat_*` можно сохранять сразу.
- Worker упал после Telegram send до записи в БД — риск дубля (known limitation до BG-F01); логировать.

## 9. Follow-up задачи

Выполняются после MVP demo-пути. Не блокируют TG-10. **На GitHub закрыты как *not planned*** (не в активном backlog); ID сохранены здесь для справки.

**Закрытые superseded-тикеты (GitHub):** TG-02, TG-04, TG-06, TG-QA-01..06, AI-01, AI-05, AI-QA-01, AI-07, QA-01, QA-02, QA-03, DB-05, DB-06, CORE-04, CORE-06, BG-02, BG-03, BG-04, BG-07, BG-08, BG-QA-01..03.

| ID | Задача | Оценка | Зависимости | Было |
| --- | --- | ---: | --- | --- |
| TG-F02 | Тесты handlers с моками сервисов | 5ч | TG-03..09 | бывш. TG-09 (tests) |
| TG-F03 | Text handler создания задачи (усложнение ТЗ) | 5ч | TG-01, CORE-03, AI-03 | бывш. TG-04 |
| AI-F01 | Ручная проверка voice + тесты AI pipeline | 7ч | AI-02..06, TG-01 | AI-QA-01 + AI-07 |
| AI-07 | *(в AI-F01)* Покрыть AI pipeline автотестами | — | AI-02..06 | отдельный issue закрыт |
| BG-F01 | Идемпотентность/claim due reminders | 6ч | BG-01 | бывш. BG-04 |
| BG-F02 | Retry policy Telegram ошибок | 5ч | BG-01..06 | бывш. BG-07 |
| BG-F03 | Автотесты фоновых сценариев | 7ч | BG-01..06 | бывш. BG-08 |
