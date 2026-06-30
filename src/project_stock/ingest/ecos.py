from __future__ import annotations

from datetime import UTC, date, datetime
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote
from urllib.request import urlopen

import yaml

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


class EcosIndicatorRecord(SchemaBase):
    indicator_id: str
    observation_period: str
    value: float
    unit: str | None = None
    release_at: datetime
    collected_at: datetime | None = None
    available_from: datetime | None = None
    consensus: float | None = None
    previous: float | None = None
    revised_previous: float | None = None
    surprise_value: float | None = None
    surprise_z: float | None = None
    source_id: str = "BOK_ECOS"
    raw_path: str | None = None
    metadata_json: dict[str, object] | None = None


class EcosSeriesDefinition(SchemaBase):
    indicator_id: str
    stat_code: str
    item_code1: str
    item_code2: str | None = None
    item_code3: str | None = None
    frequency: str
    unit: str
    description: str


def load_ecos_series_config(path: Path) -> dict[str, EcosSeriesDefinition]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    records = payload["series"] if isinstance(payload, dict) and "series" in payload else payload
    if not isinstance(records, list):
        raise ValueError("ECOS series config must be a list or a mapping with a 'series' list.")
    definitions = [EcosSeriesDefinition.model_validate(record) for record in records]
    return {definition.indicator_id: definition for definition in definitions}


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise InvalidResponseError("Invalid ECOS response: expected top-level JSON object.")
    return payload


def _parse_ecos_period(period: str, frequency: str) -> datetime:
    frequency = frequency.upper()
    if frequency == "D" and len(period) == 8:
        parsed = date(int(period[0:4]), int(period[4:6]), int(period[6:8]))
    elif frequency == "M" and len(period) >= 6:
        parsed = date(int(period[0:4]), int(period[4:6]), 1)
    elif frequency == "A" and len(period) >= 4:
        parsed = date(int(period[0:4]), 1, 1)
    else:
        raise InvalidResponseError(f"Unsupported ECOS period '{period}' for frequency '{frequency}'.")
    return datetime.combine(parsed, datetime.min.time(), tzinfo=UTC)


def _format_ecos_date(value: str, frequency: str) -> str:
    compact = value.replace("-", "")
    frequency = frequency.upper()
    if frequency == "D":
        return compact[:8]
    if frequency == "M":
        return compact[:6]
    if frequency == "A":
        return compact[:4]
    return compact


def parse_ecos_statistic_search_response(
    payload: dict[str, Any],
    series: EcosSeriesDefinition,
    raw_cache_path: str | None = None,
    collected_at: datetime | None = None,
) -> list[EcosIndicatorRecord]:
    if "RESULT" in payload:
        raise InvalidResponseError(f"Invalid ECOS response: {payload['RESULT']}")
    container = payload.get("StatisticSearch")
    if not isinstance(container, dict):
        raise InvalidResponseError("Invalid ECOS response: missing StatisticSearch object.")
    rows = container.get("row")
    if not isinstance(rows, list):
        raise InvalidResponseError("Invalid ECOS response: missing StatisticSearch.row list.")

    collected = collected_at or utc_now()
    records: list[EcosIndicatorRecord] = []
    for row in rows:
        if not isinstance(row, dict):
            raise InvalidResponseError("Invalid ECOS response: row is not an object.")
        try:
            period = str(row["TIME"])
            value = float(row["DATA_VALUE"])
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidResponseError(f"Invalid ECOS row: {row}") from exc

        release_at = _parse_ecos_period(period, series.frequency)
        metadata: dict[str, object] = {
            "indicator_id": series.indicator_id,
            "stat_code": series.stat_code,
            "item_code1": series.item_code1,
            "item_code2": series.item_code2,
            "item_code3": series.item_code3,
            "source": "BOK_ECOS",
            "description": series.description,
            "raw_cache_path": raw_cache_path,
        }
        records.append(
            EcosIndicatorRecord(
                indicator_id=series.indicator_id,
                observation_period=period,
                value=value,
                unit=series.unit,
                release_at=release_at,
                collected_at=collected,
                available_from=safe_available_from(release_at, release_at, collected),
                source_id="BOK_ECOS",
                raw_path=raw_cache_path,
                metadata_json=metadata,
            )
        )
    return records


