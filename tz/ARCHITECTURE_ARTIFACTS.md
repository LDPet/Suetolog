# Архитектурные артефакты проекта «Голосовой напоминальщик»

Документ фиксирует фактическую архитектуру MVP на 14 июля 2026 года. Он дополняет
[`ARCHITECTURE.md`](ARCHITECTURE.md), [`tables.md`](tables.md),
[`VOICE_PIPELINES.md`](VOICE_PIPELINES.md),
[`MAILING_PIPELINES.md`](MAILING_PIPELINES.md) и
[`use_cases.md`](use_cases.md). Диаграммы построены по текущим моделям и
сервисам, а не по планируемым follow-up задачам.

Исходники диаграмм для отдельного редактирования:

- [`diagrams/er-model.mmd`](diagrams/er-model.mmd);
- [`diagrams/service-architecture.mmd`](diagrams/service-architecture.mmd);
- [`diagrams/voice-reminder-sequence.mmd`](diagrams/voice-reminder-sequence.mmd).

## 1. ER-диаграмма

```mermaid
erDiagram
    USER ||--o{ TASK : "owns"
    TASK ||--o{ REMINDER : "schedules"
    TASK ||--o{ TASK_EVENT : "records"

    USER {
        bigint id PK
        bigint chat_id UK
        bigint telegram_user_id UK
        datetime created_at
    }

    TASK {
        bigint id PK
        bigint user_id FK
        string title
        text description
        datetime due_to "nullable"
        boolean due_to_has_time
        string repeat_type "nullable"
        int repeat_interval "nullable"
        string status
        datetime created_at
    }

    REMINDER {
        bigint id PK
        bigint task_id FK
        datetime reminder_time
        datetime sent_time "nullable"
        string reaction "nullable"
        bigint message_id UK "nullable"
    }

    TASK_EVENT {
        bigint id PK
        bigint task_id FK
        string event_type
        bigint message_id UK "nullable"
        datetime created_at
    }
```

Ключевые правила модели:

- `User` владеет задачами; `Task`, `Reminder` и `TaskEvent` удаляются каскадно
  вслед за родительской записью.
- `Task.status` принимает `active`, `done`, `cancelled` или `deleted`.
- `Task.repeat_type` поддерживает `minutely`, `hourly`, `daily`, `weekly` и
  `monthly`; `repeat_interval` хранит шаг повторения.
- `due_to_has_time` отличает календарную дату от точного срока. `Reminder`
  создаётся только для будущего срока с явно указанным временем.
- `Reminder.sent_time` защищает уже доставленное напоминание от обычного
  повторного запуска фоновой job.
- Уникальный `TaskEvent.message_id` связывает Reply на карточку Telegram с одной
  задачей. `Reminder.message_id` используется для поиска отправленного
  напоминания при обработке кнопки «Сделано».
- В PostgreSQL есть индексы `Task(user, status)`, `Task(user, due_to)`,
  `Reminder(reminder_time)`, `Reminder(sent_time)`, `Reminder(task)` и
  `TaskEvent(task, created_at)`.

Источник: [`reminder/models.py`](../reminder/models.py) и репозитории в
[`reminder/repositories/`](../reminder/repositories/).

## 2. Схема сервисов

