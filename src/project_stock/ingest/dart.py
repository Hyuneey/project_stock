from __future__ import annotations

from datetime import UTC, date, datetime, time
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen

import yaml
from pydantic import Field

from sqlalchemy.orm import Session

from project_stock.ingest.base import CollectorIngestResult, OfficialCollector
from project_stock.ingest.real_data import (
    InvalidResponseError,
    UnsupportedQueryError,
    build_timestamped_raw_cache_path,
    require_any_api_key,
    require_network_enabled,
    utc_now,
    write_raw_response_cache,
)
from project_stock.ingest.sources import register_official_sources
from project_stock.normalize.time import safe_available_from
from project_stock.schemas.common import SchemaBase
from project_stock.schemas.documents import RawDocumentCreate
from project_stock.storage.repository import Repository

DEFAULT_DART_DISCLOSURE_TIME = time(15, 30, tzinfo=UTC)
DART_API_KEY_ENV_VARS = ("DART_API_KEY", "OPEN_DART_API_KEY")
SUPPORTED_PBLNTF_TYPES = set("ABCDEFGHIJ")


class OpenDartCorpCode(SchemaBase):
    corp_code: str
    stock_code: str
    corp_name: str
    market: str | None = None
    aliases: list[str] = Field(default_factory=list)


class OpenDartDisclosureQuery(SchemaBase):
    corp_code: str | None = None
    stock_code: str | None = None
    bgn_de: str
    end_de: str
    page_no: int = 1
    page_count: int = 10
    pblntf_ty: str | None = None
    last_reprt_at: str | None = None


class DartDisclosureRecord(SchemaBase):
    rcept_no: str
    corp_code: str
    corp_cls: str | None = None
    corp_name: str | None = None
    stock_code: str | None = None
    report_name: str
    report_nm: str | None = None
    rcept_dt: str | None = None
    flr_nm: str | None = None
    rm: str | None = None
    received_at: datetime
    title: str | None = None
    body_text: str | None = None
    summary: str | None = None
    collected_at: datetime | None = None
    available_from: datetime | None = None
    source_id: str = "OPEN_DART"
    raw_path: str | None = None
    metadata_json: dict[str, object] | None = None


def load_opendart_corp_codes(path: Path) -> dict[str, OpenDartCorpCode]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    records = payload["companies"] if isinstance(payload, dict) and "companies" in payload else payload
    if not isinstance(records, list):
        raise ValueError("OpenDART corp-code config must be a list or mapping with a 'companies' list.")
    companies = [OpenDartCorpCode.model_validate(record) for record in records]
    return {company.stock_code: company for company in companies}


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise InvalidResponseError("Invalid OpenDART response: expected top-level JSON object.")
    return payload


def _parse_disclosure_datetime(rcept_dt: str) -> datetime:
    try:
        parsed_date = date(int(rcept_dt[0:4]), int(rcept_dt[4:6]), int(rcept_dt[6:8]))
    except (TypeError, ValueError) as exc:
        raise InvalidResponseError(f"Invalid OpenDART rcept_dt: {rcept_dt}") from exc
    return datetime.combine(parsed_date, DEFAULT_DART_DISCLOSURE_TIME)


def _summary_from_disclosure(item: dict[str, Any]) -> str:
    fields = [
        f"OpenDART disclosure received: {item.get('report_nm', '')}",
        f"company={item.get('corp_name', '')}",
        f"corp_code={item.get('corp_code', '')}",
        f"stock_code={item.get('stock_code', '')}",
        f"rcept_no={item.get('rcept_no', '')}",
        f"rcept_dt={item.get('rcept_dt', '')}",
        f"filer={item.get('flr_nm', '')}",
        f"corp_cls={item.get('corp_cls', '')}",
        f"remarks={item.get('rm', '')}",
    ]
    return "; ".join(field for field in fields if not field.endswith("="))


