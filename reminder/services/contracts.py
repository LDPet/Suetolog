"""Контракты сервисов для обработки входных данных.
Контракты фиксируют, какие методы должны быть у сервисов,
которые используются в создании задачи.
"""

from datetime import datetime
from pathlib import Path
from typing import Protocol

from reminder.services.dto import ParsedTaskInput, STTResult


class STTService(Protocol):

    def transcribe(self, audio_path: str | Path) -> STTResult:
        ...


class TaskParser(Protocol):

    def parse_task(self,
                   text: str,
                   now: datetime | None = None) -> ParsedTaskInput:
        ...


class DateParser(Protocol):

    def parse_date(self, text: str, now: datetime | None = None) -> datetime:
        ...
