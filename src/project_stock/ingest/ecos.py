from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from project_stock.ingest.base import CollectorIngestResult, OfficialCollector
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


class EcosCollector(OfficialCollector[EcosIndicatorRecord, IndicatorObservationCreate]):
    collector_id = "ecos"
    source_id = "BOK_ECOS"
    api_key_env_var = "ECOS_API_KEY"

    def raw_schema(self) -> type[EcosIndicatorRecord]:
        return EcosIndicatorRecord

    def normalize(self, raw_records: list[EcosIndicatorRecord]) -> list[IndicatorObservationCreate]:
        observations: list[IndicatorObservationCreate] = []
        for record in raw_records:
            collected_at = record.collected_at or record.release_at
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
                )
            )
        return observations

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
