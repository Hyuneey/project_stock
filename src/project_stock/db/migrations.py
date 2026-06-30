from __future__ import annotations

from sqlalchemy.engine import Engine

from project_stock.db.base import Base
from project_stock.db.models import (  # noqa: F401
    DecisionLog,
    Event,
    EventEntity,
    EvidenceLedger,
    IndicatorObservation,
    MarketTimeSeries,
    RawDocument,
    ScenarioTriggerLog,
    Source,
    ThesisStateSnapshot,
)
from project_stock.db.session import create_db_engine


def init_db(db_url: str) -> Engine:
    engine = create_db_engine(db_url)
    Base.metadata.create_all(engine)
    return engine