```mermaid
flowchart TB
    telegram_api["Telegram Bot API"]
    speechkit["Yandex SpeechKit STT"]
    foundation_models["Yandex Foundation Models"]
    postgres[("PostgreSQL")]
    redis[("Redis broker")]

    subgraph telegram_layer["Telegram-слой"]
        dispatcher["aiogram Dispatcher"]
        handlers["Handlers: start, voice, undated, date_reply, callbacks"]
        sender["TelegramSender"]
        downloader["TelegramFileDownloader"]
    end

    subgraph application_layer["Сервисный слой"]
        user_service["UserService"]
        voice_service["VoiceTaskCreationService"]
        task_service["TaskService"]
        reminder_service["ReminderService"]
        mailing_service["ReminderMailingService"]
    end

    subgraph ai_layer["AI-слой"]
        stt_service["YandexSpeechKitSTTService"]
        task_parser["TaskParser factory: mock or YandexGPTTaskParser"]
        date_parser["YandexGPTDateParser"]
        fm_client["YandexFoundationModelsClient"]
    end

    subgraph background_layer["Фоновые процессы"]
        beat["Celery Beat"]
        worker["Celery Worker"]
        due_task["reminder.tasks.send_due_reminders"]
    end

    subgraph persistence_layer["Доступ к данным"]
        repositories["UserRepository, TaskRepository, ReminderRepository, TaskEventRepository"]
        atomic_bundle["create_task_with_reminder_and_event"]
        orm["Django ORM models"]
    end

    telegram_api --> dispatcher
    dispatcher --> handlers
    handlers --> user_service
    handlers --> voice_service
    handlers --> task_service
    handlers --> reminder_service
    handlers --> date_parser
    handlers --> sender

    voice_service --> downloader
    downloader --> telegram_api
    voice_service --> stt_service
    voice_service --> task_parser
    voice_service --> task_service
    stt_service --> speechkit
    task_parser -. "date_hint" .-> date_parser
    task_parser -. "yandex backend" .-> fm_client
    date_parser --> fm_client
    fm_client --> foundation_models

    beat --> redis
    redis --> worker
    worker --> due_task
    due_task --> mailing_service
    mailing_service --> reminder_service
    mailing_service --> sender
    sender --> telegram_api

    user_service --> repositories
    task_service --> repositories
    task_service --> atomic_bundle
    reminder_service --> repositories
    sender --> repositories
    repositories --> orm
    atomic_bundle --> orm
    orm --> postgres
```

Границы ответственности:

- handlers и Celery task выполняют wiring и не содержат правил создания,
  переноса или завершения задачи;
- `VoiceTaskCreationService` управляет цепочкой download → STT → parser →
  `TaskService` и всегда удаляет временный OGG-файл;
- `TaskService` — единая точка бизнес-правил задачи и транзакций с
  `TaskEvent`;
- `ReminderMailingService` обрабатывает ограниченную пачку наступивших
  напоминаний и продолжает работу после ошибки одной записи;
- Redis хранит только очередь Celery. Пользователи, задачи, результаты доставки
  и аудит остаются в PostgreSQL;
- `TelegramSender` отвечает только за формат и отправку сообщений. Для due
  reminder событие `reminder_sent` создаёт `ReminderService.mark_sent`, чтобы
  `sent_time`, `message_id` и событие сохранялись вместе.

В коде уже есть форматирование карточек для digest/evening, но фоновые jobs
утреннего дайджеста и вечернего переноса не входят в реализованный BG-01 и на
диаграмме не показаны как работающие процессы.

## 3. Сценарий: голосовая задача и точечное напоминание

```mermaid
sequenceDiagram
    autonumber
    actor User as Пользователь
    participant TG as Telegram Bot API
    participant Handler as Voice handler
    participant Users as UserService
    participant Sender as TelegramSender
    participant Voice as VoiceTaskCreationService
    participant Files as TelegramFileDownloader
    participant STT as SpeechKit STT
    participant Parser as TaskParser
    participant Date as DateParser
    participant Tasks as TaskService
    participant DB as PostgreSQL
    participant Beat as Celery Beat
    participant Redis as Redis
    participant Worker as Celery Worker
    participant Mailing as ReminderMailingService
    participant Reminders as ReminderService

    User->>TG: Voice в формате OGG Opus
    TG->>Handler: Message.voice
    Handler->>Users: get_or_create_user(chat_id, telegram_user_id)
    Users->>DB: Найти или создать User
    DB-->>Users: User
    Handler->>Sender: send_processing(chat_id)
    Sender->>TG: «Слушаю...»
    Handler->>Voice: create_from_voice(user, voice)
    Voice->>Files: validate_voice() и download_voice(file_id)
    Files->>TG: Скачать Telegram file
    TG-->>Files: Временный OGG-файл
    Files-->>Voice: path
    Voice->>STT: transcribe(path)
    STT-->>Voice: STTResult(text, ru-RU)
    Voice->>Parser: get_parser().parse_task(text)
    opt semantic parser вернул date_hint
        Parser->>Date: parse_date(date_hint)
        Date-->>Parser: ParsedDateResult
    end
    Parser-->>Voice: ParsedTaskInput
    Voice->>Tasks: create_from_parsed(user, parsed)
    Tasks->>DB: atomic Task + optional Reminder + TaskEvent(created)
    DB-->>Tasks: Task
    Tasks-->>Voice: Task
    Voice->>Files: delete_voice(path) в finally
    Voice-->>Handler: VoiceTaskResult(success, task)
    Handler->>Sender: send_task_created(chat_id, task)
    Sender->>TG: Подтверждение
    TG-->>User: Задача создана

    Note over Beat,Worker: Каждые REMINDER_CHECK_INTERVAL_MINUTES
    Beat->>Redis: Опубликовать send_due_reminders
    Redis->>Worker: Выдать job
    Worker->>Mailing: send_due_reminders()
    Mailing->>Reminders: get_due_reminders(now, batch limit)
    Reminders->>DB: active + due + sent_time IS NULL
    DB-->>Reminders: Пачка Reminder
    Reminders-->>Mailing: reminders
    Mailing->>Sender: send_reminder(chat_id, task)
    Sender->>TG: Карточка с кнопками «Сделано» и «Удалить»
    TG-->>User: Точечное напоминание
    TG-->>Sender: message_id
    Sender-->>Mailing: message_id
    Mailing->>Reminders: mark_sent(reminder, message_id)
    Reminders->>DB: atomic sent_time + message_id + TaskEvent(reminder_sent)
```

