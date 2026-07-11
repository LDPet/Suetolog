"""DTO для передачи результата разбора задачи между сервисами."""
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from errors import ErrorCode

if TYPE_CHECKING:
    from reminder.models import Task


@dataclass(frozen=True)
class STTResult:
    text: str
    language: str | None = "ru-RU"
    provider: str = "yandex_speechkit"


@dataclass(frozen=True)
class VoiceTaskResult:
    success: bool
    task: "Task | None" = None
    error_code: ErrorCode | None = None

    def __post_init__(self):
        if self.success:
            if self.task is None or self.error_code is not None:
                raise ValueError(
                    "Successful voice result requires only a task.")
            return

        if self.task is not None or self.error_code in (None, ErrorCode.OK):
            raise ValueError(
                "Failed voice result requires only a non-OK error code.")

    @classmethod
    def ok(cls, task: "Task") -> "VoiceTaskResult":
        return cls(success=True, task=task)

    @classmethod
    def failure(cls, error_code: ErrorCode) -> "VoiceTaskResult":
        return cls(success=False, error_code=error_code)


@dataclass(frozen=True)
class ParsedTaskInput:
    title: str
    raw_text: str
    due_to: datetime | None = None
    description: str | None = None
    repeat_type: str | None = None
    repeat_interval: int | None = None

    def __post_init__(self):
        if not self.title.strip():
            raise ValueError("Название задачи не может быть пустым")

        if not self.raw_text.strip():
            raise ValueError('Исходный текст задачи не может быть пустым')

        if self.repeat_type is None and self.repeat_interval is not None:
            raise ValueError("Интервал повтора задан без типа повтора")

        if self.repeat_type is not None and self.repeat_interval is None:
            raise ValueError("Тип повтора указан без интервала повтора")

        if self.repeat_interval is not None and self.repeat_interval < 1:
            raise ValueError("Интервал повтора не может быть меньше 1")
