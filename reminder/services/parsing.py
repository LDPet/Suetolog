"""Task/date parser implementations and backend factory."""

from __future__ import annotations

import json
import logging
import re
import socket
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings

from reminder.services.contracts import TaskParser
from reminder.services.dto import ParsedDateResult, ParsedTaskInput

logger = logging.getLogger(__name__)


class ParserErrorCode:
    PARSER_FAILED = "parser_failed"
    DATE_IN_PAST = "date_in_past"


class ParserError(ValueError):

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        if code == ParserErrorCode.DATE_IN_PAST:
            logger.info("Parser validation: %s", message)
        else:
            logger.warning("Parser validation: %s", message)


class ParserConfigurationError(RuntimeError):

    def __init__(self, message: str):
        super().__init__(message)
        logger.error("Parser configuration: %s", message)


TASK_SEMANTIC_JSON_SCHEMA = {
    "type":
    "object",
    "properties": {
        "title": {
            "type":
            "string",
            "minLength":
            1,
            "description":
            "Короткое название задачи из главного действия пользователя",
        },
        "description": {
            "type": ["string", "null"],
            "description": "Детали из исходного текста без выдуманных фактов",
        },
        "date_hint": {
            "type": ["string", "null"],
            "description":
            ("Дословная подстрока с датой или временем из исходного "
             "текста либо null"),
        },
        "repeat_type": {
            "type": ["string", "null"],
            "enum": ["daily", "weekly", "monthly", None],
            "description": "Тип явно указанного повторения",
        },
        "repeat_interval": {
            "type": ["integer", "null"],
            "minimum": 1,
            "description": "Интервал повторения или null",
        },
    },
    "required": [
        "title",
        "description",
        "date_hint",
        "repeat_type",
        "repeat_interval",
    ],
    "additionalProperties":
    False,
}

TASK_JSON_SCHEMA = TASK_SEMANTIC_JSON_SCHEMA

YANDEX_GENERATION_JSON_SCHEMA = {
    **TASK_SEMANTIC_JSON_SCHEMA,
    "properties": {
        **TASK_SEMANTIC_JSON_SCHEMA["properties"],
        "title": {
            **TASK_SEMANTIC_JSON_SCHEMA["properties"]["title"],
            "minLength": 0,
        },
    },
}

DATE_GENERATION_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "due_to": {
            "type": ["string", "null"],
            "description": "ISO 8601 datetime в переданном timezone или null",
        },
        "due_to_has_time": {
            "type": "boolean",
            "description": "true, если пользователь явно указал время",
        },
    },
    "required": ["due_to", "due_to_has_time"],
    "additionalProperties": False,
}

DATE_GENERATION_MODEL = "yandexgpt-5.1"
DATE_GENERATION_TEMPERATURE = 0
DATE_GENERATION_MAX_TOKENS = 100


def build_date_generation_prompt(now: datetime) -> str:
    """Сформировать системный prompt для генерации даты через YandexGPT 5.1."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")

    now_iso = now.isoformat()
    schema = json.dumps(DATE_GENERATION_JSON_SCHEMA,
                        ensure_ascii=False,
                        separators=(",", ":"))
    calendar_rows = []
    for offset in range(31):
        day = now.date() + timedelta(days=offset)
        weekday_name = _YandexGPTParserBase._CALENDAR_WEEKDAYS[day.weekday()]
        calendar_rows.append(f"- {day.isoformat()} — {weekday_name}")
    calendar = "\n".join(calendar_rows)

    weekday_rows = []
    for weekday, weekday_name in enumerate(
            _YandexGPTParserBase._CALENDAR_WEEKDAYS):
        nearest = now + timedelta(days=(weekday - now.weekday()) % 7)
        nearest_date = nearest.date()
        next_date = nearest_date + timedelta(days=7)
        in_two_weeks = nearest_date + timedelta(days=14)
        weekday_rows.append(
            f"- {weekday_name}: ближайший={nearest_date.isoformat()}, "
            f"следующий={next_date.isoformat()}, "
            f"через 2 недели={in_two_weeks.isoformat()}")
    weekday_reference = "\n".join(weekday_rows)

    def next_weekday_at(weekday: int,
                        hour: int = 0,
                        has_time: bool = True) -> datetime:
        result = (now + timedelta(days=(weekday - now.weekday()) % 7)).replace(
            hour=hour, minute=0, second=0, microsecond=0)
        if ((has_time and result <= now)
                or (not has_time and result.date() < now.date())):
            result += timedelta(days=7)
        return result

    next_friday_date = next_weekday_at(4, has_time=False)
    next_friday_midnight = next_weekday_at(4, has_time=True)

    return f"""
Ты — детерминированный парсер даты и времени для приложения задач и напоминаний.
Ты преобразуешь русский текст, содержащий только дату или время, в datetime.
Не извлекай задачу, title или description.

Текущее локальное время пользователя:

NOW = {now_iso}

NOW является единственным источником текущей даты, времени и UTC-смещения.
Не используй реальную текущую дату из собственных знаний.

Календарь от now / NOW на 31 день:

{calendar}

Справочник дней недели, вычисленный от NOW:

{weekday_reference}

Пользователь отдельным сообщением передаст произвольный текст, который может
содержать описание даты или времени.

Верни объект строго по переданной JSON Schema:

{schema}

{{
  "due_to": "ISO 8601 datetime" или null,
  "due_to_has_time": true или false
}}

Не возвращай Markdown, пояснения, комментарии или дополнительные поля.

Правила:

1. Значение due_to

Если дату можно однозначно определить, верни due_to в формате ISO 8601:

YYYY-MM-DDTHH:MM:SS±HH:MM

Используй то же UTC-смещение, которое указано в NOW.

