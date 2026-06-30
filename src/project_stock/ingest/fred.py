from __future__ import annotations

from datetime import UTC, date, datetime
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen

from sqlalchemy.orm import Session

from project_stock.ingest.base import CollectorIngestResult, OfficialCollector
from project_stock.ingest.real_data import (
    InvalidResponseError,
    UnsupportedSeriesError,
    build_raw_cache_path,
    require_api_key,
    require_network_enabled,
    utc_now,
    write_raw_response_cache,
)
from project_stock.ingest.sources import register_official_sources
from project_stock.normalize.time import safe_available_from
from project_stock.schemas.common import SchemaBase
from project_stock.schemas.indicators import IndicatorObservationCreate
from project_stock.storage.repository import Repository


SUPPORTED_FRED_SERIES: dict[str, dict[str, str]] = {
    "DGS10": {
        "description": "10-Year Treasury Constant Maturity Rate",
        "unit": "percent",
    },
    "DGS2": {
        "description": "2-Year Treasury Constant Maturity Rate",
        "unit": "percent",
    },
    "VIXCLS": {
        "description": "CBOE Volatility Index",
        "unit": "index",
    },
    "FEDFUNDS": {
        "description": "Effective Federal Funds Rate",
        "unit": "percent",
    },
}


class FredIndicatorRecord(SchemaBase):
    indicator_id: str
    observation_period: str
    value: float
    unit: str | None = None
    release_at: datetime
    collected_at: datetime | None = None
    available_from: datetime | None = None
    vintage_date: str | None = None
    consensus: float | None = None
    previous: float | None = None
    revised_previous: float | None = None
    surprise_value: float | None = None
    surprise_z: float | None = None
    source_id: str = "FRED"
    raw_path: str | None = None
    metadata_json: dict[str, object] | None = None


def _date_at_utc_midnight(value: str) -> datetime:
    return datetime.combine(date.fromisoformat(value), datetime.min.time(), tzinfo=UTC)


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise InvalidResponseError("Invalid FRED response: expected top-level JSON object.")
    return payload


def parse_fred_observation_response(
    payload: dict[str, Any],
    series_id: str,
    raw_cache_path: str | None = None,
    collected_at: datetime | None = None,
) -> list[FredIndicatorRecord]:
    series_id = series_id.upper()
    if series_id not in SUPPORTED_FRED_SERIES:
        raise UnsupportedSeriesError(
            f"Unsupported FRED series '{series_id}'. Supported series: "
            f"{', '.join(sorted(SUPPORTED_FRED_SERIES))}."
        )

    observations = payload.get("observations")
    if not isinstance(observations, list):
        raise InvalidResponseError("Invalid FRED response: missing observations list.")

    collected = collected_at or utc_now()
    records: list[FredIndicatorRecord] = []
    for observation in observations:
        if not isinstance(observation, dict):
            raise InvalidResponseError("Invalid FRED response: observation row is not an object.")
        raw_value = observation.get("value")
        if raw_value in (None, "", "."):
            continue
        try:
            value = float(raw_value)
            observation_date = str(observation["date"])
            realtime_start = str(observation.get("realtime_start") or payload.get("realtime_start"))
            release_at = _date_at_utc_midnight(realtime_start)
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidResponseError(f"Invalid FRED observation row: {observation}") from exc

        metadata: dict[str, object] = {
            "series_id": series_id,
            "source": "FRED",
            "description": SUPPORTED_FRED_SERIES[series_id]["description"],
            "raw_cache_path": raw_cache_path,
        }
        records.append(
            FredIndicatorRecord(
                indicator_id=series_id,
                observation_period=observation_date,
                value=value,
                unit=SUPPORTED_FRED_SERIES[series_id]["unit"],
                release_at=release_at,
                collected_at=collected,
                available_from=safe_available_from(release_at, release_at, collected),
                vintage_date=realtime_start,
                source_id="FRED",
                raw_path=raw_cache_path,
                metadata_json=metadata,
            )
        )
    return records


