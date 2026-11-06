import logging
import logging.config
import os
from pathlib import Path

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