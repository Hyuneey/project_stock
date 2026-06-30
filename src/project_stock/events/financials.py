from __future__ import annotations

from collections import Counter

from sqlalchemy.orm import Session

from project_stock.db.models import FinancialStatementLineItem, Source
from project_stock.events.mapper import map_entities
from project_stock.events.normalization import EventNormalizationResult
from project_stock.ingest.opendart_financials import (
    financial_event_summary,
    financial_event_type,
    normalize_summary_account,
    pct_change,
)
from project_stock.normalize.time import safe_available_from
from project_stock.schemas.events import EventCreate
from project_stock.storage.repository import Repository
from project_stock.utils.ids import make_id


def _source_reliability(session: Session, source_id: str | None) -> float:
    if source_id is None:
        return 3.0
    source = session.get(Source, source_id)
    return float(source.reliability_default) if source else 3.0


def _surprise_score(item: FinancialStatementLineItem) -> float:
    change = pct_change(float(item.current_amount), item.previous_amount)
    if change is None:
        return 3.0
    return round(max(0.0, min(5.0, 3.0 + min(2.0, abs(change) / 20.0))), 2)


def normalize_financial_events(session: Session) -> EventNormalizationResult:
    repo = Repository(session)
    inserted = []
    skipped_count = 0
    for item in repo.list_financial_statement_line_items():
        if normalize_summary_account(item.account_name) is None:
            skipped_count += 1
            continue
        event_type = financial_event_type(
            item.account_name,
            float(item.current_amount),
            item.previous_amount,
        )
        if repo.find_event_by_source_record(
            "financial_statement_line_items",
            item.statement_id,
            event_type,
        ):
            skipped_count += 1
            continue
        event_time = item.available_from
        metadata = {
            "source_table": "financial_statement_line_items",
            "source_record_id": item.statement_id,
            "source_id": item.source_id,
            "statement_id": item.statement_id,
            "corp_code": item.corp_code,
            "stock_code": item.stock_code,
            "bsns_year": item.bsns_year,
            "reprt_code": item.reprt_code,
            "fs_div": item.fs_div,
            "sj_div": item.sj_div,
            "account_name": item.account_name,
            "current_amount": item.current_amount,
            "previous_amount": item.previous_amount,
            "pct_change": pct_change(float(item.current_amount), item.previous_amount),
            **(item.metadata_json or {}),
        }
        summary = financial_event_summary(item)
        entities = map_entities(
            f"{summary} {item.stock_code or ''} {metadata.get('corp_name', '')} semiconductor earnings"
        )
        event = repo.add_event(
            EventCreate(
                event_id=make_id("EVT", event_time),
                event_type=event_type,
                event_time=event_time,
                first_seen_at=item.available_from,
                available_from=safe_available_from(item.available_from, item.collected_at),
                summary=summary,
                source_reliability=_source_reliability(session, item.source_id),
                surprise_score=_surprise_score(item),
                persistence_score=3.0,
                market_confirmation_score=2.0,
                metadata_json=metadata,
            )
        )
        entity_rows = repo.add_event_entities(event.event_id, entities)
        inserted.append((event, len(entity_rows)))

    counts = Counter(event.event_type for event, _ in inserted)
    return EventNormalizationResult(
        inserted_event_ids=[event.event_id for event, _ in inserted],
        skipped_count=skipped_count,
        counts_by_event_type=dict(counts),
        entity_count=sum(count for _, count in inserted),
    )
