from __future__ import annotations

from datetime import date

from pydantic import Field, model_validator

from project_stock.schemas.common import SchemaBase


class BacktestPeriod(SchemaBase):
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def validate_order(self) -> "BacktestPeriod":
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self


class BacktestPolicy(SchemaBase):
    policy_name: str
    cash_symbol: str = "CASH_KRW"
    thesis_symbol_map: dict[str, list[str]] = Field(default_factory=dict)
    risk_reduction_fraction: float = Field(default=0.50, ge=0, le=1)
    portfolio_flag_reduction_fraction: float = Field(default=0.35, ge=0, le=1)
    allow_simulated_overweight: bool = False
    simulated_overweight_fraction: float = Field(default=0.0, ge=0, le=1)
    review_flag_types: list[str] = Field(
        default_factory=lambda: [
            "over_exposed_review",
            "reduce_risk_review",
            "crowding_review",
            "concentration_warning",
        ]
    )


class BacktestConfig(SchemaBase):
    backtest_id: str
    start_date: date
    end_date: date
    base_currency: str
    benchmark_symbol: str
    rebalance_frequency: str = "monthly"
    transaction_cost_bps: float = Field(default=0.0, ge=0)
    slippage_bps: float = Field(default=0.0, ge=0)
    max_turnover_per_period: float = Field(default=1.0, ge=0, le=1)
    policy_name: str
    policy: BacktestPolicy
    no_auto_trade: bool = True

    @model_validator(mode="after")
    def validate_config(self) -> "BacktestConfig":
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        if self.policy.policy_name != self.policy_name:
            raise ValueError("policy.policy_name must match policy_name")
        if not self.no_auto_trade:
            raise ValueError("backtests must keep no_auto_trade=true")
        return self


class BacktestMarketReturn(SchemaBase):
    date: date
    symbol: str
    return_value: float = Field(alias="return")
    benchmark_return: float | None = None
    available_from: date


class BacktestSignalSnapshot(SchemaBase):
    signal_id: str
    signal_date: date
    available_from: date
    signal_type: str
    thesis_id: str | None = None
    scenario_id: str | None = None
    symbol: str | None = None
    state: str | None = None
    flag_type: str | None = None
    stance: str | None = None
    expected_direction: str | None = None
    strength_score: float | None = None
    confidence_score: float | None = None
    metadata_json: dict[str, object] = Field(default_factory=dict)


class BacktestPortfolioSnapshot(SchemaBase):
    snapshot_id: str
    date: date
    available_from: date
    exposures: dict[str, float]
    cash_symbol: str = "CASH_KRW"

    @model_validator(mode="after")
    def validate_exposures(self) -> "BacktestPortfolioSnapshot":
        for symbol, exposure in self.exposures.items():
            if exposure < 0:
                raise ValueError(f"exposure for {symbol} must be non-negative")
        return self


class BacktestTradeSimulationRecord(SchemaBase):
    date: date
    symbol: str
    previous_exposure: float
    target_exposure: float
    exposure_change: float
    turnover: float
    transaction_cost: float
    policy_reason: str
    hypothetical_only: bool = True


class BacktestPerformanceMetrics(SchemaBase):
    cumulative_return: float
    annualized_return: float
    volatility: float
    max_drawdown: float
    calmar_ratio: float | None = None
    hit_ratio_review_flags: float
    average_turnover: float
    transaction_cost_impact: float
    benchmark_cumulative_return: float
    benchmark_relative_return: float
    downside_capture: float | None = None


class BacktestValidationResult(SchemaBase):
    backtest_id: str
    period: BacktestPeriod
    policy_name: str
    benchmark_symbol: str
    metrics: BacktestPerformanceMetrics
    benchmark_metrics: BacktestPerformanceMetrics | None = None
    validation_metrics: dict[str, float] = Field(default_factory=dict)
    validation_counts: dict[str, int] = Field(default_factory=dict)
    trade_records: list[BacktestTradeSimulationRecord] = Field(default_factory=list)
    period_returns: dict[str, float] = Field(default_factory=dict)
    benchmark_returns: dict[str, float] = Field(default_factory=dict)
    point_in_time_warnings: list[str] = Field(default_factory=list)
    no_auto_trade: bool = True


class BacktestReportResult(SchemaBase):
    backtest_id: str
    policy_name: str
    report_path: str
    metrics: BacktestPerformanceMetrics
    benchmark_metrics: BacktestPerformanceMetrics | None = None
    validation_metrics: dict[str, float] = Field(default_factory=dict)
    point_in_time_warnings: list[str] = Field(default_factory=list)
    no_auto_trade: bool = True
