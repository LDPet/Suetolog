import json
import urllib.error
from datetime import datetime
from io import BytesIO
from zoneinfo import ZoneInfo

import pytest

from reminder.services.parsing import (DATE_GENERATION_JSON_SCHEMA,
                                       YANDEX_GENERATION_JSON_SCHEMA,
                                       ParserError, ParserErrorCode,
                                       YandexFoundationModelsClient,
                                       YandexGPTTaskParser, get_parser)

MSK = ZoneInfo("Europe/Moscow")
NOW = datetime(2026, 7, 4, 10, 0, tzinfo=MSK)


class StubClient:

    def __init__(self, responses):
        if isinstance(responses, list):
            self.responses = responses.copy()
        else:
            self.responses = [responses]
        self.calls = []

    def complete(self, system_prompt, user_text, json_schema=None):
        self.calls.append((system_prompt, user_text, json_schema))
        return self.responses.pop(0)


class FakeHTTPResponse:

    def __init__(self, payload):
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self):
        return self._body


def task_response(**overrides):
    payload = {
        "title": "Купить корм для кота",
        "description": None,
        "date_hint": None,
        "repeat_type": None,
        "repeat_interval": None,
    }
    payload.update(overrides)
    return json.dumps(payload, ensure_ascii=False)


def date_response(due_to, due_to_has_time=False):
    return json.dumps({
        "due_to": due_to,
        "due_to_has_time": due_to_has_time,
    })


def api_response(text):
    return {
        "result": {
            "alternatives": [{
                "message": {
                    "role": "assistant",
                    "text": text,
                }
            }]
        }
    }


@pytest.mark.parametrize(
    ("transcript", "responses", "expected"),
    [
        (
            "Купить корм для кота",
            [task_response()],
            ("Купить корм для кота", None, None, False, None, None),
        ),
        (
            "Отправить отчёт сегодня до 18, добавить цифры продаж",
            [
                task_response(
                    title="Отправить отчёт",
                    description="Добавить цифры продаж",
                    date_hint="сегодня до 18",
                ),
                date_response("2026-07-04T18:00:00+03:00", True),
            ],
            (
                "Отправить отчёт",
                "Добавить цифры продаж",
                datetime(2026, 7, 4, 18, 0, tzinfo=MSK),
                True,
                None,
                None,
            ),
        ),
        (
            "Каждый понедельник в 9 проверить финансы",
            [
                task_response(
                    title="Проверить финансы",
                    date_hint="Каждый понедельник в 9",
                    repeat_type="weekly",
                    repeat_interval=1,
                ),
                date_response("2026-07-06T09:00:00+03:00", True),
            ],
            (
                "Проверить финансы",
                None,
                datetime(2026, 7, 6, 9, 0, tzinfo=MSK),
                True,
                "weekly",
                1,
            ),
        ),
    ],
)
def test_yandex_parser_orchestrates_semantics_and_date(transcript, responses,
                                                       expected):
    client = StubClient(responses)

    parsed = YandexGPTTaskParser(client=client).parse_task(transcript, now=NOW)

    assert (
        parsed.title,
        parsed.description,
        parsed.due_to,
        parsed.due_to_has_time,
        parsed.repeat_type,
        parsed.repeat_interval,
    ) == expected
    assert parsed.raw_text == transcript
    assert len(client.calls) == len(responses)
    assert client.calls[0][2] == YANDEX_GENERATION_JSON_SCHEMA
    if len(responses) == 2:
        assert client.calls[1][2] == DATE_GENERATION_JSON_SCHEMA


def test_yandex_parser_prompt_contains_semantic_schema_and_calendar():
    client = StubClient(task_response())

    YandexGPTTaskParser(client=client).parse_task("Купить корм", now=NOW)

    system_prompt, user_text, schema = client.calls[0]
    assert "2026-07-04T10:00:00+03:00" in system_prompt
    assert "Календарь от now" in system_prompt
    assert "2026-07-05 — воскресенье" in system_prompt
    assert "date_hint" in system_prompt
    assert "Не вычисляй datetime" in system_prompt
    assert "Сделать то же что вчера" in system_prompt
    assert '"date_hint":"сегодня до 18"' in system_prompt
    assert '"date_hint":"В пятницу"' in system_prompt
    assert '"repeat_type":"minutely"' in system_prompt
    assert "Каждые две минуты помыть полы" in system_prompt
    assert user_text == "Купить корм"
    assert schema == YANDEX_GENERATION_JSON_SCHEMA
    assert "date_hint" in schema["properties"]
    assert "due_to" not in schema["properties"]
    assert "minutely" in schema["properties"]["repeat_type"]["enum"]
    assert "hourly" in schema["properties"]["repeat_type"]["enum"]