class EcosCollector(OfficialCollector[EcosIndicatorRecord, IndicatorObservationCreate]):
    collector_id = "ecos"
    source_id = "BOK_ECOS"
    api_key_env_var = "ECOS_API_KEY"

    def raw_schema(self) -> type[EcosIndicatorRecord]:
        return EcosIndicatorRecord

    def fetch_raw(
        self,
        fixture: Path | None = None,
        mock: bool = True,
        *,
        indicator_id: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        series_config: Path = Path("configs/ecos.series.example.yaml"),
    ) -> list[EcosIndicatorRecord]:
        if mock:
            return super().fetch_raw(fixture=fixture, mock=mock)
        if indicator_id is None or start_date is None or end_date is None:
            raise ValueError("indicator_id, start_date, and end_date are required for real ECOS fetches")
        return self.fetch_series(
            indicator_id=indicator_id,
            start_date=start_date,
            end_date=end_date,
            series_config=series_config,
        )

    def fetch_series(
        self,
        indicator_id: str,
        start_date: str,
        end_date: str,
        *,
        series_config: Path = Path("configs/ecos.series.example.yaml"),
        fixture: Path | None = None,
        cache_raw: bool = True,
    ) -> list[EcosIndicatorRecord]:
        definitions = load_ecos_series_config(series_config)
        series = definitions.get(indicator_id)
        if series is None:
            raise UnsupportedSeriesError(
                f"Unsupported ECOS indicator '{indicator_id}'. Configured indicators: "
                f"{', '.join(sorted(definitions))}."
            )

        if fixture is not None:
            return parse_ecos_statistic_search_response(
                _load_json(fixture),
                series=series,
                raw_cache_path=str(fixture),
            )

        require_network_enabled()
        api_key = require_api_key(self.api_key_env_var or "ECOS_API_KEY")
        start = _format_ecos_date(start_date, series.frequency)
        end = _format_ecos_date(end_date, series.frequency)
        path_parts = [
            "https://ecos.bok.or.kr/api/StatisticSearch",
            quote(api_key),
            "json",
            "kr",
            "1",
            "100000",
            quote(series.stat_code),
            quote(series.frequency),
            quote(start),
            quote(end),
            quote(series.item_code1),
        ]
        for item_code in (series.item_code2, series.item_code3):
            if item_code:
                path_parts.append(quote(item_code))
        url = "/".join(path_parts)
        with urlopen(url, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict):
            raise InvalidResponseError("Invalid ECOS response: expected JSON object.")

        raw_cache_path = None
        if cache_raw:
            cache_path = build_raw_cache_path("ecos", indicator_id, start_date, end_date)
            write_raw_response_cache(payload, cache_path)
            raw_cache_path = str(cache_path)
        return parse_ecos_statistic_search_response(
            payload,
            series=series,
            raw_cache_path=raw_cache_path,
        )

    def normalize(self, raw_records: list[EcosIndicatorRecord]) -> list[IndicatorObservationCreate]:
        observations: list[IndicatorObservationCreate] = []
        for record in raw_records:
            collected_at = record.collected_at or record.release_at
            metadata = {
                "indicator_id": record.indicator_id,
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
        indicator_id: str,
        start_date: str,
        end_date: str,
        *,
        series_config: Path = Path("configs/ecos.series.example.yaml"),
        fixture: Path | None = None,
        cache_raw: bool = True,
    ) -> CollectorIngestResult:
        register_official_sources(session)
        repo = Repository(session)
        records = self.normalize(
            self.fetch_series(
                indicator_id=indicator_id,
                start_date=start_date,
                end_date=end_date,
                series_config=series_config,
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
