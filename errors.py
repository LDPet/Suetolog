from enum import IntEnum


class ErrorCode(IntEnum):
    OK = 0

    VOICE_TOO_LONG = 1001
    VOICE_TOO_LARGE = 1002
    STT_EMPTY = 1003
    PARSER_FAILED = 1004
    DATE_IN_PAST = 1005
    GENERIC = 1006


error_messages = {
    ErrorCode.VOICE_TOO_LONG:
    "Голосовое сообщение слишком длинное. Попробуйте короче",
    ErrorCode.VOICE_TOO_LARGE: "Файл слишком большой",
    ErrorCode.STT_EMPTY: "Не расслышал, повтори еще раз",
    ErrorCode.PARSER_FAILED: "Не понял задачу, попробуй сформулировать проще.",
    ErrorCode.DATE_IN_PAST: "Дата уже прошла, укажи будущую дату",
    ErrorCode.GENERIC: "Что-то пошло не так, попробуй еще раз"
}