from __future__ import annotations

from project_stock.schemas.thesis import ThesisDefinition


def latest_state_reason(thesis: ThesisDefinition) -> str:
    if not thesis.state_history:
        return "No state history recorded."
    latest = sorted(thesis.state_history, key=lambda item: item.date)[-1]
    return latest.reason
