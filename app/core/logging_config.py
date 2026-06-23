import atexit
import logging
import queue
import sys
from logging.handlers import QueueHandler, QueueListener
from pathlib import Path
from typing import Any

import structlog


def setup_logging(log_level: str) -> None:
    """
    Configuration of structlog processors and output format.
    Redirects standard logging (including uvicorn) to structlog and file.
    """
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    shared_processors: list[Any] = [
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            *shared_processors,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.UnicodeDecoder(),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter_processors: list[Any] = [
        structlog.stdlib.ProcessorFormatter.remove_processors_meta,
        structlog.processors.JSONRenderer(
            ensure_ascii=False
        ),  # Can be changed to ConsoleRenderer for readability
    ]

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=formatter_processors,
    )

    # Console output (Docker logs)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)

    # File output (app.log on the host)
    log_file_path = Path(__file__).resolve().parent.parent / "app.log"
    file_handler = logging.FileHandler(log_file_path, encoding="utf-8")
    file_handler.setFormatter(formatter)

    class StructlogQueueHandler(QueueHandler):
        def prepare(self, record: logging.LogRecord) -> logging.LogRecord:
            return record

    # Non-blocking async queue
    log_queue: queue.Queue[logging.LogRecord] = queue.Queue(-1)
    queue_handler = StructlogQueueHandler(log_queue)

    listener = QueueListener(log_queue, stream_handler, file_handler, respect_handler_level=True)
    listener.start()
    atexit.register(listener.stop)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(queue_handler)
    root_logger.setLevel(numeric_level)

    class UvicornEndpointFilter(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            msg = record.getMessage()
            return "GET /metrics " not in msg and "GET /metrics/ " not in msg

    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(logger_name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
        if logger_name == "uvicorn.access":
            uvicorn_logger.addFilter(UvicornEndpointFilter())


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Returns a structlog bound logger with the given name."""
    return structlog.stdlib.get_logger(name)
