"""Orchestration for creating a task from a downloaded Telegram voice."""

import logging
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

logger = logging.getLogger(__name__)


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
            logger.exception(
                "Ошибка валидации голосового сообщения | user_id=%s",
                user.id,
            )
            return self._failure("validate_voice",
                                 ErrorCode.GENERIC,
                                 user_id=user.id)

        if validation_error != ErrorCode.OK:
            return self._failure(
                "validate_voice",
                self._normalize_download_error(validation_error),
                user_id=user.id,
                duration=getattr(voice, "duration", None),
                file_size=getattr(voice, "file_size", None),
            )

        temp_path = None
        try:
            temp_path, download_error = await self._downloader.download_voice(
                voice.file_id)
            if download_error != ErrorCode.OK:
                return self._failure(
                    "download_voice",
                    self._normalize_download_error(download_error),
                    user_id=user.id,
                    file_id=voice.file_id,
                )
            if temp_path is None:
                return self._failure("download_voice",
                                     ErrorCode.GENERIC,
                                     user_id=user.id,
                                     file_id=voice.file_id,
                                     reason="empty_path")

            file_size = Path(temp_path).stat().st_size
            if file_size > self._max_size_bytes:
                return self._failure(
                    "file_size_check",
                    ErrorCode.VOICE_TOO_LARGE,
                    user_id=user.id,
                    file_size=file_size,
                    max_size=self._max_size_bytes,
                )

            return await self._create_from_file(user, Path(temp_path))
        except Exception:
            logger.exception(
                "Ошибка скачивания или обработки голосового файла | user_id=%s",
                user.id,
            )
            return self._failure("download_voice",
                                 ErrorCode.GENERIC,
                                 user_id=user.id,
                                 file_id=voice.file_id)
        finally:
            if temp_path is not None:
                try:
                    self._downloader.delete_voice(temp_path)
                except OSError:
                    logger.exception(
                        "Не удалось удалить временный голосовой файл | path=%s",
                        temp_path,
                    )

    async def _create_from_file(self, user: User,
                                file_path: Path) -> VoiceTaskResult:
        try:
            stt_result = await sync_to_async(self._stt.transcribe,
                                             thread_sensitive=False)(file_path)
        except STTError as error:
            if error.code == STTErrorCode.STT_EMPTY:
                return self._failure("stt",
                                     ErrorCode.STT_EMPTY,
                                     user_id=user.id)
            return self._failure("stt", ErrorCode.GENERIC, user_id=user.id)
        except Exception:
            logger.exception("Неожиданная ошибка SpeechKit | user_id=%s",
                             user.id)
            return self._failure("stt", ErrorCode.GENERIC, user_id=user.id)

        transcript = stt_result.text.strip()
        if not transcript:
            return self._failure("stt",
                                 ErrorCode.STT_EMPTY,
                                 user_id=user.id,
                                 reason="blank_transcript")

        try:
            if self._parser is None:
                self._parser = get_parser()
            parsed = await sync_to_async(self._parser.parse_task,
                                         thread_sensitive=False)(transcript)
        except ParserError as error:
            if error.code == ParserErrorCode.DATE_IN_PAST:
                return self._failure("parser",
                                     ErrorCode.DATE_IN_PAST,
                                     user_id=user.id)
            return self._failure("parser",
                                 ErrorCode.PARSER_FAILED,
                                 user_id=user.id)
        except Exception:
            logger.exception("Неожиданная ошибка parser | user_id=%s", user.id)
            return self._failure("parser", ErrorCode.GENERIC, user_id=user.id)

        try:
            task = await sync_to_async(
                self._task_service.create_from_parsed,
                thread_sensitive=True,
            )(user, parsed)
        except TaskDateInPastError as error:
            logger.info(
                "Валидация задачи: дата в прошлом | user_id=%s | %s",
                user.id,
                error,
            )
            return self._failure("create_task",
                                 ErrorCode.DATE_IN_PAST,
                                 user_id=user.id)
        except Exception:
            logger.exception("Ошибка создания задачи в БД | user_id=%s",
                             user.id)
            return self._failure("create_task",
                                 ErrorCode.GENERIC,
                                 user_id=user.id)

        logger.info(
            "Задача создана из голосового | user_id=%s | task_id=%s | title=%s",
            user.id,
            task.pk,
            task.title,
        )
        return VoiceTaskResult.ok(task)

    @staticmethod
    def _failure(step: str, error_code: ErrorCode,
                 **context) -> VoiceTaskResult:
        if context:
            details = " | ".join(f"{key}={value}"
                                 for key, value in context.items())
            logger.warning(
                "Voice pipeline [%s]: %s | %s",
                step,
                error_code.name,
                details,
            )
        else:
            logger.warning(
                "Voice pipeline [%s]: %s",
                step,
                error_code.name,
            )
        return VoiceTaskResult.failure(error_code)

    @staticmethod
    def _normalize_download_error(error_code) -> ErrorCode:
        try:
            normalized = ErrorCode(error_code)
        except (TypeError, ValueError):
            logger.warning(
                "Неизвестный код ошибки скачивания: %r",
                error_code,
            )
            return ErrorCode.GENERIC
        if normalized == ErrorCode.OK:
            return ErrorCode.GENERIC
        return normalized