@pytest.mark.parametrize(
    ("transcript", "date_hint", "due_to"),
    [
        ("Во вторник почесать яйца", "Во вторник",
         "2026-07-14T00:00:00+03:00"),
        ("В следующую среду сходить в спортзал", "В следующую среду",
         "2026-07-22T00:00:00+03:00"),
        ("В среду через 2 недели починить ноутбук", "В среду через 2 недели",
         "2026-07-29T00:00:00+03:00"),
    ],
)
def test_yandex_parser_resolves_weekday_examples(transcript, date_hint,
                                                 due_to):
    now = datetime(2026, 7, 12, 3, 0, tzinfo=MSK)
    client = StubClient([
        task_response(title="Выполнить задачу", date_hint=date_hint),
        date_response(due_to),
    ])

    parsed = YandexGPTTaskParser(client=client).parse_task(transcript, now=now)

    assert parsed.due_to == datetime.fromisoformat(due_to)
    assert parsed.due_to.weekday() in (1, 2)
    assert parsed.due_to_has_time is False


def test_yandex_parser_rejects_weekday_mismatch():
    client = StubClient([
        task_response(title="Сходить в спортзал",
                      date_hint="в следующую среду"),
        date_response("2026-07-19T00:00:00+03:00"),
    ])

    with pytest.raises(ParserError) as exc_info:
        YandexGPTTaskParser(client=client).parse_task(
            "В следующую среду сходить в спортзал",
            now=datetime(2026, 7, 12, 3, 0, tzinfo=MSK),
        )

    assert exc_info.value.code == ParserErrorCode.PARSER_FAILED


def test_yandex_parser_discards_repeat_without_explicit_marker():
    client = StubClient([
        task_response(
            title="Почесать яйца",
            date_hint="Во вторник",
            repeat_type="weekly",
            repeat_interval=None,
        ),
        date_response("2026-07-14T00:00:00+03:00"),
    ])

    parsed = YandexGPTTaskParser(client=client).parse_task(
        "Во вторник почесать яйца",
        now=datetime(2026, 7, 12, 3, 0, tzinfo=MSK),
    )

    assert parsed.repeat_type is None
    assert parsed.repeat_interval is None


def test_yandex_parser_propagates_date_error():
    client = StubClient([
        task_response(title="Позвонить врачу", date_hint="вчера"),
        date_response("2026-07-03T00:00:00+03:00"),
    ])

    with pytest.raises(ParserError) as exc_info:
        YandexGPTTaskParser(client=client).parse_task(
            "Напомни вчера позвонить врачу",
            now=NOW,
        )

    assert exc_info.value.code == ParserErrorCode.DATE_IN_PAST


def test_yandex_parser_rejects_contextual_yesterday_as_non_task():
    client = StubClient(task_response(title="", date_hint=None))

    with pytest.raises(ParserError) as exc_info:
        YandexGPTTaskParser(client=client).parse_task(
            "Сделать то же что вчера",
            now=NOW,
        )

    assert exc_info.value.code == ParserErrorCode.PARSER_FAILED
    assert len(client.calls) == 1


def test_yandex_parser_removes_description_that_duplicates_title():
    response = task_response(
        title="Позвонить врачу",
        description="Позвонить врачу",
    )

    parsed = YandexGPTTaskParser(client=StubClient(response)).parse_task(
        "Позвонить врачу",
        now=NOW,
    )

    assert parsed.description is None


@pytest.mark.parametrize(
    "response",
    [
        "not json",
        "```json\n" + task_response() + "\n```",
        task_response(title="   "),
        task_response(unexpected="field"),
        task_response(date_hint=123),
    ],
)
def test_yandex_parser_rejects_invalid_semantic_output(response):
    with pytest.raises(ParserError) as exc_info:
        YandexGPTTaskParser(client=StubClient(response)).parse_task(
            "Купить корм",
            now=NOW,
        )

    assert exc_info.value.code == ParserErrorCode.PARSER_FAILED


def test_yandex_parser_rejects_inconsistent_explicit_repeat():
    response = task_response(
        title="Проверить финансы",
        repeat_type="weekly",
        repeat_interval=None,
    )

    with pytest.raises(ParserError) as exc_info:
        YandexGPTTaskParser(client=StubClient(response)).parse_task(
            "Каждый понедельник проверить финансы",
            now=NOW,
        )

    assert exc_info.value.code == ParserErrorCode.PARSER_FAILED


