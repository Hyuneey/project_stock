from __future__ import annotations

from datetime import datetime

from project_stock.schemas.common import SchemaBase


class FinancialStatementLineItemCreate(SchemaBase):
    statement_id: str | None = None
    corp_code: str
    stock_code: str | None = None
    bsns_year: str
    reprt_code: str
    fs_div: str
    sj_div: str
    account_name: str
    current_amount: float
    previous_amount: float | None = None
    currency: str | None = None
    source_id: str = "OPEN_DART"
    collected_at: datetime | None = None
    available_from: datetime | None = None
    metadata_json: dict[str, object] | None = None
