import logging
import logging.config
import os
import time
from collections.abc import Callable
from functools import wraps
from pathlib import Path
from typing import ParamSpec, TypeVar

import yaml

from .config import settings

CONFIG_PATH = Path(__file__).with_name("logging.yaml")


def configure_logging() -> None:
    with CONFIG_PATH.open(encoding="utf-8") as config_file:
        config = yaml.safe_load(config_file)

    log_file = Path(os.getenv("LOG_FILE", settings.log_file))
    log_file.parent.mkdir(parents=True, exist_ok=True)
    config["handlers"]["file"]["filename"] = str(log_file)
    logging.config.dictConfig(config)


configure_logging()
logger = logging.getLogger("cv_applier")

P = ParamSpec("P")
R = TypeVar("R")


def timed(function: Callable[P, R]) -> Callable[P, R]:
    @wraps(function)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        started = time.perf_counter()
        try:
            result = function(*args, **kwargs)
        except Exception:
            logger.exception(
                "Timed function failed: function=%s time_taken_ms=%.1f",
                function.__qualname__,
                (time.perf_counter() - started) * 1000,
            )
            raise
        logger.info(
            "Timed function completed: function=%s time_taken_ms=%.1f",
            function.__qualname__,
            (time.perf_counter() - started) * 1000,
        )
        return result

    return wrapper