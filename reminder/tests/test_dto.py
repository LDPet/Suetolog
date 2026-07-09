from datetime import datetime, timedelta

import pytest

from reminder.services.dto import ParsedTaskInput


def test_parsed_task_input_can_be_created_with_required_fields():
    parsed = ParsedTaskInput(
        title="Позвонить врачу",
        raw_text="Напомни завтра позвонить врачу",
    )

    assert parsed.title == "Позвонить врачу"
    assert parsed.raw_text == "Напомни завтра позвонить врачу"
    assert parsed.due_to is None
    assert parsed.description is None
    assert parsed.repeat_type is None
    assert parsed.repeat_interval is None


def test_parsed_task_input_accepts_due_to_relative_to_now():
    now = datetime(2026, 7, 10, 12, 0)
    due_to = now + timedelta(days=3)

    parsed = ParsedTaskInput(
        title="Позвонить врачу",
        raw_text="Напомни через три дня позвонить врачу",
        due_to=due_to,
    )

    assert parsed.due_to == datetime(2026, 7, 13, 12, 0)


def test_empty_title_is_invalid():
    with pytest.raises(ValueError,
                       match="Название задачи не может быть пустым"):
        ParsedTaskInput(
            title="",
            raw_text="Напомни завтра позвонить врачу",
        )


def test_blank_title_is_invalid():
    with pytest.raises(ValueError,
                       match="Название задачи не может быть пустым"):
        ParsedTaskInput(
            title="   ",
            raw_text="Напомни завтра позвонить врачу",
        )


def test_empty_raw_text_is_invalid():
    with pytest.raises(ValueError,
                       match="Исходный текст задачи не может быть пустым"):
        ParsedTaskInput(
            title="Позвонить врачу",
            raw_text="",
        )


def test_blank_raw_text_is_invalid():
    with pytest.raises(ValueError,
                       match="Исходный текст задачи не может быть пустым"):
        ParsedTaskInput(
            title="Позвонить врачу",
            raw_text="   ",
        )


def test_repeat_interval_requires_repeat_type():
    with pytest.raises(ValueError,
                       match="Интервал повтора задан без типа повтора"):
        ParsedTaskInput(
            title="Тренировка",
            raw_text="Напомни каждые 2 дня тренироваться",
            repeat_interval=2,
        )


def test_repeat_type_requires_repeat_interval():
    with pytest.raises(ValueError,
                       match="Тип повтора указан без интервала повтора"):
        ParsedTaskInput(
            title="Тренировка",
            raw_text="Напомни каждую неделю тренироваться",
            repeat_type="weekly",
        )


def test_repeat_interval_must_be_positive():
    with pytest.raises(ValueError,
                       match="Интервал повтора не может быть меньше 1"):
        ParsedTaskInput(
            title="Тренировка",
            raw_text="Напомни каждую неделю тренироваться",
            repeat_type="weekly",
            repeat_interval=0,
        )


def test_valid_repeat_is_accepted():
    parsed = ParsedTaskInput(
        title="Тренировка",
        raw_text="Напомни каждую неделю тренироваться",
        repeat_type="weekly",
        repeat_interval=1,
    )

    assert parsed.repeat_type == "weekly"
    assert parsed.repeat_interval == 1
