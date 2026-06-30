from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen

from pydantic import Field
from sqlalchemy.orm import Session
import yaml

from project_stock.ingest.base import CollectorIngestResult
from project_stock.ingest.real_data import (
    InvalidResponseError,
    MissingCorpCodeMappingError,
    UnsupportedReportCodeError,
    require_any_api_key,
    require_network_enabled,
    utc_now,
    write_raw_response_cache,
)
from project_stock.ingest.sources import register_official_sources
from project_stock.normalize.time import safe_available_from
from project_stock.schemas.common import SchemaBase
from project_stock.schemas.financials import FinancialStatementLineItemCreate
from project_stock.storage.repository import Repository
from project_stock.utils.ids import make_id


DART_API_KEY_ENV_VARS = ("DART_API_KEY", "OPEN_DART_API_KEY")

SUPPORTED_REPORT_CODES: dict[str, str] = {
    "11013": "1Q",
    "11012": "half-year",
    "11014": "3Q",
    "11011": "annual",
}

SUMMARY_ACCOUNT_ALIASES: dict[str, str] = {
    "revenue": "revenue",
    "sales": "revenue",
    "매출액": "revenue",
    "operating income": "operating_income",
    "영업이익": "operating_income",
    "net income": "net_income",
    "profit for the period": "net_income",
    "당기순이익": "net_income",
    "total assets": "total_assets",
    "자산총계": "total_assets",
    "total liabilities": "total_liabilities",
    "부채총계": "total_liabilities",
    "equity": "equity",
    "total equity": "equity",
    "자본총계": "equity",
}


class OpenDartCorpCode(SchemaBase):
    corp_code: str
    stock_code: str
    corp_name: str
    market: str | None = None
    aliases: list[str] = Field(default_factory=list)


def load_opendart_corp_codes(path: Path) -> dict[str, OpenDartCorpCode]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    records = payload["companies"] if isinstance(payload, dict) and "companies" in payload else payload
    if not isinstance(records, list):
        raise ValueError("OpenDART corp-code config must be a list or mapping with a 'companies' list.")
    companies = [OpenDartCorpCode.model_validate(record) for record in records]
    return {company.stock_code: company for company in companies}


def resolve_corp_code(
    corp_code: str | None,
    stock_code: str | None,
    corp_code_config: Path,
) -> tuple[str, str | None, OpenDartCorpCode | None]:
    mappings = load_opendart_corp_codes(corp_code_config)
    if corp_code:
        for company in mappings.values():
            if company.corp_code == corp_code:
                return corp_code, company.stock_code, company
        return corp_code, stock_code, None
    if stock_code:
        company = mappings.get(stock_code)
        if company is None:
            raise MissingCorpCodeMappingError(
                f"Missing OpenDART corp_code mapping for stock_code '{stock_code}' in {corp_code_config}."
            )
        return company.corp_code, company.stock_code, company
    raise MissingCorpCodeMappingError("OpenDART financial fetch requires corp_code or mapped stock_code.")


def validate_report_code(reprt_code: str) -> None:
    if reprt_code not in SUPPORTED_REPORT_CODES:
        raise UnsupportedReportCodeError(
            f"Unsupported OpenDART reprt_code '{reprt_code}'. Supported codes: "
            f"{', '.join(sorted(SUPPORTED_REPORT_CODES))}."
        )


def parse_amount(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text in {"-", "N/A"}:
        return None
    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1]
    text = text.replace(",", "").replace(" ", "")
    try:
        amount = float(text)
    except ValueError as exc:
        raise InvalidResponseError(f"Invalid OpenDART amount: {value}") from exc
    return -amount if negative else amount


def normalize_summary_account(account_name: str) -> str | None:
    lowered = account_name.lower()
    for alias, normalized in SUMMARY_ACCOUNT_ALIASES.items():
        if alias.lower() in lowered:
            return normalized
    return None