Если дату нельзя определить однозначно, верни:

"due_to": null

2. Относительные даты

Все относительные выражения вычисляй только относительно NOW.

Примеры:

- «через 15 минут» — прибавь ровно 15 минут;
- «через полтора часа» — прибавь ровно 1 час 30 минут;
- «через 2 часа» — прибавь ровно 2 часа;
- «через 3 дня» — дата через 3 календарных дня;
- «завтра» — следующий календарный день;
- «послезавтра» — через 2 календарных дня;
- «через неделю» — через 7 календарных дней;
- «через две недели» — через 14 календарных дней.

3. Дата без времени

Если пользователь указал дату, но явно не указал время, верни начало
соответствующего локального дня:

00:00:00

И установи:

"due_to_has_time": false

4. Явно указанное время

Если пользователь явно указал время, установи:

"due_to_has_time": true

В краткой форме: due_to_has_time=true только если пользователь явно указал
время, включая 00:00.

Относительный интервал в минутах или часах считается явным указанием времени.
Относительный интервал только в днях или неделях не считается явным указанием
времени.

5. Части суток

Часть суток считается явным указанием времени.

Используй:

- «рано утром» — 07:00:00;
- «утром» — 09:00:00;
- «в обед» — 13:00:00;
- «днём» — 14:00:00;
- «вечером» — 19:00:00;
- «поздно вечером» — 22:00:00;
- «ночью» — 23:00:00;
- «в полдень» — 12:00:00;
- «в полночь» — 00:00:00.

Во всех таких случаях:

"due_to_has_time": true

6. Указано только время

Если пользователь указал время без даты:

- используй сегодняшний календарный день, если это время строго позже NOW;
- иначе используй следующий календарный день.

Иными словами, если указан только час без дня, выбери ближайшее такое время:
сегодня, если оно строго позже now, иначе завтра.

7. Дни недели

Если указан день недели без слова «следующий», выбери дату `ближайший` из
справочника дней недели.

Если сегодня указанный день недели:

- используй сегодня, если указанное время строго позже NOW;
- иначе используй тот же день следующей недели;
- если время не указано, используй тот же день следующей недели, поскольку
  00:00 текущего дня уже прошло.

Выражения «следующий понедельник», «в следующую пятницу» и аналогичные
означают дату `следующий` из справочника дней недели.

Выражения «в <день недели> через N недель» означают:

1. возьми дату `ближайший` для названного дня недели;
2. прибавь N * 7 календарных дней;
3. проверь по календарю, что итоговая дата имеет тот же день недели.

Нельзя заменять названный день недели на соседний. Если пользователь написал
«во вторник», итоговая дата обязана быть вторником. Если написал «в пятницу»,
итоговая дата обязана быть пятницей.

8. Дата без года

Если пользователь указал число и месяц, но не указал год, выбери ближайшую
такую дату в будущем относительно NOW.

9. Прошедшие даты

Если пользователь явно указал год, дату или момент времени в прошлом, не
переноси его автоматически в будущее.

Верни:

{{
  "due_to": null,
  "due_to_has_time": false
}}

Это правило не относится к времени без даты: для выражения «в 19:00» можно
использовать следующий календарный день по правилу 6.

10. Посторонний текст

Игнорируй слова, которые не относятся к дате и времени.

Пример:

«Позвонить врачу завтра в 10 утра и узнать результаты анализов»

Дата определяется по фрагменту:

«завтра в 10 утра»

11. Когда возвращать null

Верни:

{{
  "due_to": null,
  "due_to_has_time": false
}}

если:

- дата и время в тексте отсутствуют;
- выражение невозможно интерпретировать однозначно;
- указано несколько альтернативных дат;
- указан диапазон, но не один конкретный момент;
- дата явно находится в прошлом;
- выражение слишком неопределённое.

Неопределённые выражения:

- «когда-нибудь»;
- «на днях»;
- «потом»;
- «как-нибудь вечером»;
- «скоро»;
- «попозже»;
- «на следующей неделе» без конкретного дня;
- «в выходные»;
- «с понедельника по пятницу»;
- «завтра или послезавтра».

12. Итоговые ограничения

- Всегда возвращай оба поля.
- Если due_to равен null, due_to_has_time всегда должен быть false.
- Возвращай только один конкретный момент времени.
- Не возвращай массивы, диапазоны или несколько вариантов.
- Не добавляй поля, отсутствующие в JSON Schema.
- Не изменяй UTC-смещение относительно NOW.

Примеры вычисления для текущего NOW:

- «в понедельник» → возьми `ближайший` для понедельника из справочника.
- «в пятницу» → возьми `ближайший` для пятницы из справочника.
- «в следующую субботу» → возьми `следующий` для субботы из справочника.
- «в следующую среду» → возьми `следующий` для среды из справочника.
- «в среду через 2 недели» → возьми `ближайший` для среды и прибавь 14 дней.
- «во вторник через 2 недели» → возьми `ближайший` для вторника и прибавь 14 дней.
- «каждый понедельник в 9» → это дата ближайшего понедельника в 09:00; слово
  «каждый» не меняет расчёт первого срока.

