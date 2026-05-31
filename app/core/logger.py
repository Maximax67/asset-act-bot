import logging
import sys
from logging.config import dictConfig
from typing import Any

LOGGING_CONFIG: dict[str, Any] = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "format": "%(levelname)-8s | %(asctime)s | %(name)s | %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    },
    "handlers": {
        "stdout": {
            "class": "logging.StreamHandler",
            "formatter": "default",
            "stream": sys.stdout,
        },
        "stderr": {
            "class": "logging.StreamHandler",
            "formatter": "default",
            "stream": sys.stderr,
            "level": "ERROR",
        },
    },
    "loggers": {
        "app": {
            "handlers": ["stdout", "stderr"],
            "level": "INFO",
            "propagate": False,
        },
        "bot": {
            "handlers": ["stdout", "stderr"],
            "level": "INFO",
            "propagate": False,
        },
    },
}

dictConfig(LOGGING_CONFIG)

logger = logging.getLogger("app")