def build_financial_raw_cache_path(
    corp_code: str,
    bsns_year: str,
    reprt_code: str,
    collected_at: datetime | None = None,
    data_dir: Path = Path("data"),
) -> Path:
    timestamp = (collected_at or utc_now()).astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", f"{corp_code}_{bsns_year}_{reprt_code}").strip("_")
    return data_dir / "raw" / "opendart" / "financial" / f"{safe}_{timestamp}.json"


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise InvalidResponseError("Invalid OpenDART financial response: expected JSON object.")
    return payload


def parse_opendart_financial_statement_response(
    payload: dict[str, Any],
    *,
    corp_code: str,
    stock_code: str | None,
    bsns_year: str,
    reprt_code: str,
    raw_cache_path: str | None = None,
    collected_at: datetime | None = None,
) -> list[FinancialStatementLineItemCreate]:
    validate_report_code(reprt_code)
    status = str(payload.get("status", ""))
    if status == "013":
        return []
    if status and status != "000":
        raise InvalidResponseError(
            f"Invalid OpenDART financial response status={status}: {payload.get('message', '')}"
        )
    rows = payload.get("list")
    if not isinstance(rows, list):
        raise InvalidResponseError("Invalid OpenDART financial response: missing list array.")

    collected = collected_at or utc_now()
    line_items: list[FinancialStatementLineItemCreate] = []
    for row in rows:
        if not isinstance(row, dict):
            raise InvalidResponseError("Invalid OpenDART financial response: list item is not an object.")
        row_corp_code = str(row.get("corp_code") or corp_code)
        row_bsns_year = str(row.get("bsns_year") or bsns_year)
        row_reprt_code = str(row.get("reprt_code") or reprt_code)
        validate_report_code(row_reprt_code)
        try:
            account_name = str(row["account_nm"]).strip()
            fs_div = str(row["fs_div"]).strip()
            sj_div = str(row["sj_div"]).strip()
        except KeyError as exc:
            raise InvalidResponseError(f"Invalid OpenDART financial row: {row}") from exc
        current_amount = parse_amount(row.get("thstrm_amount"))
        if current_amount is None:
            continue
        previous_amount = parse_amount(row.get("frmtrm_amount"))
        row_stock_code = str(row.get("stock_code") or stock_code or "") or None
        metadata: dict[str, object] = {
            "rcept_no": row.get("rcept_no"),
            "reprt_code": row_reprt_code,
            "reprt_name": SUPPORTED_REPORT_CODES[row_reprt_code],
            "bsns_year": row_bsns_year,
            "corp_code": row_corp_code,
            "stock_code": row_stock_code,
            "account_nm": account_name,
            "fs_div": fs_div,
            "fs_nm": row.get("fs_nm"),
            "sj_div": sj_div,
            "sj_nm": row.get("sj_nm"),
            "ord": row.get("ord"),
            "raw_cache_path": raw_cache_path,
            "source": "OPEN_DART",
            "summary_account": normalize_summary_account(account_name),
        }
        statement_id = make_id("FIN", collected)
        line_items.append(
            FinancialStatementLineItemCreate(
                statement_id=statement_id,
                corp_code=row_corp_code,
                stock_code=row_stock_code,
                bsns_year=row_bsns_year,
                reprt_code=row_reprt_code,
                fs_div=fs_div,
                sj_div=sj_div,
                account_name=account_name,
                current_amount=current_amount,
                previous_amount=previous_amount,
                currency=str(row.get("currency") or "KRW"),
                source_id="OPEN_DART",
                collected_at=collected,
                available_from=safe_available_from(collected, collected),
                metadata_json=metadata,
            )
        )
    return line_items