Примеры JSON для совместимости с контрактом:
"в пятницу" -> {{"due_to":"{next_friday_date.isoformat()}","due_to_has_time":false}}
"в пятницу в 00:00" -> {{"due_to":"{next_friday_midnight.isoformat()}","due_to_has_time":true}}
""".strip()


class YandexFoundationModelsClient:
    ENDPOINT = (
        "https://llm.api.cloud.yandex.net/foundationModels/v1/completion")

    def __init__(
        self,
        *,
        api_key: str,
        folder_id: str,
        model: str,
        temperature: float,
        max_tokens: int,
        timeout: float,
    ):
        self._api_key = api_key
        self._folder_id = folder_id
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._timeout = timeout

    def complete(self,
                 system_prompt: str,
                 user_text: str,
                 json_schema: dict | None = None,
                 *,
                 model: str | None = None,
                 temperature: float | int | None = None,
                 max_tokens: int | None = None) -> str:
        response_schema = json_schema or YANDEX_GENERATION_JSON_SCHEMA
        payload = {
            "modelUri":
            f"gpt://{self._folder_id}/{model or self._model}",
            "completionOptions": {
                "stream": False,
                "temperature":
                self._temperature if temperature is None else temperature,
                "maxTokens": str(max_tokens or self._max_tokens),
            },
            "messages": [
                {
                    "role": "system",
                    "text": system_prompt,
                },
                {
                    "role": "user",
                    "text": user_text,
                },
            ],
            "jsonSchema": {
                "schema": response_schema,
            },
        }
        response_body = self._post_with_retry(payload)

        try:
            response = json.loads(response_body.decode("utf-8"))
            text = response["result"]["alternatives"][0]["message"]["text"]
        except (KeyError, IndexError, TypeError, UnicodeDecodeError,
                json.JSONDecodeError) as error:
            logger.error(
                "YandexGPT вернул невалидный ответ: %s",
                response_body[:500],
                exc_info=error,
            )
            raise ParserError(
                ParserErrorCode.PARSER_FAILED,
                "YandexGPT returned an invalid response.",
            ) from error

        if not isinstance(text, str) or not text.strip():
            raise ParserError(
                ParserErrorCode.PARSER_FAILED,
                "YandexGPT returned an empty response.",
            )

        return text

    def _post_with_retry(self, payload: dict) -> bytes:
        request_body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        for attempt in range(2):
            request = urllib.request.Request(
                self.ENDPOINT,
                data=request_body,
                headers={
                    "Authorization": f"Api-Key {self._api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )

            try:
                with urllib.request.urlopen(request,
                                            timeout=self._timeout) as response:
                    return response.read()
            except urllib.error.HTTPError as error:
                body = error.read().decode("utf-8", errors="replace")[:500]
                if 500 <= error.code < 600 and attempt == 0:
                    logger.warning(
                        "YandexGPT HTTP %s (попытка %s), повтор: %s",
                        error.code,
                        attempt + 1,
                        body,
                    )
                    error.close()
                    continue
                logger.error(
                    "YandexGPT HTTP %s (попытка %s): %s",
                    error.code,
                    attempt + 1,
                    body,
                    exc_info=error,
                )
                error.close()
                raise self._api_error() from error
            except (TimeoutError, socket.timeout) as error:
                if attempt == 0:
                    logger.warning(
                        "YandexGPT timeout (попытка %s), повтор",
                        attempt + 1,
                        exc_info=error,
                    )
                    continue
                logger.error(
                    "YandexGPT timeout (попытка %s)",
                    attempt + 1,
                    exc_info=error,
                )
                raise self._api_error() from error
            except urllib.error.URLError as error:
                if self._is_timeout(error) and attempt == 0:
                    logger.warning(
                        "YandexGPT сетевая ошибка (попытка %s), повтор: %s",
                        attempt + 1,
                        error.reason,
                        exc_info=error,
                    )
                    continue
                logger.error(
                    "YandexGPT сетевая ошибка (попытка %s): %s",
                    attempt + 1,
                    error.reason,
                    exc_info=error,
                )
                raise self._api_error() from error

        raise self._api_error()

    @staticmethod
    def _is_timeout(error: urllib.error.URLError) -> bool:
        return isinstance(error.reason, (TimeoutError, socket.timeout))

    @staticmethod
    def _api_error() -> ParserError:
        logger.error("YandexGPT: все попытки запроса исчерпаны")
        return ParserError(
            ParserErrorCode.PARSER_FAILED,
            "YandexGPT is temporarily unavailable.",
        )


class MockTaskParser:
    _NUMERIC_TIME_RE = re.compile(
        r"\bв\s+(?P<hour>[01]?\d|2[0-3])"
        r"(?::(?P<minute>[0-5]\d))?"
        r"(?:\s*(?:час|часа|часов))?\b",
        re.IGNORECASE,
    )
    _HOUR_WORDS = {
        "ноль": 0,
        "один": 1,
        "одна": 1,
        "два": 2,
        "две": 2,
        "три": 3,
        "четыре": 4,
        "пять": 5,
        "шесть": 6,
        "семь": 7,
        "восемь": 8,
        "девять": 9,
        "десять": 10,
        "одиннадцать": 11,
        "двенадцать": 12,
        "тринадцать": 13,
        "четырнадцать": 14,
        "пятнадцать": 15,
        "шестнадцать": 16,
        "семнадцать": 17,
        "восемнадцать": 18,
        "девятнадцать": 19,
        "двадцать": 20,
        "двадцать один": 21,
        "двадцать два": 22,
        "двадцать три": 23,
    }
    _WORD_TIME_RE = re.compile(
        r"\bв\s+(?P<hour_word>" +
        "|".join(sorted(map(re.escape, _HOUR_WORDS), key=len, reverse=True)) +
        r")(?:\s*(?:час|часа|часов))?\b",
        re.IGNORECASE,
    )
    _WEEKDAYS = {
        "понедельник": 0,
        "вторник": 1,
        "среду": 2,
        "среда": 2,
        "четверг": 3,
        "пятницу": 4,
        "пятница": 4,
        "субботу": 5,
        "суббота": 5,
        "воскресенье": 6,
    }
    _NOISE_WORDS = {"а", "м", "мм", "ммм", "э", "ээ", "эээ", "эм", "ну", "шум"}

    def parse_task(self,
                   text: str,
                   now: datetime | None = None) -> ParsedTaskInput:
        """Распознать задачу и сохранить признак явно указанного времени."""
        raw_text = (text or "").strip()
        normalized = self._normalize(raw_text)

        if not normalized:
            raise ParserError(
                ParserErrorCode.PARSER_FAILED,
                "Task transcript is empty.",
            )

        current = self._resolve_now(now)
        due_to, due_to_has_time = self._extract_due_to(normalized, current)
        title = self._extract_title(normalized)

        if self._is_unparseable_title(title):
            raise ParserError(
                ParserErrorCode.PARSER_FAILED,
                "Task transcript does not contain a stable title.",
            )

        return ParsedTaskInput(
            title=title,
            raw_text=raw_text,
            due_to=due_to,
            due_to_has_time=due_to_has_time,
        )

    def _extract_due_to(self, text: str,
                        now: datetime) -> tuple[datetime | None, bool]:
        """Извлечь тестовый срок вместе с признаком точного времени."""
        if re.search(r"\bбез\s+даты\b", text):
            return None, False

        if re.search(r"\bвчера\b", text):
            raise ParserError(
                ParserErrorCode.DATE_IN_PAST,
                "Task date is in the past.",
            )

        parsed_time = self._extract_time(text)
        date = None

        if re.search(r"\bсегодня\b", text):
            date = now.date()
        elif re.search(r"\bзавтра\b", text):
            date = now.date() + timedelta(days=1)
        else:
            weekday = self._extract_weekday(text)
            if weekday is not None:
                days_ahead = (weekday - now.weekday()) % 7
                weeks_match = re.search(
                    r"\bчерез\s+(?P<weeks>\d+)\s+недел(?:ю|и|ь)\b",
                    text,
                )
                if weeks_match:
                    days_ahead += int(weeks_match.group("weeks")) * 7
                elif re.search(r"\bследующ\w*\b", text):
                    days_ahead += 7
                date = now.date() + timedelta(days=days_ahead)

        if date is None:
            return None, False

        if parsed_time is None:
            due_to = now.replace(
                year=date.year,
                month=date.month,
                day=date.day,
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
            )
            return due_to, False

        due_to = now.replace(
            year=date.year,
            month=date.month,
            day=date.day,
            hour=parsed_time[0],
            minute=parsed_time[1],
            second=0,
            microsecond=0,
        )

        if due_to <= now:
            if self._extract_weekday(text) is not None:
                due_to += timedelta(days=7)
            else:
                raise ParserError(
                    ParserErrorCode.DATE_IN_PAST,
                    "Task date is in the past.",
                )

        return due_to, True

    def _extract_title(self, text: str) -> str:
        title = text
        title = re.sub(r"\bбез\s+даты\b", " ", title)
        title = re.sub(r"\b(?:сегодня|завтра|вчера)\b", " ", title)
        title = self._NUMERIC_TIME_RE.sub(" ", title)
        title = self._WORD_TIME_RE.sub(" ", title)
        title = re.sub(r"\b(?:в|во)\s+следующ\w+\s+", " ", title)
        title = re.sub(r"\bчерез\s+\d+\s+недел(?:ю|и|ь)\b", " ", title)

        for weekday in self._WEEKDAYS:
            title = re.sub(rf"\b(?:в|во)\s+{weekday}\b", " ", title)
            title = re.sub(rf"\b{weekday}\b", " ", title)

        title = re.sub(
            r"\b(?:напомни|напомнить|создай|запиши|поставь|пожалуйста|мне)\b",
            " ",
            title,
        )
        title = re.split(
            r"\s+(?:и потом|а потом|потом|затем)\s+",
            title,
            maxsplit=1,
        )[0]
        title = re.sub(r"[^\w\s-]", " ", title, flags=re.UNICODE)
        title = re.sub(r"\s+", " ", title)
        return title.strip(" -")

    def _extract_time(self, text: str) -> tuple[int, int] | None:
        numeric_match = self._NUMERIC_TIME_RE.search(text)
        if numeric_match:
            hour = int(numeric_match.group("hour"))
            minute = int(numeric_match.group("minute") or 0)
            return hour, minute

        word_match = self._WORD_TIME_RE.search(text)
        if word_match:
            return self._HOUR_WORDS[word_match.group("hour_word")], 0

        return None

    def _extract_weekday(self, text: str) -> int | None:
        for weekday, index in self._WEEKDAYS.items():
            if re.search(rf"\b(?:(?:в|во)\s+)?{weekday}\b", text):
                return index
        return None

    def _is_unparseable_title(self, title: str) -> bool:
        tokens = re.findall(r"[а-яa-z0-9]+", title)
        meaningful_tokens = [
            token for token in tokens if token not in self._NOISE_WORDS
        ]
        return len(meaningful_tokens) < 2

    def _normalize(self, text: str) -> str:
        text = text.lower().replace("ё", "е")
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _resolve_now(self, now: datetime | None) -> datetime:
        if now is not None:
            return now

        timezone_name = getattr(
            settings,
            "DEFAULT_TIMEZONE",
            getattr(settings, "TIME_ZONE", "Europe/Moscow"),
        )
        return datetime.now(ZoneInfo(timezone_name))


class _YandexGPTParserBase:

    _CALENDAR_WEEKDAYS = (
        "понедельник",
        "вторник",
        "среда",
        "четверг",
        "пятница",
        "суббота",
        "воскресенье",
    )

    def __init__(self,
                 client: YandexFoundationModelsClient | None = None,
                 timezone_name: str | None = None):
        self._timezone_name = timezone_name or getattr(
            settings,
            "DEFAULT_TIMEZONE",
            getattr(settings, "TIME_ZONE", "Europe/Moscow"),
        )
        try:
            self._timezone = ZoneInfo(self._timezone_name)
        except (KeyError, TypeError) as error:
            logger.exception(
                "Невалидный DEFAULT_TIMEZONE: %s",
                self._timezone_name,
            )
            raise ParserConfigurationError(
                "DEFAULT_TIMEZONE is not a valid timezone.") from error

        self._client = client or self._client_from_settings()

    def _client_from_settings(self) -> YandexFoundationModelsClient:
        api_key = getattr(settings, "YANDEX_API_KEY", "").strip()
        folder_id = getattr(settings, "YANDEX_FOLDER_ID", "").strip()

        if not api_key or not folder_id:
            raise ParserConfigurationError(
                "PARSER_BACKEND=yandex requires YANDEX_API_KEY and "
                "YANDEX_FOLDER_ID.")

        return YandexFoundationModelsClient(
            api_key=api_key,
            folder_id=folder_id,
            model=getattr(settings, "YANDEX_GPT_MODEL", "yandexgpt-lite"),
            temperature=getattr(settings, "YANDEX_GPT_TEMPERATURE", 0.1),
            max_tokens=getattr(settings, "YANDEX_GPT_MAX_TOKENS", 1000),
            timeout=getattr(settings, "YANDEX_GPT_TIMEOUT_SEC", 30),
        )

    def _parse_datetime(self, value: str | None) -> datetime | None:
        if value is None:
            return None

        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as error:
            logger.warning(
                "YandexGPT вернул невалидный due_to: %r",
                value,
                exc_info=error,
            )
            raise ParserError(
                ParserErrorCode.PARSER_FAILED,
                "YandexGPT returned an invalid due_to value.",
            ) from error

        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ParserError(
                ParserErrorCode.PARSER_FAILED,
                "YandexGPT returned due_to without a timezone.",
            )

        return parsed.astimezone(self._timezone)

    def _resolve_now(self, now: datetime | None) -> datetime:
        if now is None:
            return datetime.now(self._timezone)

        if now.tzinfo is None or now.utcoffset() is None:
            return now.replace(tzinfo=self._timezone)

        return now.astimezone(self._timezone)

    def _calendar_block(self, now: datetime, days: int = 22) -> str:
        """Сформировать единый календарь для task- и date-prompt."""
        dates = []
        for offset in range(days):
            day = now.date() + timedelta(days=offset)
            dates.append(
                f"{day.isoformat()} — {self._CALENDAR_WEEKDAYS[day.weekday()]}"
            )
        return "Календарь от now:\n" + "\n".join(dates)


class YandexGPTTaskParser(_YandexGPTParserBase):

    _WEEKDAY_PATTERNS = {
        0: r"\bпонедельник(?:а|у|ом|е|ам)?\b",
        1: r"\bвторник(?:а|у|ом|е|ам)?\b",
        2: r"\bсред(?:а|у|ы|е|ой|ам)\b",
        3: r"\bчетверг(?:а|у|ом|е|ам)?\b",
        4: r"\bпятниц(?:а|у|ы|е|ей|ам)\b",
        5: r"\bсуббот(?:а|у|ы|е|ой|ам)\b",
        6: r"\bвоскресень(?:е|я|ю|ем|ям)\b",
    }
    _REPEAT_MARKER_RE = re.compile(
        r"\b(?:кажд\w+|ежеднев\w*|еженедел\w*|ежемесяч\w*|"
        r"по\s+(?:понедельникам|вторникам|средам|четвергам|пятницам|"
        r"субботам|воскресеньям))\b",
        re.IGNORECASE,
    )

    def __init__(
        self,
        client: YandexFoundationModelsClient | None = None,
        timezone_name: str | None = None,
        date_parser: YandexGPTDateParser | None = None,
    ):
        super().__init__(client=client, timezone_name=timezone_name)
        self._date_parser = date_parser or YandexGPTDateParser(
            client=self._client,
            timezone_name=self._timezone_name,
        )

    def parse_task(self,
                   text: str,
                   now: datetime | None = None) -> ParsedTaskInput:
        """Извлечь семантику задачи и отдельно разрешить date_hint."""
        if not isinstance(text, str) or not text.strip():
            raise ParserError(
                ParserErrorCode.PARSER_FAILED,
                "Task transcript is empty.",
            )

        current = self._resolve_now(now)
        model_response = self._client.complete(
            self._build_system_prompt(current),
            text,
            YANDEX_GENERATION_JSON_SCHEMA,
        )
        logger.info("YandexGPT raw task response: %s", model_response)
        payload = self._decode_and_validate(model_response)
        title = payload["title"].strip()

        if not title:
            raise ParserError(
                ParserErrorCode.PARSER_FAILED,
                "YandexGPT returned an empty task title.",
            )

        description = payload["description"]
        if description is not None:
            description = description.strip() or None
            if description and description.casefold() == title.casefold():
                description = None

        date_hint = payload["date_hint"]
        if date_hint is not None:
            date_hint = date_hint.strip() or None

        if date_hint is not None and date_hint.casefold() not in text.casefold(
        ):
            raise ParserError(
                ParserErrorCode.PARSER_FAILED,
                "YandexGPT returned a date_hint outside the transcript.",
            )

        due_to = None
        due_to_has_time = False
        if date_hint is not None:
            parsed_date = self._date_parser.parse_date(date_hint, now=current)
            due_to = parsed_date.due_to
            due_to_has_time = parsed_date.due_to_has_time
            self._validate_weekday(date_hint, due_to)

        repeat_type = payload["repeat_type"]
        repeat_interval = payload["repeat_interval"]
        if not self._REPEAT_MARKER_RE.search(text):
            repeat_type = None
            repeat_interval = None

        try:
            parsed_task = ParsedTaskInput(
                title=title,
                description=description,
                due_to=due_to,
                due_to_has_time=due_to_has_time,
                repeat_type=repeat_type,
                repeat_interval=repeat_interval,
                raw_text=text,
            )
        except ValueError as error:
            logger.warning(
                "YandexGPT вернул несогласованные поля задачи",
                exc_info=error,
            )
            raise ParserError(
                ParserErrorCode.PARSER_FAILED,
                "YandexGPT returned inconsistent task fields.",
            ) from error

        logger.info(
            "YandexGPT task: title=%r | description=%r | due_to=%s | "
            "repeat_type=%s | repeat_interval=%s",
            parsed_task.title,
            parsed_task.description,
            parsed_task.due_to,
            parsed_task.repeat_type,
            parsed_task.repeat_interval,
        )
        return parsed_task

    def _build_system_prompt(self, now: datetime) -> str:
        """Сформировать prompt только для семантики задачи."""
        schema = json.dumps(YANDEX_GENERATION_JSON_SCHEMA,
                            ensure_ascii=False,
                            separators=(",", ":"))
        calendar = self._calendar_block(now)
        return f"""Ты преобразуешь русский текст в семантику одной задачи.
