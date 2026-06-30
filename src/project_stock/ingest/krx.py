from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from project_stock.ingest.base import CollectorIngestResult, OfficialCollector
from project_stock.ingest.sources import register_official_sources
from project_stock.normalize.time import safe_available_from
from project_stock.schemas.common import SchemaBase
from project_stock.schemas.market import MarketTimeSeriesCreate
from project_stock.storage.repository import Repository


class KrxMarketRecord(SchemaBase):
    symbol: str
    timestamp: datetime
    frequency: str
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    volume: float | None = None
    value: float | None = None
    adjusted_flag: bool = False
    collected_at: datetime | None = None
    available_from: datetime | None = None
    source_id: str = "KRX"


class KrxCollector(OfficialCollector[KrxMarketRecord, MarketTimeSeriesCreate]):
    collector_id = "krx"
    source_id = "KRX"
    api_key_env_var = None

    def raw_schema(self) -> type[KrxMarketRecord]:
        return KrxMarketRecord

    def normalize(self, raw_records: list[KrxMarketRecord]) -> list[MarketTimeSeriesCreate]:
        series: list[MarketTimeSeriesCreate] = []
        for record in raw_records:
            collected_at = record.collected_at or record.timestamp
            series.append(
                MarketTimeSeriesCreate(
                    source_id=self.source_id,
                    symbol=record.symbol,
                    timestamp=record.timestamp,
                    frequency=record.frequency,
                    open=record.open,
                    high=record.high,
                    low=record.low,
                    close=record.close,
                    volume=record.volume,
                    value=record.value,
                    adjusted_flag=record.adjusted_flag,
                    collected_at=collected_at,
                    available_from=safe_available_from(
                        record.available_from,
                        record.timestamp,
                        collected_at,
                    ),
                )
            )
        return series

    def ingest(
        self,
        session: Session,
        fixture: Path | None = None,
        mock: bool = True,
    ) -> CollectorIngestResult:
        register_official_sources(session)
        repo = Repository(session)
        records = self.normalize(self.fetch_raw(fixture=fixture, mock=mock))
        inserted_ids = [repo.add_market_time_series(record).series_id for record in records]
        return CollectorIngestResult(
            collector_id=self.collector_id,
            source_id=self.source_id,
            inserted_count=len(inserted_ids),
            record_ids=inserted_ids,
        )
