"""Контракты сервисов для обработки входных данных.
Контракты фиксируют, какие методы должны быть у сервисов,
которые используются в создании задачи.
"""

from datetime import datetime
from typing import Protocol

from reminder.services.dto import ParsedTaskInput


class TaskParser(Protocol):
    def parse_task(
            self,
            text: str,
            now: datetime | None = None
    ) -> ParsedTaskInput:
        ...
