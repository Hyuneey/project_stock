from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from pydantic import Field
from sqlalchemy.orm import Session
import yaml

from project_stock.ingest.base import CollectorIngestResult, OfficialCollector
from project_stock.ingest.real_data import (
    InvalidResponseError,
    UnsupportedMarketDataTypeError,
    UnsupportedSymbolError,
    build_timestamped_raw_cache_path,
    network_enabled,
    require_any_api_key,
    require_network_enabled,
    utc_now,
    write_raw_response_cache,
)
from project_stock.ingest.sources import register_official_sources
from project_stock.normalize.time import safe_available_from
from project_stock.schemas.common import SchemaBase
from project_stock.schemas.market import MarketTimeSeriesCreate
from project_stock.storage.repository import Repository


KOREA_TZ = ZoneInfo("Asia/Seoul")
KRX_AUTH_ENV_VARS = ("KRX_AUTH_TOKEN", "KRX_API_KEY")
SUPPORTED_MARKET_DATA_TYPES = {"stock", "etf", "index"}
KRX_JSON_ENDPOINT = "https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"
KRX_BLD_BY_ASSET_TYPE = {
    "stock": "dbms/MDC/STAT/standard/MDCSTAT01701",
    "etf": "dbms/MDC/STAT/standard/MDCSTAT04301",
    "index": "dbms/MDC/STAT/standard/MDCSTAT00301",
}


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
    metadata_json: dict[str, object] | None = None


class KrxSymbolConfig(SchemaBase):
    symbol: str
    name: str
    market: str
    asset_type: str
    currency: str
    theme_ids: list[str] = Field(default_factory=list)
    thesis_ids: list[str] = Field(default_factory=list)
    sector: str | None = None
    aliases: list[str] = Field(default_factory=list)
    krx_isu_cd: str | None = None
    krx_index_code: str | None = None


def load_krx_symbols(path: Path) -> dict[str, KrxSymbolConfig]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    records = payload["symbols"] if isinstance(payload, dict) and "symbols" in payload else payload
    if not isinstance(records, list):
        raise ValueError("KRX symbol config must be a list or mapping with a 'symbols' list.")
    configs = [KrxSymbolConfig.model_validate(record) for record in records]
    return {config.symbol: config for config in configs}


def resolve_krx_symbol(symbol: str, symbol_config: Path) -> KrxSymbolConfig:
    configs = load_krx_symbols(symbol_config)
    if symbol in configs:
        config = configs[symbol]
    else:
        lowered = symbol.lower()
        config = next(
            (
                item
                for item in configs.values()
                if lowered in {alias.lower() for alias in item.aliases}
            ),
            None,
        )
    if config is None:
        raise UnsupportedSymbolError(f"Unsupported KRX symbol '{symbol}' in {symbol_config}.")
    validate_market_data_type(config.asset_type)
    return config


def validate_market_data_type(asset_type: str) -> None:
    if asset_type.lower() not in SUPPORTED_MARKET_DATA_TYPES:
        raise UnsupportedMarketDataTypeError(
            f"Unsupported KRX market data type '{asset_type}'. Supported types: "
            f"{', '.join(sorted(SUPPORTED_MARKET_DATA_TYPES))}."
        )


