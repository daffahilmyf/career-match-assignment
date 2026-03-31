from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any, cast


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if isinstance(record.args, dict):
            payload.update(cast(dict[str, Any], record.args))
        extra = getattr(record, "extra", None)
        if isinstance(extra, dict):
            payload.update(cast(dict[str, Any], extra))
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)


def get_logger(name: str = "pelgo") -> logging.Logger:
    return logging.getLogger(name)


def log_event(logger: logging.Logger, event: str, **fields: Any) -> None:
    logger.info(event, extra={"extra": {"event": event, **fields}})
