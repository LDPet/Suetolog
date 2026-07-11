import asyncio
import inspect
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone

from errors import ErrorCode
from reminder.models import Task, TaskEvent
from reminder.repositories.task_event import TaskEventRepository
from reminder.services.dto import ParsedTaskInput, STTResult, VoiceTaskResult
from reminder.services.parsing import ParserError, ParserErrorCode
from reminder.services.stt import STTError, STTErrorCode
from reminder.services.tasks import TaskService
from reminder.services.voice_tasks import VoiceTaskCreationService

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def voice():
    return SimpleNamespace(
        file_id="voice-file-id",
        duration=10,
        file_size=100,
    )


@pytest.fixture
def audio_path(tmp_path):
    path = tmp_path / "voice.ogg"
    path.write_bytes(b"ogg-opus-audio")
    return path


@pytest.fixture
def downloader(audio_path):
    service = Mock()
    service.validate_voice = Mock(return_value=ErrorCode.OK)
    service.download_voice = AsyncMock(return_value=(audio_path, ErrorCode.OK))
    service.delete_voice = Mock(
        side_effect=lambda path: Path(path).unlink(missing_ok=True))
    return service


@pytest.fixture
def stt():
    service = Mock()
    service.transcribe = Mock(return_value=STTResult(
        text="  завтра в 15 позвонить врачу  "))
    return service


@pytest.fixture
def parser():
    service = Mock()
    service.parse_task = Mock(return_value=ParsedTaskInput(
        title="Позвонить врачу",
        raw_text="завтра в 15 позвонить врачу",
        due_to=(timezone.now() + timedelta(days=1)).replace(
            hour=15,
            minute=0,
            second=0,
            microsecond=0,
        ),
    ))
    return service


def build_service(downloader,
                  stt,
                  parser,
                  task_service=None,
                  max_size_bytes=None):
    return VoiceTaskCreationService(
        downloader=downloader,
        stt=stt,
        parser=parser,
        task_service=task_service,
        max_size_bytes=max_size_bytes,
    )


async def db_call(function):
    return await sync_to_async(function, thread_sensitive=True)()


@pytest.mark.asyncio
async def test_happy_path_creates_task_reminder_and_event(
        user, voice, audio_path, downloader, stt, parser):
    service = build_service(downloader, stt, parser)

    result = await service.create_from_voice(user, voice)

    assert result.success is True
    assert result.error_code is None
    assert result.task.title == "Позвонить врачу"
    assert await db_call(result.task.reminders.count) == 1
    assert await db_call(result.task.events.count) == 1
    assert await db_call(Task.objects.count) == 1
    downloader.validate_voice.assert_called_once_with(voice)
    downloader.download_voice.assert_awaited_once_with(voice.file_id)
    stt.transcribe.assert_called_once_with(audio_path)
    parser.parse_task.assert_called_once_with("завтра в 15 позвонить врачу")
    downloader.delete_voice.assert_called_once_with(audio_path)
    assert not audio_path.exists()


@pytest.mark.asyncio
async def test_voice_without_date_creates_task_without_reminder(
        user, voice, downloader, stt, parser):
    parser.parse_task.return_value = ParsedTaskInput(
        title="Купить молоко",
        raw_text="купить молоко без даты",
    )
    service = build_service(downloader, stt, parser)

    result = await service.create_from_voice(user, voice)

    assert result.success is True
    assert result.task.due_to is None
    assert await db_call(result.task.reminders.count) == 0
    event_types = await db_call(
        lambda: list(result.task.events.values_list("event_type", flat=True)))
    assert event_types == [TaskEvent.EventType.CREATED]


@pytest.mark.asyncio
async def test_voice_limit_stops_before_download(user, voice, downloader, stt,
                                                 parser):
    downloader.validate_voice.return_value = ErrorCode.VOICE_TOO_LONG
    service = build_service(downloader, stt, parser)

    result = await service.create_from_voice(user, voice)

    assert result == VoiceTaskResult.failure(ErrorCode.VOICE_TOO_LONG)
    downloader.download_voice.assert_not_awaited()
    stt.transcribe.assert_not_called()
    parser.parse_task.assert_not_called()
    assert await db_call(Task.objects.count) == 0


@pytest.mark.asyncio
async def test_downloaded_file_size_is_checked_and_cleaned(
        user, voice, audio_path, downloader, stt, parser):
    service = build_service(downloader,
                            stt,
                            parser,
                            max_size_bytes=audio_path.stat().st_size - 1)

    result = await service.create_from_voice(user, voice)

    assert result == VoiceTaskResult.failure(ErrorCode.VOICE_TOO_LARGE)
    stt.transcribe.assert_not_called()
    parser.parse_task.assert_not_called()
    downloader.delete_voice.assert_called_once_with(audio_path)
    assert not audio_path.exists()


@pytest.mark.asyncio
async def test_download_error_with_temp_file_still_cleans_up(
        user, voice, audio_path, downloader, stt, parser):
    downloader.download_voice.return_value = (audio_path, ErrorCode.GENERIC)
    service = build_service(downloader, stt, parser)

    result = await service.create_from_voice(user, voice)

    assert result == VoiceTaskResult.failure(ErrorCode.GENERIC)
    stt.transcribe.assert_not_called()
    downloader.delete_voice.assert_called_once_with(audio_path)
    assert not audio_path.exists()


