from __future__ import annotations

from datetime import UTC, datetime

from project_stock.events.classifier import classify_document
from project_stock.events.mapper import map_entities
from project_stock.schemas.events import EventCreate
from project_stock.storage.repository import Repository, create_evidence_from_event


def test_rate_keywords_classify_as_macro_rate_shock():
    document = {
        "title": "Fed rate shock",
        "body_text": "US2Y yield rises and inflation concerns lift the dollar.",
    }

    assert classify_document(document) == "macro_rate_shock"


def test_semiconductor_keywords_map_to_thesis():
    entities = map_entities("Samsung and SK Hynix semiconductor memory shares move on AI demand.")

    assert {"entity_type": "theme", "entity_id": "KOR_SEMI_MEMORY_UPCYCLE", "relevance_score": 1.0} in entities


def test_event_to_evidence_creation(db_session):
    repo = Repository(db_session)
    event = repo.add_event(
        EventCreate(
            event_type="industry_data",
            event_time=datetime(2026, 6, 29, tzinfo=UTC),
            summary="Semiconductor inventory improves.",
            surprise_score=4.0,
        )
    )
    evidence = create_evidence_from_event(
        event,
        thesis_id="KOR_SEMI_MEMORY_UPCYCLE",
        supports_or_contradicts="supports",
        session=db_session,
    )

    assert evidence.event_id == event.event_id
    assert evidence.thesis_id == "KOR_SEMI_MEMORY_UPCYCLE"
    assert evidence.immutable is True
