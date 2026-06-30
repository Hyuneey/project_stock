from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from project_stock.events.classifier import event_from_document
from project_stock.events.mapper import map_entities
from project_stock.storage.repository import Repository

MOCK_SOURCE_ID = "SRC_MOCK_NEWS"

MOCK_DOCUMENTS: list[dict[str, object]] = [
    {
        "title": "Fed rate shock hits semiconductor sentiment",
        "body_text": "US2Y yield jumps and the dollar rises, pressuring Korean semiconductor shares.",
        "published_at": datetime(2026, 6, 29, 1, 0, tzinfo=UTC),
        "source_reliability": 4.0,
        "surprise_score": 4.5,
        "persistence_score": 3.5,
        "market_confirmation_score": 4.0,
    },
    {
        "title": "Oil supply shock raises energy risk",
        "body_text": "Middle East tension lifts oil prices and adds macro pressure.",
        "published_at": datetime(2026, 6, 29, 2, 0, tzinfo=UTC),
        "source_reliability": 3.5,
        "surprise_score": 4.0,
        "persistence_score": 3.0,
        "market_confirmation_score": 3.0,
    },
    {
        "title": "Earnings guidance misses consensus",
        "body_text": "A memory supplier lowers revenue guidance and EPS expectations.",
        "published_at": datetime(2026, 6, 29, 3, 0, tzinfo=UTC),
        "source_reliability": 3.0,
        "surprise_score": 4.0,
        "persistence_score": 3.0,
        "market_confirmation_score": 3.0,
    },
    {
        "title": "HBM demand supports AI semiconductor capex",
        "body_text": "Semiconductor inventory improves as AI infrastructure demand remains resilient.",
        "published_at": datetime(2026, 6, 29, 4, 0, tzinfo=UTC),
        "source_reliability": 3.5,
        "surprise_score": 3.0,
        "persistence_score": 4.0,
        "market_confirmation_score": 3.5,
    },
]

MOCK_METRICS = {
    "US2Y_YIELD_CHANGE_1D_BP": 20,
    "DXY_CHANGE_1D_PCT": 0.8,
    "USDKRW_CHANGE_1D_PCT": 1.2,
    "SOX_CHANGE_1D_PCT": -3.1,
    "VIX_CHANGE_1D_PCT": 8.0,
}


def ingest_mock_data(session: Session) -> list[str]:
    repo = Repository(session)
    repo.get_or_create_source(
        MOCK_SOURCE_ID,
        name="Mock News Wire",
        source_type="mock",
        reliability_default=3.5,
        notes="Deterministic local fixture source.",
    )
    event_ids: list[str] = []
    for document in MOCK_DOCUMENTS:
        raw = repo.add_raw_document(
            title=str(document["title"]),
            body_text=str(document["body_text"]),
            source_id=MOCK_SOURCE_ID,
            published_at=document["published_at"],  # type: ignore[arg-type]
            available_from=document["published_at"],  # type: ignore[arg-type]
            metadata_json={"fixture": True},
        )
        event = repo.add_event(event_from_document({**document, "doc_id": raw.doc_id}))
        entities = map_entities(f"{document['title']} {document['body_text']}")
        repo.add_event_entities(event.event_id, entities)
        event_ids.append(event.event_id)
    return event_ids