def test_yandex_parser_accepts_normalized_date_hint():
    client = StubClient([
        task_response(
            title="Собирать конструктор",
            date_hint="сегодня в 21:51",
            repeat_type="minutely",
            repeat_interval=3,
        ),
        date_response("2026-07-04T21:51:00+03:00", True),
    ])

    parsed = YandexGPTTaskParser(client=client).parse_task(
        "Собирать конструктор в 21 51 сегодня повторять каждые 3 минуты",
        now=NOW,
    )

    assert parsed.title == "Собирать конструктор"
    assert parsed.due_to == datetime(2026, 7, 4, 21, 51, tzinfo=MSK)
    assert parsed.due_to_has_time is True
    assert parsed.repeat_type == "minutely"
    assert parsed.repeat_interval == 3


def test_yandex_parser_rejects_empty_transcript_without_api_call():
    client = StubClient(task_response())

    with pytest.raises(ParserError) as exc_info:
        YandexGPTTaskParser(client=client).parse_task("   ", now=NOW)

    assert exc_info.value.code == ParserErrorCode.PARSER_FAILED
    assert client.calls == []


def test_get_parser_returns_yandex_parser(settings):
    settings.PARSER_BACKEND = "yandex"
    settings.YANDEX_API_KEY = "api-key"
    settings.YANDEX_FOLDER_ID = "folder-id"

    assert isinstance(get_parser(), YandexGPTTaskParser)


@pytest.mark.parametrize("custom_schema", [None, DATE_GENERATION_JSON_SCHEMA])
def test_yandex_client_sends_expected_request(monkeypatch, custom_schema):
    requests = []

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return FakeHTTPResponse(api_response(task_response()))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = YandexFoundationModelsClient(
        api_key="secret-key",
        folder_id="folder-id",
        model="yandexgpt-lite",
        temperature=0.1,
        max_tokens=1000,
        timeout=30,
    )

    result = client.complete("system prompt", "user text", custom_schema)

    request, timeout = requests[0]
    body = json.loads(request.data.decode("utf-8"))
    assert result == task_response()
    assert request.full_url == YandexFoundationModelsClient.ENDPOINT
    assert request.method == "POST"
    assert request.get_header("Authorization") == "Api-Key secret-key"
    assert timeout == 30
    assert body == {
        "modelUri":
        "gpt://folder-id/yandexgpt-lite",
        "completionOptions": {
            "stream": False,
            "temperature": 0.1,
            "maxTokens": "1000",
        },
        "messages": [
            {
                "role": "system",
                "text": "system prompt",
            },
            {
                "role": "user",
                "text": "user text",
            },
        ],
        "jsonSchema": {
            "schema": custom_schema or YANDEX_GENERATION_JSON_SCHEMA,
        },
    }


@pytest.mark.parametrize(
    "first_error",
    [
        TimeoutError(),
        urllib.error.HTTPError(
            YandexFoundationModelsClient.ENDPOINT,
            503,
            "Service unavailable",
            {},
            BytesIO(),
        ),
    ],
)
def test_yandex_client_retries_timeout_and_5xx(monkeypatch, first_error):
    outcomes = [first_error, FakeHTTPResponse(api_response(task_response()))]

    def fake_urlopen(request, timeout):
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = YandexFoundationModelsClient(
        api_key="secret-key",
        folder_id="folder-id",
        model="yandexgpt-lite",
        temperature=0.1,
        max_tokens=1000,
        timeout=30,
    )

    assert client.complete("system", "user") == task_response()
    assert outcomes == []


def test_yandex_client_does_not_retry_401(monkeypatch):
    calls = 0

    def fake_urlopen(request, timeout):
        nonlocal calls
        calls += 1
        raise urllib.error.HTTPError(
            YandexFoundationModelsClient.ENDPOINT,
            401,
            "Unauthorized",
            {},
            BytesIO(),
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = YandexFoundationModelsClient(
        api_key="secret-key",
        folder_id="folder-id",
        model="yandexgpt-lite",
        temperature=0.1,
        max_tokens=1000,
        timeout=30,
    )

    with pytest.raises(ParserError) as exc_info:
        client.complete("system", "user")

    assert exc_info.value.code == ParserErrorCode.PARSER_FAILED
    assert calls == 1


def test_yandex_client_stops_after_one_5xx_retry(monkeypatch):
    calls = 0

    def fake_urlopen(request, timeout):
        nonlocal calls
        calls += 1
        raise urllib.error.HTTPError(
            YandexFoundationModelsClient.ENDPOINT,
            503,
            "Service unavailable",
            {},
            BytesIO(),
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = YandexFoundationModelsClient(
        api_key="secret-key",
        folder_id="folder-id",
        model="yandexgpt-lite",
        temperature=0.1,
        max_tokens=1000,
        timeout=30,
    )

    with pytest.raises(ParserError) as exc_info:
        client.complete("system", "user")

    assert exc_info.value.code == ParserErrorCode.PARSER_FAILED
    assert calls == 2
