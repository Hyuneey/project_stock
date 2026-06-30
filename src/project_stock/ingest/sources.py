from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from project_stock.db.models import Source
from project_stock.storage.repository import Repository


@dataclass(frozen=True)
class SourceDefinition:
    source_id: str
    name: str
    source_type: str
    url: str
    reliability_default: float
    notes: str


OFFICIAL_SOURCE_DEFINITIONS: tuple[SourceDefinition, ...] = (
    SourceDefinition(
        source_id="OPEN_DART",
        name="OpenDART",
        source_type="corporate_disclosure",
        url="https://opendart.fss.or.kr",
        reliability_default=4.5,
        notes="Korean Financial Supervisory Service disclosure source.",
    ),
    SourceDefinition(
        source_id="BOK_ECOS",
        name="Bank of Korea ECOS",
        source_type="macro_indicator",
        url="https://ecos.bok.or.kr",
        reliability_default=4.5,
        notes="Official Korean macroeconomic indicator source.",
    ),
    SourceDefinition(
        source_id="FRED",
        name="Federal Reserve Economic Data",
        source_type="macro_indicator",
        url="https://fred.stlouisfed.org",
        reliability_default=4.5,
        notes="US and global macro indicator source; ALFRED vintages planned later.",
    ),
    SourceDefinition(
        source_id="KRX",
        name="Korea Exchange",
        source_type="market_time_series",
        url="https://data.krx.co.kr",
        reliability_default=4.0,
        notes="Korean market price and trading data source.",
    ),
    SourceDefinition(
        source_id="NEWS_RSS",
        name="Generic News/RSS",
        source_type="news",
        url="mock://news-rss",
        reliability_default=2.5,
        notes="Mock-only RSS/news interface for offline MVP tests.",
    ),
)


def register_official_sources(session: Session) -> list[Source]:
    repo = Repository(session)
    return [
        repo.get_or_create_source(
            source_id=source.source_id,
            name=source.name,
            source_type=source.source_type,
            url=source.url,
            reliability_default=source.reliability_default,
            notes=source.notes,
        )
        for source in OFFICIAL_SOURCE_DEFINITIONS
    ]
