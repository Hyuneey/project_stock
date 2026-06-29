from __future__ import annotations

from datetime import date

from pydantic import Field

from project_stock.schemas.common import SchemaBase


class ThesisExposureBand(SchemaBase):
    review_min: float = Field(default=0.0, ge=0, le=1)
    review_max: float | None = Field(default=None, ge=0, le=1)


class PortfolioConfig(SchemaBase):
    portfolio_id: str
    base_currency: str = "KRW"
    review_frequency: str = "monthly"
    max_total_equity_exposure: float = Field(default=1.0, ge=0, le=1)
    max_theme_exposure: dict[str, float] = Field(default_factory=dict)
    max_single_asset_exposure: float = Field(default=0.20, ge=0, le=1)
    cash_buffer_min: float = Field(default=0.05, ge=0, le=1)
    risk_budget: dict[str, float] = Field(default_factory=dict)
    thesis_exposure_map: dict[str, ThesisExposureBand] = Field(default_factory=dict)
    asset_theme_map: dict[str, list[str]] = Field(default_factory=dict)
    benchmark_symbols: list[str] = Field(default_factory=list)


class PortfolioHolding(SchemaBase):
    symbol: str
    name: str
    quantity: float | None = None
    market_value: float = Field(ge=0)
    currency: str
    asset_type: str
    theme_ids: list[str] = Field(default_factory=list)
    thesis_ids: list[str] = Field(default_factory=list)
    sector: str | None = None
    beta: float | None = None
    liquidity_bucket: str | None = None


class PortfolioSnapshot(SchemaBase):
    portfolio_id: str
    as_of: date
    base_currency: str
    holdings: list[PortfolioHolding]


class PortfolioExposure(SchemaBase):
    total_market_value: float
    cash_value: float
    cash_ratio: float
    total_equity_exposure: float
    theme_exposure: dict[str, float] = Field(default_factory=dict)
    thesis_exposure: dict[str, float] = Field(default_factory=dict)
    sector_exposure: dict[str, float] = Field(default_factory=dict)
    single_asset_exposure: dict[str, float] = Field(default_factory=dict)
    high_beta_exposure: float = 0.0
    high_beta_ratio: float = 0.0
    foreign_currency_exposure: dict[str, float] = Field(default_factory=dict)


class PortfolioRiskFlag(SchemaBase):
    flag_type: str
    severity: str = "review"
    message: str
    review_action: str
    thesis_id: str | None = None
    theme_id: str | None = None
    symbol: str | None = None
    exposure: float | None = None
    threshold: float | None = None


class PortfolioReviewResult(SchemaBase):
    portfolio_id: str
    as_of: date
    exposure: PortfolioExposure
    latest_thesis_states: dict[str, str | None] = Field(default_factory=dict)
    risk_flags: list[PortfolioRiskFlag] = Field(default_factory=list)
    decision_id: str | None = None
    memo_path: str | None = None
    no_auto_trade: bool = True
