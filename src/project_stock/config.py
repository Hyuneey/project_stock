from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os

from dotenv import load_dotenv


load_dotenv()


DEFAULT_DB_URL = "sqlite:///./data/warehouse/project_stock.sqlite"


@dataclass(frozen=True)
class AppConfig:
    db_url: str = os.getenv("PROJECT_STOCK_DB_URL", DEFAULT_DB_URL)
    data_dir: Path = Path(os.getenv("PROJECT_STOCK_DATA_DIR", "./data"))
    log_level: str = os.getenv("PROJECT_STOCK_LOG_LEVEL", "INFO")


def get_config(db_url: str | None = None) -> AppConfig:
    config = AppConfig()
    if db_url:
        return AppConfig(db_url=db_url, data_dir=config.data_dir, log_level=config.log_level)
    return config
