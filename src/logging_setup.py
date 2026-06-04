"""
Logging setup for the AI Dating Assistant.

Plain-text mode (default):
    2026-06-04 14:23:11,541 - [INFO] - [DIALOG] Reply sent

Structured mode (STRUCTURED_LOGGING=true in .env):
    {"ts": "2026-06-04T14:23:11Z", "level": "INFO", "module": "DIALOG",
     "chat_id": 12345678, "msg": "Reply sent"}

Structured mode is machine-readable and compatible with Loki, Datadog, and
CloudWatch. Switch by setting STRUCTURED_LOGGING=true in .env.
"""
import json as _json
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path


def redact(text: str, max_chars: int = 0) -> str:
    """
    Redact text for safe log output.
    max_chars=0  → replace entirely with '[REDACTED]'.
    max_chars>0  → keep first N chars then append '...[REDACTED]'.
    """
    if not text:
        return text
    if max_chars <= 0:
        return "[REDACTED]"
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "...[REDACTED]"


class StructuredFormatter(logging.Formatter):
    """
    Emits one JSON object per log line.
    Optional structured fields (chat_id, module, event) are included when
    injected via extra={} or BotLogger.
    """

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%SZ"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for field in ("chat_id", "module", "model", "event"):
            if hasattr(record, field):
                entry[field] = getattr(record, field)
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return _json.dumps(entry, ensure_ascii=False)


class BotLogger:
    """
    Thin logger wrapper that pre-fills common structured fields.

    Usage in a module scoped to a chat:
        log = BotLogger("DIALOG", chat_id=12345678)
        log.info("Reply sent")
        # structured:  {..., "module": "DIALOG", "chat_id": 12345678, "msg": "Reply sent"}
        # plain text:  2026-... - [INFO] - Reply sent

    Usage for module-level logging without a chat_id:
        log = BotLogger("LEOMATCH")
        log.warning("Unrecognized text")
    """

    def __init__(self, module: str, chat_id: int = 0):
        self._logger = logging.getLogger(f"bot.{module.lower()}")
        self._extra: dict = {"module": module}
        if chat_id:
            self._extra["chat_id"] = chat_id

    def _log(self, level: int, msg: str, **kwargs):
        extra = {**self._extra, **kwargs}
        self._logger.log(level, msg, extra=extra, stacklevel=2)

    def debug(self, msg: str, **kwargs):
        self._log(logging.DEBUG, msg, **kwargs)

    def info(self, msg: str, **kwargs):
        self._log(logging.INFO, msg, **kwargs)

    def warning(self, msg: str, **kwargs):
        self._log(logging.WARNING, msg, **kwargs)

    def error(self, msg: str, **kwargs):
        self._log(logging.ERROR, msg, **kwargs)

    def critical(self, msg: str, **kwargs):
        self._log(logging.CRITICAL, msg, **kwargs)

    def with_chat(self, chat_id: int) -> "BotLogger":
        """Return a new BotLogger scoped to the given chat_id."""
        return BotLogger(self._extra.get("module", "BOT"), chat_id=chat_id)


def setup_logging():
    """
    Configure root logger.

    Reads STRUCTURED_LOGGING from environment (set in .env or shell).
    Default: plain text.  Set STRUCTURED_LOGGING=true for JSON output.
    """
    from settings import LOG_FILE_PATH

    structured = os.getenv("STRUCTURED_LOGGING", "false").lower() == "true"

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        formatter = StructuredFormatter() if structured else logging.Formatter(
            "%(asctime)s - [%(levelname)s] - %(message)s"
        )

        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)

        file_handler = RotatingFileHandler(
            str(LOG_FILE_PATH),
            maxBytes=5 * 1024 * 1024,
            backupCount=2,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)

        logger.addHandler(stream_handler)
        logger.addHandler(file_handler)

    return logger
