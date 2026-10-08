import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOGGER_NAME = "roliposter"
_FORMAT = "%(asctime)s | %(levelname)-7s | %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


class RedactFilter(logging.Filter):
    """Last line of defence: scrubs registered secrets from every log record."""

    def __init__(self):
        super().__init__()
        self._secrets: set[str] = set()

    def add_secret(self, secret: str | None) -> None:
        if secret and len(secret) >= 6:
            self._secrets.add(secret)

    def filter(self, record: logging.LogRecord) -> bool:
        if self._secrets:
            msg = record.getMessage()
            for secret in self._secrets:
                msg = msg.replace(secret, "***REDACTED***")
            record.msg, record.args = msg, None
        return True


REDACTOR = RedactFilter()


def setup_logging(log_dir: Path, extra_handlers: tuple[logging.Handler, ...] = ()) -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for h in list(logger.handlers):
        logger.removeHandler(h)

    formatter = logging.Formatter(_FORMAT, _DATEFMT)
    log_dir.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [
        RotatingFileHandler(log_dir / "poster.log", maxBytes=1_000_000, backupCount=5, encoding="utf-8")
    ]
    if sys.stderr is not None:  # windowed .exe builds have no console
        handlers.append(logging.StreamHandler(sys.stderr))
    handlers.extend(extra_handlers)

    for h in handlers:
        h.setFormatter(formatter)
        h.addFilter(REDACTOR)
        logger.addHandler(h)
    return logger
