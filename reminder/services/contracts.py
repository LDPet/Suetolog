"""Контракты сервисов для обработки входных данных.
Контракты фиксируют, какие методы должны быть у сервисов,
которые используются в создании задачи.
"""

from datetime import datetime
from pathlib import Path
from typing import Protocol

from errors import ErrorCode
from reminder.services.dto import ParsedDateResult, ParsedTaskInput, STTResult


class VoiceInput(Protocol):
    file_id: str
    duration: int
    file_size: int


class VoiceFileDownloader(Protocol):

    def validate_voice(self, voice: VoiceInput) -> ErrorCode:
        ...

    async def download_voice(self,
                             file_id: str) -> tuple[Path | None, ErrorCode]:
        ...

    def delete_voice(self, file_path: Path) -> None:
        ...


class STTService(Protocol):

    def transcribe(self, audio_path: str | Path) -> STTResult:
        ...


class TaskParser(Protocol):

    def parse_task(self,
                   text: str,
                   now: datetime | None = None) -> ParsedTaskInput:
        ...


class DateParser(Protocol):

    def parse_date(self,
                   text: str,
                   now: datetime | None = None) -> ParsedDateResult:
        """Распознать дату вместе с признаком явно указанного времени."""
        ...