class OpenDartFinancialCollector:
    collector_id = "opendart_financials"
    source_id = "OPEN_DART"

    def fetch_financials(
        self,
        *,
        corp_code: str | None,
        stock_code: str | None,
        bsns_year: str,
        reprt_code: str,
        corp_code_config: Path = Path("configs/opendart.corp_codes.example.yaml"),
        fixture: Path | None = None,
        cache_raw: bool = True,
    ) -> list[FinancialStatementLineItemCreate]:
        validate_report_code(reprt_code)
        resolved_corp_code, resolved_stock_code, _ = resolve_corp_code(
            corp_code,
            stock_code,
            corp_code_config,
        )
        if fixture is not None:
            return parse_opendart_financial_statement_response(
                _load_json(fixture),
                corp_code=resolved_corp_code,
                stock_code=resolved_stock_code,
                bsns_year=bsns_year,
                reprt_code=reprt_code,
                raw_cache_path=str(fixture),
            )

        require_network_enabled()
        api_key_name, api_key = require_any_api_key(DART_API_KEY_ENV_VARS)
        collected_at = utc_now()
        params = {
            "crtfc_key": api_key,
            "corp_code": resolved_corp_code,
            "bsns_year": bsns_year,
            "reprt_code": reprt_code,
        }
        url = f"https://opendart.fss.or.kr/api/fnlttSinglAcnt.json?{urlencode(params)}"
        with urlopen(url, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict):
            raise InvalidResponseError("Invalid OpenDART financial response: expected JSON object.")

        raw_cache_path = None
        if cache_raw:
            cache_path = build_financial_raw_cache_path(
                resolved_corp_code,
                bsns_year,
                reprt_code,
                collected_at,
            )
            write_raw_response_cache(
                {
                    "request": {
                        "corp_code": resolved_corp_code,
                        "stock_code": resolved_stock_code,
                        "bsns_year": bsns_year,
                        "reprt_code": reprt_code,
                        "api_key_env_var": api_key_name,
                    },
                    "response": payload,
                },
                cache_path,
            )
            raw_cache_path = str(cache_path)
        return parse_opendart_financial_statement_response(
            payload,
            corp_code=resolved_corp_code,
            stock_code=resolved_stock_code,
            bsns_year=bsns_year,
            reprt_code=reprt_code,
            raw_cache_path=raw_cache_path,
            collected_at=collected_at,
        )

    def ingest_financials(
        self,
        session: Session,
        *,
        corp_code: str | None,
        stock_code: str | None,
        bsns_year: str,
        reprt_code: str,
        corp_code_config: Path = Path("configs/opendart.corp_codes.example.yaml"),
        fixture: Path | None = None,
        cache_raw: bool = True,
    ) -> CollectorIngestResult:
        register_official_sources(session)
        repo = Repository(session)
        line_items = self.fetch_financials(
            corp_code=corp_code,
            stock_code=stock_code,
            bsns_year=bsns_year,
            reprt_code=reprt_code,
            corp_code_config=corp_code_config,
            fixture=fixture,
            cache_raw=cache_raw,
        )
        inserted_ids: list[str] = []
        skipped_count = 0
        for item in line_items:
            existing = repo.find_financial_statement_line_item(
                item.corp_code,
                item.bsns_year,
                item.reprt_code,
                item.fs_div,
                item.sj_div,
                item.account_name,
            )
            if existing is not None:
                skipped_count += 1
                continue
            inserted_ids.append(repo.add_financial_statement_line_item(item).statement_id)
        return CollectorIngestResult(
            collector_id=self.collector_id,
            source_id=self.source_id,
            inserted_count=len(inserted_ids),
            skipped_count=skipped_count,
            record_ids=inserted_ids,
        )


def pct_change(current: float, previous: float | None) -> float | None:
    if previous in (None, 0):
        return None
    return round((current - previous) / abs(previous) * 100.0, 4)


def financial_event_type(account_name: str, current: float, previous: float | None) -> str:
    normalized = normalize_summary_account(account_name)
    change = pct_change(current, previous)
    if normalized == "revenue" and change is not None and change > 0:
        return "revenue_growth_candidate"
    if normalized == "operating_income" and change is not None:
        return "operating_income_growth_candidate" if change > 0 else "margin_pressure_candidate"
    if normalized in {"total_liabilities", "equity"} and change is not None and abs(change) >= 5:
        return "leverage_change_candidate"
    return "financial_statement_received"


def financial_event_summary(item: Any) -> str:
    change = pct_change(float(item.current_amount), item.previous_amount)
    change_text = f", change={change}%" if change is not None else ""
    return (
        f"{item.stock_code or item.corp_code} {item.bsns_year} {SUPPORTED_REPORT_CODES[item.reprt_code]} "
        f"{item.account_name}: {item.current_amount:g} {item.currency or ''}{change_text}"
    )
