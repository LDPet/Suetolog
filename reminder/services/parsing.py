"""Task parser implementations and backend factory."""

from __future__ import annotations

import re
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


class YandexTaskParser:

    def __init__(self):
        raise ParserConfigurationError(
            "PARSER_BACKEND=yandex is not available until AI-03 is implemented."
        )


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
