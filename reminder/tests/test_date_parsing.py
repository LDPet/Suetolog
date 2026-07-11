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


def date_response(due_to, due_to_has_time=False):
    return json.dumps({
        "due_to": due_to,
        "due_to_has_time": due_to_has_time,
    })


@pytest.mark.parametrize(
    ("text", "due_to", "due_to_has_time"),
    [
        ("завтра в 15:00", "2026-07-11T15:00:00+03:00", True),
        ("15 июля в 10", "2026-07-15T10:00:00+03:00", True),
        ("в понедельник в 9", "2026-07-13T09:00:00+03:00", True),
        ("только 15 июля", "2026-07-15T00:00:00+03:00", False),
        ("15 июля в 00:00", "2026-07-15T00:00:00+03:00", True),
        ("через 2 часа", "2026-07-10T14:00:00+03:00", True),
        ("перенести на послезавтра в 18", "2026-07-12T18:00:00+03:00", True),
    ],
)
def test_yandex_date_parser_parses_supported_inputs(text, due_to,
                                                    due_to_has_time):
    parser = YandexGPTDateParser(
        client=StubClient(date_response(due_to, due_to_has_time)))

    parsed = parser.parse_date(text, now=NOW)

    assert parsed.due_to == datetime.fromisoformat(due_to)
    assert parsed.due_to.tzinfo is not None
    assert parsed.due_to_has_time is due_to_has_time


def test_yandex_date_parser_normalizes_datetime_to_default_timezone():
    parser = YandexGPTDateParser(
        client=StubClient(date_response("2026-07-11T12:00:00+00:00", True)))

    parsed = parser.parse_date("завтра в 15:00", now=NOW)

    assert parsed.due_to == datetime(2026, 7, 11, 15, 0, tzinfo=MSK)
    assert parsed.due_to.tzinfo == MSK
    assert parsed.due_to_has_time is True


def test_yandex_date_parser_rejects_datetime_equal_to_now():
    parser = YandexGPTDateParser(
        client=StubClient(date_response(NOW.isoformat(), True)))

    with pytest.raises(ParserError) as exc_info:
        parser.parse_date("сейчас", now=NOW)

    assert exc_info.value.code == ParserErrorCode.DATE_IN_PAST


def test_yandex_date_parser_allows_today_without_time():
    parser = YandexGPTDateParser(
        client=StubClient(date_response("2026-07-10T00:00:00+03:00", False)))

    parsed = parser.parse_date("сегодня", now=NOW)

    assert parsed.due_to == datetime(2026, 7, 10, 0, 0, tzinfo=MSK)
    assert parsed.due_to_has_time is False


def test_yandex_date_parser_moves_past_time_only_to_tomorrow():
    parser = YandexGPTDateParser(
        client=StubClient(date_response("2026-07-10T10:00:00+03:00", True)))

    parsed = parser.parse_date("в 10:00", now=NOW)

    assert parsed.due_to == datetime(2026, 7, 11, 10, 0, tzinfo=MSK)
    assert parsed.due_to_has_time is True


def test_yandex_date_parser_does_not_move_explicit_past_date():
    parser = YandexGPTDateParser(
        client=StubClient(date_response("2026-07-10T10:00:00+03:00", True)))

    with pytest.raises(ParserError) as exc_info:
        parser.parse_date("сегодня в 10:00", now=NOW)

    assert exc_info.value.code == ParserErrorCode.DATE_IN_PAST


def test_yandex_date_parser_rejects_past_date():
    parser = YandexGPTDateParser(
        client=StubClient(date_response("2026-07-09T00:00:00+03:00", False)))

    with pytest.raises(ParserError) as exc_info:
        parser.parse_date("вчера", now=NOW)

    assert exc_info.value.code == ParserErrorCode.DATE_IN_PAST


@pytest.mark.parametrize("text", ["asdf", "потом"])
def test_yandex_date_parser_rejects_unrecognized_text(text):
    parser = YandexGPTDateParser(client=StubClient(date_response(None, False)))

    with pytest.raises(ParserError) as exc_info:
        parser.parse_date(text, now=NOW)

    assert exc_info.value.code == ParserErrorCode.PARSER_FAILED


def test_yandex_date_parser_rejects_empty_text_without_api_call():
    client = StubClient(date_response("2026-07-11T15:00:00+03:00", True))

    with pytest.raises(ParserError) as exc_info:
        YandexGPTDateParser(client=client).parse_date("   ", now=NOW)

    assert exc_info.value.code == ParserErrorCode.PARSER_FAILED
    assert client.calls == []


@pytest.mark.parametrize(
    "response",
    [
        "not json",
        '```json\n{"due_to":"2026-07-11T15:00:00+03:00","due_to_has_time":true}\n```',
        "{}",
        '{"due_to":null,"due_to_has_time":false,"title":"Лишнее поле"}',
        '{"due_to":123,"due_to_has_time":true}',
        '{"due_to":"not-a-date","due_to_has_time":true}',
        '{"due_to":"not-a-date","due_to_has_time":false}',
        '{"due_to":"2026-07-11T15:00:00","due_to_has_time":true}',
        '{"due_to":null,"due_to_has_time":true}',
        '{"due_to":"2026-07-11T15:00:00+03:00","due_to_has_time":"yes"}',
    ],
)
def test_yandex_date_parser_rejects_invalid_model_output(response):
    parser = YandexGPTDateParser(client=StubClient(response))

    with pytest.raises(ParserError) as exc_info:
        parser.parse_date("завтра в 15:00", now=NOW)

    assert exc_info.value.code == ParserErrorCode.PARSER_FAILED


def test_yandex_date_parser_uses_separate_prompt_and_schema():
    client = StubClient(date_response("2026-07-11T15:00:00+03:00", True))

    YandexGPTDateParser(client=client).parse_date("завтра в 15:00", now=NOW)

    system_prompt, user_text, schema = client.calls[0]
    assert "2026-07-10T12:00:00+03:00" in system_prompt
    assert "только дату или время" in system_prompt
    assert "ближайшее такое время" in system_prompt
    assert "строго позже now, иначе завтра" in system_prompt
    assert '"required":["due_to","due_to_has_time"]' in system_prompt
    assert "due_to_has_time=true" in system_prompt
    assert "title или description" in system_prompt
    assert user_text == "завтра в 15:00"
    assert schema == DATE_GENERATION_JSON_SCHEMA


def test_yandex_date_parser_distinguishes_date_from_explicit_midnight():
    client = StubClient(date_response("2026-07-17T00:00:00+03:00", True))

    YandexGPTDateParser(client=client).parse_date("в пятницу в 00:00", now=NOW)

    system_prompt = client.calls[0][0]
    assert ('"в пятницу" -> '
            '{"due_to":"2026-07-10T00:00:00+03:00",'
            '"due_to_has_time":false}') in system_prompt
    assert ('"в пятницу в 00:00" -> '
            '{"due_to":"2026-07-17T00:00:00+03:00",'
            '"due_to_has_time":true}') in system_prompt


def test_yandex_date_parser_requires_credentials(settings):
    settings.YANDEX_API_KEY = ""
    settings.YANDEX_FOLDER_ID = ""

    with pytest.raises(ParserConfigurationError, match="YANDEX_API_KEY"):
        YandexGPTDateParser()