def parse_krx_number(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text in {"-", "N/A"}:
        return None
    text = text.replace(",", "").replace("%", "").replace(" ", "")
    try:
        return float(text)
    except ValueError as exc:
        raise InvalidResponseError(f"Invalid KRX numeric value: {value}") from exc


def _first(row: dict[str, Any], *names: str) -> object | None:
    for name in names:
        if name in row and row[name] not in (None, ""):
            return row[name]
    return None


def _records_from_payload(payload: dict[str, Any] | list[Any]) -> list[dict[str, Any]]:
    records = payload
    if isinstance(payload, dict):
        for key in ("records", "OutBlock_1", "output", "data", "rows"):
            if key in payload:
                records = payload[key]
                break
    if not isinstance(records, list):
        raise InvalidResponseError("Invalid KRX daily response: expected a records array.")
    if not all(isinstance(record, dict) for record in records):
        raise InvalidResponseError("Invalid KRX daily response: records must be objects.")
    return records


def _parse_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _parse_trade_date(value: object) -> date:
    text = str(value).strip().replace("/", "-").replace(".", "-")
    if len(text) == 8 and text.isdigit():
        text = f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return date.fromisoformat(text)


def market_close_timestamp(trading_date: date) -> datetime:
    close_local = datetime.combine(trading_date, time(15, 30), tzinfo=KOREA_TZ)
    return close_local.astimezone(UTC)


def market_close_available_from(close_timestamp: datetime) -> datetime:
    return close_timestamp.astimezone(UTC) + timedelta(minutes=15)


def _row_timestamp(row: dict[str, Any]) -> datetime:
    raw_timestamp = _first(row, "timestamp", "trade_timestamp", "TRD_DTTM")
    if raw_timestamp is not None:
        return _parse_datetime(raw_timestamp)
    raw_date = _first(row, "date", "trade_date", "TRD_DD", "BAS_DD")
    if raw_date is None:
        raise InvalidResponseError("Invalid KRX daily row: missing trade date or timestamp.")
    return market_close_timestamp(_parse_trade_date(raw_date))


def _row_available_from(
    row: dict[str, Any],
    timestamp: datetime,
    collected_at: datetime,
) -> datetime:
    explicit = _first(row, "available_from")
    market_close_ready = market_close_available_from(timestamp)
    if explicit is not None:
        return safe_available_from(_parse_datetime(explicit), timestamp, market_close_ready, collected_at)
    return safe_available_from(market_close_ready, timestamp, collected_at)


def build_krx_raw_cache_path(
    symbol: str,
    start_date: str,
    end_date: str,
    collected_at: datetime | None = None,
    data_dir: Path = Path("data"),
    suffix: str = "json",
) -> Path:
    return build_timestamped_raw_cache_path(
        "krx",
        f"{symbol}_{start_date}_{end_date}",
        collected_at=collected_at,
        data_dir=data_dir,
        suffix=suffix,
    )


def parse_krx_daily_market_response(
    payload: dict[str, Any] | list[Any],
    *,
    symbol_config: KrxSymbolConfig,
    collected_at: datetime | None = None,
    raw_cache_path: str | None = None,
) -> list[MarketTimeSeriesCreate]:
    validate_market_data_type(symbol_config.asset_type)
    collected = collected_at or utc_now()
    rows = _records_from_payload(payload)
    series: list[MarketTimeSeriesCreate] = []
    for row in rows:
        symbol = str(_first(row, "symbol", "ISU_SRT_CD", "IDX_NM", "index_code") or symbol_config.symbol)
        if symbol not in {symbol_config.symbol, symbol_config.name}:
            aliases = {alias.lower() for alias in symbol_config.aliases}
            if symbol.lower() not in aliases:
                continue
        timestamp = _row_timestamp(row)
        row_collected = _first(row, "collected_at")
        row_collected_at = _parse_datetime(row_collected) if row_collected is not None else collected
        metadata: dict[str, object] = {
            "source": "KRX",
            "source_table": "market_time_series",
            "symbol": symbol_config.symbol,
            "name": symbol_config.name,
            "market": symbol_config.market,
            "asset_type": symbol_config.asset_type,
            "currency": symbol_config.currency,
            "theme_ids": symbol_config.theme_ids,
            "thesis_ids": symbol_config.thesis_ids,
            "sector": symbol_config.sector,
            "raw_cache_path": raw_cache_path,
            "raw_symbol": symbol,
        }
        if symbol_config.krx_isu_cd:
            metadata["krx_isu_cd"] = symbol_config.krx_isu_cd
        if symbol_config.krx_index_code:
            metadata["krx_index_code"] = symbol_config.krx_index_code
        series.append(
            MarketTimeSeriesCreate(
                symbol=symbol_config.symbol,
                timestamp=timestamp,
                frequency="daily",
                open=parse_krx_number(_first(row, "open", "TDD_OPNPRC", "OPEN")),
                high=parse_krx_number(_first(row, "high", "TDD_HGPRC", "HIGH")),
                low=parse_krx_number(_first(row, "low", "TDD_LWPRC", "LOW")),
                close=parse_krx_number(_first(row, "close", "TDD_CLSPRC", "CLSPRC", "CLOSE", "IDX_CLSPRC")),
                volume=parse_krx_number(_first(row, "volume", "ACC_TRDVOL", "VOLUME")),
                value=parse_krx_number(_first(row, "value", "ACC_TRDVAL", "VALUE")),
                adjusted_flag=bool(_first(row, "adjusted_flag", "ADJUSTED", "adjStkPrc") or False),
                source_id="KRX",
                collected_at=row_collected_at,
                available_from=_row_available_from(row, timestamp, row_collected_at),
                metadata_json=metadata,
            )
        )
    return series


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
                    metadata_json=record.metadata_json or {},
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
        records = self.normalize(self.fetch_raw(fixture=fixture, mock=mock))
        return self._append_series(session, records)

    def _append_series(
        self,
        session: Session,
        records: list[MarketTimeSeriesCreate],
    ) -> CollectorIngestResult:
        repo = Repository(session)
        inserted_ids: list[str] = []
        skipped_count = 0
        for record in records:
            if repo.find_market_time_series(
                record.symbol,
                record.timestamp,
                record.frequency,
                record.source_id,
            ):
                skipped_count += 1
                continue
            inserted_ids.append(repo.add_market_time_series(record).series_id)
        return CollectorIngestResult(
            collector_id=self.collector_id,
            source_id=self.source_id,
            inserted_count=len(inserted_ids),
            skipped_count=skipped_count,
            record_ids=inserted_ids,
        )

    def fetch_daily(
        self,
        *,
        symbol: str,
        start_date: str,
        end_date: str,
        symbol_config: Path = Path("configs/krx.symbols.example.yaml"),
        fixture: Path | None = None,
        cache_raw: bool = True,
        require_auth: bool = False,
    ) -> list[MarketTimeSeriesCreate]:
        config = resolve_krx_symbol(symbol, symbol_config)
        if fixture is not None:
            payload = json.loads(fixture.read_text(encoding="utf-8"))
            return parse_krx_daily_market_response(
                payload,
                symbol_config=config,
                raw_cache_path=str(fixture),
            )

        require_network_enabled()
        headers = {
            "User-Agent": "project-stock/0.1 offline-first adapter",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        }
        if require_auth:
            key_name, token = require_any_api_key(KRX_AUTH_ENV_VARS)
            headers["Authorization"] = f"Bearer {token}"
        else:
            key_name = None
        collected_at = utc_now()
        payload = self._fetch_real_daily_payload(config, start_date, end_date, headers)
        raw_cache_path = None
        if cache_raw:
            cache_path = build_krx_raw_cache_path(
                config.symbol,
                start_date,
                end_date,
                collected_at,
            )
            write_raw_response_cache(
                {
                    "request": {
                        "symbol": config.symbol,
                        "start_date": start_date,
                        "end_date": end_date,
                        "asset_type": config.asset_type,
                        "credential_env_var": key_name,
                    },
                    "response": payload,
                },
                cache_path,
            )
            raw_cache_path = str(cache_path)
        return parse_krx_daily_market_response(
            payload,
            symbol_config=config,
            collected_at=collected_at,
            raw_cache_path=raw_cache_path,
        )

    def ingest_daily(
        self,
        session: Session,
        *,
        symbol: str,
        start_date: str,
        end_date: str,
        symbol_config: Path = Path("configs/krx.symbols.example.yaml"),
        fixture: Path | None = None,
        cache_raw: bool = True,
    ) -> CollectorIngestResult:
        register_official_sources(session)
        records = self.fetch_daily(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            symbol_config=symbol_config,
            fixture=fixture,
            cache_raw=cache_raw,
        )
        return self._append_series(session, records)

    def _fetch_real_daily_payload(
        self,
        config: KrxSymbolConfig,
        start_date: str,
        end_date: str,
        headers: dict[str, str],
    ) -> dict[str, Any]:
        asset_type = config.asset_type.lower()
        validate_market_data_type(asset_type)
        params: dict[str, object] = {
            "bld": KRX_BLD_BY_ASSET_TYPE[asset_type],
            "locale": "ko_KR",
            "strtDd": start_date.replace("-", ""),
            "endDd": end_date.replace("-", ""),
            "share": "1",
            "money": "1",
            "csvxls_isNo": "false",
        }
        if asset_type in {"stock", "etf"}:
            params["isuCd"] = config.krx_isu_cd or config.symbol
            params["adjStkPrc"] = "2"
            params["adjStkPrc_check"] = "Y"
        else:
            params["indIdx"] = config.krx_index_code or config.symbol

        body = urlencode(params).encode("utf-8")
        request = Request(KRX_JSON_ENDPOINT, data=body, headers=headers, method="POST")
        with urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict):
            raise InvalidResponseError("Invalid KRX daily response: expected JSON object.")
        return payload


def krx_doctor_payload(
    db_url: str,
    symbol_config: Path = Path("configs/krx.symbols.example.yaml"),
) -> dict[str, object]:
    symbols: list[str] = []
    config_exists = symbol_config.exists()
    if config_exists:
        symbols = sorted(load_krx_symbols(symbol_config))
    return {
        "db_url": db_url,
        "PROJECT_STOCK_ALLOW_NETWORK": network_enabled(),
        "KRX_AUTH_TOKEN_set": any(os.getenv(name, "").strip() for name in KRX_AUTH_ENV_VARS),
        "KRX_credentials_required": False,
        "symbol_config": str(symbol_config),
        "symbol_config_exists": config_exists,
        "configured_symbols": symbols,
        "raw_cache_dir": "data/raw/krx",
        "point_in_time_caution": "daily KRX data uses market-close plus 15 minutes or collected_at, whichever is later",
        "no_auto_trade": True,
    }