Верни только один чистый JSON-объект без Markdown, комментариев и пояснений.
Текущие дата и время: {now.isoformat()}. Часовой пояс: {self._timezone_name}.

{calendar}

Правила:
- Выбери одну главную задачу. Если задач несколько, возьми первую; не объединяй действия в title и не помещай вторую задачу в description.
- При словах «и потом», «затем», «после этого» всё после них является второй задачей: игнорируй его полностью, description=null.
- title — короткое главное действие. Не добавляй факты, которых нет в тексте.
- Служебные слова «напомни» и «напомнить» не являются действием. Если кроме них и даты нет действия, верни title="", description=null, date_hint с датой и repeat-поля null.
- description — только отдельные явно сказанные детали, иначе null; не повторяй в нём title.
- date_hint — одна дословная непрерывная подстрока исходного текста с полной фразой даты/времени; не исправляй падеж, порядок слов и числа.
- Не вычисляй datetime и не возвращай due_to. Если даты или времени нет, date_hint=null.
- Для «в следующую среду» date_hint="в следующую среду"; для «в среду через 2 недели» date_hint="в среду через 2 недели".
- Одна дата («в пятницу», «во вторник») означает разовую задачу, а не повторение.
- Повторение возвращай только при явных словах «каждый», «еженедельно», «по пятницам»; иначе оба repeat-поля null.
- Предлог «в» или «во» перед единственным днём недели никогда не означает повтор: «во вторник» даёт repeat_type=null и repeat_interval=null.
- repeat_type и repeat_interval всегда заполняй вместе: для обычного еженедельного повтора укажи "weekly" и 1.
- Для повторения date_hint всё равно содержит дословную фразу первого срока, например «каждый понедельник в 9».
- Если текст не является задачей или название определить нельзя, верни title="", description=null, date_hint=null и repeat-поля null.
- Фраза «сделать то же что вчера» не содержит самостоятельного действия: верни title="" и date_hint=null. Но в «напомни вчера позвонить врачу» слово «вчера» является сроком: верни title="Позвонить врачу" и date_hint="вчера".

