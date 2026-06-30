from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from project_stock.db.models import DecisionLog, Event, EvidenceLedger, RawDocument, Source
from project_stock.schemas.decisions import DecisionCreate
from project_stock.schemas.events import EventCreate
from project_stock.schemas.evidence import EvidenceCreate
from project_stock.storage.repository import Repository


def test_db_init_and_core_inserts(db_session):
    repo = Repository(db_session)
    source = repo.get_or_create_source("SRC_TEST", "Test Source", "mock")
    raw = repo.add_raw_document(
        title="Fed rate shock",
        body_text="Yield and dollar shock.",
        source_id=source.source_id,
        published_at=datetime(2026, 6, 29, tzinfo=UTC),
    )
    event = repo.add_event(
        EventCreate(
            event_type="macro_rate_shock",
            event_time=datetime(2026, 6, 29, tzinfo=UTC),
            summary="Fed rate shock",
        )
    )
    evidence = repo.append_evidence(
        EvidenceCreate(
            event_id=event.event_id,
            thesis_id="KOR_SEMI_MEMORY_UPCYCLE",
            evidence_type="event",
            claim="Rates moved sharply.",
        )
    )
    decision = repo.append_decision(
        DecisionCreate(
            decision_type="risk_review",
            event_id=event.event_id,
            action="no_new_buy",
            rationale="Risk action only; no order execution.",
        )
    )
    db_session.commit()

    assert db_session.scalar(select(Source).where(Source.source_id == "SRC_TEST")) == source
    assert db_session.scalar(select(RawDocument).where(RawDocument.doc_id == raw.doc_id)) == raw
    assert db_session.scalar(select(Event).where(Event.event_id == event.event_id)) == event
    assert db_session.scalar(
        select(EvidenceLedger).where(EvidenceLedger.evidence_id == evidence.evidence_id)
    )
    assert db_session.scalar(
        select(DecisionLog).where(DecisionLog.decision_id == decision.decision_id)
    )
    assert not hasattr(repo, "update_evidence")


def test_audit_repository_has_create_and_list_paths_only(db_session):
    repo = Repository(db_session)
    evidence = repo.append_evidence(
        EvidenceCreate(
            thesis_id="KOR_SEMI_MEMORY_UPCYCLE",
            evidence_type="manual",
            claim="Append-only evidence.",
        )
    )
    decision = repo.append_decision(
        DecisionCreate(
            decision_type="manual_review",
            action="record_only",
            rationale="Append-only decision.",
        )
    )
    db_session.commit()

    assert evidence in repo.list_evidence()
    assert decision in repo.list_decisions()
    forbidden_prefixes = ("update_evidence", "delete_evidence", "update_decision", "delete_decision")
    assert not any(hasattr(repo, name) for name in forbidden_prefixes)


def test_evidence_ledger_update_and_delete_are_guarded(db_session):
    repo = Repository(db_session)
    evidence = repo.append_evidence(
        EvidenceCreate(
            thesis_id="KOR_SEMI_MEMORY_UPCYCLE",
            evidence_type="manual",
            claim="Original claim.",
        )
    )
    db_session.commit()

    evidence.claim = "Changed claim."
    with pytest.raises(RuntimeError, match="EvidenceLedger is append-only"):
        db_session.commit()
    db_session.rollback()

    db_session.delete(evidence)
    with pytest.raises(RuntimeError, match="EvidenceLedger is append-only"):
        db_session.commit()


def test_decision_log_update_and_delete_are_guarded(db_session):
    repo = Repository(db_session)
    decision = repo.append_decision(
        DecisionCreate(
            decision_type="manual_review",
            action="record_only",
            rationale="Original rationale.",
        )
    )
    db_session.commit()

    decision.rationale = "Changed rationale."
    with pytest.raises(RuntimeError, match="DecisionLog is append-only"):
        db_session.commit()
    db_session.rollback()

    db_session.delete(decision)
    with pytest.raises(RuntimeError, match="DecisionLog is append-only"):
        db_session.commit()
