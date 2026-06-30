from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import Field

from project_stock.schemas.common import SchemaBase


SmokeMode = Literal["dry_run", "fixture", "real"]


class OpenDartSmokeCompany(SchemaBase):
    name: str
    stock_code: str
    corp_code: str


class OpenDartDisclosureRange(SchemaBase):
    bgn_de: str
    end_de: str
    page_count: int = 10


class OpenDartFinancialSmokeConfig(SchemaBase):
    years: list[str] = Field(default_factory=list)
    report_codes: list[str] = Field(default_factory=list)


class RealDataSmokeFixturePaths(SchemaBase):
    fred_observations: Path = Path("tests/fixtures/official/fred_observations_response.json")
    ecos_statistic_search: Path = Path("tests/fixtures/official/ecos_statistic_search_response.json")
    opendart_disclosures: Path = Path("tests/fixtures/opendart_disclosure_list_response.json")
    opendart_financials: Path = Path("tests/fixtures/opendart_financial_statement_response.json")
    krx_daily: Path = Path("tests/fixtures/krx_daily_market_response.json")
    portfolio: Path | None = Path("tests/fixtures/portfolio_holdings_core_satellite.json")


class RealDataSmokeConfigPaths(SchemaBase):
    ecos_series: Path = Path("configs/ecos.series.example.yaml")
    opendart_corp_codes: Path = Path("configs/opendart.corp_codes.example.yaml")
    krx_symbols: Path = Path("configs/krx.symbols.example.yaml")
    portfolio: Path | None = Path("configs/portfolio.example.yaml")


class RealDataSmokeConfig(SchemaBase):
    smoke_id: str
    thesis_ids: list[str]
    fred_series: list[str]
    ecos_indicators: list[str]
    opendart_companies: list[OpenDartSmokeCompany]
    opendart_disclosure: OpenDartDisclosureRange
    opendart_financials: OpenDartFinancialSmokeConfig
    krx_symbols: list[str]
    start_date: date
    end_date: date
    memo_dir: Path = Path("data/processed")
    max_records: int = 500
    max_days: int = 31
    fixture_paths: RealDataSmokeFixturePaths = Field(default_factory=RealDataSmokeFixturePaths)
    config_paths: RealDataSmokeConfigPaths = Field(default_factory=RealDataSmokeConfigPaths)
    no_auto_trade: bool = True


class RealDataSmokeSourceStatus(SchemaBase):
    source_id: str
    adapter: str
    would_run: bool = True
    network_enabled: bool = False
    required_api_keys: list[str] = Field(default_factory=list)
    api_key_set: bool = False
    available: bool = False
    reason: str


class RealDataSmokeResult(SchemaBase):
    smoke_id: str
    mode: SmokeMode
    source_statuses: list[RealDataSmokeSourceStatus] = Field(default_factory=list)
    inserted_counts: dict[str, int] = Field(default_factory=dict)
    skipped_duplicate_counts: dict[str, int] = Field(default_factory=dict)
    normalized_event_count: int = 0
    events_by_type: dict[str, int] = Field(default_factory=dict)
    evidence_count: int = 0
    evidence_by_thesis: dict[str, int] = Field(default_factory=dict)
    thesis_snapshot_count: int = 0
    thesis_states: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    memo_path: str | None = None
    portfolio_memo_path: str | None = None
    no_auto_trade: bool = True
