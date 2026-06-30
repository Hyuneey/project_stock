from __future__ import annotations

from datetime import UTC, datetime


def parse_datetime(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def safe_available_from(
    provided: str | datetime | None = None,
    *not_before: str | datetime | None,
) -> datetime:
    """Return an availability time that is not earlier than any known source time."""
    parsed_provided = parse_datetime(provided)
    floors = [parse_datetime(value) for value in not_before]
    floor_candidates = [value for value in floors if value is not None]
    if not floor_candidates and parsed_provided is None:
        return datetime.now(UTC)
    floor = max(floor_candidates, default=parsed_provided)
    if parsed_provided is None:
        return floor
    return max(parsed_provided, floor)
