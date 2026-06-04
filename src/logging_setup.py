import logging
from logging.handlers import RotatingFileHandler

from settings import LOG_FILE_PATH


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


def setup_logging():
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        formatter = logging.Formatter("%(asctime)s - [%(levelname)s] - %(message)s")
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
