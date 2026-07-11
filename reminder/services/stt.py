"""Speech-to-text service implementations."""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from django.conf import settings

from reminder.services.dto import STTResult


class STTErrorCode:
    STT_EMPTY = "stt_empty"
    STT_FAILED = "stt_failed"


class STTError(RuntimeError):

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class STTConfigurationError(RuntimeError):
    pass


class YandexSpeechKitSTTService:
    ENDPOINT = "https://stt.api.cloud.yandex.net/speech/v1/stt:recognize"
    PROVIDER = "yandex_speechkit"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        folder_id: str | None = None,
        language: str | None = None,
        audio_format: str | None = None,
        timeout: float | None = None,
    ):
        self._api_key = self._setting_or_value(api_key, "YANDEX_API_KEY", "")
        self._folder_id = self._setting_or_value(folder_id, "YANDEX_FOLDER_ID",
                                                 "")
        self._language = self._setting_or_value(language,
                                                "YANDEX_STT_LANGUAGE", "ru-RU")
        self._audio_format = self._setting_or_value(audio_format,
                                                    "YANDEX_STT_FORMAT",
                                                    "oggopus")
        self._timeout = (timeout if timeout is not None else getattr(
            settings, "YANDEX_STT_TIMEOUT_SEC", 30))

        if not self._api_key or not self._folder_id:
            raise STTConfigurationError(
                "Yandex SpeechKit requires YANDEX_API_KEY and "
                "YANDEX_FOLDER_ID.")

    @staticmethod
    def _setting_or_value(value: str | None, name: str, default: str) -> str:
        resolved = value if value is not None else getattr(
            settings, name, default)
        return str(resolved).strip()

    def transcribe(self, audio_path: str | Path) -> STTResult:
        try:
            audio = Path(audio_path).read_bytes()
        except (OSError, TypeError, ValueError) as error:
            raise self._failed_error() from error

        response_body = self._post_with_retry(audio)
        try:
            payload = json.loads(response_body.decode("utf-8"))
            transcript = payload["result"]
        except (KeyError, TypeError, UnicodeDecodeError,
                json.JSONDecodeError) as error:
            raise self._failed_error() from error

        if not isinstance(transcript, str):
            raise self._failed_error()

        transcript = transcript.strip()
        if not transcript:
            raise STTError(
                STTErrorCode.STT_EMPTY,
                "SpeechKit returned an empty transcript.",
            )

        return STTResult(
            text=transcript,
            language=self._language,
            provider=self.PROVIDER,
        )

    def _post_with_retry(self, audio: bytes) -> bytes:
        query = urllib.parse.urlencode({
            "folderId": self._folder_id,
            "lang": self._language,
            "format": self._audio_format,
        })
        url = f"{self.ENDPOINT}?{query}"

        for attempt in range(2):
            request = urllib.request.Request(
                url,
                data=audio,
                headers={
                    "Authorization": f"Api-Key {self._api_key}",
                    "Content-Type": "application/octet-stream",
                },
                method="POST",
            )

            try:
                with urllib.request.urlopen(request,
                                            timeout=self._timeout) as response:
                    return response.read()
            except urllib.error.HTTPError as error:
                error.close()
                if 500 <= error.code < 600 and attempt == 0:
                    continue
                raise self._failed_error() from error
            except (TimeoutError, socket.timeout) as error:
                if attempt == 0:
                    continue
                raise self._failed_error() from error
            except urllib.error.URLError as error:
                if self._is_timeout(error) and attempt == 0:
                    continue
                raise self._failed_error() from error

        raise self._failed_error()

    @staticmethod
    def _is_timeout(error: urllib.error.URLError) -> bool:
        return isinstance(error.reason, (TimeoutError, socket.timeout))

    @staticmethod
    def _failed_error() -> STTError:
        return STTError(
            STTErrorCode.STT_FAILED,
            "Yandex SpeechKit is unavailable.",
        )
