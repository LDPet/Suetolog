import json
import urllib.error
from datetime import datetime
from io import BytesIO
from zoneinfo import ZoneInfo

import pytest

from reminder.services.parsing import (YANDEX_GENERATION_JSON_SCHEMA,
                                       ParserError, ParserErrorCode,
                                       YandexFoundationModelsClient,
                                       YandexGPTTaskParser, get_parser)

MSK = ZoneInfo("Europe/Moscow")
NOW = datetime(2026, 7, 4, 10, 0, tzinfo=MSK)


class StubClient:

    def __init__(self, response):
        self.response = response
        self.calls = []

    def complete(self, system_prompt, user_text):
        self.calls.append((system_prompt, user_text))
        return self.response


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
        "due_to": None,
        "repeat_type": None,
        "repeat_interval": None,
    }
    payload.update(overrides)
    return json.dumps(payload, ensure_ascii=False)


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
    ("transcript", "response", "expected"),
    [
        (
            "Купить корм для кота",
            task_response(),
            {
                "title": "Купить корм для кота",
                "description": None,
                "due_to": None,
                "repeat_type": None,
                "repeat_interval": None,
            },
        ),
        (
            "Отправить отчёт сегодня до 18, добавить цифры продаж",
            task_response(
                title="Отправить отчёт",
                description="Добавить цифры продаж",
                due_to="2026-07-04T18:00:00+03:00",
            ),
            {
                "title": "Отправить отчёт",
                "description": "Добавить цифры продаж",
                "due_to": datetime(2026, 7, 4, 18, 0, tzinfo=MSK),
                "repeat_type": None,
                "repeat_interval": None,
            },
        ),
        (
            "Каждый понедельник в 9 проверить финансы",
            task_response(
                title="Проверить финансы",
                repeat_type="weekly",
                repeat_interval=1,
            ),
            {
                "title": "Проверить финансы",
                "description": None,
                "due_to": None,
                "repeat_type": "weekly",
                "repeat_interval": 1,
            },
        ),
    ],
)
def test_yandex_parser_parses_voice_pipeline_examples(transcript, response,
                                                      expected):
    client = StubClient(response)

    parsed = YandexGPTTaskParser(client=client).parse_task(transcript, now=NOW)

    assert parsed.title == expected["title"]
    assert parsed.description == expected["description"]
    assert parsed.due_to == expected["due_to"]
    assert parsed.repeat_type == expected["repeat_type"]
    assert parsed.repeat_interval == expected["repeat_interval"]
    assert parsed.raw_text == transcript


def test_yandex_parser_prompt_contains_now_schema_and_examples():
    client = StubClient(task_response())

    YandexGPTTaskParser(client=client).parse_task("Купить корм", now=NOW)

    system_prompt, user_text = client.calls[0]
    assert "2026-07-04T10:00:00+03:00" in system_prompt
    assert '"additionalProperties":false' in system_prompt
    assert '"minLength":0' in system_prompt
    assert "Отправить отчёт сегодня до 18" in system_prompt
    assert "Каждый понедельник в 9" in system_prompt
    assert "В пятницу позвонить врачу" in system_prompt
    assert "Одна дата («в пятницу», «во вторник»)" in system_prompt
    assert "Служебные слова «напомни»" in system_prompt
    assert "При словах «и потом», «затем», «после этого»" in system_prompt
    assert "ближайшее строго будущее первое выполнение" in system_prompt
    assert "По пятницам в 9 проверять финансы" in system_prompt
    assert "Сделать то же что вчера" in system_prompt
    assert '"due_to":"2026-07-10T00:00:00+03:00"' in system_prompt
    assert '"due_to":"2026-07-10T09:00:00+03:00"' in system_prompt
    assert '"due_to":"2026-07-05T15:30:00+03:00"' in system_prompt
    assert '"due_to":"2026-07-03T00:00:00+03:00"' in system_prompt
    assert user_text == "Купить корм"


def test_yandex_parser_allows_due_date_equal_to_now():
    response = task_response(due_to=NOW.isoformat())

    parsed = YandexGPTTaskParser(client=StubClient(response)).parse_task(
        "Купить корм сейчас",
        now=NOW,
    )

    assert parsed.due_to == NOW


def test_yandex_parser_reports_empty_title_after_schema_validation():
    with pytest.raises(ParserError,
                       match="YandexGPT returned an empty task title"):
        YandexGPTTaskParser(client=StubClient(task_response(
            title=""))).parse_task(
                "Привет как дела",
                now=NOW,
            )


def test_yandex_parser_removes_description_that_duplicates_title():
    response = task_response(
        title="Позвонить врачу",
        description="Позвонить врачу",
        due_to="2026-07-04T18:00:00+03:00",
    )

    parsed = YandexGPTTaskParser(client=StubClient(response)).parse_task(
        "Напомни сегодня в 18:00 позвонить врачу",
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
        task_response(due_to="2026-07-05T12:00:00"),
        task_response(repeat_type="weekly", repeat_interval=None),
    ],
)
def test_yandex_parser_rejects_invalid_model_output(response):
    with pytest.raises(ParserError) as exc_info:
        YandexGPTTaskParser(client=StubClient(response)).parse_task(
            "Купить корм",
            now=NOW,
        )

    assert exc_info.value.code == ParserErrorCode.PARSER_FAILED


def test_yandex_parser_rejects_past_date():
    response = task_response(
        title="Сделать то же что вчера",
        due_to="2026-07-03T10:00:00+03:00",
    )

    with pytest.raises(ParserError) as exc_info:
        YandexGPTTaskParser(client=StubClient(response)).parse_task(
            "Сделать то же что вчера",
            now=NOW,
        )

    assert exc_info.value.code == ParserErrorCode.DATE_IN_PAST


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


def test_yandex_client_sends_expected_request(monkeypatch):
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

    result = client.complete("system prompt", "user text")

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
            "schema": YANDEX_GENERATION_JSON_SCHEMA,
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