class FredCollector(OfficialCollector[FredIndicatorRecord, IndicatorObservationCreate]):
    collector_id = "fred"
    source_id = "FRED"
    api_key_env_var = "FRED_API_KEY"

    def raw_schema(self) -> type[FredIndicatorRecord]:
        return FredIndicatorRecord

    def fetch_raw(
        self,
        fixture: Path | None = None,
        mock: bool = True,
        *,
        series_id: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[FredIndicatorRecord]:
        if mock:
            return super().fetch_raw(fixture=fixture, mock=mock)
        if series_id is None or start_date is None or end_date is None:
            raise ValueError("series_id, start_date, and end_date are required for real FRED fetches")
        return self.fetch_series(series_id=series_id, start_date=start_date, end_date=end_date)

    def fetch_series(
        self,
        series_id: str,
        start_date: str,
        end_date: str,
        *,
        fixture: Path | None = None,
        cache_raw: bool = True,
    ) -> list[FredIndicatorRecord]:
        series_id = series_id.upper()
        if series_id not in SUPPORTED_FRED_SERIES:
            raise UnsupportedSeriesError(
                f"Unsupported FRED series '{series_id}'. Supported series: "
                f"{', '.join(sorted(SUPPORTED_FRED_SERIES))}."
            )

        if fixture is not None:
            return parse_fred_observation_response(
                _load_json(fixture),
                series_id=series_id,
                raw_cache_path=str(fixture),
            )

        require_network_enabled()
        api_key = require_api_key(self.api_key_env_var or "FRED_API_KEY")
        query = urlencode(
            {
                "series_id": series_id,
                "api_key": api_key,
                "file_type": "json",
                "observation_start": start_date,
                "observation_end": end_date,
            }
        )
        url = f"https://api.stlouisfed.org/fred/series/observations?{query}"
        with urlopen(url, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict):
            raise InvalidResponseError("Invalid FRED response: expected JSON object.")

        raw_cache_path = None
        if cache_raw:
            cache_path = build_raw_cache_path("fred", series_id, start_date, end_date)
            write_raw_response_cache(payload, cache_path)
            raw_cache_path = str(cache_path)
        return parse_fred_observation_response(
            payload,
            series_id=series_id,
            raw_cache_path=raw_cache_path,
        )

    def normalize(self, raw_records: list[FredIndicatorRecord]) -> list[IndicatorObservationCreate]:
        observations: list[IndicatorObservationCreate] = []
        for record in raw_records:
            collected_at = record.collected_at or record.release_at
            metadata = {
                "vintage_support": "alfred_ready",
                "series_id": record.indicator_id,
                "source": self.source_id,
            }
            if record.raw_path:
                metadata["raw_cache_path"] = record.raw_path
            if record.metadata_json:
                metadata.update(record.metadata_json)
            observations.append(
                IndicatorObservationCreate(
                    source_id=self.source_id,
                    indicator_id=record.indicator_id,
                    observation_period=record.observation_period,
                    value=record.value,
                    unit=record.unit,
                    release_at=record.release_at,
                    collected_at=collected_at,
                    available_from=safe_available_from(
                        record.available_from,
                        record.release_at,
                        collected_at,
                    ),
                    vintage_date=record.vintage_date,
                    consensus=record.consensus,
                    previous=record.previous,
                    revised_previous=record.revised_previous,
                    surprise_value=record.surprise_value,
                    surprise_z=record.surprise_z,
                    metadata_json=metadata,
                )
            )
        return observations

    def ingest_series(
        self,
        session: Session,
        series_id: str,
        start_date: str,
        end_date: str,
        *,
        fixture: Path | None = None,
        cache_raw: bool = True,
    ) -> CollectorIngestResult:
        register_official_sources(session)
        repo = Repository(session)
        records = self.normalize(
            self.fetch_series(
                series_id=series_id,
                start_date=start_date,
                end_date=end_date,
                fixture=fixture,
                cache_raw=cache_raw,
            )
        )
        inserted_ids = [repo.add_indicator_observation(record).observation_id for record in records]
        return CollectorIngestResult(
            collector_id=self.collector_id,
            source_id=self.source_id,
            inserted_count=len(inserted_ids),
            record_ids=inserted_ids,
        )

    def ingest(
        self,
        session: Session,
        fixture: Path | None = None,
        mock: bool = True,
    ) -> CollectorIngestResult:
        register_official_sources(session)
        repo = Repository(session)
        records = self.normalize(self.fetch_raw(fixture=fixture, mock=mock))
        inserted_ids = [repo.add_indicator_observation(record).observation_id for record in records]
        return CollectorIngestResult(
            collector_id=self.collector_id,
            source_id=self.source_id,
            inserted_count=len(inserted_ids),
            record_ids=inserted_ids,
        )
