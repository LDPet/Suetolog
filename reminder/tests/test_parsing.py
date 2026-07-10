from datetime import datetime

import pytest

from reminder.services.parsing import (MockTaskParser,
                                       ParserConfigurationError, ParserError,
                                       ParserErrorCode, get_parser)


def test_mock_parser_parses_task_without_date():
    parsed = MockTaskParser().parse_task(
        "купить молоко без даты",
        now=datetime(2026, 7, 10, 12, 0),
    )

    assert parsed.title == "купить молоко"
    assert parsed.raw_text == "купить молоко без даты"
    assert parsed.due_to is None


def test_mock_parser_parses_tomorrow_with_numeric_time():
    parsed = MockTaskParser().parse_task(
        "завтра в 15 позвонить врачу",
        now=datetime(2026, 7, 10, 12, 0),
    )

    assert parsed.title == "позвонить врачу"
    assert parsed.due_to == datetime(2026, 7, 11, 15, 0)


def test_mock_parser_parses_tomorrow_with_word_time():
    parsed = MockTaskParser().parse_task(
        "завтра в три часа позвонить маме",
        now=datetime(2026, 7, 10, 12, 0),
    )

    assert parsed.title == "позвонить маме"
    assert parsed.due_to == datetime(2026, 7, 11, 3, 0)


def test_mock_parser_parses_weekday_with_default_time():
    parsed = MockTaskParser().parse_task(
        "напомни в понедельник проверить почту",
        now=datetime(2026, 7, 10, 12, 0),
    )

    assert parsed.title == "проверить почту"
    assert parsed.due_to == datetime(2026, 7, 13, 9, 0)


def test_mock_parser_keeps_tomorrow_without_time_undated():
    parsed = MockTaskParser().parse_task(
        "завтра купить хлеб",
        now=datetime(2026, 7, 10, 12, 0),
    )

    assert parsed.title == "купить хлеб"
    assert parsed.due_to is None


@pytest.mark.parametrize("text", ["", "   ", "э-э-э...", "молоко"])
def test_mock_parser_raises_parser_failed_for_unstable_text(text):
    with pytest.raises(ParserError) as exc_info:
        MockTaskParser().parse_task(text, now=datetime(2026, 7, 10, 12, 0))

    assert exc_info.value.code == ParserErrorCode.PARSER_FAILED


def test_mock_parser_raises_date_in_past():
    with pytest.raises(ParserError) as exc_info:
        MockTaskParser().parse_task(
            "напомни вчера позвонить врачу",
            now=datetime(2026, 7, 10, 12, 0),
        )

    assert exc_info.value.code == ParserErrorCode.DATE_IN_PAST


def test_get_parser_returns_mock_for_default_backend(settings):
    settings.PARSER_BACKEND = "mock"

    assert isinstance(get_parser(), MockTaskParser)


def test_get_parser_requires_yandex_credentials(settings):
    settings.PARSER_BACKEND = "yandex"
    settings.YANDEX_API_KEY = ""
    settings.YANDEX_FOLDER_ID = ""

    with pytest.raises(ParserConfigurationError, match="YANDEX_API_KEY"):
        get_parser()


def test_get_parser_raises_configuration_error_for_unknown_backend(settings):
    settings.PARSER_BACKEND = "unknown"

    with pytest.raises(ParserConfigurationError, match="PARSER_BACKEND"):
        get_parser()
