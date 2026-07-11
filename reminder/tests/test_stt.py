import json
import urllib.error
import urllib.parse
from io import BytesIO

import pytest

from reminder.services.dto import STTResult
from reminder.services.stt import (STTConfigurationError, STTError,
                                   STTErrorCode, YandexSpeechKitSTTService)


class FakeHTTPResponse:

    def __init__(self, body: bytes):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self) -> bytes:
        return self._body


def speechkit_response(result: object) -> bytes:
    return json.dumps({"result": result}, ensure_ascii=False).encode("utf-8")


@pytest.fixture
def audio_path(tmp_path):
    path = tmp_path / "voice.ogg"
    path.write_bytes(b"ogg-opus-audio")
    return path


@pytest.fixture
def service():
    return YandexSpeechKitSTTService(
        api_key="secret-key",
        folder_id="folder-id",
        language="ru-RU",
        audio_format="oggopus",
        timeout=30,
    )


def test_stt_sends_oggopus_and_returns_trimmed_russian_text(
        monkeypatch, audio_path, service):
    requests = []

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return FakeHTTPResponse(
            speechkit_response("  завтра в 15 позвонить врачу  "))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    result = service.transcribe(audio_path)

    assert result == STTResult(
        text="завтра в 15 позвонить врачу",
        language="ru-RU",
        provider="yandex_speechkit",
    )
    assert len(requests) == 1
    request, timeout = requests[0]
    parsed_url = urllib.parse.urlparse(request.full_url)
    assert f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path}" == (
        YandexSpeechKitSTTService.ENDPOINT)
    assert urllib.parse.parse_qs(parsed_url.query) == {
        "folderId": ["folder-id"],
        "lang": ["ru-RU"],
        "format": ["oggopus"],
    }
    assert request.method == "POST"
    assert request.data == b"ogg-opus-audio"
    assert request.get_header("Authorization") == "Api-Key secret-key"
    assert request.get_header("Content-type") == "application/octet-stream"
    assert timeout == 30


@pytest.mark.parametrize("transcript", ["", "   "])
def test_stt_rejects_empty_transcript(monkeypatch, audio_path, service,
                                      transcript):
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout: FakeHTTPResponse(
            speechkit_response(transcript)),
    )

    with pytest.raises(STTError) as exc_info:
        service.transcribe(audio_path)

    assert exc_info.value.code == STTErrorCode.STT_EMPTY


@pytest.mark.parametrize(
    "first_error",
    [
        TimeoutError(),
        urllib.error.HTTPError(
            YandexSpeechKitSTTService.ENDPOINT,
            503,
            "Service unavailable",
            {},
            BytesIO(),
        ),
    ],
)
def test_stt_retries_timeout_and_5xx(monkeypatch, audio_path, service,
                                     first_error):
    outcomes = [
        first_error,
        FakeHTTPResponse(speechkit_response("купить хлеб")),
    ]

    def fake_urlopen(request, timeout):
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    assert service.transcribe(audio_path).text == "купить хлеб"
    assert outcomes == []


@pytest.mark.parametrize("status", [401, 403])
def test_stt_does_not_retry_auth_errors(monkeypatch, audio_path, service,
                                        status):
    calls = 0

    def fake_urlopen(request, timeout):
        nonlocal calls
        calls += 1
        raise urllib.error.HTTPError(
            request.full_url,
            status,
            "Authorization failed",
            {},
            BytesIO(),
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with pytest.raises(STTError) as exc_info:
        service.transcribe(audio_path)

    assert exc_info.value.code == STTErrorCode.STT_FAILED
    assert calls == 1


def test_stt_stops_after_one_5xx_retry(monkeypatch, audio_path, service):
    calls = 0

    def fake_urlopen(request, timeout):
        nonlocal calls
        calls += 1
        raise urllib.error.HTTPError(
            request.full_url,
            503,
            "Service unavailable",
            {},
            BytesIO(),
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with pytest.raises(STTError) as exc_info:
        service.transcribe(audio_path)

    assert exc_info.value.code == STTErrorCode.STT_FAILED
    assert calls == 2


def test_stt_rejects_invalid_response(monkeypatch, audio_path, service):
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout: FakeHTTPResponse(b"not-json"),
    )

    with pytest.raises(STTError) as exc_info:
        service.transcribe(audio_path)

    assert exc_info.value.code == STTErrorCode.STT_FAILED


def test_stt_requires_credentials(settings):
    settings.YANDEX_API_KEY = ""
    settings.YANDEX_FOLDER_ID = ""

    with pytest.raises(STTConfigurationError, match="YANDEX_API_KEY"):
        YandexSpeechKitSTTService()


def test_stt_uses_django_settings(settings):
    settings.YANDEX_API_KEY = "api-key"
    settings.YANDEX_FOLDER_ID = "folder-id"
    settings.YANDEX_STT_LANGUAGE = "ru-RU"
    settings.YANDEX_STT_FORMAT = "oggopus"
    settings.YANDEX_STT_TIMEOUT_SEC = 12

    service = YandexSpeechKitSTTService()

    assert service._language == "ru-RU"
    assert service._audio_format == "oggopus"
    assert service._timeout == 12


def test_stt_does_not_log_key_or_transcript(monkeypatch, audio_path, service,
                                            caplog):

    def fake_urlopen(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url,
            401,
            "Authorization failed",
            {},
            BytesIO(),
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with pytest.raises(STTError):
        service.transcribe(audio_path)

    assert "secret-key" not in caplog.text
    assert "завтра в 15 позвонить врачу" not in caplog.text
