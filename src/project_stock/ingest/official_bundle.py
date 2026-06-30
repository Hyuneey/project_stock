from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from project_stock.ingest.base import CollectorIngestResult
from project_stock.ingest.dart import OpenDartCollector
from project_stock.ingest.ecos import EcosCollector
from project_stock.ingest.fred import FredCollector
from project_stock.ingest.krx import KrxCollector
from project_stock.ingest.news import NewsRssCollector


def ingest_official_mock_bundle(
    session: Session,
    fixture_dir: Path,
) -> list[CollectorIngestResult]:
    collectors = [
        (OpenDartCollector(), fixture_dir / "dart_disclosures.json"),
        (EcosCollector(), fixture_dir / "ecos_indicators.json"),
        (FredCollector(), fixture_dir / "fred_indicators.json"),
        (KrxCollector(), fixture_dir / "krx_market.json"),
        (NewsRssCollector(), fixture_dir / "news_rss.json"),
    ]
    return [
        collector.ingest(session, fixture=fixture, mock=True) for collector, fixture in collectors
    ]
