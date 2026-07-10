import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from reminder.services.parsing import (DATE_GENERATION_JSON_SCHEMA,
                                       ParserConfigurationError, ParserError,
                                       ParserErrorCode, YandexGPTDateParser)

MSK = ZoneInfo("Europe/Moscow")
NOW = datetime(2026, 7, 10, 12, 0, tzinfo=MSK)


class StubClient:

    def __init__(self, response):
        self.response = response
        self.calls = []

    def complete(self, system_prompt, user_text, json_schema=None):
        self.calls.append((system_prompt, user_text, json_schema))
        return self.response


def date_response(due_to):
    return json.dumps({"due_to": due_to})


@pytest.mark.parametrize(
    ("text", "due_to"),
    [
        ("завтра в 15:00", "2026-07-11T15:00:00+03:00"),
        ("15 июля в 10", "2026-07-15T10:00:00+03:00"),
        ("в понедельник в 9", "2026-07-13T09:00:00+03:00"),
        ("только 15 июля", "2026-07-15T00:00:00+03:00"),
        ("через 2 часа", "2026-07-10T14:00:00+03:00"),
        ("перенести на послезавтра в 18", "2026-07-12T18:00:00+03:00"),
    ],
)
def test_yandex_date_parser_parses_supported_inputs(text, due_to):
    parser = YandexGPTDateParser(client=StubClient(date_response(due_to)))

    parsed = parser.parse_date(text, now=NOW)

    assert parsed == datetime.fromisoformat(due_to)
    assert parsed.tzinfo is not None


def test_yandex_date_parser_normalizes_datetime_to_default_timezone():
    parser = YandexGPTDateParser(
        client=StubClient(date_response("2026-07-11T12:00:00+00:00")))

    parsed = parser.parse_date("завтра в 15:00", now=NOW)

    assert parsed == datetime(2026, 7, 11, 15, 0, tzinfo=MSK)
    assert parsed.tzinfo == MSK


def test_yandex_date_parser_allows_datetime_equal_to_now():
    parser = YandexGPTDateParser(
        client=StubClient(date_response(NOW.isoformat())))

    assert parser.parse_date("сейчас", now=NOW) == NOW


def test_yandex_date_parser_moves_past_time_only_to_tomorrow():
    parser = YandexGPTDateParser(
        client=StubClient(date_response("2026-07-10T10:00:00+03:00")))

    parsed = parser.parse_date("в 10:00", now=NOW)

    assert parsed == datetime(2026, 7, 11, 10, 0, tzinfo=MSK)


def test_yandex_date_parser_does_not_move_explicit_past_date():
    parser = YandexGPTDateParser(
        client=StubClient(date_response("2026-07-10T10:00:00+03:00")))

    with pytest.raises(ParserError) as exc_info:
        parser.parse_date("сегодня в 10:00", now=NOW)

    assert exc_info.value.code == ParserErrorCode.DATE_IN_PAST


def test_yandex_date_parser_rejects_past_date():
    parser = YandexGPTDateParser(
        client=StubClient(date_response("2026-07-09T12:00:00+03:00")))

    with pytest.raises(ParserError) as exc_info:
        parser.parse_date("вчера", now=NOW)

    assert exc_info.value.code == ParserErrorCode.DATE_IN_PAST


@pytest.mark.parametrize("text", ["asdf", "потом"])
def test_yandex_date_parser_rejects_unrecognized_text(text):
    parser = YandexGPTDateParser(client=StubClient(date_response(None)))

    with pytest.raises(ParserError) as exc_info:
        parser.parse_date(text, now=NOW)

    assert exc_info.value.code == ParserErrorCode.PARSER_FAILED


def test_yandex_date_parser_rejects_empty_text_without_api_call():
    client = StubClient(date_response("2026-07-11T15:00:00+03:00"))

    with pytest.raises(ParserError) as exc_info:
        YandexGPTDateParser(client=client).parse_date("   ", now=NOW)

    assert exc_info.value.code == ParserErrorCode.PARSER_FAILED
    assert client.calls == []


@pytest.mark.parametrize(
    "response",
    [
        "not json",
        '```json\n{"due_to":"2026-07-11T15:00:00+03:00"}\n```',
        "{}",
        '{"due_to":null,"title":"Лишнее поле"}',
        '{"due_to":123}',
        '{"due_to":"not-a-date"}',
        '{"due_to":"2026-07-11T15:00:00"}',
    ],
)
def test_yandex_date_parser_rejects_invalid_model_output(response):
    parser = YandexGPTDateParser(client=StubClient(response))

    with pytest.raises(ParserError) as exc_info:
        parser.parse_date("завтра в 15:00", now=NOW)

    assert exc_info.value.code == ParserErrorCode.PARSER_FAILED


def test_yandex_date_parser_uses_separate_prompt_and_schema():
    client = StubClient(date_response("2026-07-11T15:00:00+03:00"))

    YandexGPTDateParser(client=client).parse_date("завтра в 15:00", now=NOW)

    system_prompt, user_text, schema = client.calls[0]
    assert "2026-07-10T12:00:00+03:00" in system_prompt
    assert "только дату или время" in system_prompt
    assert "ближайшее такое время" in system_prompt
    assert "не раньше now, иначе завтра" in system_prompt
    assert '"required":["due_to"]' in system_prompt
    assert "title или description" in system_prompt
    assert user_text == "завтра в 15:00"
    assert schema == DATE_GENERATION_JSON_SCHEMA


def test_yandex_date_parser_requires_credentials(settings):
    settings.YANDEX_API_KEY = ""
    settings.YANDEX_FOLDER_ID = ""

    with pytest.raises(ParserConfigurationError, match="YANDEX_API_KEY"):
        YandexGPTDateParser()
