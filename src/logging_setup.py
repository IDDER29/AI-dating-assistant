import logging
from logging.handlers import RotatingFileHandler

from config import LOG_FILE_PATH


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