def parse_opendart_disclosure_list_response(
    payload: dict[str, Any],
    raw_cache_path: str | None = None,
    collected_at: datetime | None = None,
) -> list[DartDisclosureRecord]:
    status = str(payload.get("status", ""))
    if status == "013":
        return []
    if status and status != "000":
        raise InvalidResponseError(
            f"Invalid OpenDART response status={status}: {payload.get('message', '')}"
        )
    rows = payload.get("list")
    if not isinstance(rows, list):
        raise InvalidResponseError("Invalid OpenDART response: missing list array.")

    collected = collected_at or utc_now()
    records: list[DartDisclosureRecord] = []
    for item in rows:
        if not isinstance(item, dict):
            raise InvalidResponseError("Invalid OpenDART response: list item is not an object.")
        try:
            rcept_no = str(item["rcept_no"])
            corp_code = str(item["corp_code"])
            report_nm = str(item["report_nm"])
            rcept_dt = str(item["rcept_dt"])
            received_at = _parse_disclosure_datetime(rcept_dt)
        except KeyError as exc:
            raise InvalidResponseError(f"Invalid OpenDART disclosure item: {item}") from exc
        metadata: dict[str, object] = {
            "rcept_no": rcept_no,
            "corp_cls": item.get("corp_cls"),
            "corp_code": corp_code,
            "corp_name": item.get("corp_name"),
            "stock_code": item.get("stock_code"),
            "report_nm": report_nm,
            "report_name": report_nm,
            "rcept_dt": rcept_dt,
            "flr_nm": item.get("flr_nm"),
            "rm": item.get("rm"),
            "raw_cache_path": raw_cache_path,
            "source": "OPEN_DART",
        }
        records.append(
            DartDisclosureRecord(
                rcept_no=rcept_no,
                corp_cls=str(item.get("corp_cls") or ""),
                corp_code=corp_code,
                corp_name=str(item.get("corp_name") or ""),
                stock_code=str(item.get("stock_code") or "") or None,
                report_name=report_nm,
                report_nm=report_nm,
                rcept_dt=rcept_dt,
                flr_nm=str(item.get("flr_nm") or ""),
                rm=str(item.get("rm") or ""),
                received_at=received_at,
                title=report_nm,
                body_text=_summary_from_disclosure(item),
                summary=_summary_from_disclosure(item),
                collected_at=collected,
                available_from=safe_available_from(received_at, received_at, collected),
                raw_path=raw_cache_path,
                metadata_json=metadata,
            )
        )
    return records


def resolve_opendart_query(
    *,
    corp_code: str | None,
    stock_code: str | None,
    bgn_de: str,
    end_de: str,
    page_no: int = 1,
    page_count: int = 10,
    pblntf_ty: str | None = None,
    last_reprt_at: str | None = None,
    corp_code_config: Path = Path("configs/opendart.corp_codes.example.yaml"),
) -> OpenDartDisclosureQuery:
    if stock_code and not corp_code:
        mappings = load_opendart_corp_codes(corp_code_config)
        company = mappings.get(stock_code)
        if company is None:
            raise UnsupportedQueryError(
                f"Unsupported OpenDART stock_code '{stock_code}'. Add it to {corp_code_config}."
            )
        corp_code = company.corp_code
    if not bgn_de or not end_de:
        raise UnsupportedQueryError("OpenDART disclosure query requires bgn_de and end_de.")
    if page_no < 1:
        raise UnsupportedQueryError("OpenDART page_no must be >= 1.")
    if page_count < 1 or page_count > 100:
        raise UnsupportedQueryError("OpenDART page_count must be between 1 and 100.")
    if pblntf_ty and pblntf_ty not in SUPPORTED_PBLNTF_TYPES:
        raise UnsupportedQueryError("OpenDART pblntf_ty must be one of A through J.")
    if last_reprt_at and last_reprt_at not in {"Y", "N"}:
        raise UnsupportedQueryError("OpenDART last_reprt_at must be Y or N.")
    return OpenDartDisclosureQuery(
        corp_code=corp_code,
        stock_code=stock_code,
        bgn_de=bgn_de,
        end_de=end_de,
        page_no=page_no,
        page_count=page_count,
        pblntf_ty=pblntf_ty,
        last_reprt_at=last_reprt_at,
    )