JSON Schema:
{schema}

Примеры:
Текст "Отправить отчёт сегодня до 18, добавить цифры продаж":
{{"title":"Отправить отчёт","description":"Добавить цифры продаж","date_hint":"сегодня до 18","repeat_type":null,"repeat_interval":null}}
Текст "Купить корм для кота":
{{"title":"Купить корм для кота","description":null,"date_hint":null,"repeat_type":null,"repeat_interval":null}}
Текст "Каждый понедельник в 9 проверить финансы":
{{"title":"Проверить финансы","description":null,"date_hint":"Каждый понедельник в 9","repeat_type":"weekly","repeat_interval":1}}
Текст "В пятницу позвонить врачу":
{{"title":"Позвонить врачу","description":null,"date_hint":"В пятницу","repeat_type":null,"repeat_interval":null}}
Текст "Во вторник почесать яйца":
{{"title":"Почесать яйца","description":null,"date_hint":"Во вторник","repeat_type":null,"repeat_interval":null}}
Текст "Напомни в пятницу":
{{"title":"","description":null,"date_hint":"в пятницу","repeat_type":null,"repeat_interval":null}}
Текст "Завтра в 15:30 купить продукты и потом забрать посылку":
{{"title":"Купить продукты","description":null,"date_hint":"Завтра в 15:30","repeat_type":null,"repeat_interval":null}}
Текст "Сделать то же что вчера":
{{"title":"","description":null,"date_hint":null,"repeat_type":null,"repeat_interval":null}}"""

    def _decode_and_validate(self, model_response: str) -> dict:
        """Декодировать ответ парсера задачи и проверить JSON-схему."""
        try:
            payload = json.loads(model_response)
        except (TypeError, json.JSONDecodeError) as error:
            logger.error(
                "YandexGPT вернул невалидный JSON задачи: %s",
                model_response[:500],
                exc_info=error,
            )
            raise ParserError(
                ParserErrorCode.PARSER_FAILED,
                "YandexGPT returned invalid JSON.",
            ) from error

        if not self._matches_schema(payload):
            raise ParserError(
                ParserErrorCode.PARSER_FAILED,
                "YandexGPT response does not match the task schema.",
            )

        return payload

    @staticmethod
    def _matches_schema(payload: object) -> bool:
        """Проверить типы всех обязательных полей ответа с задачей."""
        if not isinstance(payload, dict):
            return False

        required_fields = set(TASK_SEMANTIC_JSON_SCHEMA["required"])
        if set(payload) != required_fields:
            return False

        if not isinstance(payload["title"], str):
            return False

        if payload["description"] is not None and not isinstance(
                payload["description"], str):
            return False

        if payload["date_hint"] is not None and not isinstance(
                payload["date_hint"], str):
            return False

        if payload["repeat_type"] not in ("daily", "weekly", "monthly", None):
            return False

        repeat_interval = payload["repeat_interval"]
        if repeat_interval is not None:
            if isinstance(repeat_interval,
                          bool) or not isinstance(repeat_interval, int):
                return False
            if repeat_interval < 1:
                return False

        return True

    def _validate_weekday(self, date_hint: str, due_to: datetime) -> None:
        expected_weekdays = [
            weekday for weekday, pattern in self._WEEKDAY_PATTERNS.items()
            if re.search(pattern, date_hint, re.IGNORECASE)
        ]
        if expected_weekdays and due_to.weekday() not in expected_weekdays:
            raise ParserError(
                ParserErrorCode.PARSER_FAILED,
                "YandexGPT returned a date with an inconsistent weekday.",
            )


class YandexGPTDateParser(_YandexGPTParserBase):
    _ONLY_TIME_RE = re.compile(
        r"^(?:в\s+)?(?:[01]?\d|2[0-3])"
        r"(?::[0-5]\d)?"
        r"(?:\s*(?:час|часа|часов))?$",
        re.IGNORECASE,
    )
    _WEEKDAY_PATTERNS = {
        0: r"\bпонедельник(?:а|у|ом|е|ам)?\b",
        1: r"\bвторник(?:а|у|ом|е|ам)?\b",
        2: r"\bсред(?:а|у|ы|е|ой|ам)\b",
        3: r"\bчетверг(?:а|у|ом|е|ам)?\b",
        4: r"\bпятниц(?:а|у|ы|е|ей|ам)\b",
        5: r"\bсуббот(?:а|у|ы|е|ой|ам)\b",
        6: r"\bвоскресень(?:е|я|ю|ем|ям)\b",
    }
    _EXPLICIT_TIME_RE = re.compile(
        r"\b(?:в|во|до|к)\s+(?P<hour>[01]?\d|2[0-3])"
        r"(?::(?P<minute>[0-5]\d))?\b",
        re.IGNORECASE,
    )
    _PART_OF_DAY_TIMES = (
        (re.compile(r"\bрано\s+утром\b", re.IGNORECASE), (7, 0)),
        (re.compile(r"\bутром\b", re.IGNORECASE), (9, 0)),
        (re.compile(r"\bв\s+обед\b", re.IGNORECASE), (13, 0)),
        (re.compile(r"\bдн[её]м\b", re.IGNORECASE), (14, 0)),
        (re.compile(r"\bпоздно\s+вечером\b", re.IGNORECASE), (22, 0)),
        (re.compile(r"\bвечером\b", re.IGNORECASE), (19, 0)),
        (re.compile(r"\bночью\b", re.IGNORECASE), (23, 0)),
        (re.compile(r"\bв\s+полдень\b", re.IGNORECASE), (12, 0)),
        (re.compile(r"\bв\s+полночь\b", re.IGNORECASE), (0, 0)),
    )
    _NUMBER_WORDS = {
        "одну": 1,
        "один": 1,
        "два": 2,
        "две": 2,
        "три": 3,
        "четыре": 4,
    }

    def parse_date(self,
                   text: str,
                   now: datetime | None = None) -> ParsedDateResult:
        """Распознать дату и вернуть признак явно указанного времени."""
        if not isinstance(text, str) or not text.strip():
            raise ParserError(
                ParserErrorCode.PARSER_FAILED,
                "Date text is empty.",
            )

        current = self._resolve_date_now(now)
        supports_date_options = True
        try:
            model_response = self._client.complete(
                self._build_system_prompt(current),
                text.strip(),
                DATE_GENERATION_JSON_SCHEMA,
                model=DATE_GENERATION_MODEL,
                temperature=DATE_GENERATION_TEMPERATURE,
                max_tokens=DATE_GENERATION_MAX_TOKENS,
            )
        except TypeError:
            supports_date_options = False
            model_response = self._client.complete(
                self._build_system_prompt(current),
                text.strip(),
                DATE_GENERATION_JSON_SCHEMA,
            )
        payload = self._decode_and_validate(model_response)
        weekday_result = (self._resolve_weekday_expression(text, current)
                          if supports_date_options else None)

        if payload["due_to"] is None:
            if weekday_result is not None:
                due_to, due_to_has_time = weekday_result
                return self._build_result(text, current, due_to,
                                          due_to_has_time)
            if self._looks_like_past_date(text):
                raise ParserError(
                    ParserErrorCode.DATE_IN_PAST,
                    "Parsed date is in the past.",
                )
            raise ParserError(
                ParserErrorCode.PARSER_FAILED,
                "YandexGPT could not recognize a date.",
            )

        if weekday_result is not None:
            due_to, due_to_has_time = weekday_result
        else:
            due_to = self._parse_date_datetime(payload["due_to"])
            if due_to.utcoffset() != current.utcoffset():
                if supports_date_options:
                    raise ParserError(
                        ParserErrorCode.PARSER_FAILED,
                        "YandexGPT returned due_to with a different UTC offset.",
                    )
                due_to = due_to.astimezone(self._timezone)
            due_to_has_time = payload["due_to_has_time"]

        return self._build_result(text, current, due_to, due_to_has_time)

    def _build_result(self, text: str, current: datetime, due_to: datetime,
                      due_to_has_time: bool) -> ParsedDateResult:
        """Проверить вычисленную дату и собрать результат."""

        if (due_to_has_time and due_to <= current
                and self._ONLY_TIME_RE.fullmatch(text.strip())):
            due_to += timedelta(days=1)

        if due_to_has_time:
            is_past = due_to <= current
        else:
            is_past = due_to.date() < current.date()

        if is_past:
            raise ParserError(
                ParserErrorCode.DATE_IN_PAST,
                "Parsed date is in the past.",
            )

        return ParsedDateResult(
            due_to=due_to,
            due_to_has_time=due_to_has_time,
        )

    def _build_system_prompt(self, now: datetime) -> str:
        """Сформировать prompt для генерации даты через YandexGPT 5.1."""
        return build_date_generation_prompt(now)

    def _resolve_date_now(self, now: datetime | None) -> datetime:
        if now is None:
            return datetime.now(self._timezone)

        if now.tzinfo is None or now.utcoffset() is None:
            raise ParserError(
                ParserErrorCode.PARSER_FAILED,
                "Date parser requires timezone-aware now.",
            )

        return now

    @staticmethod
    def _looks_like_past_date(text: str) -> bool:
        normalized = text.casefold().replace("ё", "е")
        if re.search(r"\b(?:вчера|позавчера|прошл\w+)\b", normalized):
            return True
        return bool(
            re.search(
                r"\b\d{1,2}\s+"
                r"(?:января|февраля|марта|апреля|мая|июня|июля|"
                r"августа|сентября|октября|ноября|декабря)\s+"
                r"(?:19|20)\d{2}\b",
                normalized,
            ))

    def _resolve_weekday_expression(
        self,
        text: str,
        current: datetime,
    ) -> tuple[datetime, bool] | None:
        weekday = self._extract_weekday(text)
        if weekday is None:
            return None

        time_parts = self._extract_explicit_time(text)
        due_to_has_time = time_parts is not None
        hour, minute = time_parts or (0, 0)

        days_ahead = (weekday - current.weekday()) % 7
        weeks = self._extract_week_interval(text)
        if weeks is not None:
            days_ahead += weeks * 7
        elif re.search(r"\bследующ\w*\b", text, re.IGNORECASE):
            days_ahead += 7

        due_to = (current + timedelta(days=days_ahead)).replace(
            hour=hour,
            minute=minute,
            second=0,
            microsecond=0,
        )

        if weeks is None and due_to <= current:
            due_to += timedelta(days=7)

        return due_to, due_to_has_time

    def _extract_weekday(self, text: str) -> int | None:
        for weekday, pattern in self._WEEKDAY_PATTERNS.items():
            if re.search(pattern, text, re.IGNORECASE):
                return weekday
        return None

    def _extract_explicit_time(self, text: str) -> tuple[int, int] | None:
        match = self._EXPLICIT_TIME_RE.search(text)
        if match:
            return int(match.group("hour")), int(match.group("minute") or 0)

        for pattern, time_parts in self._PART_OF_DAY_TIMES:
            if pattern.search(text):
                return time_parts

        return None

    def _extract_week_interval(self, text: str) -> int | None:
        match = re.search(
            r"\bчерез\s+(?P<value>\d+|одну|один|два|две|три|четыре)"
            r"\s+недел(?:ю|и|ь)\b",
            text,
            re.IGNORECASE,
        )
        if not match:
            return None

        value = match.group("value").casefold()
        if value.isdigit():
            return int(value)
        return self._NUMBER_WORDS[value]

    @staticmethod
    def _parse_date_datetime(value: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as error:
            logger.warning(
                "YandexGPT вернул невалидный due_to: %r",
                value,
                exc_info=error,
            )
            raise ParserError(
                ParserErrorCode.PARSER_FAILED,
                "YandexGPT returned an invalid due_to value.",
            ) from error

        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ParserError(
                ParserErrorCode.PARSER_FAILED,
                "YandexGPT returned due_to without a timezone.",
            )

        return parsed

    @staticmethod
    def _decode_and_validate(model_response: str) -> dict:
        """Декодировать ответ парсера даты и проверить структуру JSON."""
        try:
            payload = json.loads(model_response)
        except (TypeError, json.JSONDecodeError) as error:
            logger.error(
                "YandexGPT вернул невалидный JSON даты: %s",
                model_response[:500],
                exc_info=error,
            )
            raise ParserError(
                ParserErrorCode.PARSER_FAILED,
                "YandexGPT returned invalid date JSON.",
            ) from error

        if not isinstance(payload, dict) or set(payload) != {
                "due_to", "due_to_has_time"
        }:
            raise ParserError(
                ParserErrorCode.PARSER_FAILED,
                "YandexGPT response does not match the date schema.",
            )

        if payload["due_to"] is not None and not isinstance(
                payload["due_to"], str):
            raise ParserError(
                ParserErrorCode.PARSER_FAILED,
                "YandexGPT response does not match the date schema.",
            )

        if not isinstance(payload["due_to_has_time"], bool):
            raise ParserError(
                ParserErrorCode.PARSER_FAILED,
                "YandexGPT response does not match the date schema.",
            )

        if payload["due_to"] is None and payload["due_to_has_time"]:
            raise ParserError(
                ParserErrorCode.PARSER_FAILED,
                "YandexGPT response does not match the date schema.",
            )

        return payload


YandexTaskParser = YandexGPTTaskParser
YandexDateParser = YandexGPTDateParser


def get_parser(backend: str | None = None) -> TaskParser:
    selected_backend = (backend or getattr(settings, "PARSER_BACKEND",
                                           "mock")).strip().lower()
    logger.info("Выбран parser backend: %s", selected_backend)

    if selected_backend == "mock":
        return MockTaskParser()

    if selected_backend == "yandex":
        return YandexTaskParser()

    raise ParserConfigurationError(
        "Unsupported PARSER_BACKEND="
        f"{selected_backend!r}. Expected 'mock' or 'yandex'.")
