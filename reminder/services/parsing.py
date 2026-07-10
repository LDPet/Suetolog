"""Task parser implementations and backend factory."""

from __future__ import annotations

import json
import re
import socket
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings

from reminder.services.contracts import TaskParser
from reminder.services.dto import ParsedTaskInput


class ParserErrorCode:
    PARSER_FAILED = "parser_failed"
    DATE_IN_PAST = "date_in_past"


class ParserError(ValueError):

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class ParserConfigurationError(RuntimeError):
    pass


TASK_JSON_SCHEMA = {
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
        "due_to": {
            "type": ["string", "null"],
            "description": "ISO 8601 datetime в Europe/Moscow или null",
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
        "due_to",
        "repeat_type",
        "repeat_interval",
    ],
    "additionalProperties":
    False,
}

YANDEX_GENERATION_JSON_SCHEMA = {
    **TASK_JSON_SCHEMA,
    "properties": {
        **TASK_JSON_SCHEMA["properties"],
        "title": {
            **TASK_JSON_SCHEMA["properties"]["title"],
            "minLength": 0,
        },
    },
}


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

    def complete(self, system_prompt: str, user_text: str) -> str:
        payload = {
            "modelUri":
            f"gpt://{self._folder_id}/{self._model}",
            "completionOptions": {
                "stream": False,
                "temperature": self._temperature,
                "maxTokens": str(self._max_tokens),
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
                "schema": YANDEX_GENERATION_JSON_SCHEMA,
            },
        }
        response_body = self._post_with_retry(payload)

        try:
            response = json.loads(response_body.decode("utf-8"))
            text = response["result"]["alternatives"][0]["message"]["text"]
        except (KeyError, IndexError, TypeError, UnicodeDecodeError,
                json.JSONDecodeError) as error:
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
                error.close()
                if 500 <= error.code < 600 and attempt == 0:
                    continue
                raise self._api_error() from error
            except (TimeoutError, socket.timeout) as error:
                if attempt == 0:
                    continue
                raise self._api_error() from error
            except urllib.error.URLError as error:
                if self._is_timeout(error) and attempt == 0:
                    continue
                raise self._api_error() from error

        raise self._api_error()

    @staticmethod
    def _is_timeout(error: urllib.error.URLError) -> bool:
        return isinstance(error.reason, (TimeoutError, socket.timeout))

    @staticmethod
    def _api_error() -> ParserError:
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
        raw_text = (text or "").strip()
        normalized = self._normalize(raw_text)

        if not normalized:
            raise ParserError(
                ParserErrorCode.PARSER_FAILED,
                "Task transcript is empty.",
            )

        current = self._resolve_now(now)
        due_to = self._extract_due_to(normalized, current)
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
        )

    def _extract_due_to(self, text: str, now: datetime) -> datetime | None:
        if re.search(r"\bбез\s+даты\b", text):
            return None

        if re.search(r"\bвчера\b", text):
            raise ParserError(
                ParserErrorCode.DATE_IN_PAST,
                "Task date is in the past.",
            )

        parsed_time = self._extract_time(text)
        date = None
        default_weekday_time = False

        if re.search(r"\bсегодня\b", text):
            date = now.date()
        elif re.search(r"\bзавтра\b", text):
            date = now.date() + timedelta(days=1)
        else:
            weekday = self._extract_weekday(text)
            if weekday is not None:
                days_ahead = (weekday - now.weekday()) % 7
                date = now.date() + timedelta(days=days_ahead)
                default_weekday_time = parsed_time is None

        if date is None:
            return None

        if parsed_time is None:
            if not default_weekday_time:
                return None
            parsed_time = (9, 0)

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

        return due_to

    def _extract_title(self, text: str) -> str:
        title = text
        title = re.sub(r"\bбез\s+даты\b", " ", title)
        title = re.sub(r"\b(?:сегодня|завтра|вчера)\b", " ", title)
        title = self._NUMERIC_TIME_RE.sub(" ", title)
        title = self._WORD_TIME_RE.sub(" ", title)

        for weekday in self._WEEKDAYS:
            title = re.sub(rf"\bв\s+{weekday}\b", " ", title)
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
            if re.search(rf"\b(?:в\s+)?{weekday}\b", text):
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