Если голос слишком длинный/большой, STT вернул пустой текст, parser вернул
ошибку или срок находится в прошлом, `VoiceTaskCreationService` возвращает
код ошибки, а `Task` не создаётся. Если точная дата отсутствует, создаётся
задача без `Reminder`.

Для due reminder действует MVP-ограничение: если Telegram уже принял сообщение,
а запись результата в PostgreSQL затем упала, следующий запуск может отправить
дубль. Claim/lock для параллельных workers и расширенная retry policy вынесены в
отдельные follow-up задачи.

## 4. Как пройти демонстрационный сценарий

Актуальный для этого снимка кода запуск использует Docker только для PostgreSQL
и Redis, а приложение запускается с хоста:

```bash
make install
cp .env.example .env
make up
python manage.py migrate
python manage.py runbot
make worker
make beat
```

`runbot`, worker и beat запускаются в отдельных терминалах. В `.env` нужно
задать собственные значения `DJANGO_SECRET_KEY`, `TELEGRAM_BOT_TOKEN`, а для
реального voice — `YANDEX_FOLDER_ID` и `YANDEX_API_KEY`. При
`PARSER_BACKEND=mock` YandexGPT не используется, но реальный voice всё равно
проходит через SpeechKit.

Проверка:

1. Отправить `/start`.
2. Отправить voice с одной задачей и точным будущим временем.
3. Убедиться, что пришло подтверждение создания.
4. Дождаться карточки напоминания (Beat проверяет due reminders раз в минуту).
5. Проверить в БД `Task(active)`, `Reminder.sent_time`,
   `Reminder.message_id`, `TaskEvent(created)` и
   `TaskEvent(reminder_sent, message_id)`.
6. Повторно запустить `send_due_reminders`: уже отправленный `Reminder` не
   должен породить второе сообщение.

Реальные токены и API-ключи нельзя добавлять в этот документ, README, тесты или
логи.

## 5. Карта синхронизации

| Артефакт | Источник истины в коде | Профильный документ |
| --- | --- | --- |
| ER-диаграмма | [`reminder/models.py`](../reminder/models.py), [`reminder/repositories/`](../reminder/repositories/) | [`tables.md`](tables.md) |
| Сервисная схема | [`reminder/services/`](../reminder/services/), [`reminder/bot/`](../reminder/bot/), [`reminder/tasks.py`](../reminder/tasks.py) | [`ARCHITECTURE.md`](ARCHITECTURE.md) |
| Voice creation | [`reminder/bot/handlers/voice.py`](../reminder/bot/handlers/voice.py), [`reminder/services/voice_tasks.py`](../reminder/services/voice_tasks.py) | [`VOICE_PIPELINES.md`](VOICE_PIPELINES.md), UC-02 |
| Due reminder | [`config/celery.py`](../config/celery.py), [`reminder/services/mailing.py`](../reminder/services/mailing.py), [`reminder/services/reminders.py`](../reminder/services/reminders.py) | [`MAILING_PIPELINES.md`](MAILING_PIPELINES.md), UC-09 |
| Команды и env | [`Makefile`](../Makefile), [`.env.example`](../.env.example), [`config/settings.py`](../config/settings.py) | [`README.md`](../README.md) |

При изменении моделей, внешних методов сервисов, event types, Celery schedule
или команд запуска этот документ и три `.mmd`-исходника нужно обновлять в том же
PR.