@pytest.mark.asyncio
async def test_stt_empty_error_is_mapped_and_temp_file_is_deleted(
        user, voice, audio_path, downloader, stt, parser):
    stt.transcribe.side_effect = STTError(STTErrorCode.STT_EMPTY,
                                          "Empty transcript")
    service = build_service(downloader, stt, parser)

    result = await service.create_from_voice(user, voice)

    assert result == VoiceTaskResult.failure(ErrorCode.STT_EMPTY)
    parser.parse_task.assert_not_called()
    assert await db_call(Task.objects.count) == 0
    assert not audio_path.exists()


@pytest.mark.asyncio
async def test_whitespace_transcript_is_stt_empty(user, voice, audio_path,
                                                  downloader, stt, parser):
    stt.transcribe.return_value = STTResult(text="   ")
    service = build_service(downloader, stt, parser)

    result = await service.create_from_voice(user, voice)

    assert result == VoiceTaskResult.failure(ErrorCode.STT_EMPTY)
    parser.parse_task.assert_not_called()
    assert not audio_path.exists()


@pytest.mark.parametrize(
    ("parser_code", "expected_error"),
    [
        (ParserErrorCode.PARSER_FAILED, ErrorCode.PARSER_FAILED),
        (ParserErrorCode.DATE_IN_PAST, ErrorCode.DATE_IN_PAST),
    ],
)
@pytest.mark.asyncio
async def test_parser_errors_are_mapped_without_partial_task(
        user, voice, audio_path, downloader, stt, parser, parser_code,
        expected_error):
    parser.parse_task.side_effect = ParserError(parser_code, "Parse failed")
    service = build_service(downloader, stt, parser)

    result = await service.create_from_voice(user, voice)

    assert result == VoiceTaskResult.failure(expected_error)
    assert await db_call(Task.objects.count) == 0
    assert not audio_path.exists()


@pytest.mark.asyncio
async def test_task_creation_failure_rolls_back_and_returns_generic(
        user, voice, audio_path, downloader, stt, parser, monkeypatch):
    monkeypatch.setattr(
        TaskEventRepository,
        "create",
        Mock(side_effect=RuntimeError("Event storage failed")),
    )
    service = build_service(downloader, stt, parser, TaskService())

    result = await service.create_from_voice(user, voice)

    assert result == VoiceTaskResult.failure(ErrorCode.GENERIC)
    assert await db_call(Task.objects.count) == 0
    assert not audio_path.exists()


@pytest.mark.asyncio
async def test_past_date_from_task_service_is_mapped_without_partial_task(
        user, voice, audio_path, downloader, stt, parser):
    parser.parse_task.return_value = ParsedTaskInput(
        title="Опоздавшая задача",
        raw_text="напомни вчера",
        due_to=timezone.now() - timedelta(days=1),
    )
    service = build_service(downloader, stt, parser)

    result = await service.create_from_voice(user, voice)

    assert result == VoiceTaskResult.failure(ErrorCode.DATE_IN_PAST)
    assert await db_call(Task.objects.count) == 0
    assert not audio_path.exists()


@pytest.mark.asyncio
async def test_parser_factory_is_used_when_parser_is_not_injected(
        user, voice, downloader, stt, parser, monkeypatch):
    factory = Mock(return_value=parser)
    monkeypatch.setattr("reminder.services.voice_tasks.get_parser", factory)
    task_service = Mock()
    task_service.create_from_parsed = Mock(return_value=Mock())
    service = VoiceTaskCreationService(
        downloader=downloader,
        stt=stt,
        task_service=task_service,
    )

    result = await service.create_from_voice(user, voice)

    assert result.success is True
    factory.assert_called_once_with()
    task_service.create_from_parsed.assert_called_once()


@pytest.mark.asyncio
async def test_two_voices_create_two_tasks(user, voice, tmp_path, stt, parser):
    paths = [tmp_path / "first.ogg", tmp_path / "second.ogg"]
    for path in paths:
        path.write_bytes(b"ogg-opus-audio")

    downloader = Mock()
    downloader.validate_voice = Mock(return_value=ErrorCode.OK)
    downloader.download_voice = AsyncMock(side_effect=[
        (paths[0], ErrorCode.OK),
        (paths[1], ErrorCode.OK),
    ])
    downloader.delete_voice = Mock(
        side_effect=lambda path: Path(path).unlink(missing_ok=True))
    service = build_service(downloader, stt, parser)

    first, second = await asyncio.gather(
        service.create_from_voice(user, voice),
        service.create_from_voice(user, voice),
    )

    assert first.success is True
    assert second.success is True
    assert first.task.id != second.task.id
    assert await db_call(Task.objects.count) == 2
    assert await db_call(TaskEvent.objects.count) == 2
    assert all(not path.exists() for path in paths)


def test_voice_result_rejects_inconsistent_states(task):
    with pytest.raises(ValueError):
        VoiceTaskResult(success=True)
    with pytest.raises(ValueError):
        VoiceTaskResult(success=False)
    with pytest.raises(ValueError):
        VoiceTaskResult(success=False, task=task, error_code=ErrorCode.GENERIC)
    with pytest.raises(ValueError):
        VoiceTaskResult.failure(ErrorCode.OK)


def test_voice_service_has_no_telegram_or_celery_imports():
    import reminder.services.voice_tasks as voice_tasks

    source = inspect.getsource(voice_tasks)
    assert "aiogram" not in source
    assert "reminder.bot" not in source
    assert "celery" not in source
