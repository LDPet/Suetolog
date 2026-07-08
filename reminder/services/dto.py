"""DTO для передачи результата разбора задачи между сервисами."""
from dataclasses import dataclass
from datetime import datetime


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
