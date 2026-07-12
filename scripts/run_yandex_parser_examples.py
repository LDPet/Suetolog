"""Run voice integration parser examples against the configured YandexGPT API.

Includes:
- ORIGINAL: baseline from tz/VOICE_INTEGRATION_TESTS.md
- VAR: shifted-date variations (same intent, different values)
- X: known failures to fix via date-prompt tuning (expect success when fixed)

Reference now: Sunday 2026-07-12 03:00 MSK (Europe/Moscow).
See tz/YANDEX_PARSER_VARIATION_RESULTS.md for last run notes.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import django

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.conf import settings  # noqa: E402

from reminder.services.parsing import DATE_GENERATION_JSON_SCHEMA  # noqa: E402
from reminder.services.parsing import \
    YANDEX_GENERATION_JSON_SCHEMA  # noqa: E402
from reminder.services.parsing import ParserError  # noqa: E402
from reminder.services.parsing import ParserErrorCode  # noqa: E402
from reminder.services.parsing import \
    YandexFoundationModelsClient  # noqa: E402
from reminder.services.parsing import YandexGPTTaskParser  # noqa: E402

FIXED_NOW = datetime(
    2026,
    7,
    12,
    3,
    0,
    tzinfo=ZoneInfo(settings.DEFAULT_TIMEZONE),
)


def _dt(year: int,
        month: int,
        day: int,
        hour: int = 0,
        minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=FIXED_NOW.tzinfo)


@dataclass(frozen=True)
class Case:
    case_id: str
    text: str
    error: str | None = None
    title: str | None = None
    description: str | None = None
    due_to: datetime | None | object = ...
    due_to_has_time: bool | None = None
    weekday: int | None = None
    repeat_type: str | None = None
    repeat_interval: int | None = None


_UNSET = object()


@dataclass(frozen=True)
class RawYandexCall:
    step: str
    model: str
    user_text: str
    response_text: str | None = None
    error: str | None = None


class RecordingYandexClient(YandexFoundationModelsClient):
    """YandexGPT client that records raw model text for diagnostics."""

    def __init__(self):
        super().__init__(
            api_key=settings.YANDEX_API_KEY,
            folder_id=settings.YANDEX_FOLDER_ID,
            model=settings.YANDEX_GPT_MODEL,
            temperature=settings.YANDEX_GPT_TEMPERATURE,
            max_tokens=settings.YANDEX_GPT_MAX_TOKENS,
            timeout=settings.YANDEX_GPT_TIMEOUT_SEC,
        )
        self.calls: list[RawYandexCall] = []

    def complete(
        self,
        system_prompt: str,
        user_text: str,
        json_schema: dict | None = None,
        *,
        model: str | None = None,
        temperature: float | int | None = None,
        max_tokens: int | None = None,
    ) -> str:
        step = _schema_step(json_schema)
        effective_model = model or self._model
        try:
            response_text = super().complete(
                system_prompt,
                user_text,
                json_schema,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception as error:
            self.calls.append(
                RawYandexCall(
                    step=step,
                    model=effective_model,
                    user_text=user_text,
                    error=f"{type(error).__name__}: {error}",
                ))
            raise

        self.calls.append(
            RawYandexCall(
                step=step,
                model=effective_model,
                user_text=user_text,
                response_text=response_text,
            ))
        return response_text


def _schema_step(json_schema: dict | None) -> str:
    if json_schema == YANDEX_GENERATION_JSON_SCHEMA:
        return "semantic"
    if json_schema == DATE_GENERATION_JSON_SCHEMA:
        return "date"
    if json_schema is None:
        return "semantic"
    return "unknown"


ORIGINAL_CASES: tuple[Case, ...] = (
    Case(
        "O-A1",
        "Купить корм для кота",
        title="Купить корм для кота",
        due_to=None,
        due_to_has_time=False,
    ),
    Case(
        "O-A2",
        "Напомни завтра в 15:00 позвонить врачу",
        title="Позвонить врачу",
        due_to=_dt(2026, 7, 13, 15),
        due_to_has_time=True,
    ),
    Case(
        "O-A3",
        "Отправить отчёт сегодня до 18, добавить цифры продаж",
        title="Отправить отчёт",
        description="Добавить цифры продаж",
        due_to=_dt(2026, 7, 12, 18),
        due_to_has_time=True,
    ),
    Case(
        "O-A4",
        "Каждый понедельник в 9 проверить финансы",
        title="Проверить финансы",
        due_to=_dt(2026, 7, 13, 9),
        due_to_has_time=True,
        weekday=0,
        repeat_type="weekly",
        repeat_interval=1,
    ),
    Case("O-A5", "Напомни в пятницу", error=ParserErrorCode.PARSER_FAILED),
    Case("O-A6",
         "Сделать то же что вчера",
         error=ParserErrorCode.PARSER_FAILED),
    Case("O-A7", "Привет как дела", error=ParserErrorCode.PARSER_FAILED),
    Case(
        "O-B1",
        "В пятницу позвонить врачу",
        title="Позвонить врачу",
        due_to=_dt(2026, 7, 17),
        due_to_has_time=False,
        weekday=4,
    ),
    Case(
        "O-B2",
        "Купить продукты завтра",
        title="Купить продукты",
        due_to=_dt(2026, 7, 13),
        due_to_has_time=False,
    ),
    Case(
        "O-B3",
        "Завтра в 15:30 купить продукты и потом забрать посылку",
        title="Купить продукты",
        due_to=_dt(2026, 7, 13, 15, 30),
        due_to_has_time=True,
    ),
    Case(
        "O-B4",
        "По пятницам в 9 проверять финансы",
        title="Проверить финансы",
        due_to=_dt(2026, 7, 17, 9),
        due_to_has_time=True,
        weekday=4,
        repeat_type="weekly",
        repeat_interval=1,
    ),
    Case("O-B5",
         "Сдать отчёт 1 января 2020",
         error=ParserErrorCode.DATE_IN_PAST),
    Case(
        "O-C1",
        "Во вторник почесать яйца",
        due_to=_dt(2026, 7, 14),
        due_to_has_time=False,
        weekday=1,
    ),
    Case(
        "O-C2",
        "В следующую среду сходить в спортзал",
        due_to=_dt(2026, 7, 22),
        due_to_has_time=False,
        weekday=2,
    ),
    Case(
        "O-C3",
        "В среду через 2 недели починить ноутбук",
        due_to=_dt(2026, 7, 29),
        due_to_has_time=False,
        weekday=2,
    ),
    Case("O-D1",
         "Сделать то же что вчера",
         error=ParserErrorCode.PARSER_FAILED),
    Case("O-D2",
         "Напомни вчера позвонить врачу",
         error=ParserErrorCode.DATE_IN_PAST),
    Case("O-D3", "Позвонить врачу вчера", error=ParserErrorCode.DATE_IN_PAST),
)

VARIATION_CASES: tuple[Case, ...] = (
    Case(
        "V-A1",
        "Купить корм для собаки",
        title="Купить корм для собаки",
        due_to=None,
        due_to_has_time=False,
    ),
    Case(
        "V-A2",
        "Напомни послезавтра в 13:00 позвонить врачу",
        title="Позвонить врачу",
        due_to=_dt(2026, 7, 14, 13),
        due_to_has_time=True,
    ),
    Case(
        "V-A3",
        "Отправить отчёт завтра до 10, добавить цифры продаж",
        title="Отправить отчёт",
        description="Добавить цифры продаж",
        due_to=_dt(2026, 7, 13, 10),
        due_to_has_time=True,
    ),
    Case(
        "V-A4",
        "Каждый вторник в 10 проверить финансы",
        title="Проверить финансы",
        due_to=_dt(2026, 7, 14, 10),
        due_to_has_time=True,
        weekday=1,
        repeat_type="weekly",
        repeat_interval=1,
    ),
    Case("V-A5", "Напомни в понедельник", error=ParserErrorCode.PARSER_FAILED),
    Case("V-A6",
         "Сделать то же что вчера",
         error=ParserErrorCode.PARSER_FAILED),
    Case("V-A7", "Привет как дела", error=ParserErrorCode.PARSER_FAILED),
    Case(
        "V-B1",
        "В среду позвонить врачу",
        title="Позвонить врачу",
        due_to=_dt(2026, 7, 15),
        due_to_has_time=False,
        weekday=2,
    ),
    Case(
        "V-B2",
        "Купить продукты послезавтра",
        title="Купить продукты",
        due_to=_dt(2026, 7, 14),
        due_to_has_time=False,
    ),
    Case(
        "V-B3",
        "Послезавтра в 11:00 купить продукты и потом забрать посылку",
        title="Купить продукты",
        due_to=_dt(2026, 7, 14, 11),
        due_to_has_time=True,
    ),
    Case(
        "V-B4",
        "По понедельникам в 9 проверять финансы",
        title="Проверить финансы",
        due_to=_dt(2026, 7, 13, 9),
        due_to_has_time=True,
        weekday=0,
        repeat_type="weekly",
        repeat_interval=1,
    ),
    Case("V-B5", "Сдать отчёт 15 мая 2019",
         error=ParserErrorCode.DATE_IN_PAST),
    Case(
        "V-C1",
        "В понедельник почесать яйца",
        due_to=_dt(2026, 7, 13),
        due_to_has_time=False,
        weekday=0,
    ),
    Case(
        "V-C2",
        "В следующую субботу сходить в спортзал",
        due_to=_dt(2026, 7, 25),
        due_to_has_time=False,
        weekday=5,
    ),
    Case(
        "V-C3",
        "В воскресенье через 2 недели починить ноутбук",
        due_to=_dt(2026, 7, 26),
        due_to_has_time=False,
        weekday=6,
    ),
    Case("V-D1",
         "Сделать то же что вчера",
         error=ParserErrorCode.PARSER_FAILED),
    Case("V-D2",
         "Напомни позавчера позвонить врачу",
         error=ParserErrorCode.DATE_IN_PAST),
    Case("V-D3",
         "Позвонить врачу позавчера",
         error=ParserErrorCode.DATE_IN_PAST),
)

# Currently fail on date-prompt weekday resolution; expect success after prompt fix.
REGRESSION_CASES: tuple[Case, ...] = (
    Case(
        "X1",
        "В четверг позвонить врачу",
        title="Позвонить врачу",
        due_to=_dt(2026, 7, 16),
        due_to_has_time=False,
        weekday=3,
    ),
    Case(
        "X2",
        "В пятницу через 2 недели починить ноутбук",
        due_to=_dt(2026, 7, 31),
        due_to_has_time=False,
        weekday=4,
    ),
    Case(
        "X3",
        "В вторник через 2 недели починить ноутбук",
        due_to=_dt(2026, 7, 28),
        due_to_has_time=False,
        weekday=1,
    ),
)

CASES: tuple[Case, ...] = ORIGINAL_CASES + VARIATION_CASES + REGRESSION_CASES


def _format_mismatch(field: str, expected: Any, actual: Any) -> str:
    return f"{field}: expected {expected!r}, got {actual!r}"


def _validate_case(case: Case, parsed) -> list[str]:
    mismatches: list[str] = []

    if case.title is not None and parsed.title != case.title:
        mismatches.append(_format_mismatch("title", case.title, parsed.title))

    if case.description is not None and parsed.description != case.description:
        mismatches.append(
            _format_mismatch("description", case.description,
                             parsed.description))

    if case.due_to is not _UNSET:
        if parsed.due_to != case.due_to:
            mismatches.append(
                _format_mismatch("due_to", case.due_to, parsed.due_to))

    if case.due_to_has_time is not None:
        if parsed.due_to_has_time != case.due_to_has_time:
            mismatches.append(
                _format_mismatch(
                    "due_to_has_time",
                    case.due_to_has_time,
                    parsed.due_to_has_time,
                ))

    if case.weekday is not None:
        actual_weekday = parsed.due_to.weekday() if parsed.due_to else None
        if actual_weekday != case.weekday:
            mismatches.append(
                _format_mismatch("weekday", case.weekday, actual_weekday))

    if case.repeat_type is not None and parsed.repeat_type != case.repeat_type:
        mismatches.append(
            _format_mismatch("repeat_type", case.repeat_type,
                             parsed.repeat_type))

    if case.repeat_interval is not None:
        if parsed.repeat_interval != case.repeat_interval:
            mismatches.append(
                _format_mismatch(
                    "repeat_interval",
                    case.repeat_interval,
                    parsed.repeat_interval,
                ))

    return mismatches


def _format_multiline(value: str) -> str:
    return value.replace("\n", "\n    ")


def _print_raw_yandex_calls(calls: list[RawYandexCall]) -> None:
    for call in calls:
        print(f"  RAW {call.step} model={call.model} "
              f"user={call.user_text!r}")
        if call.response_text is not None:
            print(f"    -> {_format_multiline(call.response_text)}")
        if call.error is not None:
            print(f"    !! {call.error}")


def main() -> int:
    timezone_name = settings.DEFAULT_TIMEZONE
    now = FIXED_NOW
    client = RecordingYandexClient()
    parser = YandexGPTTaskParser(client=client)
    unexpected = 0

    print(f"now={now.isoformat()} timezone={timezone_name}")
    print(f"suite: original={len(ORIGINAL_CASES)} "
          f"variations={len(VARIATION_CASES)} "
          f"regression={len(REGRESSION_CASES)}")
    for case in CASES:
        prefix = f"[{case.case_id}]"
        call_start = len(client.calls)
        try:
            parsed = parser.parse_task(case.text, now=now)
        except ParserError as error:
            if case.error == error.code:
                print(f"EXPECTED {prefix} [{error.code}] {case.text}")
            else:
                unexpected += 1
                expected = case.error or "success"
                print(f"ERROR {prefix} [{error.code}] {case.text}: "
                      f"expected {expected}, got {error}")
            _print_raw_yandex_calls(client.calls[call_start:])
            continue
        except Exception as error:
            unexpected += 1
            print(
                f"ERROR {prefix} [{type(error).__name__}] {case.text}: {error}"
            )
            _print_raw_yandex_calls(client.calls[call_start:])
            continue

        if case.error is not None:
            unexpected += 1
            print(f"ERROR {prefix} expected {case.error}: {case.text} "
                  f"(parsed title={parsed.title!r})")
            _print_raw_yandex_calls(client.calls[call_start:])
            continue

        mismatches = _validate_case(case, parsed)
        if mismatches:
            unexpected += 1
            print(f"MISMATCH {prefix} {case.text}")
            for mismatch in mismatches:
                print(f"  - {mismatch}")
            _print_raw_yandex_calls(client.calls[call_start:])
            continue

        weekday = parsed.due_to.weekday() if parsed.due_to else None
        print(f"OK {prefix} title={parsed.title!r} due_to={parsed.due_to!s} "
              f"has_time={parsed.due_to_has_time} weekday={weekday} "
              f"repeat={parsed.repeat_type}/{parsed.repeat_interval}")
        _print_raw_yandex_calls(client.calls[call_start:])

    print(f"cases={len(CASES)} unexpected={unexpected}")
    return 1 if unexpected else 0


if __name__ == "__main__":
    raise SystemExit(main())
