# Тикеты проекта

Markdown-файлы в этом каталоге — источник правды для GitHub Issues. Структура:

```text
issues/
  APP/APP-01.md
  DB/DB-01.md
  TG/TG-01.md
  ...
```

Поддерживается также формат `issues/APP/APP-01/README.md` (если тикет лежит в подкаталоге).

Каждый файл содержит поля:

- **Тег** — ID тикета (`APP-01`, `TG-QA-02`, …)
- **Эпик** — принадлежность к эпику
- **Результат** — краткий outcome
- **Зависимости** — prerequisites (`нет`, `APP-02`, `DB-01..DB-04`, …)
- **Описание**, **Критерии приемки**, **Что проверить**

Полная декомпозиция, оценки и порядок волн — в [`tz/decomp.md`](../tz/decomp.md).

### Закрытые issues (follow-up / superseded)

Не в активном backlog на GitHub — статус **Closed as not planned**. Список и маппинг — в `tz/decomp.md` §9:

`TG-02`, `TG-04`, `TG-06`, `TG-QA-01..06`, `AI-01`, `AI-05`, `AI-QA-01`, `AI-07`, `QA-01`, `QA-02`, `QA-03`, `DB-05`, `DB-06`, `CORE-04`, `CORE-06`, `BG-02`, `BG-03`, `BG-04`, `BG-07`, `BG-08`, `BG-QA-01..03`.

Follow-up без отдельных issues: `TG-F02`, `TG-F03`, `AI-F01`.

## Автоматическое создание GitHub Issues

Скрипт: [`scripts/create_github_issues.py`](../scripts/create_github_issues.py)

### Prerequisites

1. Установите [GitHub CLI](https://cli.github.com/) **2.94+** (native issue dependencies).
2. Авторизуйтесь: `gh auth login`.
3. Убедитесь, что remote указывает на нужный репозиторий, или передайте `--repo owner/Suetolog`.

### Dry-run (без создания issues)

```bash
python3 scripts/create_github_issues.py --dry-run
```

Покажет:

- порядок создания (обратная топологическая сортировка);
- labels, milestones и зависимости по каждому тикету;
- план обновления body-секции **Blocked by**;
- план `gh issue edit --add-blocked-by` для native dependencies.

Безопасно запускать сколько угодно раз.

### Создание issues

```bash
python3 scripts/create_github_issues.py --repo YOUR_ORG/Suetolog
```

Скрипт:

1. Строит граф зависимостей из поля `Зависимости:` (включая диапазоны `DB-01..DB-04`).
2. Сортирует тикеты топологически; при равном in-degree tie-break — порядок первого появления в волнах [`tz/decomp.md`](../tz/decomp.md), затем лексикографический ID.
3. **Создаёт issues в обратном топологическом порядке** (см. раздел «Порядок в backlog» ниже).
4. Создаёт labels и milestones (если их ещё нет).
5. Ставит labels, milestone и маркер `<!-- suetolog-ticket: APP-01 -->` в body.
6. После создания всех issues добавляет в body секцию **Blocked by** со ссылками `#123`.
7. Выставляет **native GitHub blocked-by** через `gh issue edit --add-blocked-by` (требует gh 2.94+).

Повторный запуск **идемпотентен**:

- существующие issues определяются по label `ticket:APP-01` (или по маркеру/title) и не дублируются;
- уже проставленные native blocked-by не дублируются (скрипт читает текущие связи и игнорирует повторные ошибки gh).

### Порядок в backlog GitHub Issues

Список Issues по умолчанию сортируется **Newest first** (новые сверху). Позицию issue в этом списке нельзя задать через API — только порядок создания.

| Подход | Поведение |
| --- | --- |
| **Реализовано скриптом** | Создание в **обратном** топологическом порядке: последним создаётся `APP-01` и прочие ранние волны → при **Newest first** они оказываются **сверху**. |
| Альтернатива | Создавать в прямом topo-порядке и в UI переключить сортировку на **Oldest first**. |
| GitHub Projects | Position в project board задаётся отдельно (Projects API); скрипт project items не трогает. |

Пример: при topo `APP-01 → APP-02 → DB-01 → …` скрипт создаст сначала финальные тикеты волны 6, затем …, и **последним** — `APP-01`. В списке Issues (Newest first) `APP-01` будет первым.

### Только обновить связи Blocked by

Если issues уже созданы вручную или после правки зависимостей в markdown:

```bash
python3 scripts/create_github_issues.py --repo YOUR_ORG/Suetolog --update-links
```

Обновит body-секцию **Blocked by** и native `blocked-by` (если не передан `--skip-native-blocks`).

### Опции

| Флаг | Описание |
| --- | --- |
| `--dry-run` | Показать план обеих фаз без вызова GitHub |
| `--repo owner/name` | Целевой репозиторий |
| `--issues-dir PATH` | Каталог с тикетами (по умолчанию `issues/`) |
| `--decomp PATH` | `tz/decomp.md` для tie-break волн (по умолчанию `tz/decomp.md`) |
| `--skip-milestones` | Не назначать milestones |
| `--skip-label-bootstrap` | Не создавать labels/milestones заранее |
| `--skip-native-blocks` | Не вызывать `gh issue edit --add-blocked-by` |
| `--update-links` | Только обновить body + native blocked-by |

## Маппинг на GitHub

| Поле markdown | GitHub |
| --- | --- |
| `# APP-01: ...` | Title issue |
| Содержимое файла | Body issue |
| Каталог / префикс ID | Labels `APP`, `epic:APP` |
| `TG-QA-*`, `AI-QA-*`, … | Label `type:qa` |
| Остальные тикеты | Label `type:dev` |
| Каждый тикет | Label `ticket:APP-01` (для идемпотентности) |
| Эпик | Milestone (см. ниже) |
| `Зависимости:` | Native **Blocked by** + секция в body |

### Milestones по эпикам

| Префикс | Milestone |
| --- | --- |
| APP | EPIC-00. Проектная основа и окружение |
| DB | EPIC-01. Модель данных и PostgreSQL |
| CORE | EPIC-02. Сервисный слой |
| TG | EPIC-03. Telegram-бот и пользовательские сценарии |
| AI | EPIC-04. AI и голосовой пайплайн |
| BG | EPIC-05. Celery, Redis и фоновые рассылки |
| QA, DOC | EPIC-06. Документация |

### Зависимости

GitHub поддерживает **native issue dependencies** (gh 2.94+). Скрипт:

- парсит `Зависимости:` включая диапазоны (`DB-01..DB-04`);
- после создания всех issues вызывает `gh issue edit ISSUE --add-blocked-by BLOCKER,...` для каждого resolved blocker;
- дописывает в body секцию **Blocked by** со ссылками вида `- APP-01: #12`;
- для неформализованных зависимостей (например, «основные эпики») оставляет текст без ссылки и native blocked-by.

Для Kanban-доски по-прежнему используйте колонку **Ready** только когда зависимости закрыты — см. [`README.md`](../README.md#kanban-доска).
