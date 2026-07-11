"""Orchestration for creating a task from a downloaded Telegram voice."""

from pathlib import Path

from asgiref.sync import sync_to_async
from django.conf import settings

from errors import ErrorCode
from reminder.models import User
from reminder.services.contracts import (STTService, TaskParser,
                                         VoiceFileDownloader, VoiceInput)
from reminder.services.dto import VoiceTaskResult
from reminder.services.parsing import ParserError, ParserErrorCode, get_parser
from reminder.services.stt import STTError, STTErrorCode
from reminder.services.tasks import TaskDateInPastError, TaskService


class VoiceTaskCreationService:

    def __init__(
        self,
        downloader: VoiceFileDownloader,
        stt: STTService,
        parser: TaskParser | None = None,
        task_service: TaskService | None = None,
        max_size_bytes: int | None = None,
    ):
        self._downloader = downloader
        self._stt = stt
        self._parser = parser
        self._task_service = task_service or TaskService()
        self._max_size_bytes = (max_size_bytes if max_size_bytes is not None
                                else getattr(settings, "VOICE_MAX_SIZE_BYTES",
                                             20 * 1024 * 1024))

    async def create_from_voice(self, user: User,
                                voice: VoiceInput) -> VoiceTaskResult:
        try:
            validation_error = self._downloader.validate_voice(voice)
        except Exception:
            return VoiceTaskResult.failure(ErrorCode.GENERIC)

        if validation_error != ErrorCode.OK:
            return VoiceTaskResult.failure(
                self._normalize_download_error(validation_error))

        temp_path = None
        try:
            temp_path, download_error = await self._downloader.download_voice(
                voice.file_id)
            if download_error != ErrorCode.OK:
                return VoiceTaskResult.failure(
                    self._normalize_download_error(download_error))
            if temp_path is None:
                return VoiceTaskResult.failure(ErrorCode.GENERIC)

            if Path(temp_path).stat().st_size > self._max_size_bytes:
                return VoiceTaskResult.failure(ErrorCode.VOICE_TOO_LARGE)

            return await self._create_from_file(user, Path(temp_path))
        except Exception:
            return VoiceTaskResult.failure(ErrorCode.GENERIC)
        finally:
            if temp_path is not None:
                try:
                    self._downloader.delete_voice(temp_path)
                except OSError:
                    pass

    async def _create_from_file(self, user: User,
                                file_path: Path) -> VoiceTaskResult:
        try:
            stt_result = await sync_to_async(self._stt.transcribe,
                                             thread_sensitive=False)(file_path)
        except STTError as error:
            if error.code == STTErrorCode.STT_EMPTY:
                return VoiceTaskResult.failure(ErrorCode.STT_EMPTY)
            return VoiceTaskResult.failure(ErrorCode.GENERIC)
        except Exception:
            return VoiceTaskResult.failure(ErrorCode.GENERIC)

        transcript = stt_result.text.strip()
        if not transcript:
            return VoiceTaskResult.failure(ErrorCode.STT_EMPTY)

        try:
            if self._parser is None:
                self._parser = get_parser()
            parsed = await sync_to_async(self._parser.parse_task,
                                         thread_sensitive=False)(transcript)
        except ParserError as error:
            if error.code == ParserErrorCode.DATE_IN_PAST:
                return VoiceTaskResult.failure(ErrorCode.DATE_IN_PAST)
            return VoiceTaskResult.failure(ErrorCode.PARSER_FAILED)
        except Exception:
            return VoiceTaskResult.failure(ErrorCode.GENERIC)

        try:
            task = await sync_to_async(
                self._task_service.create_from_parsed,
                thread_sensitive=True,
            )(user, parsed)
        except TaskDateInPastError:
            return VoiceTaskResult.failure(ErrorCode.DATE_IN_PAST)
        except Exception:
            return VoiceTaskResult.failure(ErrorCode.GENERIC)

        return VoiceTaskResult.ok(task)

    @staticmethod
    def _normalize_download_error(error_code) -> ErrorCode:
        try:
            normalized = ErrorCode(error_code)
        except (TypeError, ValueError):
            return ErrorCode.GENERIC
        if normalized == ErrorCode.OK:
            return ErrorCode.GENERIC
        return normalized
