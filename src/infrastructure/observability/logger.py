from __future__ import annotations

from infrastructure.config import LoggingSettings
from datetime import datetime
import json
import logging
import sys
from pathlib import Path


class LoggingService:
    configured = False

    class JsonFormatter(logging.Formatter):
        """Custom formatter to output logs in JSON format."""

        def format(self, record: logging.LogRecord) -> str:
            log_data = {
                "timestamp": self.formatTime(record, self.datefmt),
                "level": record.levelname,
                "message": record.getMessage(),
                "logger": record.name,
            }

            if record.exc_info:
                log_data["exception"] = self.formatException(record.exc_info)

            return json.dumps(log_data)

    @staticmethod
    def setup(settings: LoggingSettings) -> None:
        LoggingService.configured = True

        root_logger = logging.getLogger()
        root_logger.setLevel(settings.level.upper())

        # Remove existing handlers to avoid duplicate output.
        for handler in list(root_logger.handlers):
            root_logger.removeHandler(handler)

        # --- File handler ---
        if settings.file_handler_enabled:
            date_str = datetime.now().strftime("%Y-%m-%d")
            file_path = Path(settings.file_path_pattern.format(date=date_str))
            file_path.parent.mkdir(parents=True, exist_ok=True)

            file_handler = logging.FileHandler(file_path, encoding="utf-8")
            file_handler.setFormatter(
                LoggingService.JsonFormatter()
                if settings.json_output
                else logging.Formatter(
                    fmt="%(asctime)s %(levelname)-8s %(name)s - %(message)s"
                )
            )
            root_logger.addHandler(file_handler)

        # --- Stream handler ---
        if settings.stream_handler_enabled:
            stream_handler = logging.StreamHandler(sys.stderr)
            stream_handler.setFormatter(
                LoggingService.JsonFormatter()
                if settings.json_output
                else logging.Formatter(
                    fmt=settings.stream_format,
                    datefmt=settings.stream_date_format,
                )
            )
            root_logger.addHandler(stream_handler)

    @staticmethod
    def is_configured() -> bool:
        return LoggingService.configured