class OpenDartCollector(OfficialCollector[DartDisclosureRecord, RawDocumentCreate]):
    collector_id = "opendart"
    source_id = "OPEN_DART"
    api_key_env_var = "DART_API_KEY"

    def raw_schema(self) -> type[DartDisclosureRecord]:
        return DartDisclosureRecord

    def fetch_raw(
        self,
        fixture: Path | None = None,
        mock: bool = True,
        *,
        corp_code: str | None = None,
        stock_code: str | None = None,
        bgn_de: str | None = None,
        end_de: str | None = None,
        page_no: int = 1,
        page_count: int = 10,
        pblntf_ty: str | None = None,
        last_reprt_at: str | None = None,
        corp_code_config: Path = Path("configs/opendart.corp_codes.example.yaml"),
    ) -> list[DartDisclosureRecord]:
        if mock:
            return super().fetch_raw(fixture=fixture, mock=mock)
        if bgn_de is None or end_de is None:
            raise UnsupportedQueryError("bgn_de and end_de are required for real OpenDART fetches.")
        return self.fetch_disclosures(
            corp_code=corp_code,
            stock_code=stock_code,
            bgn_de=bgn_de,
            end_de=end_de,
            page_no=page_no,
            page_count=page_count,
            pblntf_ty=pblntf_ty,
            last_reprt_at=last_reprt_at,
            corp_code_config=corp_code_config,
        )

    def fetch_disclosures(
        self,
        *,
        corp_code: str | None,
        stock_code: str | None,
        bgn_de: str,
        end_de: str,
        page_no: int = 1,
        page_count: int = 10,
        pblntf_ty: str | None = None,
        last_reprt_at: str | None = None,
        corp_code_config: Path = Path("configs/opendart.corp_codes.example.yaml"),
        fixture: Path | None = None,
        cache_raw: bool = True,
    ) -> list[DartDisclosureRecord]:
        query = resolve_opendart_query(
            corp_code=corp_code,
            stock_code=stock_code,
            bgn_de=bgn_de,
            end_de=end_de,
            page_no=page_no,
            page_count=page_count,
            pblntf_ty=pblntf_ty,
            last_reprt_at=last_reprt_at,
            corp_code_config=corp_code_config,
        )
        if fixture is not None:
            return parse_opendart_disclosure_list_response(
                _load_json(fixture),
                raw_cache_path=str(fixture),
            )

        require_network_enabled()
        api_key_name, api_key = require_any_api_key(DART_API_KEY_ENV_VARS)
        collected_at = utc_now()
        params: dict[str, object] = {
            "crtfc_key": api_key,
            "bgn_de": query.bgn_de,
            "end_de": query.end_de,
            "page_no": query.page_no,
            "page_count": query.page_count,
        }
        if query.corp_code:
            params["corp_code"] = query.corp_code
        if query.pblntf_ty:
            params["pblntf_ty"] = query.pblntf_ty
        if query.last_reprt_at:
            params["last_reprt_at"] = query.last_reprt_at
        url = f"https://opendart.fss.or.kr/api/list.json?{urlencode(params)}"
        with urlopen(url, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict):
            raise InvalidResponseError("Invalid OpenDART response: expected JSON object.")

        raw_cache_path = None
        if cache_raw:
            prefix = f"disclosure_list_{query.corp_code or query.stock_code or 'all'}_{query.bgn_de}_{query.end_de}"
            cache_path = build_timestamped_raw_cache_path("opendart", prefix, collected_at)
            write_raw_response_cache(
                {
                    "request": {
                        key: value for key, value in params.items() if key != "crtfc_key"
                    }
                    | {"api_key_env_var": api_key_name},
                    "response": payload,
                },
                cache_path,
            )
            raw_cache_path = str(cache_path)
        return parse_opendart_disclosure_list_response(
            payload,
            raw_cache_path=raw_cache_path,
            collected_at=collected_at,
        )

    def normalize(self, raw_records: list[DartDisclosureRecord]) -> list[RawDocumentCreate]:
        documents: list[RawDocumentCreate] = []
        for record in raw_records:
            collected_at = record.collected_at or record.received_at
            report_name = record.report_nm or record.report_name
            metadata = {
                "rcept_no": record.rcept_no,
                "corp_cls": record.corp_cls,
                "corp_code": record.corp_code,
                "corp_name": record.corp_name,
                "stock_code": record.stock_code,
                "report_nm": report_name,
                "report_name": report_name,
                "rcept_dt": record.rcept_dt,
                "flr_nm": record.flr_nm,
                "rm": record.rm,
                "source": self.source_id,
            }
            if record.raw_path:
                metadata["raw_cache_path"] = record.raw_path
            if record.metadata_json:
                metadata.update(record.metadata_json)
            documents.append(
                RawDocumentCreate(
                    source_id=self.source_id,
                    title=record.title or report_name,
                    body_text=record.body_text or record.summary or "",
                    language="ko",
                    published_at=record.received_at,
                    collected_at=collected_at,
                    available_from=safe_available_from(
                        record.available_from,
                        record.received_at,
                        collected_at,
                    ),
                    checksum=f"opendart:{record.rcept_no}",
                    raw_path=record.raw_path,
                    metadata_json=metadata,
                )
            )
        return documents

    def ingest(
        self,
        session: Session,
        fixture: Path | None = None,
        mock: bool = True,
    ) -> CollectorIngestResult:
        register_official_sources(session)
        repo = Repository(session)
        records = self.normalize(self.fetch_raw(fixture=fixture, mock=mock))
        inserted_ids: list[str] = []
        skipped_count = 0
        for record in records:
            if record.checksum and repo.find_raw_document_by_checksum(record.checksum, self.source_id):
                skipped_count += 1
                continue
            inserted_ids.append(repo.add_raw_document_create(record).doc_id)
        return CollectorIngestResult(
            collector_id=self.collector_id,
            source_id=self.source_id,
            inserted_count=len(inserted_ids),
            skipped_count=skipped_count,
            record_ids=inserted_ids,
        )

    def ingest_disclosures(
        self,
        session: Session,
        *,
        corp_code: str | None,
        stock_code: str | None,
        bgn_de: str,
        end_de: str,
        page_no: int = 1,
        page_count: int = 10,
        pblntf_ty: str | None = None,
        last_reprt_at: str | None = None,
        corp_code_config: Path = Path("configs/opendart.corp_codes.example.yaml"),
        fixture: Path | None = None,
        cache_raw: bool = True,
    ) -> CollectorIngestResult:
        register_official_sources(session)
        repo = Repository(session)
        records = self.normalize(
            self.fetch_disclosures(
                corp_code=corp_code,
                stock_code=stock_code,
                bgn_de=bgn_de,
                end_de=end_de,
                page_no=page_no,
                page_count=page_count,
                pblntf_ty=pblntf_ty,
                last_reprt_at=last_reprt_at,
                corp_code_config=corp_code_config,
                fixture=fixture,
                cache_raw=cache_raw,
            )
        )
        inserted_ids: list[str] = []
        skipped_count = 0
        for record in records:
            if record.checksum and repo.find_raw_document_by_checksum(record.checksum, self.source_id):
                skipped_count += 1
                continue
            inserted_ids.append(repo.add_raw_document_create(record).doc_id)
        return CollectorIngestResult(
            collector_id=self.collector_id,
            source_id=self.source_id,
            inserted_count=len(inserted_ids),
            skipped_count=skipped_count,
            record_ids=inserted_ids,
        )