class YandexGPTTaskParser:

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
            raise ParserConfigurationError(
                "DEFAULT_TIMEZONE is not a valid timezone.") from error

        self._client = client or self._client_from_settings()

    def parse_task(self,
                   text: str,
                   now: datetime | None = None) -> ParsedTaskInput:
        if not isinstance(text, str) or not text.strip():
            raise ParserError(
                ParserErrorCode.PARSER_FAILED,
                "Task transcript is empty.",
            )

        current = self._resolve_now(now)
        model_response = self._client.complete(
            self._build_system_prompt(current),
            text,
        )
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

        due_to = self._parse_due_to(payload["due_to"])
        if due_to is not None and due_to < current:
            raise ParserError(
                ParserErrorCode.DATE_IN_PAST,
                "Task date is in the past.",
            )

        try:
            return ParsedTaskInput(
                title=title,
                description=description,
                due_to=due_to,
                repeat_type=payload["repeat_type"],
                repeat_interval=payload["repeat_interval"],
                raw_text=text,
            )
        except ValueError as error:
            raise ParserError(
                ParserErrorCode.PARSER_FAILED,
                "YandexGPT returned inconsistent task fields.",
            ) from error

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

    def _build_system_prompt(self, now: datetime) -> str:
        schema = json.dumps(YANDEX_GENERATION_JSON_SCHEMA,
                            ensure_ascii=False,
                            separators=(",", ":"))
        next_friday = now + timedelta(days=(4 - now.weekday()) % 7)
        next_friday = next_friday.replace(hour=0,
                                          minute=0,
                                          second=0,
                                          microsecond=0)
        first_friday_at_nine = next_friday.replace(hour=9)
        if first_friday_at_nine <= now:
            first_friday_at_nine += timedelta(days=7)
        tomorrow_at_1530 = (now + timedelta(days=1)).replace(hour=15,
                                                             minute=30,
                                                             second=0,
                                                             microsecond=0)
        yesterday = (now - timedelta(days=1)).replace(hour=0,
                                                      minute=0,
                                                      second=0,
                                                      microsecond=0)
        return f"""Ты преобразуешь русский текст в одну задачу.
Верни только один чистый JSON-объект без Markdown, комментариев и пояснений.
Текущие дата и время: {now.isoformat()}. Часовой пояс: {self._timezone_name}.

Правила:
- Выбери одну главную задачу. Если задач несколько, возьми первую; не объединяй действия в title и не помещай вторую задачу в description.
- При словах «и потом», «затем», «после этого» всё после них является второй задачей: игнорируй его полностью, description=null.
- title — короткое главное действие. Не добавляй факты, которых нет в тексте.
- Служебные слова «напомни» и «напомнить» не являются действием. Если кроме них и даты нет действия, верни title="" и остальные поля null.
- description — только отдельные явно сказанные детали, иначе null; не повторяй в нём title.
- due_to — ISO 8601 datetime с UTC offset. Разрешай относительные даты через now.
- Если дата и время не указаны, due_to=null.
- Если указана дата без времени, используй 00:00:00 как маркер отсутствия точного времени.
- Одна дата («в пятницу», «во вторник») означает разовую задачу, а не повторение. День недели без слова «прошлый» всегда разрешай в ближайшее будущее.
- Повторение возвращай только при явных словах «каждый», «еженедельно», «по пятницам»; иначе оба repeat-поля null.
- repeat_type и repeat_interval всегда заполняй вместе: для обычного еженедельного повтора укажи "weekly" и 1.
- Для повторения с днём недели и временем due_to — ближайшее строго будущее первое выполнение. Если время сегодня уже прошло, выбери следующую неделю.
- Проверяй день недели в due_to: «в пятницу» и «по пятницам» всегда дают пятницу (weekday=4), не предыдущую пятницу.
- Если текст не является задачей или название определить нельзя, верни title="" и остальные поля null.
- Для явной прошедшей даты верни вычисленную дату; приложение само отклонит её.

JSON Schema:
{schema}

Примеры:
При now=2026-07-04T10:00:00+03:00 текст "Отправить отчёт сегодня до 18, добавить цифры продаж":
{{"title":"Отправить отчёт","description":"Добавить цифры продаж","due_to":"2026-07-04T18:00:00+03:00","repeat_type":null,"repeat_interval":null}}
Текст "Купить корм для кота":
{{"title":"Купить корм для кота","description":null,"due_to":null,"repeat_type":null,"repeat_interval":null}}
Текст "Каждый понедельник в 9 проверить финансы":
{{"title":"Проверить финансы","description":null,"due_to":null,"repeat_type":"weekly","repeat_interval":1}}
Текст "В пятницу позвонить врачу":
{{"title":"Позвонить врачу","description":null,"due_to":"{next_friday.isoformat()}","repeat_type":null,"repeat_interval":null}}
Текст "Напомни в пятницу":
{{"title":"","description":null,"due_to":null,"repeat_type":null,"repeat_interval":null}}
Текст "По пятницам в 9 проверять финансы":
{{"title":"Проверить финансы","description":null,"due_to":"{first_friday_at_nine.isoformat()}","repeat_type":"weekly","repeat_interval":1}}
Текст "Завтра в 15:30 купить продукты и потом забрать посылку":
{{"title":"Купить продукты","description":null,"due_to":"{tomorrow_at_1530.isoformat()}","repeat_type":null,"repeat_interval":null}}
Текст "Сделать то же что вчера":
{{"title":"Сделать то же","description":null,"due_to":"{yesterday.isoformat()}","repeat_type":null,"repeat_interval":null}}"""

    def _decode_and_validate(self, model_response: str) -> dict:
        try:
            payload = json.loads(model_response)
        except (TypeError, json.JSONDecodeError) as error:
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
        if not isinstance(payload, dict):
            return False

        required_fields = set(TASK_JSON_SCHEMA["required"])
        if set(payload) != required_fields:
            return False

        if not isinstance(payload["title"], str):
            return False

        if payload["description"] is not None and not isinstance(
                payload["description"], str):
            return False

        if payload["due_to"] is not None and not isinstance(
                payload["due_to"], str):
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

    def _parse_due_to(self, value: str | None) -> datetime | None:
        if value is None:
            return None

        try:
            due_to = datetime.fromisoformat(value)
        except ValueError as error:
            raise ParserError(
                ParserErrorCode.PARSER_FAILED,
                "YandexGPT returned an invalid due_to value.",
            ) from error

        if due_to.tzinfo is None or due_to.utcoffset() is None:
            raise ParserError(
                ParserErrorCode.PARSER_FAILED,
                "YandexGPT returned due_to without a timezone.",
            )

        return due_to.astimezone(self._timezone)

    def _resolve_now(self, now: datetime | None) -> datetime:
        if now is None:
            return datetime.now(self._timezone)

        if now.tzinfo is None or now.utcoffset() is None:
            return now.replace(tzinfo=self._timezone)

        return now.astimezone(self._timezone)


YandexTaskParser = YandexGPTTaskParser


def get_parser(backend: str | None = None) -> TaskParser:
    selected_backend = (backend or getattr(settings, "PARSER_BACKEND",
                                           "mock")).strip().lower()

    if selected_backend == "mock":
        return MockTaskParser()

    if selected_backend == "yandex":
        return YandexTaskParser()

    raise ParserConfigurationError(
        "Unsupported PARSER_BACKEND="
        f"{selected_backend!r}. Expected 'mock' or 'yandex'.")
