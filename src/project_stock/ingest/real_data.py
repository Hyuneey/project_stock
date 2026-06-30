from __future__ import annotations

from datetime import UTC, datetime
import json
import os
from pathlib import Path
import re
from typing import Any

from dotenv import load_dotenv

from project_stock.ingest.base import CollectorConfigError


load_dotenv()

NETWORK_ENV_VAR = "PROJECT_STOCK_ALLOW_NETWORK"
TRUE_VALUES = {"1", "true", "yes", "y", "on"}


class NetworkDisabledError(CollectorConfigError):
    """Raised when a real API fetch is attempted without explicit network opt-in."""


class MissingApiKeyError(CollectorConfigError):
    """Raised when a real API fetch is attempted without the required API key."""


class InvalidResponseError(CollectorConfigError):
    """Raised when a real API response cannot be parsed into supported records."""


class UnsupportedSeriesError(CollectorConfigError):
    """Raised when a requested real-data series is outside the MVP allowlist."""


class UnsupportedQueryError(CollectorConfigError):
    """Raised when a requested query is outside the MVP-supported scope."""


def network_enabled() -> bool:
    return os.getenv(NETWORK_ENV_VAR, "false").strip().lower() in TRUE_VALUES


def require_network_enabled() -> None:
    if not network_enabled():
        raise NetworkDisabledError(
            f"Network access is disabled. Set {NETWORK_ENV_VAR}=true to opt in to real API calls."
        )


def require_api_key(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise MissingApiKeyError(f"Missing API key: set {name} in the environment or .env.")
    return value


def require_any_api_key(names: tuple[str, ...]) -> tuple[str, str]:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return name, value
    joined = " or ".join(names)
    raise MissingApiKeyError(f"Missing API key: set {joined} in the environment or .env.")


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


def sanitize_cache_component(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_") or "unknown"


def build_raw_cache_path(
    source: str,
    series_id: str,
    start_date: str,
    end_date: str,
    data_dir: Path = Path("data"),
) -> Path:
    source_dir = sanitize_cache_component(source).lower()
    series = sanitize_cache_component(series_id)
    start = sanitize_cache_component(start_date)
    end = sanitize_cache_component(end_date)
    return data_dir / "raw" / source_dir / f"{series}_{start}_{end}.json"


def build_timestamped_raw_cache_path(
    source: str,
    prefix: str,
    collected_at: datetime | None = None,
    data_dir: Path = Path("data"),
) -> Path:
    timestamp = (collected_at or utc_now()).astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    source_dir = sanitize_cache_component(source).lower()
    safe_prefix = sanitize_cache_component(prefix)
    return data_dir / "raw" / source_dir / f"{safe_prefix}_{timestamp}.json"


def write_raw_response_cache(payload: Any, cache_path: Path) -> Path:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
    return cache_path
